from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Protocol


class Embedder(Protocol):
    dim: int
    model_type: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


def pack_vector(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *[float(v) for v in values])


def unpack_vector(blob: bytes) -> list[float]:
    count = len(blob) // 4
    if count == 0:
        return []
    return list(struct.unpack(f"<{count}f", blob[: count * 4]))


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right, strict=True):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / math.sqrt(left_norm * right_norm)


def validate_model_dir(path: Path) -> dict:
    if not path.exists() or not path.is_dir():
        raise ValueError("模型路径必须是已存在的目录")
    config_path = path / "config.json"
    if not config_path.is_file():
        raise ValueError("缺少 config.json，无法确认模型兼容性")
    try:
        meta = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("config.json 无法解析") from exc
    if not isinstance(meta, dict):
        raise ValueError("config.json 格式不正确")
    weights = [
        item
        for item in path.rglob("*")
        if item.is_file() and item.suffix.lower() in {".safetensors", ".bin", ".onnx", ".ot"} and item.name != "tokenizer.json"
    ]
    if not weights:
        raise ValueError("未找到模型权重文件（safetensors / bin / onnx）")
    model_type = meta.get("model_type") or ""
    architectures = meta.get("architectures") or []
    if isinstance(architectures, list):
        arch = ",".join(str(item) for item in architectures)
    else:
        arch = str(architectures)
    identity = model_type or arch or "unknown"
    return {
        "model_type": str(identity)[:120],
        "weight_files": len(weights),
        "path": str(path.resolve()),
    }


def sentence_transformers_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


class SentenceTransformerEmbedder:
    def __init__(self, model_path: str) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_path)
        self.model_type = Path(model_path).name
        sample = self.embed(["agentshelf"])
        self.dim = len(sample[0]) if sample else 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(list(texts), normalize_embeddings=True)
        return [list(map(float, row)) for row in vectors]


def load_local_embedder(model_path: str) -> Embedder:
    if not sentence_transformers_available():
        raise RuntimeError("未安装可选依赖 sentence-transformers，基础检索仍可使用")
    return SentenceTransformerEmbedder(model_path)
