"""
调度系统 — 任务存储（JSON 持久化）

支持任务类型：
- once: 单次执行（ISO 时间或 +5m 相对时间）
- interval: 间隔执行（秒）
- cron: Cron 表达式

任务持久化到 JSON 文件，重启不丢失。
"""
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """定时任务定义"""
    id: str
    name: str
    task_type: str  # "once" | "interval" | "cron"
    action_type: str  # "message" | "ai_generate"
    action_config: dict = field(default_factory=dict)
    schedule_config: dict = field(default_factory=dict)
    next_run: Optional[str] = None  # ISO format
    enabled: bool = True
    created_at: str = ""
    last_run: Optional[str] = None
    run_count: int = 0


def _parse_relative_time(expression: str) -> Optional[datetime]:
    """解析相对时间表达式: +5m, +2h, +1d"""
    match = re.match(r"\+(\d+)([mhd])", expression)
    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2)

    now = datetime.utcnow()
    if unit == "m":
        return now + timedelta(minutes=value)
    elif unit == "h":
        return now + timedelta(hours=value)
    elif unit == "d":
        return now + timedelta(days=value)
    return None


def _parse_iso_time(expression: str) -> Optional[datetime]:
    """解析 ISO 时间"""
    try:
        return datetime.fromisoformat(expression)
    except (ValueError, TypeError):
        return None


def _parse_cron(expression: str) -> Optional[str]:
    """验证 cron 表达式格式（不做精确解析，只做格式校验）"""
    parts = expression.strip().split()
    if len(parts) != 5:
        return None
    return expression.strip()


def compute_next_run(task: ScheduledTask) -> Optional[str]:
    """计算下次执行时间"""
    sc = task.schedule_config

    if task.task_type == "once":
        expr = sc.get("time", "")
        # 相对时间
        dt = _parse_relative_time(expr)
        if dt:
            return dt.isoformat()
        # ISO 时间
        dt = _parse_iso_time(expr)
        if dt:
            return dt.isoformat()
        return None

    elif task.task_type == "interval":
        interval_seconds = sc.get("interval_seconds", 3600)
        now = datetime.utcnow()
        return (now + timedelta(seconds=interval_seconds)).isoformat()

    elif task.task_type == "cron":
        # 简化为每 N 分钟检查一次
        return None  # 由调度器定期检查

    return None


class TaskStore:
    """任务持久化存储（JSON 文件）"""

    def __init__(self, filepath: str = "data/scheduler_tasks.json"):
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._tasks: dict[str, ScheduledTask] = {}
        self._load()

    def _load(self):
        if self.filepath.exists():
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        task = ScheduledTask(**item)
                        self._tasks[task.id] = task
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"任务存储加载失败: {e}")

    def _save(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            data = [asdict(t) for t in self._tasks.values()]
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add(self, task: ScheduledTask) -> bool:
        with self._lock:
            if task.id in self._tasks:
                return False
            self._tasks[task.id] = task
            self._save()
            return True

    def remove(self, task_id: str) -> bool:
        with self._lock:
            if task_id not in self._tasks:
                return False
            del self._tasks[task_id]
            self._save()
            return True

    def get(self, task_id: str) -> Optional[ScheduledTask]:
        return self._tasks.get(task_id)

    def list_all(self) -> list[ScheduledTask]:
        return list(self._tasks.values())

    def get_due(self) -> list[ScheduledTask]:
        """获取到期待执行的任务"""
        now = datetime.utcnow().isoformat()
        due = []
        with self._lock:
            for task in self._tasks.values():
                if not task.enabled:
                    continue
                if task.next_run and task.next_run <= now:
                    due.append(task)
                elif task.task_type == "cron":
                    # cron 任务每次检查都触发
                    due.append(task)
        return due

    def update_after_run(self, task_id: str):
        """更新任务执行后的状态"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.last_run = datetime.utcnow().isoformat()
            task.run_count += 1
            task.next_run = compute_next_run(task)
            self._save()

    def clear(self):
        with self._lock:
            self._tasks.clear()
            self._save()
