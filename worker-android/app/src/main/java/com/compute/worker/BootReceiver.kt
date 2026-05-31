package com.compute.worker

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import timber.log.Timber

/**
 * BootReceiver
 * 设备重启后自动启动Worker服务（如果之前已配置）
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            Timber.i("Boot completed, checking if auto-start is enabled")

            // 检查SharedPreferences中是否启用了自动启动
            val prefs = context.getSharedPreferences("mdcs_prefs", Context.MODE_PRIVATE)
            val autoStart = prefs.getBoolean("auto_start", false)
            val lastServerUrl = prefs.getString("last_server_url", null)

            if (autoStart && !lastServerUrl.isNullOrBlank()) {
                Timber.i("Auto-starting WorkerService with $lastServerUrl")
                Intent(context, WorkerService::class.java).also {
                    it.action = WorkerService.ACTION_START
                    it.putExtra(WorkerService.EXTRA_SERVER_URL, lastServerUrl)
                    context.startForegroundService(it)
                }
            }
        }
    }
}
