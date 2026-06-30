"""
SLA 配置：按优先级定义目标解决时间
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass
class SLAConfig:
    response_minutes: int
    resolve_minutes: int


SLA_TABLE: dict[str, SLAConfig] = {
    "urgent": SLAConfig(response_minutes=30, resolve_minutes=240),
    "high":   SLAConfig(response_minutes=60, resolve_minutes=480),
    "normal": SLAConfig(response_minutes=240, resolve_minutes=1440),
    "low":    SLAConfig(response_minutes=480, resolve_minutes=2880),
}

DEFAULT_PRIORITY = "normal"


def get_sla_deadline(priority: str, created_at: Optional[datetime] = None) -> Optional[datetime]:
    """根据优先级计算 SLA 截止时间"""
    config = SLA_TABLE.get(priority)
    if config is None:
        config = SLA_TABLE[DEFAULT_PRIORITY]
    base = created_at or datetime.now(timezone.utc)
    return base + timedelta(minutes=config.resolve_minutes)
