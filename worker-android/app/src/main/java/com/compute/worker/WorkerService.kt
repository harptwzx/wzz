package com.compute.worker

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import com.compute.worker.data.model.ActivationTransfer
import com.compute.worker.data.model.TaskAssignment
import com.compute.worker.distributed.DistributedCoordinator
import com.compute.worker.inference.InferenceEngine
import com.compute.worker.network.WebSocketClient
import kotlinx.coroutines.*
import timber.log.Timber

/**
 * WorkerService
 * 前台服务：保持长连接、处理推理任务、低电量保护
 * 即使App退到后台也持续运行
 */
class WorkerService : Service() {

    companion object {
        const val CHANNEL_ID = "mdcs_worker_channel"
        const val NOTIFICATION_ID = 1001
        const val ACTION_START = "com.compute.worker.ACTION_START"
        const val ACTION_STOP = "com.compute.worker.ACTION_STOP"
        const val EXTRA_SERVER_URL = "server_url"
    }

    private val binder = LocalBinder()
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    lateinit var webSocketClient: WebSocketClient
    lateinit var inferenceEngine: InferenceEngine
    lateinit var distributedCoordinator: DistributedCoordinator
    lateinit var securityManager: SecurityManager
    lateinit var deviceProfiler: DeviceProfiler

    private var wakeLock: PowerManager.WakeLock? = null
    private var isRunning = false

    // 状态回调
    var onStatusUpdate: ((String, String) -> Unit)? = null

    inner class LocalBinder : Binder() {
        fun getService(): WorkerService = this@WorkerService
    }

    override fun onCreate() {
        super.onCreate()
        Timber.i("WorkerService created")

        deviceProfiler = DeviceProfiler(this)
        securityManager = SecurityManager(this)
        inferenceEngine = InferenceEngine(this)

        webSocketClient = WebSocketClient(
            context = this,
            serverUrl = "", // Will be set in onStartCommand
            deviceProfiler = deviceProfiler,
            securityManager = securityManager,
            onTaskAssigned = { task -> handleTaskAssignment(task) },
            onActivationReceived = { activation -> handleActivation(activation) },
            onThrottleCommand = { action -> handleThrottle(action) }
        )

        distributedCoordinator = DistributedCoordinator(
            context = this,
            inferenceEngine = inferenceEngine,
            webSocketClient = webSocketClient,
            securityManager = securityManager
        )

        webSocketClient.onConnectionStateChange = { connected ->
            val status = if (connected) "online" else "disconnected"
            updateNotification("Status: ${status.uppercase()}")
            onStatusUpdate?.invoke("connection", status)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                val serverUrl = intent.getStringExtra(EXTRA_SERVER_URL) ?: return START_NOT_STICKY
                startWorker(serverUrl)
            }
            ACTION_STOP -> {
                stopWorker()
            }
        }
        return START_STICKY // 如果被系统杀死，尝试重启
    }

    private fun startWorker(serverUrl: String) {
        if (isRunning) return
        isRunning = true

        // 创建通知渠道（Android 8+）
        createNotificationChannel()

        // 启动前台服务
        startForeground(NOTIFICATION_ID, buildNotification("Initializing..."))

        // 获取WakeLock防止Doze模式断网
        val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = powerManager.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "MDCS::WorkerWakeLock"
        )
        wakeLock?.acquire(10*60*1000L) // 10分钟

        // 更新WebSocket URL并连接
        webSocketClient = WebSocketClient(
            context = this,
            serverUrl = serverUrl,
            deviceProfiler = deviceProfiler,
            securityManager = securityManager,
            onTaskAssigned = { task -> handleTaskAssignment(task) },
            onActivationReceived = { activation -> handleActivation(activation) },
            onThrottleCommand = { action -> handleThrottle(action) }
        ).apply {
            onConnectionStateChange = { connected ->
                val status = if (connected) "online" else "disconnected"
                updateNotification("Status: ${status.uppercase()}")
                onStatusUpdate?.invoke("connection", status)
            }
        }

        webSocketClient.connect()

        // 启动低电量监控
        serviceScope.launch {
            monitorBatteryAndThrottle()
        }

        Timber.i("Worker started, connecting to $serverUrl")
    }

    private fun stopWorker() {
        isRunning = false
        webSocketClient.disconnect()
        inferenceEngine.release()
        distributedCoordinator.release()
        wakeLock?.release()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun handleTaskAssignment(task: TaskAssignment) {
        serviceScope.launch {
            onStatusUpdate?.invoke("task", "Running ${task.taskId} (layers ${task.layers})")
            distributedCoordinator.handleTaskAssignment(task)
        }
    }

    private fun handleActivation(activation: ActivationTransfer) {
        distributedCoordinator.handleActivationReceived(activation)
    }

    private fun handleThrottle(action: String) {
        when (action) {
            "reduce_freq" -> {
                // 降低CPU频率（需要root权限，实际中通过Thermal API或降低线程优先级）
                Timber.w("Throttling: reducing CPU frequency")
                android.os.Process.setThreadPriority(android.os.Process.myTid(), 10)
            }
            "stop_tasks" -> {
                // 低电量保护：停止接受新任务
                Timber.w("Throttling: stopping new tasks due to low battery")
            }
        }
    }

    /**
     * 监控电池状态：低电量自动退出集群
     */
    private suspend fun monitorBatteryAndThrottle() {
        while (isRunning) {
            val (percent, charging) = deviceProfiler.getBatteryStatus()

            when {
                percent < 10 && !charging -> {
                    // 电量极低：断开连接并退出集群
                    Timber.w("Battery critical ($percent%), disconnecting from cluster")
                    webSocketClient.reportError("LOW_BATTERY", null, "Battery below 10%, leaving cluster")
                    webSocketClient.disconnect()
                    onStatusUpdate?.invoke("battery", "critical")
                }
                percent < 20 && !charging -> {
                    // 低电量：请求Coordinator降低任务分配
                    onStatusUpdate?.invoke("battery", "low")
                }
                else -> {
                    onStatusUpdate?.invoke("battery", "ok")
                }
            }

            delay(30000) // 每30秒检查一次
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                getString(R.string.notification_channel),
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "MDCS Worker background service"
                setShowBadge(false)
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(content: String): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.notification_title))
            .setContentText(content)
            .setSmallIcon(android.R.drawable.ic_menu_compass)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    private fun updateNotification(content: String) {
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, buildNotification(content))
    }

    override fun onBind(intent: Intent): IBinder = binder

    override fun onDestroy() {
        super.onDestroy()
        serviceScope.cancel()
        webSocketClient.cleanup()
        inferenceEngine.release()
        distributedCoordinator.release()
        wakeLock?.release()
        Timber.i("WorkerService destroyed")
    }
}
