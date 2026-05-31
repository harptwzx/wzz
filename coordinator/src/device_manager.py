"""
Device Manager Module
管理设备生命周期、资源监控、性能追踪
"""
import logging
import time
from typing import Dict, List, Optional
from collections import defaultdict

from websocket_server import DeviceInfo

logger = logging.getLogger("MDCS.DeviceManager")

class DeviceManager:
    """
    设备管理器
    - 维护设备注册表
    - 实时资源监控
    - 设备性能画像
    - 故障设备标记
    """

    def __init__(self):
        # device_id -> DeviceInfo
        self.devices: Dict[str, DeviceInfo] = {}

        # Performance tracking: device_id -> {timestamp: tokens/sec}
        self.performance_log: Dict[str, List[tuple]] = defaultdict(list)

        # Failure count for graceful degradation
        self.failure_counts: Dict[str, int] = defaultdict(int)

    def register_device(self, device: DeviceInfo):
        """注册新设备或更新现有设备"""
        existing = self.devices.get(device.device_id)
        if existing:
            # Preserve assigned layers and history if reconnecting
            device.assigned_layers = existing.assigned_layers
            logger.info(f"Device reconnected: {device.device_id}")
        else:
            logger.info(f"New device registered: {device.device_id}")

        self.devices[device.device_id] = device
        self.failure_counts[device.device_id] = 0

    def unregister_device(self, device_id: str):
        """注销设备"""
        if device_id in self.devices:
            del self.devices[device_id]
            logger.info(f"Device unregistered: {device_id}")

    def mark_offline(self, device_id: str):
        """标记设备离线（保留记录用于可能的重连）"""
        if device_id in self.devices:
            self.devices[device_id].status = "offline"
            logger.info(f"Device marked offline: {device_id}")

    def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        """获取设备信息"""
        return self.devices.get(device_id)

    def get_online_devices(self) -> List[DeviceInfo]:
        """获取在线设备列表"""
        return [d for d in self.devices.values() if d.status in ("online", "busy")]

    def get_all_devices(self) -> List[DeviceInfo]:
        """获取所有设备"""
        return list(self.devices.values())

    def get_available_devices(self) -> List[DeviceInfo]:
        """获取可用于任务分配的设备（在线且非忙碌）"""
        return [d for d in self.devices.values() 
                if d.status == "online" and d.battery_percent > 10]

    def update_device_layers(self, device_id: str, layers: List[int]):
        """更新设备分配的层"""
        if device_id in self.devices:
            self.devices[device_id].assigned_layers = layers

    def record_performance(self, device_id: str, tokens_per_sec: float):
        """记录设备性能指标"""
        self.performance_log[device_id].append((time.time(), tokens_per_sec))
        # Keep last 100 records
        if len(self.performance_log[device_id]) > 100:
            self.performance_log[device_id] = self.performance_log[device_id][-100:]

    def get_device_throughput(self, device_id: str) -> float:
        """获取设备最近平均吞吐量"""
        logs = self.performance_log.get(device_id, [])
        if not logs:
            return 0.0
        recent = [tps for _, tps in logs[-10:]]
        return sum(recent) / len(recent)

    def report_failure(self, device_id: str):
        """报告设备故障"""
        self.failure_counts[device_id] += 1
        if self.failure_counts[device_id] >= 3:
            # Mark as unreliable after 3 failures
            if device_id in self.devices:
                self.devices[device_id].status = "unreliable"
                logger.warning(f"Device {device_id} marked unreliable after 3 failures")

    def get_cluster_summary(self) -> dict:
        """获取集群摘要信息"""
        online = self.get_online_devices()
        total_ram = sum(d.total_ram_mb for d in self.devices.values())
        available_ram = sum(d.available_ram_mb for d in online)

        return {
            "total_devices": len(self.devices),
            "online_devices": len(online),
            "total_ram_mb": total_ram,
            "available_ram_mb": available_ram,
            "avg_battery": sum(d.battery_percent for d in online) / len(online) if online else 0,
            "npus_available": sum(1 for d in online if d.has_npu),
            "gpus_available": sum(1 for d in online if d.has_gpu)
        }
