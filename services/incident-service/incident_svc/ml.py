"""ML anomaly detection (Isolation Forest). The model file is made by ml/train.py."""
import json
import os
from pathlib import Path

FEATURES = ["cpu", "memory", "latency_ms", "error_rate", "request_count"]
SIGNAL_NAMES = {
    "cpu": "CPU", "memory": "memory", "latency_ms": "latency",
    "error_rate": "error rate", "request_count": "traffic",
}

def _find_model_dir() -> Path:
    """MODEL_DIR (set in the Docker image) wins; otherwise look for ml/models above this file."""
    if os.getenv("MODEL_DIR"):
        return Path(os.environ["MODEL_DIR"])
    for parent in Path(__file__).resolve().parents:
        if (parent / "ml" / "models").is_dir():
            return parent / "ml" / "models"
    return Path("ml/models")


_MODEL_DIR = _find_model_dir()
_state = {"loaded": False, "model": None, "meta": None}


def _load():
    if _state["loaded"]:
        return
    _state["loaded"] = True
    try:
        import joblib
        _state["model"] = joblib.load(_MODEL_DIR / "isolation_forest.joblib")
        _state["meta"] = json.loads((_MODEL_DIR / "metadata.json").read_text())
        print(f"[ml] model loaded from {_MODEL_DIR}")
    except Exception as exc:  # noqa: BLE001
        print(f"[ml] model NOT loaded ({exc}). Running with rules only.")


def predict(snapshot: dict) -> dict:
    """Return {available, anomaly, anomaly_score (0-1, higher = more unusual), signals}."""
    _load()
    model, meta = _state["model"], _state["meta"]
    if model is None:
        return {"available": False, "anomaly": False, "anomaly_score": 0.0, "signals": []}
    import numpy as np
    x = np.array([[float(snapshot[f]) for f in FEATURES]])
    anomaly = bool(model.predict(x)[0] == -1)
    score = float(round(-model.score_samples(x)[0], 3))
    signals = []
    for f in FEATURES:
        mean, std = meta["baseline"][f]["mean"], max(meta["baseline"][f]["std"], 1e-6)
        z = (float(snapshot[f]) - mean) / std
        if z >= 3:
            signals.append(f"{SIGNAL_NAMES[f]} increase")
        elif z <= -3:
            signals.append(f"{SIGNAL_NAMES[f]} drop")
    return {"available": True, "anomaly": anomaly, "anomaly_score": score, "signals": signals}
