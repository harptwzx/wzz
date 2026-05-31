# MDCS API 文档

## 基础信息
- Base URL: `http://localhost:8080/api/v1`
- WebSocket: `wss://localhost:8765`
- Content-Type: `application/json`

## 认证
当前版本使用设备指纹验证（WebSocket连接时）。未来版本将支持API Key。

## 端点详情

### POST /inference
提交分布式推理任务。

**请求体：**
```json
{
  "prompt": "请介绍一下量子计算",
  "max_tokens": 128,
  "temperature": 0.7,
  "top_p": 0.9,
  "model": "qwen-1.8b",
  "priority": 5,
  "strategy": "auto"
}
```

**参数说明：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| prompt | string | 是 | 输入提示词，1-4096字符 |
| max_tokens | int | 否 | 最大生成token数，默认128 |
| temperature | float | 否 | 采样温度，默认0.7 |
| top_p | float | 否 | 核采样概率，默认0.9 |
| model | string | 否 | 模型名称，默认qwen-1.8b |
| priority | int | 否 | 优先级1-10，默认5 |
| strategy | string | 否 | 并行策略：auto/pipeline/data |

**响应：**
```json
{
  "task_id": "task_1704067200000",
  "status": "queued",
  "created_at": 1704067200.0,
  "estimated_duration_ms": 2500,
  "assigned_devices": ["dev_abc123", "dev_def456"]
}
```

### GET /tasks/{task_id}
查询任务状态和结果。

**响应：**
```json
{
  "task_id": "task_1704067200000",
  "status": "completed",
  "progress": 1.0,
  "result": "量子计算是一种利用量子力学原理进行计算的技术...",
  "created_at": 1704067200.0,
  "completed_at": 1704067202.5,
  "devices": ["dev_abc123", "dev_def456"],
  "error": null
}
```

### GET /devices
获取集群中所有设备列表。

**响应：**
```json
[
  {
    "device_id": "dev_abc123",
    "device_name": "Xiaomi 14",
    "status": "online",
    "cpu_cores": 8,
    "available_ram_mb": 6144,
    "battery_percent": 85,
    "latency_ms": 12.5,
    "assigned_layers": [0, 1, 2, 3, 4, 5, 6, 7],
    "throughput_tokens_per_sec": 15.3
  }
]
```

### GET /cluster/stats
获取集群整体统计。

**响应：**
```json
{
  "total_devices": 5,
  "online_devices": 4,
  "busy_devices": 2,
  "total_ram_mb": 32768,
  "total_compute_score": 3.45,
  "active_tasks": 1,
  "queue_length": 0,
  "avg_latency_ms": 18.2
}
```

### POST /benchmark
运行集群基准测试。

**请求体：**
```json
{
  "devices": ["dev_abc123", "dev_def456"]
}
```
（不传则测试所有在线设备）

**响应：**
```json
{
  "benchmark_id": "bench_1704067200",
  "devices_tested": 2,
  "results": [
    {
      "device_id": "dev_abc123",
      "tokens_per_sec": 15.3,
      "latency_ms": 12.5,
      "ram_usage_percent": 45.2
    }
  ],
  "cluster_throughput": 28.7
}
```
