"""
MCDM (Multi-Criteria Decision Making) Scheduler
多标准决策调度算法

综合指标：
- CPU性能（频率 x 核心数）
- 可用内存
- 电量状态（低电量降权）
- 网络延迟（RTT）
- 历史吞吐量

算法：TOPSIS (Technique for Order Preference by Similarity to Ideal Solution)
"""
import logging
import numpy as np
from typing import List, Dict, Tuple
from dataclasses import dataclass

logger = logging.getLogger("MDCS.Scheduler")

@dataclass
class DeviceScore:
    device_id: str
    score: float
    criteria: Dict[str, float]

class MCDMScheduler:
    """
    TOPSIS-based Multi-Criteria Decision Making Scheduler
    支持流水线并行(Pipeline Parallelism)和数据并行(Data Parallelism)决策
    """

    # Criteria weights (sum = 1.0)
    WEIGHTS = {
        "cpu": 0.25,      # CPU计算能力
        "memory": 0.20,   # 可用内存
        "battery": 0.15,  # 电量状态（越高越好，但低电量惩罚）
        "latency": 0.20,  # 网络延迟（越低越好）
        "history": 0.20   # 历史性能表现
    }

    # Low battery threshold
    BATTERY_LOW = 20
    BATTERY_CRITICAL = 10

    def __init__(self):
        self.device_history: Dict[str, List[float]] = {}  # device_id -> [tokens/sec]

    def compute_device_score(self, device) -> float:
        """计算单个设备的综合得分（用于监控展示）"""
        scores = self._evaluate_devices([device])
        return scores[0].score if scores else 0.0

    def _evaluate_devices(self, devices: List) -> List[DeviceScore]:
        """
        TOPSIS核心算法
        1. 构建决策矩阵
        2. 标准化
        3. 加权
        4. 确定正负理想解
        5. 计算欧氏距离并排序
        """
        if not devices:
            return []

        n = len(devices)

        # Build decision matrix [n_devices x 5_criteria]
        # Columns: [cpu_score, memory_score, battery_score, latency_score, history_score]
        matrix = np.zeros((n, 5))

        for i, d in enumerate(devices):
            # CPU score: freq * cores (normalized later)
            matrix[i, 0] = d.cpu_freq_mhz * d.cpu_cores

            # Memory score: available RAM
            matrix[i, 1] = d.available_ram_mb

            # Battery score: apply penalty for low battery
            battery = d.battery_percent
            if battery < self.BATTERY_CRITICAL:
                matrix[i, 2] = battery * 0.1  # Severe penalty
            elif battery < self.BATTERY_LOW:
                matrix[i, 2] = battery * 0.5
            else:
                matrix[i, 2] = battery

            # Latency score: inverse of RTT (lower is better)
            # Add small epsilon to avoid division by zero
            matrix[i, 3] = 1000.0 / (d.latency_ms + 1.0)

            # History score: average throughput
            history = self.device_history.get(d.device_id, [10.0])
            matrix[i, 4] = np.mean(history[-5:])  # Last 5 measurements

        # Step 1: Vector normalization
        norms = np.sqrt(np.sum(matrix ** 2, axis=0))
        norms[norms == 0] = 1  # Avoid division by zero
        normalized = matrix / norms

        # Step 2: Weighted normalized matrix
        weights = np.array([
            self.WEIGHTS["cpu"],
            self.WEIGHTS["memory"],
            self.WEIGHTS["battery"],
            self.WEIGHTS["latency"],
            self.WEIGHTS["history"]
        ])
        weighted = normalized * weights

        # Step 3: Determine ideal solutions
        # All criteria are benefit-type (higher is better) after transformation
        ideal_best = np.max(weighted, axis=0)
        ideal_worst = np.min(weighted, axis=0)

        # Step 4: Calculate Euclidean distances
        dist_best = np.sqrt(np.sum((weighted - ideal_best) ** 2, axis=1))
        dist_worst = np.sqrt(np.sum((weighted - ideal_worst) ** 2, axis=1))

        # Step 5: Calculate relative closeness to ideal solution
        # C_i = dist_worst / (dist_best + dist_worst)
        scores = dist_worst / (dist_best + dist_worst + 1e-10)

        return [
            DeviceScore(
                device_id=devices[i].device_id,
                score=float(scores[i]),
                criteria={
                    "cpu": float(normalized[i, 0]),
                    "memory": float(normalized[i, 1]),
                    "battery": float(normalized[i, 2]),
                    "latency": float(normalized[i, 3]),
                    "history": float(normalized[i, 4])
                }
            )
            for i in range(n)
        ]

    def select_strategy(self, model_name: str, devices: List) -> str:
        """
        自动选择并行策略
        - Pipeline: 设备异构性高、内存差异大、模型层数多
        - Data: 设备性能相近、内存充足、高并发请求
        """
        if not devices:
            return "pipeline"

        scores = self._evaluate_devices(devices)
        scores_sorted = sorted(scores, key=lambda x: x.score, reverse=True)

        # Calculate coefficient of variation (CV) of scores
        score_values = [s.score for s in scores]
        mean_score = np.mean(score_values)
        std_score = np.std(score_values)
        cv = std_score / (mean_score + 1e-10)

        # Heuristics
        if cv > 0.3:
            # High heterogeneity -> Pipeline parallelism better
            logger.info(f"Auto-selected PIPELINE strategy (CV={cv:.2f}, heterogeneous devices)")
            return "pipeline"
        elif len(devices) >= 4 and mean_score > 0.6:
            # Many powerful devices -> Data parallelism
            logger.info(f"Auto-selected DATA strategy (CV={cv:.2f}, {len(devices)} powerful devices)")
            return "data"
        else:
            logger.info(f"Auto-selected PIPELINE strategy (CV={cv:.2f}, default)")
            return "pipeline"

    def partition_layers(self, model_name: str, total_layers: int, 
                         devices: List, strategy: str = "auto") -> Dict[str, List[int]]:
        """
        模型层分配算法

        Pipeline Parallel: 按设备能力比例分配连续层段
        Data Parallel: 每个设备复制全部层（用于数据并行）

        Returns: {device_id: [layer_indices]}
        """
        if strategy == "auto":
            strategy = self.select_strategy(model_name, devices)

        if strategy == "data":
            # Data parallel: each device gets all layers (replication)
            all_layers = list(range(total_layers))
            return {d.device_id: all_layers for d in devices}

        # Pipeline parallel: proportional partition by device score
        scores = self._evaluate_devices(devices)
        scores_dict = {s.device_id: s.score for s in scores}

        # Filter out devices with too low score (critical battery, etc.)
        valid_devices = [d for d in devices if scores_dict.get(d.device_id, 0) > 0.1]
        if not valid_devices:
            valid_devices = devices  # Fallback

        valid_scores = [scores_dict.get(d.device_id, 0.1) for d in valid_devices]
        total_score = sum(valid_scores)

        # Calculate layer counts proportionally
        layer_counts = []
        remaining = total_layers
        for i, d in enumerate(valid_devices[:-1]):
            count = int(total_layers * valid_scores[i] / total_score)
            count = max(1, min(count, remaining - (len(valid_devices) - i - 1)))
            layer_counts.append(count)
            remaining -= count
        layer_counts.append(remaining)

        # Assign layer ranges
        assignment = {}
        start = 0
        for i, d in enumerate(valid_devices):
            end = start + layer_counts[i]
            assignment[d.device_id] = list(range(start, end))
            start = end

        logger.info(f"Layer partition ({strategy}): {assignment}")
        return assignment

    def estimate_duration(self, model_name: str, num_devices: int) -> int:
        """估算推理耗时（毫秒）"""
        # Simplified estimation based on model size and device count
        base_time = {
            "qwen-1.8b": 5000,
            "qwen-0.5b": 2000
        }.get(model_name, 5000)

        # Speedup factor (sub-linear due to communication overhead)
        if num_devices <= 1:
            return base_time
        speedup = min(num_devices * 0.7, 3.0)  # Max 3x speedup
        return int(base_time / speedup)

    def update_device_performance(self, device_id: str, tokens_per_sec: float):
        """更新设备历史性能记录"""
        if device_id not in self.device_history:
            self.device_history[device_id] = []
        self.device_history[device_id].append(tokens_per_sec)
        # Keep last 20 records
        self.device_history[device_id] = self.device_history[device_id][-20:]
