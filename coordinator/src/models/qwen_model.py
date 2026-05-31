"""
Model Partition Configuration for Qwen Series
模型分割配置：定义层边界、内存需求、检查点策略
"""
import json
import logging
from typing import List, Dict, Tuple
from dataclasses import dataclass

logger = logging.getLogger("MDCS.Model")

@dataclass
class LayerConfig:
    """单层配置"""
    layer_index: int
    layer_type: str  # embedding/attention/feedforward/norm
    params_count: int  # Number of parameters
    memory_mb_fp32: float
    memory_mb_int8: float
    flops_forward: int
    input_shape: Tuple[int, ...]
    output_shape: Tuple[int, ...]

class QwenModelPartition:
    """
    Qwen模型分割器
    支持按层拆分（流水线并行）和按数据拆分（数据并行）
    """

    def __init__(self, model_name: str = "qwen-1.8b"):
        self.model_name = model_name
        self.config = self._load_config(model_name)
        self.layers = self._build_layer_configs()

    def _load_config(self, model_name: str) -> dict:
        """加载模型配置"""
        configs = {
            "qwen-1.8b": {
                "num_layers": 24,
                "hidden_size": 2048,
                "intermediate_size": 5504,
                "num_attention_heads": 16,
                "vocab_size": 151936,
                "embedding_size": 2048,
                "layer_memory_mb": {
                    "embedding": 1200,  # Large due to vocab size
                    "attention": 45,
                    "feedforward": 85,
                    "norm": 2
                }
            },
            "qwen-0.5b": {
                "num_layers": 24,
                "hidden_size": 1024,
                "intermediate_size": 2816,
                "num_attention_heads": 16,
                "vocab_size": 151936,
                "embedding_size": 1024,
                "layer_memory_mb": {
                    "embedding": 600,
                    "attention": 12,
                    "feedforward": 22,
                    "norm": 1
                }
            }
        }
        return configs.get(model_name, configs["qwen-1.8b"])

    def _build_layer_configs(self) -> List[LayerConfig]:
        """构建每层配置"""
        cfg = self.config
        layers = []

        # Embedding layer (layer 0)
        layers.append(LayerConfig(
            layer_index=0,
            layer_type="embedding",
            params_count=cfg["vocab_size"] * cfg["embedding_size"],
            memory_mb_fp32=cfg["layer_memory_mb"]["embedding"],
            memory_mb_int8=cfg["layer_memory_mb"]["embedding"] * 0.3,
            flops_forward=0,
            input_shape=(1, 1),  # (batch, seq_len)
            output_shape=(1, 1, cfg["hidden_size"])
        ))

        # Transformer layers
        for i in range(cfg["num_layers"]):
            # Attention sub-layer
            layers.append(LayerConfig(
                layer_index=i * 2 + 1,
                layer_type="attention",
                params_count=4 * cfg["hidden_size"] * cfg["hidden_size"],  # Q,K,V,O
                memory_mb_fp32=cfg["layer_memory_mb"]["attention"],
                memory_mb_int8=cfg["layer_memory_mb"]["attention"] * 0.3,
                flops_forward=2 * cfg["hidden_size"] * cfg["hidden_size"] * 2,
                input_shape=(1, 1, cfg["hidden_size"]),
                output_shape=(1, 1, cfg["hidden_size"])
            ))

            # FFN sub-layer
            layers.append(LayerConfig(
                layer_index=i * 2 + 2,
                layer_type="feedforward",
                params_count=cfg["hidden_size"] * cfg["intermediate_size"] * 3,
                memory_mb_fp32=cfg["layer_memory_mb"]["feedforward"],
                memory_mb_int8=cfg["layer_memory_mb"]["feedforward"] * 0.3,
                flops_forward=2 * cfg["hidden_size"] * cfg["intermediate_size"] * 2,
                input_shape=(1, 1, cfg["hidden_size"]),
                output_shape=(1, 1, cfg["hidden_size"])
            ))

        # Final norm + LM head
        layers.append(LayerConfig(
            layer_index=len(layers),
            layer_type="norm",
            params_count=cfg["hidden_size"],
            memory_mb_fp32=cfg["layer_memory_mb"]["norm"],
            memory_mb_int8=cfg["layer_memory_mb"]["norm"],
            flops_forward=0,
            input_shape=(1, 1, cfg["hidden_size"]),
            output_shape=(1, 1, cfg["vocab_size"])
        ))

        return layers

    def get_layer_memory_requirement(self, layer_indices: List[int], quantization: str = "int8") -> float:
        """计算指定层组合的内存需求（MB）"""
        total = 0.0
        for idx in layer_indices:
            if 0 <= idx < len(self.layers):
                layer = self.layers[idx]
                if quantization == "int8":
                    total += layer.memory_mb_int8
                else:
                    total += layer.memory_mb_fp32
        return total

    def get_optimal_partition(self, device_capabilities: List[dict]) -> Dict[str, List[int]]:
        """
        基于线性规划的优化分割（参考LinguaLinked论文方法）
        目标：最小化最大完成时间（makespan）
        约束：每个设备的内存不超过上限
        """
        # Simplified greedy partition for demonstration
        # In production, use scipy.optimize.linprog or OR-Tools

        total_layers = len(self.layers)
        num_devices = len(device_capabilities)

        if num_devices == 0:
            return {}

        # Calculate device scores based on compute and memory
        scores = []
        for cap in device_capabilities:
            compute_score = cap.get("cpu_cores", 4) * cap.get("cpu_freq_mhz", 1000) / 1000
            memory_score = cap.get("available_ram_mb", 512) / 512
            score = compute_score * 0.6 + memory_score * 0.4
            scores.append(score)

        total_score = sum(scores)
        assignment = {}
        start = 0

        for i, cap in enumerate(device_capabilities[:-1]):
            ratio = scores[i] / total_score
            count = max(1, int(total_layers * ratio))
            end = min(start + count, total_layers - (num_devices - i - 1))
            assignment[cap["device_id"]] = list(range(start, end))
            start = end

        # Last device gets remaining
        assignment[device_capabilities[-1]["device_id"]] = list(range(start, total_layers))

        return assignment

    def export_config(self, path: str):
        """导出模型配置到JSON"""
        config = {
            "model_name": self.model_name,
            "num_layers": len(self.layers),
            "config": self.config,
            "layers": [
                {
                    "index": l.layer_index,
                    "type": l.layer_type,
                    "params": l.params_count,
                    "memory_int8_mb": l.memory_mb_int8
                }
                for l in self.layers
            ]
        }
        with open(path, "w") as f:
            json.dump(config, f, indent=2)
