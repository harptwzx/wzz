"""
Task Manager Module
分布式任务管理：创建、调度、执行、监控、容错、迁移
支持流水线并行和数据并行
"""
import asyncio
import json
import logging
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from scheduler import MCDMScheduler
from device_manager import DeviceManager

logger = logging.getLogger("MDCS.TaskManager")

@dataclass
class Task:
    """任务数据结构"""
    task_id: str
    prompt: str
    max_tokens: int
    temperature: float
    top_p: float
    model: str
    priority: int
    strategy: str
    status: str = "queued"  # queued/running/completed/failed/migrating
    progress: float = 0.0  # 0.0 - 1.0
    assigned_devices: List = field(default_factory=list)
    layer_assignment: Dict = field(default_factory=dict)
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: float = 0.0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    checkpoint_interval: int = 5  # Save checkpoint every N layers
    completed_layers: set = field(default_factory=set)

    # For pipeline parallel: track intermediate activations
    activation_buffer: Dict[int, dict] = field(default_factory=dict)

class TaskManager:
    """
    任务管理器
    - 任务队列管理（优先级队列）
    - 模型层分配与调度
    - 流水线执行协调
    - 容错与任务迁移
    - 分层检查点
    """

    def __init__(self, device_manager: DeviceManager, scheduler: MCDMScheduler):
        self.device_manager = device_manager
        self.scheduler = scheduler

        # task_id -> Task
        self.tasks: Dict[str, Task] = {}

        # Priority queue: (priority, created_at, task_id)
        self.task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()

        # Active task execution tasks
        self.running_tasks: Dict[str, asyncio.Task] = {}

        # Model configurations
        self.model_configs: Dict[str, dict] = {}

        # Task locks for thread safety
        self.task_locks: Dict[str, asyncio.Lock] = {}

    async def load_model_config(self, config_path: str):
        """加载模型配置（层数、隐藏层大小等）"""
        # In production, load from JSON file
        self.model_configs = {
            "qwen-1.8b": {
                "layers": 24,
                "hidden_size": 2048,
                "intermediate_size": 5504,
                "vocab_size": 151936,
                "quantization": "int8"
            },
            "qwen-0.5b": {
                "layers": 24,
                "hidden_size": 1024,
                "intermediate_size": 2816,
                "vocab_size": 151936,
                "quantization": "int8"
            }
        }
        logger.info(f"Loaded {len(self.model_configs)} model configurations")

    async def create_task(self, task_id: str, prompt: str, max_tokens: int,
                         temperature: float, top_p: float, model: str,
                         priority: int, strategy: str) -> Task:
        """创建新任务"""

        # Get available devices
        available = self.device_manager.get_available_devices()
        if not available:
            raise ValueError("No available devices in cluster")

        # Determine strategy
        if strategy == "auto":
            strategy = self.scheduler.select_strategy(model, available)

        # Get model layer count
        config = self.model_configs.get(model, {"layers": 24})
        total_layers = config["layers"]

        # Partition layers across devices
        layer_assignment = self.scheduler.partition_layers(
            model, total_layers, available, strategy
        )

        # Create task
        assigned = [self.device_manager.get_device(did) for did in layer_assignment.keys()]
        assigned = [d for d in assigned if d is not None]

        task = Task(
            task_id=task_id,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            model=model,
            priority=priority,
            strategy=strategy,
            assigned_devices=assigned,
            layer_assignment=layer_assignment,
            created_at=time.time()
        )

        self.tasks[task_id] = task
        self.task_locks[task_id] = asyncio.Lock()

        # Update device status to busy
        for d in assigned:
            d.status = "busy"
            d.assigned_layers = layer_assignment.get(d.device_id, [])

        logger.info(f"Task {task_id} created with strategy={strategy}, "
                   f"devices={[d.device_id for d in assigned]}")
        return task

    async def execute_task(self, task_id: str):
        """执行任务主流程"""
        task = self.tasks.get(task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return

        async with self.task_locks[task_id]:
            task.status = "running"
            task.started_at = time.time()

            try:
                if task.strategy == "data":
                    await self._execute_data_parallel(task)
                else:
                    await self._execute_pipeline_parallel(task)

                task.status = "completed"
                task.completed_at = time.time()
                task.progress = 1.0

                # Update performance metrics
                duration = task.completed_at - task.started_at
                tokens = task.max_tokens  # Simplified
                for d in task.assigned_devices:
                    self.scheduler.update_device_performance(d.device_id, tokens / duration)

                logger.info(f"Task {task_id} completed in {duration:.2f}s")

            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                logger.error(f"Task {task_id} failed: {e}")
            finally:
                # Release devices
                for d in task.assigned_devices:
                    d.status = "online"
                    d.assigned_layers = []

    async def _execute_pipeline_parallel(self, task: Task):
        """
        流水线并行执行
        设备链：Device A (layers 0-7) -> Device B (layers 8-15) -> Device C (layers 16-23)
        中间激活值通过WebSocket传输
        """
        from main import state

        devices = sorted(task.assigned_devices, 
                          key=lambda d: min(task.layer_assignment.get(d.device_id, [0])))

        if not devices:
            raise ValueError("No devices assigned for pipeline execution")

        # Step 1: Send initial input to first device
        first_device = devices[0]
        await state.ws_server.send_to_device(first_device.device_id, {
            "type": "TASK_ASSIGN",
            "task_id": task.task_id,
            "layers": task.layer_assignment[first_device.device_id],
            "input": task.prompt,
            "max_tokens": task.max_tokens,
            "temperature": task.temperature,
            "is_first": True,
            "is_last": len(devices) == 1,
            "model": task.model
        })

        # Step 2: Coordinate intermediate activations between devices
        # In real implementation, this would wait for ACTIVATION_SEND messages
        # and forward to next device. Here we simulate the flow.

        # Wait for completion or timeout
        timeout = 300  # 5 minutes
        start = time.time()
        while task.status == "running" and time.time() - start < timeout:
            if len(task.completed_layers) >= sum(len(l) for l in task.layer_assignment.values()):
                break
            await asyncio.sleep(0.1)

        # Simulate result aggregation
        task.result = f"[Generated text for: {task.prompt[:50]}...]"

    async def _execute_data_parallel(self, task: Task):
        """
        数据并行执行
        所有设备拥有完整模型，各自处理不同输入分片（或同一输入的不同token生成）
        """
        from main import state

        # Broadcast task to all assigned devices
        for device in task.assigned_devices:
            await state.ws_server.send_to_device(device.device_id, {
                "type": "TASK_ASSIGN",
                "task_id": task.task_id,
                "layers": task.layer_assignment[device.device_id],
                "input": task.prompt,
                "max_tokens": task.max_tokens // len(task.assigned_devices),
                "temperature": task.temperature,
                "is_first": True,
                "is_last": True,  # Each device handles full pipeline for its data shard
                "model": task.model,
                "shard_id": task.assigned_devices.index(device),
                "total_shards": len(task.assigned_devices)
            })

        # Wait for all shards to complete
        timeout = 300
        start = time.time()
        while task.status == "running" and time.time() - start < timeout:
            # Check if all devices reported completion
            all_done = all(
                len(task.completed_layers) >= len(task.layer_assignment.get(d.device_id, []))
                for d in task.assigned_devices
            )
            if all_done:
                break
            await asyncio.sleep(0.1)

        # Aggregate results (simplified)
        task.result = f"[Data-parallel generated text for: {task.prompt[:50]}...]"

    async def handle_layer_completion(self, task_id: str, device_id: str, 
                                      layer_index: int, result: dict):
        """处理单层完成通知"""
        task = self.tasks.get(task_id)
        if not task:
            return

        task.completed_layers.add(layer_index)
        total_layers = sum(len(l) for l in task.layer_assignment.values())
        task.progress = len(task.completed_layers) / total_layers

        # Checkpoint every N layers
        if layer_index % task.checkpoint_interval == 0:
            logger.info(f"Task {task_id} checkpoint at layer {layer_index}")
            # In production: save activation state to Redis/disk

        # Check if all layers completed
        if task.progress >= 0.99:
            logger.info(f"Task {task_id} all layers completed")

    async def migrate_task(self, task_id: str, failed_device_id: str):
        """
        任务迁移：将故障设备的层重新分配到其他设备
        利用分层检查点恢复进度
        """
        task = self.tasks.get(task_id)
        if not task:
            return

        logger.warning(f"Migrating task {task_id} from failed device {failed_device_id}")
        task.status = "migrating"

        # Get layers that were on failed device
        failed_layers = task.layer_assignment.get(failed_device_id, [])
        if not failed_layers:
            return

        # Find replacement device
        available = self.device_manager.get_available_devices()
        available = [d for d in available if d.device_id != failed_device_id]

        if not available:
            task.status = "failed"
            task.error = f"No available device to migrate layers from {failed_device_id}"
            return

        # Simple migration: assign all failed layers to best available device
        from main import state
        scores = state.scheduler._evaluate_devices(available)
        best = max(scores, key=lambda x: x.score)

        # Reassign layers
        del task.layer_assignment[failed_device_id]
        task.layer_assignment[best.device_id] = failed_layers

        # Send migration command to new device with checkpoint info
        await state.ws_server.send_to_device(best.device_id, {
            "type": "TASK_MIGRATE",
            "task_id": task_id,
            "layers": failed_layers,
            "checkpoint_layer": max([l for l in task.completed_layers if l < min(failed_layers)], default=-1),
            "model": task.model
        })

        task.status = "running"
        logger.info(f"Task {task_id} migrated to {best.device_id}")

    async def migrate_all_tasks(self, failed_device_id: str):
        """迁移故障设备上的所有任务"""
        for task in self.tasks.values():
            if task.status == "running" and failed_device_id in task.layer_assignment:
                await self.migrate_task(task.task_id, failed_device_id)

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务信息"""
        return self.tasks.get(task_id)

    def get_active_task_count(self) -> int:
        """获取活跃任务数"""
        return sum(1 for t in self.tasks.values() if t.status == "running")

    def get_queue_length(self) -> int:
        """获取队列长度"""
        return sum(1 for t in self.tasks.values() if t.status == "queued")

    async def run_benchmark(self, device_ids: List[str]) -> List[dict]:
        """运行基准测试"""
        results = []
        for did in device_ids:
            device = self.device_manager.get_device(did)
            if not device:
                continue

            # Simulate benchmark: measure inference time for a standard layer
            # In production, this would run actual model inference
            import random
            base_time = 1000 / (device.cpu_freq_mhz * device.cpu_cores / 1000 + 1)
            tokens_per_sec = random.uniform(5, 20) * (device.cpu_cores / 8)

            self.device_manager.record_performance(did, tokens_per_sec)
            results.append({
                "device_id": did,
                "tokens_per_sec": round(tokens_per_sec, 2),
                "latency_ms": round(device.latency_ms, 2),
                "ram_usage_percent": round(
                    (device.total_ram_mb - device.available_ram_mb) / device.total_ram_mb * 100, 2
                ) if device.total_ram_mb else 0
            })
        return results
