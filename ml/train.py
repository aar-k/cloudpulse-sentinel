"""Train and evaluate the anomaly detector.

Run from the project root:   python ml/train.py
Makes: ml/models/isolation_forest.joblib, ml/models/metadata.json, data/synthetic_metrics.csv
There are no real labels, so we SYNTHESISE 7 days of normal metrics, inject labelled incidents,
train WITHOUT labels, and use the labels only to score the result.
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import classification_report, precision_recall_fscore_support

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ["cpu", "memory", "latency_ms", "error_rate", "request_count"]
MINUTES = 7 * 24 * 60   # 7 days, one sample per minute


def make_service(rng, name: str, inject: bool, idle: bool = False) -> pd.DataFrame:
    t = np.arange(MINUTES)
    daily = np.sin(2 * np.pi * (t % 1440) / 1440)            # busy by day, quiet by night
    df = pd.DataFrame({
        "service": name,
        "minute": t,
        "cpu": rng.normal(35, 5, MINUTES) + 4 * daily,
        "memory": rng.normal(50, 4, MINUTES),
        "latency_ms": rng.normal(120, 15, MINUTES) + 8 * daily,
        "error_rate": np.abs(rng.normal(0.5, 0.2, MINUTES)),
        "request_count": rng.normal(100, 8, MINUTES) + 8 * daily,
        "label": 0,
    })
    if idle:                                                 # a lightly used batch worker
        df["cpu"] = rng.normal(6, 2, MINUTES)
        df["memory"] = rng.normal(28, 3, MINUTES)
    if inject and not idle:                                  # ~5% of time is an incident
        kinds = ["cpu_latency", "error_surge", "traffic_spike"]
        n_events = 45
        for _ in range(n_events):
            start = int(rng.integers(0, MINUTES - 20))
            length = int(rng.integers(5, 15))
            sl = slice(start, start + length)
            kind = kinds[int(rng.integers(0, 3))]
            if kind == "cpu_latency":
                df.loc[df.index[sl], "cpu"] = rng.normal(92, 3, length)
                df.loc[df.index[sl], "memory"] = rng.normal(82, 4, length)
                df.loc[df.index[sl], "latency_ms"] = rng.normal(850, 80, length)
                df.loc[df.index[sl], "error_rate"] = rng.normal(8, 1.5, length)
                df.loc[df.index[sl], "request_count"] = rng.normal(210, 20, length)
            elif kind == "error_surge":
                df.loc[df.index[sl], "error_rate"] = rng.normal(12, 2, length)
                df.loc[df.index[sl], "latency_ms"] = rng.normal(400, 50, length)
            else:
                df.loc[df.index[sl], "request_count"] = rng.normal(300, 30, length)
                df.loc[df.index[sl], "cpu"] = rng.normal(70, 5, length)
            df.loc[df.index[sl], "label"] = 1
    df["cpu"] = df["cpu"].clip(0, 100)
    df["memory"] = df["memory"].clip(0, 100)
    df["error_rate"] = df["error_rate"].clip(0, 100)
    df["latency_ms"] = df["latency_ms"].clip(1, None)
    df["request_count"] = df["request_count"].clip(0, None)
    return df


def make_dataset(seed: int, inject: bool) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = [make_service(rng, s, inject) for s in ("payment-api", "auth-api", "orders-api")]
    frames.append(make_service(rng, "batch-worker", inject, idle=True))
    return pd.concat(frames, ignore_index=True)


def main():
    train = make_dataset(seed=42, inject=True)      # mostly normal, a few incidents mixed in
    test = make_dataset(seed=7, inject=True)        # different random data for honest scoring
    (ROOT / "data").mkdir(exist_ok=True)
    train.to_csv(ROOT / "data" / "synthetic_metrics.csv", index=False)

    normal = train[train["label"] == 0]
    baseline = {f: {"mean": float(normal[f].mean()), "std": float(normal[f].std())} for f in FEATURES}

    model = IsolationForest(n_estimators=200, contamination=0.03, random_state=42)
    model.fit(train[FEATURES].values)                      # unsupervised: labels are NOT used

    pred = (model.predict(test[FEATURES].values) == -1).astype(int)
    p, r, f1, _ = precision_recall_fscore_support(test["label"], pred, average="binary")
    print(classification_report(test["label"], pred, target_names=["normal", "anomaly"]))

    fp_rate = float(((pred == 1) & (test["label"] == 0)).sum() / (test["label"] == 0).sum())
    meta = {
        "algorithm": "IsolationForest(n_estimators=200, contamination=0.03)",
        "features": FEATURES, "baseline": baseline,
        "train_rows": int(len(train)), "test_rows": int(len(test)),
        "precision": round(float(p), 3), "recall": round(float(r), 3), "f1": round(float(f1), 3),
        "false_positive_rate": round(fp_rate, 3),
        "note": "Trained on synthetic data; labels used only for evaluation.",
    }
    out = ROOT / "ml" / "models"
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out / "isolation_forest.joblib")
    (out / "metadata.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps({k: meta[k] for k in ("precision", "recall", "f1", "false_positive_rate")}))


if __name__ == "__main__":
    main()
