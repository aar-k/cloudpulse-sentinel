"""Cost and waste intelligence: flags consistently under-used services.

Prices are EXAMPLE on-demand list prices (US East, USD per hour) used only to illustrate the
calculation. Replace them with your provider's real pricing for a real estimate.
"""
from datetime import timedelta

from sqlalchemy import func, select

from .db import utcnow

EXAMPLE_HOURLY_PRICE = {"t3.micro": 0.0104, "t3.small": 0.0208, "t3.medium": 0.0416, "t3.large": 0.0832}
SIZE_ORDER = ["t3.micro", "t3.small", "t3.medium", "t3.large"]

# Which (pretend) instance each demo service runs on.
SERVICE_INSTANCE = {
    "payment-api": "t3.medium", "auth-api": "t3.medium", "orders-api": "t3.medium",
    "batch-worker": "t3.large",
}
DEFAULT_INSTANCE = "t3.medium"
HOURS_PER_MONTH = 730


def _smaller(instance: str):
    i = SIZE_ORDER.index(instance) if instance in SIZE_ORDER else -1
    return SIZE_ORDER[i - 1] if i > 0 else None


def waste_report(conn, metrics, hours: int = 24, cpu_threshold: float = 10.0,
                 min_samples: int = 20) -> list[dict]:
    cutoff = utcnow() - timedelta(hours=hours)
    rows = conn.execute(
        select(metrics.c.service,
               func.count().label("n"),
               func.avg(metrics.c.cpu).label("avg_cpu"), func.max(metrics.c.cpu).label("peak_cpu"),
               func.avg(metrics.c.memory).label("avg_mem"), func.max(metrics.c.memory).label("peak_mem"))
        .where(metrics.c.ts >= cutoff).group_by(metrics.c.service)
    ).all()
    report = []
    for r in rows:
        instance = SERVICE_INSTANCE.get(r.service, DEFAULT_INSTANCE)
        hourly = EXAMPLE_HOURLY_PRICE[instance]
        under = r.n >= min_samples and r.avg_cpu < cpu_threshold and r.peak_cpu < 50
        smaller = _smaller(instance)
        saving = 0.0
        if under and smaller:
            saving = round((hourly - EXAMPLE_HOURLY_PRICE[smaller]) * HOURS_PER_MONTH, 2)
        if under:
            reason = (f"Average CPU {r.avg_cpu:.1f}% is below {cpu_threshold:.0f}% and peak CPU is "
                      f"{r.peak_cpu:.0f}% over the last {hours} h")
            action = f"Consider downsizing {instance} -> {smaller}" if smaller else "Consider consolidating"
        elif r.n < min_samples:
            reason, action = f"Only {r.n} samples so far (need {min_samples})", "Wait for more data"
        else:
            reason, action = "Utilization is healthy", "No action"
        report.append({
            "service": r.service, "instance_type": instance, "samples": r.n,
            "avg_cpu": round(float(r.avg_cpu), 1), "peak_cpu": round(float(r.peak_cpu), 1),
            "avg_memory": round(float(r.avg_mem), 1), "peak_memory": round(float(r.peak_mem), 1),
            "underutilized": under, "reason": reason, "recommendation": action,
            "estimated_monthly_cost_usd": round(hourly * HOURS_PER_MONTH, 2),
            "estimated_monthly_saving_usd": saving,
        })
    return sorted(report, key=lambda x: (not x["underutilized"], x["service"]))
