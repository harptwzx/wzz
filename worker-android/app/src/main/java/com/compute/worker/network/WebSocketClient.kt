package com.compute.worker.network

import android.content.Context
import com.compute.worker.data.model.*
import com.google.gson.Gson
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import okhttp3.*
import okio.ByteString
import timber.log.Timber
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * WebSocketClient
 * 基于OkHttp的长连接客户端
 * 功能：注册、心跳（5秒）、延迟测试（Ping-Pong）、任务接收、结果回传、断线重连
 */
class WebSocketClient(
    private val context: Context,
    private val serverUrl: String,  // wss://host:port
    private val deviceProfiler: com.compute.worker.DeviceProfiler,
    private val securityManager: com.compute.worker.SecurityManager,
    private val onTaskAssigned: (TaskAssignment) -> Unit,
    private val onActivationReceived: (ActivationTransfer) -> Unit,
    private val onThrottleCommand: (String) -> Unit
) {
    companion object {
        private const val HEARTBEAT_INTERVAL_MS = 5000L
        private const val RECONNECT_DELAY_MS = 3000L
        private const val MAX_RECONNECT_ATTEMPTS = 10
        private const val PING_INTERVAL_MS = 30000L
    }

    private val client = OkHttpClient.Builder()
        .pingInterval(PING_INTERVAL_MS, TimeUnit.MILLISECONDS)
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val gson = Gson()
    private var webSocket: WebSocket? = null
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val isConnected = AtomicBoolean(false)
    private val messageQueue = Channel<String>(Channel.BUFFERED)
    private var reconnectAttempts = 0
    private var heartbeatJob: Job? = null
    private var queueJob: Job? = null
    private var serverTimeOffset = 0L

    var onConnectionStateChange: ((Boolean) -> Unit)? = null

    fun connect() {
        if (isConnected.get()) return

        val request = Request.Builder()
            .url(serverUrl)
            .build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                Timber.i("WebSocket connected")
                isConnected.set(true)
                reconnectAttempts = 0
                onConnectionStateChange?.invoke(true)
                sendRegister()
                startHeartbeat()
                startMessageQueue()
            }

            override fun onMessage(ws: WebSocket, text: String) {
                handleMessage(text)
            }

            override fun onMessage(ws: WebSocket, bytes: ByteString) {
                handleBinaryMessage(bytes.toByteArray())
            }

            override fun onClosing(ws: WebSocket, code: Int, reason: String) {
                Timber.w("WebSocket closing: $code / $reason")
                ws.close(1000, null)
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                handleDisconnect()
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                Timber.e(t, "WebSocket failure")
                handleDisconnect()
                scheduleReconnect()
            }
        })
    }

    private fun sendRegister() {
        val deviceId = securityManager.getDeviceId()
        val secret = securityManager.getDeviceSecret()
        val fingerprint = deviceProfiler.generateFingerprint(deviceId, secret)
        val (totalRam, availRam) = deviceProfiler.getMemoryInfo()
        val (battery, charging) = deviceProfiler.getBatteryStatus()

        val register = RegisterMessage(
            deviceId = deviceId,
            deviceName = android.os.Build.MODEL ?: "Unknown",
            androidVersion = android.os.Build.VERSION.RELEASE ?: "Unknown",
            sdkLevel = android.os.Build.VERSION.SDK_INT,
            cpuCores = deviceProfiler.getCpuCores(),
            cpuFreqMhz = deviceProfiler.getCpuMaxFreqMhz(),
            totalRamMb = totalRam,
            availableRamMb = availRam,
            batteryPercent = battery,
            isCharging = charging,
            hasNpu = deviceProfiler.hasNpu(),
            hasGpu = deviceProfiler.hasGpu(),
            networkType = deviceProfiler.getNetworkType(),
            fingerprint = fingerprint
        )

        send(gson.toJson(register))
    }

    private fun startHeartbeat() {
        heartbeatJob?.cancel()
        heartbeatJob = scope.launch {
            while (isActive && isConnected.get()) {
                delay(HEARTBEAT_INTERVAL_MS)
                val (_, availRam) = deviceProfiler.getMemoryInfo()
                val (battery, charging) = deviceProfiler.getBatteryStatus()

                val heartbeat = HeartbeatMessage(
                    availableRamMb = availRam,
                    batteryPercent = battery,
                    isCharging = charging,
                    status = "online"
                )
                send(gson.toJson(heartbeat))
            }
        }
    }

    private fun startMessageQueue() {
        queueJob?.cancel()
        queueJob = scope.launch {
            for (msg in messageQueue) {
                if (isConnected.get()) {
                    webSocket?.send(msg)
                }
            }
        }
    }

    private fun handleMessage(text: String) {
        try {
            val json = org.json.JSONObject(text)
            val type = json.getString("type")

            when (type) {
                "REGISTER_ACK" -> {
                    val serverTime = json.getDouble("server_time")
                    serverTimeOffset = (System.currentTimeMillis() - serverTime * 1000).toLong()
                    Timber.i("Registered with server, time offset: ${serverTimeOffset}ms")
                }
                "HEARTBEAT_ACK" -> {}
                "PING" -> {
                    val pong = PongMessage(sentTime = json.getDouble("sent_time"))
                    send(gson.toJson(pong))
                }
                "TASK_ASSIGN" -> {
                    val task = gson.fromJson(text, TaskAssignment::class.java)
                    onTaskAssigned(task)
                }
                "ACTIVATION_RECV" -> {
                    val activation = gson.fromJson(text, ActivationTransfer::class.java)
                    onActivationReceived(activation)
                }
                "TASK_MIGRATE" -> {
                    val migrateTask = gson.fromJson(text, TaskAssignment::class.java)
                    onTaskAssigned(migrateTask)
                }
                "THROTTLE" -> {
                    val action = json.getString("action")
                    onThrottleCommand(action)
                }
                "ERROR" -> {
                    Timber.e("Server error: ${json.getString("message")}")
                }
                else -> {
                    Timber.w("Unknown message type: $type")
                }
            }
        } catch (e: Exception) {
            Timber.e(e, "Failed to parse message: $text")
        }
    }

    private fun handleBinaryMessage(data: ByteArray) {
        try {
            val decompressed = securityManager.decompress(data)
            Timber.d("Received binary activation: ${decompressed.size} bytes")
        } catch (e: Exception) {
            Timber.e(e, "Failed to process binary message")
        }
    }

    fun send(message: String) {
        scope.launch {
            messageQueue.send(message)
        }
    }

    fun sendTaskResult(result: TaskResult) {
        send(gson.toJson(result))
    }

    fun sendActivation(transfer: ActivationTransfer, activationData: ByteArray) {
        scope.launch {
            val compressed = securityManager.compress(activationData)
            val base64 = android.util.Base64.encodeToString(compressed, android.util.Base64.NO_WRAP)
            val msg = transfer.copy(activation = base64)
            send(gson.toJson(msg))
        }
    }

    fun reportError(errorCode: String, taskId: String? = null, message: String) {
        val error = ErrorReportMessage(
            errorCode = errorCode,
            taskId = taskId,
            message = message
        )
        send(gson.toJson(error))
    }

    private fun handleDisconnect() {
        isConnected.set(false)
        heartbeatJob?.cancel()
        queueJob?.cancel()
        onConnectionStateChange?.invoke(false)
    }

    private fun scheduleReconnect() {
        if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            Timber.e("Max reconnection attempts reached")
            return
        }
        reconnectAttempts++
        val delay = RECONNECT_DELAY_MS * reconnectAttempts.coerceAtMost(5)
        Timber.i("Scheduling reconnect in ${delay}ms (attempt $reconnectAttempts)")
        scope.launch {
            delay(delay)
            connect()
        }
    }

    fun disconnect() {
        heartbeatJob?.cancel()
        queueJob?.cancel()
        webSocket?.close(1000, "Client disconnect")
        isConnected.set(false)
        reconnectAttempts = MAX_RECONNECT_ATTEMPTS
    }

    fun isConnected(): Boolean = isConnected.get()

    fun cleanup() {
        disconnect()
        scope.cancel()
        client.dispatcher.executorService.shutdown()
    }
}
