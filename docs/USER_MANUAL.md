# MDCS 用户手册

## 系统要求

### 协调器（Coordinator）
- Docker 20.10+ 或 Python 3.11+
- 4GB RAM, 2 CPU cores
- 网络：与所有Worker节点可达

### 工作节点（Worker）
- Android 8.0+ (API 26+)
- 2GB+ RAM（推荐4GB+）
- 支持ARM64或ARMv7
- 可选：NPU/GPU加速（提升2-4x性能）

## 安装步骤

### 1. 安装协调器

**使用Docker（推荐）：**
```bash
# 1. 下载项目
git clone https://github.com/your-org/mdcs.git
cd mdcs

# 2. 生成TLS证书（生产环境使用真实CA证书）
mkdir -p certs
openssl req -x509 -newkey rsa:2048 -keyout certs/server.key \
  -out certs/server.crt -days 365 -nodes \
  -subj "/C=CN/O=MDCS/CN=mdcs-coordinator"

# 3. 启动服务
docker-compose up -d

# 4. 验证
 curl http://localhost:8080/health
```

**本地运行：**
```bash
cd coordinator
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m src.main
```

### 2. 安装工作节点

**从源码构建：**
```bash
cd worker-android

# 使用Android Studio打开项目
# 或命令行构建
./gradlew assembleDebug

# 安装到设备
adb install app/build/outputs/apk/debug/app-debug.apk
```

**配置证书固定：**
1. 将协调器证书复制到 `app/src/main/res/raw/coordinator_cert.crt`
2. 更新 `network_security_config.xml` 中的pin

## 使用指南

### 连接设备到集群

1. 打开MDCS Worker App
2. 在输入框中输入协调器地址：
   - 局域网：`wss://192.168.1.100:8765`
   - 公网：`wss://your-server.com:8765`
3. 点击"Join Cluster"
4. 等待状态变为"ONLINE"

### 提交推理任务

```bash
# 使用curl
curl -X POST http://<coordinator-ip>:8080/api/v1/inference \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "请写一首关于春天的诗",
    "max_tokens": 256,
    "model": "qwen-1.8b"
  }'

# 或使用Python
import requests
response = requests.post("http://localhost:8080/api/v1/inference", json={
    "prompt": "Explain quantum computing",
    "max_tokens": 128
})
print(response.json()["task_id"])
```

### 监控集群状态

打开浏览器访问 `http://<coordinator-ip>:8080/api/v1/cluster/stats`

### 查看设备信息

在Worker App主界面可查看：
- 设备型号和Android版本
- CPU核心数和频率
- 内存使用情况
- 电池状态
- NPU/GPU可用性

## 故障排除

### 设备无法连接
1. 检查协调器是否运行：`curl http://localhost:8080/health`
2. 检查防火墙：确保8765端口开放
3. 检查网络：确保设备与协调器在同一网络或路由可达
4. 检查证书：确保证书固定配置正确

### 推理速度慢
1. 检查设备性能：低端设备可能只有2-5 tokens/sec
2. 启用NPU/GPU：在代码中设置`useNpu=true`
3. 减少设备数量：过多设备会增加通信开销
4. 使用INT8量化：默认已启用

### OOM错误
1. 减少分配的层数
2. 启用内存池（默认已启用）
3. 关闭其他App释放内存
4. 使用更小模型（qwen-0.5b）

### 低电量断开
- 这是正常保护机制
- 连接充电器后可重新加入集群
- 可在设置中调整低电量阈值

## 高级配置

### 自定义模型
1. 将模型转换为MNN/TFLite格式
2. 按层分割为多个文件
3. 更新`coordinator/src/models/qwen_model.py`中的配置
4. 重新部署协调器

### 调整调度权重
编辑`coordinator/src/scheduler.py`中的`WEIGHTS`字典：
```python
WEIGHTS = {
    "cpu": 0.30,      # 提高CPU权重
    "memory": 0.15,
    "battery": 0.20,  # 提高电量权重
    "latency": 0.20,
    "history": 0.15
}
```

### 修改心跳间隔
在`WebSocketClient.kt`中：
```kotlin
private const val HEARTBEAT_INTERVAL_MS = 5000L  // 改为10000L即10秒
```
