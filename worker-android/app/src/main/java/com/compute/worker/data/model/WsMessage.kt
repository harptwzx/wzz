package com.compute.worker.data.model

import com.google.gson.annotations.SerializedName

/**
 * WebSocket消息基类
 */
sealed class WsMessage {
    abstract val type: String
}

/**
 * 注册请求
 */
data class RegisterMessage(
    @SerializedName("type") override val type: String = "REGISTER",
    @SerializedName("device_id") val deviceId: String,
    @SerializedName("device_name") val deviceName: String,
    @SerializedName("android_version") val androidVersion: String,
    @SerializedName("sdk_level") val sdkLevel: Int,
    @SerializedName("cpu_cores") val cpuCores: Int,
    @SerializedName("cpu_freq_mhz") val cpuFreqMhz: Float,
    @SerializedName("total_ram_mb") val totalRamMb: Int,
    @SerializedName("available_ram_mb") val availableRamMb: Int,
    @SerializedName("battery_percent") val batteryPercent: Int,
    @SerializedName("is_charging") val isCharging: Boolean,
    @SerializedName("has_npu") val hasNpu: Boolean,
    @SerializedName("has_gpu") val hasGpu: Boolean,
    @SerializedName("network_type") val networkType: String,
    @SerializedName("fingerprint") val fingerprint: String
) : WsMessage()

/**
 * 心跳包
 */
data class HeartbeatMessage(
    @SerializedName("type") override val type: String = "HEARTBEAT",
    @SerializedName("available_ram_mb") val availableRamMb: Int,
    @SerializedName("battery_percent") val batteryPercent: Int,
    @SerializedName("is_charging") val isCharging: Boolean,
    @SerializedName("status") val status: String,
    @SerializedName("timestamp") val timestamp: Long = System.currentTimeMillis()
) : WsMessage()

/**
 * Pong响应（延迟测试）
 */
data class PongMessage(
    @SerializedName("type") override val type: String = "PONG",
    @SerializedName("sent_time") val sentTime: Double
) : WsMessage()

/**
 * 错误报告
 */
data class ErrorReportMessage(
    @SerializedName("type") override val type: String = "ERROR_REPORT",
    @SerializedName("error_code") val errorCode: String,
    @SerializedName("task_id") val taskId: String? = null,
    @SerializedName("message") val message: String
) : WsMessage()
