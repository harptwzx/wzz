package com.compute.worker

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Bundle
import android.os.IBinder
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import timber.log.Timber

/**
 * MainActivity
 * 工作节点主界面：显示设备状态、集群连接、任务信息
 */
class MainActivity : AppCompatActivity() {

    private lateinit var tvDeviceInfo: TextView
    private lateinit var tvStatus: TextView
    private lateinit var tvTasks: TextView
    private lateinit var etServerUrl: EditText
    private lateinit var btnConnect: Button
    private lateinit var btnDisconnect: Button

    private var workerService: WorkerService? = null
    private var isBound = false

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
            val binder = service as WorkerService.LocalBinder
            workerService = binder.getService()
            isBound = true

            workerService?.onStatusUpdate = { type, value ->
                runOnUiThread {
                    when (type) {
                        "connection" -> tvStatus.text = "Status: ${value.uppercase()}"
                        "task" -> tvTasks.text = "Task: $value"
                        "battery" -> {
                            val color = when (value) {
                                "critical" -> android.graphics.Color.RED
                                "low" -> android.graphics.Color.YELLOW
                                else -> android.graphics.Color.GREEN
                            }
                            tvStatus.setTextColor(color)
                        }
                    }
                }
            }
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            workerService = null
            isBound = false
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        initViews()
        displayDeviceInfo()
    }

    private fun initViews() {
        tvDeviceInfo = findViewById(R.id.tvDeviceInfo)
        tvStatus = findViewById(R.id.tvStatus)
        tvTasks = findViewById(R.id.tvTasks)
        etServerUrl = findViewById(R.id.etServerUrl)
        btnConnect = findViewById(R.id.btnConnect)
        btnDisconnect = findViewById(R.id.btnDisconnect)

        etServerUrl.setText("wss://192.168.1.100:8765")

        btnConnect.setOnClickListener {
            val url = etServerUrl.text.toString()
            if (url.isNotBlank()) {
                startAndBindService(url)
                btnConnect.isEnabled = false
                btnDisconnect.isEnabled = true
            } else {
                Toast.makeText(this, "Please enter server URL", Toast.LENGTH_SHORT).show()
            }
        }

        btnDisconnect.setOnClickListener {
            stopAndUnbindService()
            btnConnect.isEnabled = true
            btnDisconnect.isEnabled = false
            tvStatus.text = "Status: DISCONNECTED"
        }

        btnDisconnect.isEnabled = false
    }

    private fun displayDeviceInfo() {
        val profiler = DeviceProfiler(this)
        val (totalRam, availRam) = profiler.getMemoryInfo()
        val (battery, charging) = profiler.getBatteryStatus()

        val info = buildString {
            appendLine("Device: ${android.os.Build.MODEL}")
            appendLine("Android: ${android.os.Build.VERSION.RELEASE} (API ${android.os.Build.VERSION.SDK_INT})")
            appendLine("CPU: ${profiler.getCpuCores()} cores @ ${profiler.getCpuMaxFreqMhz().toInt()} MHz")
            appendLine("RAM: ${availRam}MB / ${totalRam}MB")
            appendLine("Battery: ${battery}% ${if (charging) "(Charging)" else ""}")
            appendLine("NPU: ${if (profiler.hasNpu()) "Yes" else "No"}")
            appendLine("GPU: ${if (profiler.hasGpu()) "Yes" else "No"}")
            appendLine("Device ID: ${SecurityManager(this@MainActivity).getDeviceId().take(8)}...")
        }

        tvDeviceInfo.text = info
    }

    private fun startAndBindService(serverUrl: String) {
        Intent(this, WorkerService::class.java).also { intent ->
            intent.action = WorkerService.ACTION_START
            intent.putExtra(WorkerService.EXTRA_SERVER_URL, serverUrl)
            startForegroundService(intent)
            bindService(intent, connection, Context.BIND_AUTO_CREATE)
        }
    }

    private fun stopAndUnbindService() {
        if (isBound) {
            unbindService(connection)
            isBound = false
        }
        Intent(this, WorkerService::class.java).also { intent ->
            intent.action = WorkerService.ACTION_STOP
            startService(intent)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        if (isBound) {
            unbindService(connection)
        }
    }
}
