package com.compute.worker.data.model

import com.google.gson.annotations.SerializedName

/**
 * 任务分配数据类
 * Coordinator下发的推理任务
 */
data class TaskAssignment(
    @SerializedName("type") val type: String = "TASK_ASSIGN",
    @SerializedName("task_id") val taskId: String,
    @SerializedName("layers") val layers: List<Int>,
    @SerializedName("input") val input: String,
    @SerializedName("max_tokens") val maxTokens: Int,
    @SerializedName("temperature") val temperature: Float,
    @SerializedName("is_first") val isFirst: Boolean,
    @SerializedName("is_last") val isLast: Boolean,
    @SerializedName("model") val model: String,
    @SerializedName("shard_id") val shardId: Int = 0,
    @SerializedName("total_shards") val totalShards: Int = 1
)

/**
 * 任务结果回传
 */
data class TaskResult(
    @SerializedName("type") val type: String = "TASK_RESULT",
    @SerializedName("task_id") val taskId: String,
    @SerializedName("layer_index") val layerIndex: Int,
    @SerializedName("result") val result: String,
    @SerializedName("output_activation") val outputActivation: String? = null, // base64 compressed
    @SerializedName("next_device") val nextDevice: String? = null
)

/**
 * 中间激活值传输（流水线并行）
 */
data class ActivationTransfer(
    @SerializedName("type") val type: String = "ACTIVATION_SEND",
    @SerializedName("task_id") val taskId: String,
    @SerializedName("target_device") val targetDevice: String,
    @SerializedName("activation") val activation: String, // base64 snappy compressed
    @SerializedName("shape") val shape: List<Int>,
    @SerializedName("dtype") val dtype: String = "float32"
)
