"""
WebSocket Server Module
处理设备注册、心跳、任务分发、结果回传、断线重连
使用asyncio + websockets库实现长连接框架
"""
import asyncio
import json
import logging
import time
from typing import Dict, Set, Optional
from dataclasses import dataclass, asdict

import websockets
from websockets.server import WebSocketServerProtocol

logger = logging.getLogger("MDCS.WebSocket")

@dataclass
class DeviceInfo:
    """设备信息数据结构"""
    device_id: str
    device_name: str
    android_version: str
    sdk_level: int
    cpu_cores: int
    cpu_freq_mhz: float
    total_ram_mb: int
    available_ram_mb: int
    battery_percent: int
    is_charging: bool
    has_npu: bool
    has_gpu: bool
    network_type: str  # wifi/5g/4g
    latency_ms: float = 0.0
    last_heartbeat: float = 0.0
    status: str = "offline"  # offline/online/busy/error
    assigned_layers: list = None

    def to_dict(self):
        return asdict(self)

class CoordinatorWebSocketServer:
    """
    中心协调器WebSocket服务器
    协议设计：
    - REGISTER: 设备注册
    - HEARTBEAT: 心跳包（每5秒）
    - PING/PONG: 延迟测试
    - TASK_ASSIGN: 任务分配
    - TASK_RESULT: 结果回传
    - ACTIVATION_SEND: 中间激活值传输
    - CHECKPOINT: 分层检查点
    """

    def __init__(self, host: str, port: int, device_manager, task_manager, security):
        self.host = host
        self.port = port
        self.device_manager = device_manager
        self.task_manager = task_manager
        self.security = security

        # Active connections: device_id -> WebSocket
        self.connections: Dict[str, WebSocketServerProtocol] = {}

        # Pending reconnections: device_id -> reconnect_task
        self.reconnect_tasks: Dict[str, asyncio.Task] = {}

        # Server instance
        self.server = None
        self.running = False

        # Heartbeat check interval
        self.heartbeat_interval = 5.0
        self.heartbeat_timeout = 15.0  # 3次心跳未收到视为断线

    async def start(self):
        """启动WebSocket服务器"""
        self.running = True
        self.server = await websockets.serve(
            self._handle_connection,
            self.host,
            self.port,
            ping_interval=None,  # 使用自定义心跳机制
            ssl=self.security.get_ssl_context() if self.security else None
        )
        logger.info(f"WebSocket server started on ws://{self.host}:{self.port}")

        # Start heartbeat monitor
        asyncio.create_task(self._heartbeat_monitor())

        await self.server.wait_closed()

    async def stop(self):
        """优雅关闭服务器"""
        self.running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        logger.info("WebSocket server stopped")

    async def _handle_connection(self, websocket: WebSocketServerProtocol, path: str):
        """处理新连接"""
        device_id = None
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "REGISTER":
                        device_id = await self._handle_register(websocket, data)
                    elif msg_type == "HEARTBEAT":
                        await self._handle_heartbeat(device_id, data)
                    elif msg_type == "PONG":
                        await self._handle_pong(device_id, data)
                    elif msg_type == "TASK_RESULT":
                        await self._handle_task_result(device_id, data)
                    elif msg_type == "ACTIVATION_SEND":
                        await self._handle_activation(device_id, data)
                    elif msg_type == "ERROR_REPORT":
                        await self._handle_error(device_id, data)
                    else:
                        await self._send_message(websocket, {
                            "type": "ERROR",
                            "code": "UNKNOWN_TYPE",
                            "message": f"Unknown message type: {msg_type}"
                        })
                except json.JSONDecodeError:
                    await self._send_message(websocket, {
                        "type": "ERROR",
                        "code": "INVALID_JSON",
                        "message": "Invalid JSON format"
                    })
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Connection closed for device {device_id}")
        finally:
            if device_id:
                await self._handle_disconnect(device_id)

    async def _handle_register(self, websocket: WebSocketServerProtocol, data: dict) -> str:
        """处理设备注册"""
        device_info = DeviceInfo(
            device_id=data["device_id"],
            device_name=data.get("device_name", "Unknown"),
            android_version=data.get("android_version", "Unknown"),
            sdk_level=data.get("sdk_level", 0),
            cpu_cores=data.get("cpu_cores", 0),
            cpu_freq_mhz=data.get("cpu_freq_mhz", 0.0),
            total_ram_mb=data.get("total_ram_mb", 0),
            available_ram_mb=data.get("available_ram_mb", 0),
            battery_percent=data.get("battery_percent", 100),
            is_charging=data.get("is_charging", False),
            has_npu=data.get("has_npu", False),
            has_gpu=data.get("has_gpu", False),
            network_type=data.get("network_type", "wifi"),
            last_heartbeat=time.time(),
            status="online"
        )

        # Verify device fingerprint
        fingerprint = data.get("fingerprint")
        if not self.security.verify_fingerprint(device_info.device_id, fingerprint):
            await self._send_message(websocket, {
                "type": "REGISTER_REJECT",
                "reason": "Invalid fingerprint"
            })
            raise ValueError("Invalid device fingerprint")

        self.connections[device_info.device_id] = websocket
        self.device_manager.register_device(device_info)

        # Cancel any pending reconnection task
        if device_info.device_id in self.reconnect_tasks:
            self.reconnect_tasks[device_info.device_id].cancel()
            del self.reconnect_tasks[device_info.device_id]

        await self._send_message(websocket, {
            "type": "REGISTER_ACK",
            "server_time": time.time(),
            "heartbeat_interval": self.heartbeat_interval,
            "config": {
                "max_layers_per_device": 8,
                "quantization": "int8",
                "compression": "snappy"
            }
        })

        logger.info(f"Device registered: {device_info.device_id} ({device_info.device_name})")
        return device_info.device_id

    async def _handle_heartbeat(self, device_id: str, data: dict):
        """处理心跳包"""
        if device_id not in self.connections:
            return

        device = self.device_manager.get_device(device_id)
        if device:
            device.last_heartbeat = time.time()
            device.available_ram_mb = data.get("available_ram_mb", device.available_ram_mb)
            device.battery_percent = data.get("battery_percent", device.battery_percent)
            device.is_charging = data.get("is_charging", device.is_charging)
            device.status = data.get("status", device.status)

            # Low battery protection: auto throttle or exit
            if device.battery_percent < 15 and not device.is_charging:
                await self._send_message(self.connections[device_id], {
                    "type": "THROTTLE",
                    "action": "reduce_freq",
                    "reason": "Low battery"
                })

        # Send heartbeat acknowledgment
        await self._send_message(self.connections[device_id], {
            "type": "HEARTBEAT_ACK",
            "server_time": time.time()
        })

    async def _handle_pong(self, device_id: str, data: dict):
        """处理Pong延迟测试回包"""
        sent_time = data.get("sent_time", 0)
        latency = (time.time() - sent_time) * 1000  # ms

        device = self.device_manager.get_device(device_id)
        if device:
            device.latency_ms = latency
            logger.debug(f"Device {device_id} latency: {latency:.2f}ms")

    async def _handle_task_result(self, device_id: str, data: dict):
        """处理任务结果回传"""
        task_id = data.get("task_id")
        result = data.get("result")
        layer_index = data.get("layer_index")

        logger.info(f"Received result for task {task_id}, layer {layer_index} from {device_id}")
        await self.task_manager.handle_layer_completion(task_id, device_id, layer_index, result)

    async def _handle_activation(self, device_id: str, data: dict):
        """处理中间激活值传输（流水线并行）"""
        task_id = data.get("task_id")
        target_device = data.get("target_device")
        activation_data = data.get("activation")  # base64 encoded, snappy compressed
        shape = data.get("shape")
        dtype = data.get("dtype")

        # Forward activation to next device in pipeline
        if target_device in self.connections:
            await self._send_message(self.connections[target_device], {
                "type": "ACTIVATION_RECV",
                "task_id": task_id,
                "from_device": device_id,
                "activation": activation_data,
                "shape": shape,
                "dtype": dtype
            })

    async def _handle_error(self, device_id: str, data: dict):
        """处理设备错误报告，触发容错机制"""
        error_code = data.get("error_code")
        task_id = data.get("task_id")

        logger.error(f"Device {device_id} reported error: {error_code}, task: {task_id}")

        # Mark device as error state
        device = self.device_manager.get_device(device_id)
        if device:
            device.status = "error"

        # Trigger task migration if task_id provided
        if task_id:
            await self.task_manager.migrate_task(task_id, device_id)

    async def _handle_disconnect(self, device_id: str):
        """处理设备断线，启动重连等待"""
        if not device_id:
            return

        logger.warning(f"Device {device_id} disconnected, starting reconnection grace period")
        self.device_manager.mark_offline(device_id)

        if device_id in self.connections:
            del self.connections[device_id]

        # Start reconnection grace period (30 seconds)
        task = asyncio.create_task(self._reconnection_grace_period(device_id))
        self.reconnect_tasks[device_id] = task

    async def _reconnection_grace_period(self, device_id: str):
        """断线重连宽限期：30秒内允许设备重新注册并恢复任务"""
        try:
            await asyncio.sleep(30)
            # If device hasn't reconnected after grace period
            if device_id not in self.connections:
                logger.info(f"Device {device_id} failed to reconnect, migrating tasks")
                await self.task_manager.migrate_all_tasks(device_id)
                self.device_manager.unregister_device(device_id)
        except asyncio.CancelledError:
            logger.info(f"Reconnection grace period cancelled for {device_id}")

    async def _heartbeat_monitor(self):
        """心跳监控：检测超时设备"""
        while self.running:
            await asyncio.sleep(self.heartbeat_interval)
            current_time = time.time()

            for device_id, device in list(self.device_manager.devices.items()):
                if device.status == "online":
                    if current_time - device.last_heartbeat > self.heartbeat_timeout:
                        logger.warning(f"Device {device_id} heartbeat timeout")
                        device.status = "timeout"
                        if device_id in self.connections:
                            await self.connections[device_id].close()
                    else:
                        # Send ping for latency measurement
                        await self._send_message(self.connections[device_id], {
                            "type": "PING",
                            "sent_time": time.time()
                        })

    async def _send_message(self, websocket: WebSocketServerProtocol, message: dict):
        """发送JSON消息到设备"""
        try:
            await websocket.send(json.dumps(message))
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Failed to send message, connection closed")

    async def broadcast(self, message: dict, filter_fn=None):
        """广播消息到所有或筛选后的设备"""
        targets = self.connections.values()
        if filter_fn:
            targets = [ws for did, ws in self.connections.items() if filter_fn(did)]

        if targets:
            await asyncio.gather(
                *[self._send_message(ws, message) for ws in targets],
                return_exceptions=True
            )

    async def send_to_device(self, device_id: str, message: dict):
        """发送消息到指定设备"""
        if device_id in self.connections:
            await self._send_message(self.connections[device_id], message)
        else:
            logger.warning(f"Device {device_id} not connected")
