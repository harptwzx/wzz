package com.compute.worker.inference

import android.content.Context
import android.os.Build
import com.compute.worker.data.model.TaskAssignment
import com.compute.worker.data.model.TaskResult
import com.compute.worker.data.model.ActivationTransfer
import kotlinx.coroutines.*
import timber.log.Timber
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

/**
 * InferenceEngine
 * 端侧推理引擎核心
 * - 基于MNN/TensorFlow Lite的抽象层
 * - 支持INT8量化模型
 * - 接入NNAPI调用NPU/GPU
 * - 内存池管理防止OOM
 * - 分片加载大模型
 */
class InferenceEngine(private val context: Context) {

    companion object {
        private const val MEMORY_POOL_SIZE_MB = 512
        private const val CHECKPOINT_INTERVAL_LAYERS = 5
    }

    // 模型层缓存：layer_index -> ModelRunner
    private val layerRunners = ConcurrentHashMap<Int, ModelRunner>()

    // 内存池：预分配ByteBuffer复用
    private val memoryPool = MemoryPool(MEMORY_POOL_SIZE_MB)

    // 当前任务状态
    private val activeTasks = ConcurrentHashMap<String, TaskState>()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    // 检查点存储：task_id -> {layer_index -> activation_bytes}
    private val checkpoints = ConcurrentHashMap<String, MutableMap<Int, ByteArray>>()

    // 回调接口
    var onLayerComplete: ((TaskResult) -> Unit)? = null
    var onActivationReady: ((ActivationTransfer, ByteArray) -> Unit)? = null
    var onError: ((String, String?, String) -> Unit)? = null

    /**
     * 初始化引擎：加载模型配置
     */
    fun initialize(modelName: String, quantization: String = "int8") {
        Timber.i("Initializing inference engine for $modelName (quantization: $quantization)")
        // 在实际实现中，这里会加载模型文件并构建Interpreter
    }

    /**
     * 执行分配的任务（流水线并行模式）
     */
    fun executeTask(task: TaskAssignment, inputActivation: ByteArray? = null) {
        scope.launch {
            try {
                val taskState = TaskState(
                    taskId = task.taskId,
                    layers = task.layers,
                    currentLayer = 0,
                    startTime = System.currentTimeMillis()
                )
                activeTasks[task.taskId] = taskState

                var currentInput = if (task.isFirst) {
                    // 第一层：将文本token转换为embedding
                    tokenizeAndEmbed(task.input)
                } else {
                    inputActivation ?: throw IllegalStateException("Missing input activation for non-first layer")
                }

                for (layerIndex in task.layers) {
                    // 检查内存压力
                    if (memoryPool.isLowMemory()) {
                        Timber.w("Low memory detected, triggering GC and cache eviction")
                        evictOldLayers()
                    }

                    // 加载模型层（如果未缓存）
                    val runner = loadLayerRunner(layerIndex, task.model)

                    // 执行推理
                    val output = runner.run(currentInput)

                    // 更新进度
                    taskState.currentLayer++

                    // 保存检查点（每5层）
                    if (layerIndex % CHECKPOINT_INTERVAL_LAYERS == 0) {
                        saveCheckpoint(task.taskId, layerIndex, output)
                    }

                    // 释放输入内存回池
                    memoryPool.release(currentInput)
                    currentInput = output

                    // 发送层完成通知
                    onLayerComplete?.invoke(TaskResult(
                        taskId = task.taskId,
                        layerIndex = layerIndex,
                        result = "layer_complete",
                        outputActivation = null,
                        nextDevice = null
                    ))
                }

                // 如果是最后一层，生成最终结果
                if (task.isLast) {
                    val resultText = generateOutput(currentInput)
                    onLayerComplete?.invoke(TaskResult(
                        taskId = task.taskId,
                        layerIndex = task.layers.last(),
                        result = resultText,
                        outputActivation = null,
                        nextDevice = null
                    ))
                    memoryPool.release(currentInput)
                } else {
                    // 不是最后一层：发送中间激活值到下一个设备
                    val nextDevice = findNextDevice(task.taskId, task.layers.last())
                    if (nextDevice != null) {
                        val transfer = ActivationTransfer(
                            taskId = task.taskId,
                            targetDevice = nextDevice,
                            activation = "", // Will be filled by callback
                            shape = listOf(1, 1, 2048), // Qwen-1.8B hidden size
                            dtype = "float32"
                        )
                        onActivationReady?.invoke(transfer, currentInput)
                    }
                }

                activeTasks.remove(task.taskId)
                Timber.i("Task ${task.taskId} completed in ${System.currentTimeMillis() - taskState.startTime}ms")

            } catch (e: OutOfMemoryError) {
                Timber.e(e, "OOM during inference")
                handleOOM(task.taskId)
                onError?.invoke("OOM", task.taskId, e.message ?: "Out of memory")
            } catch (e: Exception) {
                Timber.e(e, "Inference error")
                onError?.invoke("INFERENCE_ERROR", task.taskId, e.message ?: "Unknown error")
            }
        }
    }

    /**
     * 加载模型层运行器（分片加载）
     */
    private fun loadLayerRunner(layerIndex: Int, modelName: String): ModelRunner {
        return layerRunners.getOrPut(layerIndex) {
            Timber.d("Loading layer $layerIndex for $modelName")
            // 实际实现：从assets或下载目录加载.tflite/.mnn模型分片
            ModelRunner(layerIndex, modelName, useNpu = true, useGpu = true)
        }
    }

