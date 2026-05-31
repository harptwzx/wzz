"""
Integration Tests for Coordinator
测试断线重连、任务迁移等集成场景
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock

from device_manager import DeviceManager
from task_manager import TaskManager
from scheduler import MCDMScheduler
from websocket_server import DeviceInfo

class TestIntegration:
    @pytest.fixture
    def setup(self):
        self.dm = DeviceManager()
        self.scheduler = MCDMScheduler()
        self.tm = TaskManager(self.dm, self.scheduler)
        return self.dm, self.tm, self.scheduler

    @pytest.mark.asyncio
    async def test_device_reconnect_preserves_assignment(self, setup):
        """测试设备重连后保留层分配信息"""
        dm, tm, _ = setup

        device = DeviceInfo("dev1", "Phone", "13", 33, 8, 2800, 8192, 4096, 80, True, True, True, "wifi")
        dm.register_device(device)
        dm.update_device_layers("dev1", [0, 1, 2, 3])

        # Simulate disconnect and reconnect
        dm.mark_offline("dev1")
        new_device = DeviceInfo("dev1", "Phone", "13", 33, 8, 2800, 8192, 4096, 75, True, True, True, "wifi")
        dm.register_device(new_device)

        # Should preserve assigned layers
        assert dm.get_device("dev1").assigned_layers == [0, 1, 2, 3]

    @pytest.mark.asyncio
    async def test_task_migration_on_failure(self, setup):
        """测试设备故障时任务迁移"""
        dm, tm, _ = setup

        # Register devices
        dev1 = DeviceInfo("dev1", "PhoneA", "13", 33, 8, 2800, 8192, 4096, 80, True, True, True, "wifi")
        dev2 = DeviceInfo("dev2", "PhoneB", "13", 33, 8, 2800, 8192, 4096, 80, True, True, True, "wifi")
        dm.register_device(dev1)
        dm.register_device(dev2)

        await tm.load_model_config("")

        # Create task assigned to dev1
        task = await tm.create_task("t1", "Hello", 10, 0.7, 0.9, "qwen-1.8b", 5, "pipeline")

        # Simulate dev1 failure
        await tm.migrate_task("t1", "dev1")

        # Task should be migrated to dev2
        task_after = tm.get_task("t1")
        assert "dev2" in task_after.layer_assignment
        assert "dev1" not in task_after.layer_assignment

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
