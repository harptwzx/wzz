"""
Benchmark & Testing Suite for MDCS
测试脚本：单元测试、集成测试、压力测试、基准测试
"""
import asyncio
import json
import time
import random
import statistics
from typing import List, Dict
import concurrent.futures

import httpx
import websockets

# Test configuration
COORDINATOR_HTTP = "http://localhost:8080"
COORDINATOR_WS = "ws://localhost:8765"

class MDCSBenchmark:
    """MDCS基准测试套件"""

    def __init__(self):
        self.results = []

    async def test_health(self) -> bool:
        """健康检查测试"""
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{COORDINATOR_HTTP}/health", timeout=5)
                data = resp.json()
                assert data["status"] == "healthy"
                print(f"✓ Health check passed: {data}")
                return True
            except Exception as e:
                print(f"✗ Health check failed: {e}")
                return False

    async def test_device_registration(self, num_devices: int = 5) -> List[str]:
        """模拟设备注册测试"""
        device_ids = []

        async def register_device(ws, device_id: str):
            register_msg = {
                "type": "REGISTER",
                "device_id": device_id,
                "device_name": f"TestDevice_{device_id[-4:]}",
                "android_version": "13",
                "sdk_level": 33,
                "cpu_cores": random.choice([4, 6, 8]),
                "cpu_freq_mhz": random.choice([1800, 2400, 3000]),
                "total_ram_mb": random.choice([4096, 6144, 8192, 12288]),
                "available_ram_mb": random.choice([2048, 3072, 4096, 6144]),
                "battery_percent": random.choice([30, 50, 70, 90]),
                "is_charging": random.choice([True, False]),
                "has_npu": random.choice([True, False]),
                "has_gpu": True,
                "network_type": random.choice(["wifi", "5g", "4g"]),
                "fingerprint": "a" * 64
            }
            await ws.send(json.dumps(register_msg))
            response = await ws.recv()
            data = json.loads(response)
            assert data["type"] == "REGISTER_ACK"
            return device_id

        connections = []
        for i in range(num_devices):
            ws = await websockets.connect(COORDINATOR_WS)
            device_id = f"test_dev_{i}_{int(time.time())}"
            await register_device(ws, device_id)
            device_ids.append(device_id)
            connections.append(ws)

        print(f"✓ Registered {num_devices} devices: {device_ids}")

        # Keep connections alive for heartbeat test
        await asyncio.sleep(6)

        # Cleanup
        for ws in connections:
            await ws.close()

        return device_ids

    async def test_heartbeat(self, duration: int = 15) -> Dict:
        """心跳测试：验证5秒间隔和超时检测"""
        ws = await websockets.connect(COORDINATOR_WS)

        # Register
        await ws.send(json.dumps({
            "type": "REGISTER",
            "device_id": "heartbeat_test",
            "device_name": "HeartbeatTest",
            "android_version": "13",
            "sdk_level": 33,
            "cpu_cores": 8,
            "cpu_freq_mhz": 2800,
            "total_ram_mb": 8192,
            "available_ram_mb": 4096,
            "battery_percent": 80,
            "is_charging": True,
            "has_npu": True,
            "has_gpu": True,
            "network_type": "wifi",
            "fingerprint": "b" * 64
        }))
        await ws.recv()  # REGISTER_ACK

        heartbeats_sent = 0
        heartbeats_acked = 0
        start = time.time()

        while time.time() - start < duration:
            await ws.send(json.dumps({
                "type": "HEARTBEAT",
                "available_ram_mb": 4000,
                "battery_percent": 79,
                "is_charging": True,
                "status": "online"
            }))
            heartbeats_sent += 1

            try:
                response = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(response)
                if data["type"] == "HEARTBEAT_ACK":
                    heartbeats_acked += 1
            except asyncio.TimeoutError:
                pass

            await asyncio.sleep(5)

        await ws.close()

        result = {
            "sent": heartbeats_sent,
            "acked": heartbeats_acked,
            "success_rate": heartbeats_acked / heartbeats_sent if heartbeats_sent > 0 else 0
        }
        print(f"✓ Heartbeat test: {result}")
        return result

    async def test_inference(self, prompt: str = "Hello world") -> Dict:
        """端到端推理测试"""
        async with httpx.AsyncClient() as client:
            # Submit task
            start = time.time()
            resp = await client.post(
                f"{COORDINATOR_HTTP}/api/v1/inference",
                json={
                    "prompt": prompt,
                    "max_tokens": 32,
                    "temperature": 0.7,
                    "model": "qwen-1.8b",
                    "strategy": "pipeline"
                },
                timeout=30
            )

            task_data = resp.json()
            task_id = task_data["task_id"]
            print(f"✓ Task submitted: {task_id}")

            # Poll for completion
            for _ in range(60):  # Max 60 seconds
                await asyncio.sleep(1)
                status_resp = await client.get(
                    f"{COORDINATOR_HTTP}/api/v1/tasks/{task_id}",
                    timeout=5
                )
                status = status_resp.json()

                if status["status"] in ("completed", "failed"):
                    duration = time.time() - start
                    result = {
                        "task_id": task_id,
                        "status": status["status"],
                        "duration_sec": round(duration, 2),
                        "result_preview": str(status.get("result", ""))[:100]
                    }
                    print(f"✓ Inference test: {result}")
                    return result

            print("✗ Inference test timeout")
            return {"status": "timeout"}

    async def test_scheduler_mcdm(self) -> bool:
        """MCDM调度算法测试"""
        from scheduler import MCDMScheduler
        from websocket_server import DeviceInfo

        scheduler = MCDMScheduler()

        # Test 1: Basic scoring
        devices = [
            DeviceInfo("d1", "Flagship", "14", 34, 8, 3000, 12288, 8192, 90, True, True, True, "wifi"),
            DeviceInfo("d2", "Mid", "12", 31, 6, 2200, 6144, 3072, 60, False, False, True, "5g"),
            DeviceInfo("d3", "Budget", "10", 29, 4, 1500, 4096, 2048, 30, False, False, False, "4g"),
        ]

        scores = scheduler._evaluate_devices(devices)
        assert len(scores) == 3
        assert scores[0].score > scores[2].score  # Flagship > Budget

        # Test 2: Layer partition
        assignment = scheduler.partition_layers("qwen-1.8b", 24, devices, "pipeline")
        total = sum(len(v) for v in assignment.values())
        assert total == 24
        assert len(assignment["d1"]) > len(assignment["d3"])

        # Test 3: Strategy selection
        homogeneous = [devices[0]] * 4
        assert scheduler.select_strategy("qwen-1.8b", homogeneous) == "data"

        print("✓ MCDM scheduler tests passed")
        return True

    async def stress_test(self, num_devices: int = 10, num_tasks: int = 20) -> Dict:
        """压力测试：模拟大量设备并发"""
        print(f"
--- Stress Test: {num_devices} devices, {num_tasks} tasks ---")

        # Register devices
        connections = []
        for i in range(num_devices):
            ws = await websockets.connect(COORDINATOR_WS)
            await ws.send(json.dumps({
                "type": "REGISTER",
                "device_id": f"stress_dev_{i}",
                "device_name": f"Stress{i}",
                "android_version": "13",
                "sdk_level": 33,
                "cpu_cores": 8,
                "cpu_freq_mhz": 2800,
                "total_ram_mb": 8192,
                "available_ram_mb": 4096,
                "battery_percent": 80,
                "is_charging": True,
                "has_npu": True,
                "has_gpu": True,
                "network_type": "wifi",
                "fingerprint": "c" * 64
            }))
            await ws.recv()
            connections.append(ws)

        print(f"✓ {num_devices} devices registered")

        # Submit tasks concurrently
        async with httpx.AsyncClient() as client:
            tasks = []
            for i in range(num_tasks):
                task = client.post(
                    f"{COORDINATOR_HTTP}/api/v1/inference",
                    json={
                        "prompt": f"Test prompt {i}",
                        "max_tokens": 16,
                        "model": "qwen-1.8b",
                        "priority": random.randint(1, 10)
                    },
                    timeout=30
                )
                tasks.append(task)

            start = time.time()
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            submit_duration = time.time() - start

            success = sum(1 for r in responses if not isinstance(r, Exception))

            result = {
                "devices": num_devices,
                "tasks_submitted": num_tasks,
                "successful": success,
                "failed": num_tasks - success,
                "submit_time_sec": round(submit_duration, 2),
                "throughput_tasks_per_sec": round(num_tasks / submit_duration, 2)
            }
            print(f"✓ Stress test: {result}")

        # Cleanup
        for ws in connections:
            await ws.close()

        return result

    async def benchmark_cluster(self) -> Dict:
        """集群基准测试"""
        print("
--- Cluster Benchmark ---")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{COORDINATOR_HTTP}/api/v1/benchmark",
                timeout=60
            )
            result = resp.json()
            print(f"✓ Benchmark: {json.dumps(result, indent=2)}")
            return result

    async def run_all_tests(self):
        """运行完整测试套件"""
        print("=" * 60)
        print("MDCS Test Suite")
        print("=" * 60)

        results = {}

        # 1. Health check
        results["health"] = await self.test_health()

        # 2. Scheduler unit tests
        results["scheduler"] = await self.test_scheduler_mcdm()

        # 3. Device registration
        device_ids = await self.test_device_registration(num_devices=3)
        results["devices_registered"] = len(device_ids)

        # 4. Heartbeat
        results["heartbeat"] = await self.test_heartbeat(duration=12)

        # 5. Inference (requires devices to be online)
        # Re-register one device for inference
        ws = await websockets.connect(COORDINATOR_WS)
        await ws.send(json.dumps({
            "type": "REGISTER",
            "device_id": "inference_test_dev",
            "device_name": "InferenceTest",
            "android_version": "13",
            "sdk_level": 33,
            "cpu_cores": 8,
            "cpu_freq_mhz": 3000,
            "total_ram_mb": 12288,
            "available_ram_mb": 8192,
            "battery_percent": 90,
            "is_charging": True,
            "has_npu": True,
            "has_gpu": True,
            "network_type": "wifi",
            "fingerprint": "d" * 64
        }))
        await ws.recv()

        results["inference"] = await self.test_inference("What is machine learning?")
        await ws.close()

        # 6. Stress test
        results["stress"] = await self.stress_test(num_devices=10, num_tasks=20)

        # 7. Benchmark
        results["benchmark"] = await self.benchmark_cluster()

        # Summary
        print("
" + "=" * 60)
        print("Test Summary")
        print("=" * 60)
        print(json.dumps(results, indent=2, default=str))

        return results


if __name__ == "__main__":
    benchmark = MDCSBenchmark()
    asyncio.run(benchmark.run_all_tests())
