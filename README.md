# MDCS - Multi-Device Compute System

多设备算力共享系统：支持Android集群协同运行大语言模型（如Qwen-1.8B）。

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Coordinator (PC/Server)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ WebSocket    │  │ MCDM         │  │ Task Manager     │   │
│  │ Server       │  │ Scheduler    │  │ (Pipeline/Data)  │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ HTTP API     │  │ Security     │  │ Model Partition  │   │
│  │ (FastAPI)    │  │ (TLS/Pin)    │  │ (Qwen Config)    │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │ WebSocket+TLS │               │
              ▼               ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  Android Device │ │  Android Device │ │  Android Device │
│  (Worker Node)  │ │  (Worker Node)  │ │  (Worker Node)  │
│ ┌─────────────┐ │ │ ┌─────────────┐ │ │ ┌─────────────┐ │
│ │ Inference   │ │ │ │ Inference   │ │ │ │ Inference   │ │
│ │ Engine      │ │ │ │ Engine      │ │ │ │ Engine      │ │
│ │ (MNN/TFLite)│ │ │ │ (MNN/TFLite)│ │ │ │ (MNN/TFLite)│ │
│ └─────────────┘ │ │ └─────────────┘ │ │ └─────────────┘ │
│ ┌─────────────┐ │ │ ┌─────────────┐ │ │ ┌─────────────┐ │
│ │ WebSocket   │ │ │ │ WebSocket   │ │ │ │ WebSocket   │ │
│ │ Client      │ │ │ │ Client      │ │ │ │ Client      │ │
│ └─────────────┘ │ │ └─────────────┘ │ │ └─────────────┘ │
│ ┌─────────────┐ │ │ ┌─────────────┐ │ │ ┌─────────────┐ │
│ │ Memory Pool │ │ │ │ Memory Pool │ │ │ │ Memory Pool │ │
│ │ (Anti-OOM)  │ │ │ │ (Anti-OOM)  │ │ │ │ (Anti-OOM)  │ │
│ └─────────────┘ │ │ └─────────────┘ │ │ └─────────────┘ │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

## 项目结构

```
├── coordinator/              # 中心协调器（Python/FastAPI）
│   ├── src/
│   │   ├── main.py             # 入口点
│   │   ├── websocket_server.py # WebSocket服务器
│   │   ├── http_api.py         # REST API
│   │   ├── scheduler.py        # MCDM调度器（TOPSIS）
│   │   ├── device_manager.py   # 设备管理
│   │   ├── task_manager.py     # 任务管理
│   │   ├── security.py         # TLS/加密
│   │   └── models/
│   │       └── qwen_model.py   # 模型分割配置
│   ├── tests/                  # 单元/集成测试
│   ├── Dockerfile
│   └── requirements.txt
│
├── worker-android/             # Android工作节点
│   ├── app/src/main/java/com/compute/worker/
│   │   ├── MainActivity.kt      # 主界面
│   │   ├── WorkerService.kt     # 前台服务
│   │   ├── DeviceProfiler.kt  # 硬件信息采集
│   │   ├── SecurityManager.kt  # 安全/加密
│   │   ├── BootReceiver.kt    # 开机自启
│   │   ├── MdcsApplication.kt # 应用入口
│   │   ├── data/model/        # 数据模型
│   │   ├── network/           # WebSocket客户端
│   │   │   └── WebSocketClient.kt
│   │   ├── inference/         # 推理引擎
│   │   │   └── InferenceEngine.kt
│   │   └── distributed/       # 分布式协同
│   │       └── DistributedCoordinator.kt
│   └── app/src/main/cpp/      # Native桥接（NEON优化）
│
├── docker-compose.yml          # Docker编排
├── docs/                       # 文档
└── benchmarks/                 # 基准测试
```

## 快速开始

### 1. 部署协调器（Coordinator）

```bash
# 克隆项目
cd multi-device-compute

# 启动服务（Docker）
docker-compose up -d

# 或本地运行
cd coordinator
pip install -r requirements.txt
python -m src.main
```

协调器将监听：
- HTTP API: http://localhost:8080
- WebSocket: ws://localhost:8765
- Prometheus: http://localhost:9090

### 2. 部署工作节点（Android）

```bash
cd worker-android

# 使用Android Studio打开项目
# 或使用命令行
./gradlew assembleDebug

# 安装到设备
adb install app/build/outputs/apk/debug/app-debug.apk
```

### 3. 连接设备到集群

1. 打开MDCS Worker App
2. 输入协调器地址（如 `wss://192.168.1.100:8765`）
3. 点击"Join Cluster"
4. 设备将自动注册并开始接收任务

## API文档

### 提交推理任务
```bash
curl -X POST http://localhost:8080/api/v1/inference   -H "Content-Type: application/json"   -d '{
    "prompt": "请介绍一下量子计算",
    "max_tokens": 128,
    "temperature": 0.7,
    "model": "qwen-1.8b",
    "strategy": "auto"
  }'
```

响应：
```json
{
  "task_id": "task_1704067200000",
  "status": "queued",
  "estimated_duration_ms": 2500,
  "assigned_devices": ["dev_abc123", "dev_def456"]
}
```

### 查询任务状态
```bash
curl http://localhost:8080/api/v1/tasks/task_1704067200000
```

### 查看集群状态
```bash
curl http://localhost:8080/api/v1/cluster/stats
```

## 核心算法说明

### MCDM调度器（TOPSIS）

1. **构建决策矩阵**：每个设备作为一行，5个指标作为列
   - CPU性能（频率×核心数）
   - 可用内存
   - 电量状态（低电量惩罚）
   - 网络延迟倒数
   - 历史吞吐量

2. **向量标准化**：消除量纲影响

3. **加权标准化**：应用预设权重

4. **确定理想解**：
   - 正理想解：各指标最大值
   - 负理想解：各指标最小值

5. **计算欧氏距离**：每个设备到正负理想解的距离

6. **相对贴近度排序**：距离正理想解越近，得分越高

### 模型分割策略

- **流水线并行**：设备异构性高时选择，按能力比例分配连续层段
- **数据并行**：设备性能相近且数量≥4时选择，每个设备复制全部模型

## 安全特性

- **TLS 1.3**：所有通信加密
- **证书固定**：防止中间人攻击
- **设备指纹**：HMAC-SHA256硬件绑定验证
- **Snappy压缩**：减少网络传输量
- **低电量保护**：<10%自动断开，<20%降频

## 性能优化

- **内存池**：预分配ByteBuffer复用，防止OOM
- **分片加载**：按需加载模型层，减少内存占用
- **INT8量化**：模型体积减少75%，推理速度提升2-4x
- **NNAPI加速**：自动调用NPU/GPU
- **分层检查点**：每5层保存状态，支持快速迁移

## 测试

```bash
# 协调器测试
cd coordinator
pytest tests/ -v

# Android单元测试
./gradlew test

# 集成测试（需要2-5台真实设备）
# 1. 启动协调器
# 2. 连接所有设备
# 3. 运行benchmark API
```

## 参考文献

- CROWDio (MobiSys '24): Collaborative inference on Android clusters
- LinguaLinked (ArXiv 2024): Distributed LLM serving at the edge
- Exo: Open-source distributed AI framework
- MNN: Alibaba's mobile neural network inference engine

## License

MIT License
