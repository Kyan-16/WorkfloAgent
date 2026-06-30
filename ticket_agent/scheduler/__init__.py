"""
调度系统

定时任务管理，支持：
- once: 单次执行（ISO 时间或 +5m 相对时间）
- interval: 间隔执行（秒）
- cron: Cron 表达式

使用方式：
    service = SchedulerService(on_task_callback=my_handler)
    await service.start()

    task = ScheduledTask(id="report", name="报告", task_type="interval",
                         schedule_config={"interval_seconds": 3600})
    service.add_task(task)
    await service.stop()
"""
from ticket_agent.scheduler.task_store import TaskStore, ScheduledTask, compute_next_run
from ticket_agent.scheduler.scheduler_service import SchedulerService

__all__ = ["TaskStore", "ScheduledTask", "SchedulerService", "compute_next_run"]
