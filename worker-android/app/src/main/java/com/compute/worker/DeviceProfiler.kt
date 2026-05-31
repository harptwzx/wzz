package com.compute.worker

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.SystemClock
import timber.log.Timber
import java.io.File
import java.io.RandomAccessFile
import java.util.regex.Pattern

/**
 * DeviceProfiler
 * 实时采集设备硬件信息：CPU、内存、电量、网络状态
 * 用于注册上报和心跳更新
 */
class DeviceProfiler(private val context: Context) {

    private val activityManager = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager

    /**
     * 获取CPU核心数
     */
    fun getCpuCores(): Int {
        return Runtime.getRuntime().availableProcessors()
    }

    /**
     * 获取CPU最大频率（MHz）
     * 读取 /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq
     */
    fun getCpuMaxFreqMhz(): Float {
        return try {
            val file = File("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
            if (file.exists()) {
                val freqKhz = file.readText().trim().toLong()
                freqKhz / 1000f
            } else {
                // Fallback: estimate based on device model
                estimateFreqFromModel()
            }
        } catch (e: Exception) {
            Timber.w(e, "Failed to read CPU freq")
            estimateFreqFromModel()
        }
    }

    private fun estimateFreqFromModel(): Float {
        return when {
            Build.BOARD?.contains("gold") == true -> 3000f  // Snapdragon 8 series
            Build.BOARD?.contains("silver") == true -> 2300f
            else -> 2000f
        }
    }

    /**
     * 获取内存信息
     */
    fun getMemoryInfo(): Pair<Int, Int> { // total, available (MB)
        val memInfo = ActivityManager.MemoryInfo()
        activityManager.getMemoryInfo(memInfo)

        val totalMb = (memInfo.totalMem / (1024 * 1024)).toInt()
        val availMb = (memInfo.availMem / (1024 * 1024)).toInt()
        return Pair(totalMb, availMb)
    }

    /**
     * 获取电池状态
     */
    fun getBatteryStatus(): Pair<Int, Boolean> { // percent, isCharging
        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = intent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: 0
        val scale = intent?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: 100
        val percent = (level * 100 / scale)

        val status = intent?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: 0
        val isCharging = status == BatteryManager.BATTERY_STATUS_CHARGING ||
                          status == BatteryManager.BATTERY_STATUS_FULL

        return Pair(percent, isCharging)
    }

    /**
     * 检测NPU可用性
     * 通过检查nnapi或特定so库
     */
    fun hasNpu(): Boolean {
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.P &&
               context.packageManager.hasSystemFeature("android.hardware.neuralnetworks")
    }

    /**
     * 检测GPU可用性（通过GLES版本推断）
     */
    fun hasGpu(): Boolean {
        val activityManager = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        return activityManager.deviceConfigurationInfo?.reqGlEsVersion ?: 0 >= 0x30000
    }

    /**
     * 获取网络类型
     */
    fun getNetworkType(): String {
        // Simplified - in production use ConnectivityManager
        return "wifi" // or "5g", "4g", "3g"
    }

    /**
     * 生成设备指纹
     * 基于硬件标识的HMAC-SHA256（与Coordinator验证匹配）
     */
    fun generateFingerprint(deviceId: String, secret: String): String {
        val hardwareSerial = Build.SERIAL ?: Build.ID ?: "unknown"
        val message = "$deviceId:$hardwareSerial"

        val mac = javax.crypto.Mac.getInstance("HmacSHA256")
        val key = javax.crypto.spec.SecretKeySpec(secret.toByteArray(), "HmacSHA256")
        mac.init(key)
        val hash = mac.doFinal(message.toByteArray())

        return hash.joinToString("") { "%02x".format(it) }
    }

    /**
     * 获取CPU温度（如果可用）
     */
    fun getCpuTemperature(): Float {
        return try {
            val temp = File("/sys/class/thermal/thermal_zone0/temp").readText().trim().toFloat()
            temp / 1000f
        } catch (e: Exception) {
            0f
        }
    }

    /**
     * 获取当前CPU使用率（采样方式）
     */
    fun getCpuUsagePercent(): Float {
        return try {
            val reader = RandomAccessFile("/proc/stat", "r")
            val load = reader.readLine()
            reader.close()

            val toks = load.split(" ").filter { it.isNotEmpty() }
            val idle = toks[4].toLong()
            val cpu = toks[1].toLong() + toks[2].toLong() + toks[3].toLong()

            // Simplified - would need two samples for accurate calculation
            (cpu.toFloat() / (cpu + idle)) * 100f
        } catch (e: Exception) {
            0f
        }
    }
}
