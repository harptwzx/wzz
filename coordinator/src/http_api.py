"""
HTTP REST API Module
提供任务提交、状态查询、设备管理、模型配置等接口
"""
import json
import logging
import time
from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends

logger = logging.getLogger("MDCS.HTTP")
router = APIRouter()

# ===== Request/Response Models =====
class InferenceRequest(BaseModel):
    """推理请求模型"""
    prompt: str = Field(..., min_length=1, max_length=4096, description="输入提示词")
    max_tokens: int = Field(128, ge=1, le=2048, description="最大生成token数")
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    top_p: float = Field(0.9, ge=0.0, le=1.0)
    model: str = Field("qwen-1.8b", description="模型名称")
    priority: int = Field(5, ge=1, le=10, description="任务优先级")
    strategy: str = Field("auto", description="并行策略: auto/pipeline/data")

class TaskResponse(BaseModel):
    """任务响应模型"""
    task_id: str
    status: str
    created_at: float
    estimated_duration_ms: int
    assigned_devices: List[str]

class DeviceStatusResponse(BaseModel):
    """设备状态响应"""
    device_id: str
    device_name: str
    status: str
    cpu_cores: int
    available_ram_mb: int
    battery_percent: int
    latency_ms: float
    assigned_layers: List[int]
    throughput_tokens_per_sec: float

class ClusterStatsResponse(BaseModel):
    """集群统计响应"""
    total_devices: int
    online_devices: int
    busy_devices: int
    total_ram_mb: int
    total_compute_score: float
    active_tasks: int
    queue_length: int
    avg_latency_ms: float

# ===== API Endpoints =====

@router.post("/inference", response_model=TaskResponse)
async def submit_inference(request: InferenceRequest, background_tasks: BackgroundTasks):
    """
    提交分布式推理任务

    流程：
    1. 接收请求并验证参数
    2. 调度器根据集群状态选择最优策略（流水线/数据并行）
    3. 任务管理器拆分模型层并分配到设备
    4. 返回task_id供轮询结果
    """
    from main import state

    task_id = f"task_{int(time.time() * 1000)}"
    logger.info(f"Received inference request: {task_id}, model={request.model}, strategy={request.strategy}")

    # Check cluster capacity
    online_devices = state.device_manager.get_online_devices()
    if len(online_devices) == 0:
        raise HTTPException(status_code=503, detail="No devices online in cluster")

    # Create task
    task = await state.task_manager.create_task(
        task_id=task_id,
        prompt=request.prompt,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        top_p=request.top_p,
        model=request.model,
        priority=request.priority,
        strategy=request.strategy
    )

    # Start task execution in background
    background_tasks.add_task(state.task_manager.execute_task, task_id)

    return TaskResponse(
        task_id=task_id,
        status="queued",
        created_at=time.time(),
        estimated_duration_ms=state.scheduler.estimate_duration(request.model, len(online_devices)),
        assigned_devices=[d.device_id for d in task.assigned_devices]
    )

@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """查询任务状态和结果"""
    from main import state

    task = state.task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "task_id": task_id,
        "status": task.status,
        "progress": task.progress,
        "result": task.result if task.status == "completed" else None,
        "created_at": task.created_at,
        "completed_at": task.completed_at,
        "devices": [d.device_id for d in task.assigned_devices],
        "error": task.error
    }

@router.get("/devices", response_model=List[DeviceStatusResponse])
async def list_devices():
    """列出集群中所有设备及其状态"""
    from main import state

    devices = state.device_manager.get_all_devices()
    return [
        DeviceStatusResponse(
            device_id=d.device_id,
            device_name=d.device_name,
            status=d.status,
            cpu_cores=d.cpu_cores,
            available_ram_mb=d.available_ram_mb,
            battery_percent=d.battery_percent,
            latency_ms=d.latency_ms,
            assigned_layers=d.assigned_layers or [],
            throughput_tokens_per_sec=state.device_manager.get_device_throughput(d.device_id)
        )
        for d in devices
    ]

@router.get("/cluster/stats", response_model=ClusterStatsResponse)
async def cluster_stats():
    """获取集群整体统计信息"""
    from main import state

    devices = state.device_manager.get_all_devices()
    online = [d for d in devices if d.status == "online"]
    busy = [d for d in devices if d.status == "busy"]

    return ClusterStatsResponse(
        total_devices=len(devices),
        online_devices=len(online),
        busy_devices=len(busy),
        total_ram_mb=sum(d.total_ram_mb for d in devices),
        total_compute_score=sum(state.scheduler.compute_device_score(d) for d in online),
        active_tasks=state.task_manager.get_active_task_count(),
        queue_length=state.task_manager.get_queue_length(),
        avg_latency_ms=sum(d.latency_ms for d in online) / len(online) if online else 0
    )

@router.post("/devices/{device_id}/migrate")
async def manual_migrate(device_id: str):
    """手动触发设备任务迁移（维护模式）"""
    from main import state

    device = state.device_manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    await state.task_manager.migrate_all_tasks(device_id)
    return {"message": f"All tasks migrated from {device_id}", "success": True}

@router.get("/models")
async def list_models():
    """列出支持的模型及其配置"""
    return {
        "models": [
            {
                "name": "qwen-1.8b",
                "layers": 24,
                "hidden_size": 2048,
                "quantization": ["fp32", "fp16", "int8", "int4"],
                "min_ram_mb": 512,
                "recommended_devices": 2
            },
            {
                "name": "qwen-0.5b",
                "layers": 24,
                "hidden_size": 1024,
                "quantization": ["fp32", "fp16", "int8", "int4"],
                "min_ram_mb": 256,
                "recommended_devices": 1
            }
        ]
    }

@router.post("/benchmark")
async def run_benchmark(devices: Optional[List[str]] = None):
    """运行集群基准测试"""
    from main import state

    target_devices = devices or [d.device_id for d in state.device_manager.get_online_devices()]
    if not target_devices:
        raise HTTPException(status_code=503, detail="No devices available for benchmark")

    results = await state.task_manager.run_benchmark(target_devices)
    return {
        "benchmark_id": f"bench_{int(time.time())}",
        "devices_tested": len(target_devices),
        "results": results,
        "cluster_throughput": sum(r["tokens_per_sec"] for r in results)
    }
