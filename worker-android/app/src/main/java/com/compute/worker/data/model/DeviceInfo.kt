package com.compute.worker.data.model

import com.google.gson.annotations.SerializedName

/**
 * 设备信息数据类
 * 用于注册时上报给Coordinator
 */
data class DeviceInfo(
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
)
