# MDCS 架构设计文档

## 1. 系统概述

MDCS（Multi-Device Compute System）是一个支持多Android设备算力聚合的分布式推理系统。系统采用"中心协调器 + 工作节点"架构，能够将大语言模型（如Qwen-1.8B）的推理负载分散到多台设备上执行。

## 2. 通信协议

### 2.1 WebSocket协议（长连接）

| 消息类型 | 方向 | 说明 |
|---------|------|------|
| REGISTER | Worker → Coordinator | 设备注册，上报硬件信息 |
| REGISTER_ACK | Coordinator → Worker | 注册确认，下发配置 |
| HEARTBEAT | Worker → Coordinator | 心跳包（5秒间隔） |
| HEARTBEAT_ACK | Coordinator → Worker | 心跳确认 |
| PING | Coordinator → Worker | 延迟测试请求 |
| PONG | Worker → Coordinator | 延迟测试响应 |
| TASK_ASSIGN | Coordinator → Worker | 任务分配 |
| TASK_RESULT | Worker → Coordinator | 结果回传 |
| ACTIVATION_SEND | Worker → Worker | 中间激活值传输 |
| ACTIVATION_RECV | Coordinator → Worker | 转发激活值 |
| TASK_MIGRATE | Coordinator → Worker | 任务迁移指令 |
| THROTTLE | Coordinator → Worker | 降频/停止指令 |
| ERROR_REPORT | Worker → Coordinator | 错误报告 |

### 2.2 HTTP REST API

| 端点 | 方法 | 说明 |
|------|------|------|
| /health | GET | 健康检查 |
| /api/v1/inference | POST | 提交推理任务 |
| /api/v1/tasks/{id} | GET | 查询任务状态 |
| /api/v1/devices | GET | 设备列表 |
| /api/v1/cluster/stats | GET | 集群统计 |
| /api/v1/benchmark | POST | 运行基准测试 |

## 3. 调度算法

### 3.1 TOPSIS多标准决策

**指标与权重：**
- CPU计算能力：25%
- 可用内存：20%
- 电量状态：15%（低电量惩罚）
- 网络延迟：20%
- 历史性能：20%

**算法流程：**
1. 构建n×5决策矩阵
2. 向量标准化：rij = xij / √(Σxij²)
3. 加权：vij = wj × rij
4. 确定正理想解A+和负理想解A-
5. 计算欧氏距离Di+和Di-
6. 贴近度：Ci = Di- / (Di+ + Di-)

### 3.2 并行策略选择

| 条件 | 策略 | 说明 |
|------|------|------|
| CV > 0.3 | Pipeline | 设备异构性高 |
| 设备≥4且性能>0.6 | Data | 同构高性能设备 |
| 默认 | Pipeline | 保守选择 |

## 4. 容错机制

### 4.1 断线重连
- 宽限期：30秒
- 指数退避重连：3s, 6s, 9s, 12s, 15s
- 最大重试：10次

### 4.2 任务迁移
- 触发条件：设备故障报告/心跳超时
- 恢复点：最近检查点（每5层）
- 迁移目标：TOPSIS得分最高的可用设备

### 4.3 低电量保护
- <20%：降频，减少任务分配
- <10%：自动断开，迁移任务

## 5. 安全设计

### 5.1 通信安全
- TLS 1.3加密
- 证书固定（SHA-256公钥指纹）
- 自签名证书（开发）/ CA证书（生产）

### 5.2 设备认证
- 设备指纹 = HMAC-SHA256(device_id + hardware_serial, secret)
- 防止非法设备接入

### 5.3 数据安全
- AES-256-GCM加密敏感数据
- Snappy压缩减少传输
- 激活值校验和验证

## 6. 性能优化

### 6.1 推理优化
- INT8量化：体积-75%，速度+2-4x
- NNAPI加速：自动调用NPU/GPU
- 内存池：预分配复用，防止OOM
- 分片加载：按需加载模型层

### 6.2 网络优化
- Snappy压缩：比zlib快，压缩率适中
- 批量传输：合并小消息
- 二进制协议：激活值直接传输

## 7. 部署架构

```
┌─────────────────────────────────────────┐
│              Docker Host                 │
│  ┌─────────────┐    ┌─────────────┐    │
│  │ Coordinator │◄──►│   Redis     │    │
│  │  (Python)   │    │  (State)    │    │
│  └─────────────┘    └─────────────┘    │
│         ▲                               │
│         │ WebSocket/TLS                 │
│    ┌────┴────┬────────┬────────┐       │
│    ▼         ▼        ▼        ▼       │
│ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐   │
│ │Phone1│ │Phone2│ │Phone3│ │Phone4│   │
│ │Worker│ │Worker│ │Worker│ │Worker│   │
│ └──────┘ └──────┘ └──────┘ └──────┘   │
└─────────────────────────────────────────┘
```