    /**
     * 分词并生成Embedding（第一层）
     */
    private fun tokenizeAndEmbed(text: String): ByteArray {
        // 简化实现：实际应使用SentencePiece或BERT tokenizer
        // 返回float32数组的byte表示
        val hiddenSize = 2048
        val buffer = memoryPool.allocate(hiddenSize * 4)
        // 填充模拟数据（实际应为真实embedding）
        val floatBuffer = buffer.asFloatBuffer()
        for (i in 0 until hiddenSize) {
            floatBuffer.put(i, 0.0f) // Placeholder
        }
        return buffer.array()
    }

    /**
     * 从激活值生成输出文本（最后一层）
     */
    private fun generateOutput(activation: ByteArray): String {
        // 简化实现：实际应通过LM head生成token概率分布
        return "[Generated output from activation]"
    }

    /**
     * 保存分层检查点
     */
    private fun saveCheckpoint(taskId: String, layerIndex: Int, activation: ByteArray) {
        val taskCheckpoints = checkpoints.getOrPut(taskId) { mutableMapOf() }
        taskCheckpoints[layerIndex] = activation.copyOf()
        Timber.d("Checkpoint saved for task $taskId at layer $layerIndex")
    }

    /**
     * 获取检查点（用于任务迁移恢复）
     */
    fun getCheckpoint(taskId: String, layerIndex: Int): ByteArray? {
        return checkpoints[taskId]?.get(layerIndex)
    }

    /**
     * 查找下一个设备（流水线中的下一个节点）
     */
    private fun findNextDevice(taskId: String, currentLayer: Int): String? {
        // 实际应从Coordinator获取流水线拓扑
        return null
    }

    /**
     * 处理OOM：释放缓存和检查点
     */
    private fun handleOOM(taskId: String) {
        layerRunners.clear()
        memoryPool.clear()
        checkpoints[taskId]?.clear()
        System.gc()
    }

    /**
     * 释放旧层缓存（LRU策略）
     */
    private fun evictOldLayers() {
        if (layerRunners.size > 4) {
            val oldest = layerRunners.keys.minOrNull() ?: return
            layerRunners.remove(oldest)
            Timber.d("Evicted layer $oldest from cache")
        }
    }

    /**
     * 清理任务资源
     */
    fun cleanupTask(taskId: String) {
        activeTasks.remove(taskId)
        checkpoints.remove(taskId)
    }

    /**
     * 释放所有资源
     */
    fun release() {
        scope.cancel()
        layerRunners.clear()
        memoryPool.clear()
        checkpoints.clear()
    }

    // ===== 内部类 =====

    /**
     * 模型层运行器（MNN/TFLite抽象）
     */
    inner class ModelRunner(
        private val layerIndex: Int,
        private val modelName: String,
        private val useNpu: Boolean,
        private val useGpu: Boolean
    ) {
        // 实际实现中持有Interpreter实例
        // private val interpreter: Interpreter (TFLite) or MNN.Session (MNN)

        fun run(input: ByteArray): ByteArray {
            // 模拟推理延迟（实际调用MNN/TFLite）
            val outputSize = 2048 * 4 // float32 hidden state
            val output = memoryPool.allocate(outputSize)

            // 模拟计算耗时
            Thread.sleep(50) // ~20 layers/sec on mid-range device

            return output.array()
        }
    }

    /**
     * 内存池管理器
     * 预分配大ByteBuffer并复用，防止频繁GC和OOM
     */
    inner class MemoryPool(private val maxSizeMb: Int) {
        private val pool = ArrayDeque<ByteBuffer>()
        private val used = AtomicInteger(0)
        private val maxBytes = maxSizeMb * 1024 * 1024

        fun allocate(size: Int): ByteBuffer {
            synchronized(pool) {
                // 尝试复用池中buffer
                val iterator = pool.iterator()
                while (iterator.hasNext()) {
                    val buffer = iterator.next()
                    if (buffer.capacity() >= size) {
                        iterator.remove()
                        buffer.clear()
                        used.addAndGet(size)
                        return buffer
                    }
                }
            }

            // 池中没有合适的，分配新的
            used.addAndGet(size)
            return ByteBuffer.allocateDirect(size).order(ByteOrder.nativeOrder())
        }

        fun release(buffer: ByteArray) {
            // ByteArray无法直接回池，仅减少计数
            used.addAndGet(-buffer.size)
        }

        fun release(buffer: ByteBuffer) {
            synchronized(pool) {
                if (used.get() < maxBytes) {
                    pool.addLast(buffer)
                }
            }
            used.addAndGet(-buffer.capacity())
        }

        fun isLowMemory(): Boolean {
            val runtime = Runtime.getRuntime()
            val usedMem = (runtime.totalMemory() - runtime.freeMemory()) / (1024 * 1024)
            val maxMem = runtime.maxMemory() / (1024 * 1024)
            return usedMem > maxMem * 0.85 // 85%内存使用率警告
        }

        fun clear() {
            synchronized(pool) {
                pool.clear()
            }
            used.set(0)
        }
    }

    data class TaskState(
        val taskId: String,
        val layers: List<Int>,
        @Volatile var currentLayer: Int,
        val startTime: Long
    )
}
