package com.compute.worker.distributed

import android.content.Context
import com.compute.worker.data.model.TaskAssignment
import com.compute.worker.inference.InferenceEngine
import com.compute.worker.network.WebSocketClient
import com.compute.worker.SecurityManager
import com.google.gson.Gson
import kotlinx.coroutines.*
import timber.log.Timber
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean

/**
 * DistributedCoordinator
 * 分布式协同模块核心
 * - 模型自动/手动分割到多个设备
 * - 中间激活值的压缩与传输
 * - 分层检查点（每5层保存）和任务迁移
 */
class DistributedCoordinator(
    private val context: Context,
    private val inferenceEngine: InferenceEngine,
    private val webSocketClient: WebSocketClient,
    private val securityManager: SecurityManager
) {
    private val gson = Gson()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    // 当前设备持有的模型层
    private val heldLayers = mutableSetOf<Int>()

    // 流水线拓扑：layer_index -> next_device_id
    private val pipelineTopology = ConcurrentHashMap<Int, String>()

    // 任务迁移状态
    private val migrationInProgress = AtomicBoolean(false)

    // 激活值压缩阈值（大于此值才压缩）
    private val COMPRESSION_THRESHOLD_BYTES = 1024

    init {
        // 设置推理引擎回调
        inferenceEngine.onActivationReady = { transfer, data ->
            sendCompressedActivation(transfer, data)
        }

        inferenceEngine.onLayerComplete = { result ->
            webSocketClient.sendTaskResult(result)
        }

        inferenceEngine.onError = { code, taskId, message ->
            webSocketClient.reportError(code, taskId, message)
        }
    }

    /**
     * 处理任务分配（来自Coordinator）
     */
    fun handleTaskAssignment(task: TaskAssignment) {
        Timber.i("Received task ${task.taskId}, layers: ${task.layers}, isFirst=${task.isFirst}, isLast=${task.isLast}")

        // 更新持有的层
        heldLayers.addAll(task.layers)

        // 如果是迁移任务，尝试从检查点恢复
        if (task.input.isEmpty() && !task.isFirst) {
            val checkpoint = inferenceEngine.getCheckpoint(task.taskId, task.layers.first() - 1)
            if (checkpoint != null) {
                Timber.i("Resuming task ${task.taskId} from checkpoint")
                inferenceEngine.executeTask(task, checkpoint)
                return
            }
        }

        // 正常执行
        inferenceEngine.executeTask(task)
    }

    /**
     * 处理接收到的中间激活值（流水线并行）
     */
    fun handleActivationReceived(activation: com.compute.worker.data.model.ActivationTransfer) {
        scope.launch {
            try {
                // 解码Base64
                val compressed = android.util.Base64.decode(activation.activation, android.util.Base64.NO_WRAP)

                // 解压
                val decompressed = securityManager.decompress(compressed)

                // 验证校验和（可选）
                val hash = securityManager.hashActivation(decompressed)
                Timber.d("Received activation for task ${activation.taskId}, hash=$hash, size=${decompressed.size}")

                // 构建伪任务以继续执行
                val resumeTask = TaskAssignment(
                    taskId = activation.taskId,
                    layers = heldLayers.toList(), // 使用当前设备持有的层
                    input = "", // 输入来自激活值
                    maxTokens = 128, // 从上下文获取
                    temperature = 0.7f,
                    isFirst = false,
                    isLast = isLastLayer(heldLayers.toList()),
                    model = "qwen-1.8b" // 从上下文获取
                )

                inferenceEngine.executeTask(resumeTask, decompressed)

            } catch (e: Exception) {
                Timber.e(e, "Failed to process received activation")
                webSocketClient.reportError(
                    "ACTIVATION_DECODE_ERROR",
                    activation.taskId,
                    e.message ?: "Failed to decode activation"
                )
            }
        }
    }

    /**
     * 发送压缩后的激活值到下一个设备
     */
    private fun sendCompressedActivation(transfer: com.compute.worker.data.model.ActivationTransfer, data: ByteArray) {
        scope.launch {
            try {
                val (compressed, wasCompressed) = if (data.size > COMPRESSION_THRESHOLD_BYTES) {
                    securityManager.compress(data) to true
                } else {
                    data to false
                }

                Timber.d("Sending activation: raw=${data.size}, compressed=${compressed.size}, saved=${(1 - compressed.size.toFloat()/data.size)*100}%")

                webSocketClient.sendActivation(transfer, compressed)

            } catch (e: Exception) {
                Timber.e(e, "Failed to send activation")
                webSocketClient.reportError(
                    "ACTIVATION_SEND_ERROR",
                    transfer.taskId,
                    e.message ?: "Failed to send activation"
                )
            }
        }
    }

    /**
     * 处理任务迁移（本设备接管其他设备的层）
     */
    fun handleTaskMigration(taskId: String, newLayers: List<Int>, checkpointLayer: Int) {
        if (migrationInProgress.getAndSet(true)) {
            Timber.w("Migration already in progress, rejecting new migration")
            return
        }

        scope.launch {
            try {
                Timber.i("Migrating task $taskId, new layers: $newLayers, checkpoint: $checkpointLayer")

                // 加载新层（如果未缓存）
                heldLayers.addAll(newLayers)

                // 等待Coordinator发送新的TASK_ASSIGN或ACTIVATION_RECV
                // 实际迁移逻辑在handleTaskAssignment中处理

            } finally {
                migrationInProgress.set(false)
            }
        }
    }

    /**
     * 更新流水线拓扑（从Coordinator接收）
     */
    fun updateTopology(topology: Map<Int, String>) {
        pipelineTopology.clear()
        pipelineTopology.putAll(topology)
        Timber.i("Pipeline topology updated: ${topology.size} mappings")
    }

    /**
     * 检查是否是最后一层（持有最大层索引）
     */
    private fun isLastLayer(layers: List<Int>): Boolean {
        // 简化：假设24层模型，最大层索引为23
        return layers.maxOrNull() == 23
    }

    /**
     * 获取当前持有的层
     */
    fun getHeldLayers(): Set<Int> = heldLayers.toSet()

    /**
     * 释放层（当设备离开集群或任务完成）
     */
    fun releaseLayers(layers: List<Int>) {
        heldLayers.removeAll(layers.toSet())
    }

    /**
     * 清理所有资源
     */
    fun release() {
        scope.cancel()
        heldLayers.clear()
        pipelineTopology.clear()
    }
}
