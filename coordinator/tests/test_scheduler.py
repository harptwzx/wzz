"""
Unit Tests for MCDM Scheduler
"""
import pytest
import numpy as np
from scheduler import MCDMScheduler
from websocket_server import DeviceInfo

class TestMCDMScheduler:
    def test_topsis_basic(self):
        """测试TOPSIS基本排序功能"""
        scheduler = MCDMScheduler()

        # Create mock devices
        devices = [
            DeviceInfo("dev1", "PhoneA", "13", 33, 8, 2800, 8192, 4096, 80, True, True, True, "wifi"),
            DeviceInfo("dev2", "PhoneB", "11", 30, 4, 1800, 4096, 2048, 30, False, False, False, "4g"),
            DeviceInfo("dev3", "PhoneC", "14", 34, 8, 3000, 12288, 8192, 95, True, True, True, "wifi"),
        ]

        scores = scheduler._evaluate_devices(devices)

        # dev3 should have highest score (best specs)
        assert scores[2].score > scores[0].score
        # dev2 should have lowest score (worst specs, low battery)
        assert scores[1].score < scores[0].score

    def test_low_battery_penalty(self):
        """测试低电量惩罚机制"""
        scheduler = MCDMScheduler()

        devices = [
            DeviceInfo("dev1", "PhoneA", "13", 33, 8, 2800, 8192, 4096, 100, True, True, True, "wifi"),
            DeviceInfo("dev2", "PhoneB", "13", 33, 8, 2800, 8192, 4096, 5, False, True, True, "wifi"),
        ]

        scores = scheduler._evaluate_devices(devices)
        # Same hardware, but dev2 has 5% battery -> significantly lower score
        assert scores[1].score < scores[0].score * 0.5

    def test_layer_partition_pipeline(self):
        """测试流水线并行层分配"""
        scheduler = MCDMScheduler()

        devices = [
            DeviceInfo("dev1", "HighEnd", "14", 34, 8, 3000, 12288, 8192, 90, True, True, True, "wifi"),
            DeviceInfo("dev2", "LowEnd", "11", 30, 4, 1800, 4096, 2048, 60, False, False, False, "4g"),
        ]

        assignment = scheduler.partition_layers("qwen-1.8b", 24, devices, "pipeline")

        # High-end device should get more layers
        assert len(assignment["dev1"]) > len(assignment["dev2"])
        # All layers assigned
        total = sum(len(v) for v in assignment.values())
        assert total == 24
        # No overlap
        all_layers = []
        for layers in assignment.values():
            all_layers.extend(layers)
        assert len(all_layers) == len(set(all_layers))

    def test_auto_strategy_selection(self):
        """测试自动策略选择"""
        scheduler = MCDMScheduler()

        # Homogeneous powerful devices -> data parallel
        homogeneous = [
            DeviceInfo(f"dev{i}", f"Phone{i}", "14", 34, 8, 3000, 12288, 8192, 90, True, True, True, "wifi")
            for i in range(4)
        ]
        strategy = scheduler.select_strategy("qwen-1.8b", homogeneous)
        assert strategy == "data"

        # Heterogeneous devices -> pipeline parallel
        heterogeneous = [
            DeviceInfo("dev1", "Flagship", "14", 34, 8, 3000, 12288, 8192, 90, True, True, True, "wifi"),
            DeviceInfo("dev2", "Budget", "10", 29, 4, 1500, 2048, 1024, 40, False, False, False, "3g"),
        ]
        strategy = scheduler.select_strategy("qwen-1.8b", heterogeneous)
        assert strategy == "pipeline"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
