"""
调度系统 — 后台调度服务

独立线程运行，每 5 秒检查一次到期任务。
支持正常启动/停止生命周期管理。
"""
import asyncio
import logging
import threading
import time
from typing import Optional, Callable

from ticket_agent.scheduler.task_store import TaskStore, ScheduledTask, compute_next_run

logger = logging.getLogger(__name__)

# 默认检查间隔（秒）
_DEFAULT_CHECK_INTERVAL = 5


class SchedulerService:
    """
    后台调度服务

    使用示例：
        async def on_task(task):
            print(f"执行任务: {task.name}")

        service = SchedulerService(on_task_callback=on_task)
        await service.start()

        # 添加任务
        task = ScheduledTask(
            id="daily_report",
            name="每日报告",
            task_type="interval",
            action_type="message",
            schedule_config={"interval_seconds": 3600},
            action_config={"message": "生成每日报告"},
        )
        service.store.add(task)

        # 停止
        await service.stop()
    """

    def __init__(
        self,
        on_task_callback: Optional[Callable] = None,
        store: Optional[TaskStore] = None,
        check_interval: int = _DEFAULT_CHECK_INTERVAL,
    ):
        self.store = store or TaskStore()
        self._callback = on_task_callback
        self._check_interval = check_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self):
        """启动调度服务"""
        if self._running:
            logger.warning("调度服务已在运行")
            return

        self._running = True
        self._loop = asyncio.get_event_loop()

        # 在独立线程中运行检查循环
        self._thread = threading.Thread(
            target=self._run_loop,
            name="scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"调度服务已启动 (检查间隔={self._check_interval}s)")

    def _run_loop(self):
        """后台检查循环"""
        while self._running:
            try:
                due_tasks = self.store.get_due()
                for task in due_tasks:
                    # 提交到事件循环执行
                    if self._loop and self._loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            self._execute_task(task), self._loop
                        )
            except Exception as e:
                logger.error(f"调度检查异常: {e}")

            time.sleep(self._check_interval)

    async def _execute_task(self, task: ScheduledTask):
        """执行单个任务"""
        try:
            logger.info(f"执行调度任务: {task.name} (id={task.id})")

            if self._callback:
                await self._callback(task)

            self.store.update_after_run(task.id)
            logger.info(f"调度任务完成: {task.name}")

        except Exception as e:
            logger.error(f"调度任务执行失败: {task.name}: {e}")
            self.store.update_after_run(task.id)

    async def stop(self):
        """停止调度服务"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._thread = None
        logger.info("调度服务已停止")

    def add_task(self, task: ScheduledTask) -> bool:
        """添加定时任务"""
        task.next_run = compute_next_run(task)
        return self.store.add(task)

    def remove_task(self, task_id: str) -> bool:
        """删除定时任务"""
        return self.store.remove(task_id)

    @property
    def is_running(self) -> bool:
        return self._running
