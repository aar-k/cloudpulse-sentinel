"""Transparent rule-based incident risk score (brief, Section 14).

Risk = 0.25*CPU + 0.20*Memory + 0.20*Latency + 0.20*ErrorRate + 0.15*Traffic
Each component is normalized to 0-100. Weights/bands are project-defined.
"""
from dataclasses import dataclass

WEIGHTS = {"cpu": 0.25, "memory": 0.20, "latency": 0.20, "error": 0.20, "traffic": 0.15}

# Tunable normalization ranges (document any changes after testing)
LATENCY_OK_MS, LATENCY_BAD_MS = 100.0, 1000.0
ERROR_BAD_PCT = 10.0            # >=10% error rate => 100 risk
TRAFFIC_BAD_DEVIATION = 1.0     # +/-100% from baseline => 100 risk


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class Sample:
    cpu: float             # percent 0-100
    memory: float          # percent 0-100
    latency_ms: float
    error_rate: float      # percent 0-100
    request_count: float
    baseline_requests: float = 100.0


def components(s: Sample) -> dict:
    latency = (s.latency_ms - LATENCY_OK_MS) / (LATENCY_BAD_MS - LATENCY_OK_MS) * 100
    error = s.error_rate / ERROR_BAD_PCT * 100
    dev = abs(s.request_count - s.baseline_requests) / max(s.baseline_requests, 1)
    traffic = dev / TRAFFIC_BAD_DEVIATION * 100
    return {
        "cpu": _clamp(s.cpu),
        "memory": _clamp(s.memory),
        "latency": _clamp(latency),
        "error": _clamp(error),
        "traffic": _clamp(traffic),
    }


def risk_score(s: Sample) -> float:
    c = components(s)
    return round(sum(WEIGHTS[k] * c[k] for k in WEIGHTS), 2)


def severity(score: float) -> str:
    if score >= 80: return "Critical"
    if score >= 60: return "High"
    if score >= 30: return "Moderate"
    return "Low"


def explain(s: Sample) -> dict:
    """Score plus per-signal contribution, so the score is explainable."""
    c = components(s)
    contrib = {k: round(WEIGHTS[k] * c[k], 2) for k in WEIGHTS}
    score = round(sum(contrib.values()), 2)
    top = sorted(contrib, key=contrib.get, reverse=True)[:3]
    return {"risk_score": score, "severity": severity(score),
            "components": c, "contributions": contrib, "top_signals": top}
