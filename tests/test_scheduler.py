"""
调度系统测试
"""
import os
import tempfile
import pytest
from datetime import datetime

from ticket_agent.scheduler.task_store import TaskStore, ScheduledTask, compute_next_run


@pytest.fixture
def temp_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TaskStore(filepath=os.path.join(tmpdir, "tasks.json"))
        yield store


def test_add_and_get_task(temp_store):
    task = ScheduledTask(
        id="test1", name="测试任务", task_type="interval",
        action_type="message", action_config={"message": "hello"},
        schedule_config={"interval_seconds": 3600},
        created_at=datetime.utcnow().isoformat(),
    )
    assert temp_store.add(task)
    assert temp_store.get("test1") is not None
    assert temp_store.get("test1").name == "测试任务"


def test_add_duplicate(temp_store):
    task = ScheduledTask(id="test1", name="t1", task_type="once",
                         action_type="message", schedule_config={},
                         created_at=datetime.utcnow().isoformat())
    assert temp_store.add(task)
    assert not temp_store.add(task)  # 重复添加应返回 False


def test_remove_task(temp_store):
    task = ScheduledTask(id="test1", name="t1", task_type="once",
                         action_type="message", schedule_config={},
                         created_at=datetime.utcnow().isoformat())
    temp_store.add(task)
    assert temp_store.remove("test1")
    assert temp_store.get("test1") is None


def test_list_all(temp_store):
    for i in range(3):
        task = ScheduledTask(id=f"t{i}", name=f"task{i}", task_type="once",
                             action_type="message", schedule_config={},
                             created_at=datetime.utcnow().isoformat())
        temp_store.add(task)
    assert len(temp_store.list_all()) == 3


def test_get_due(temp_store):
    # 过去的时间 → 到期
    task = ScheduledTask(
        id="due_task", name="到期任务", task_type="once",
        action_type="message", schedule_config={},
        next_run="2020-01-01T00:00:00",
        created_at=datetime.utcnow().isoformat(),
    )
    temp_store.add(task)
    due = temp_store.get_due()
    assert len(due) == 1


def test_get_due_not_yet(temp_store):
    task = ScheduledTask(
        id="future_task", name="未来任务", task_type="once",
        action_type="message", schedule_config={},
        next_run="2099-01-01T00:00:00",
        created_at=datetime.utcnow().isoformat(),
    )
    temp_store.add(task)
    due = temp_store.get_due()
    assert len(due) == 0


def test_disabled_task_not_due(temp_store):
    task = ScheduledTask(
        id="disabled", name="禁用任务", task_type="once",
        action_type="message", schedule_config={},
        next_run="2020-01-01T00:00:00",
        enabled=False,
        created_at=datetime.utcnow().isoformat(),
    )
    temp_store.add(task)
    assert len(temp_store.get_due()) == 0


def test_update_after_run(temp_store):
    task = ScheduledTask(
        id="t1", name="t1", task_type="interval",
        action_type="message", schedule_config={"interval_seconds": 60},
        next_run="2020-01-01T00:00:00",
        created_at=datetime.utcnow().isoformat(),
    )
    temp_store.add(task)
    temp_store.update_after_run("t1")
    updated = temp_store.get("t1")
    assert updated.run_count == 1
    assert updated.last_run is not None


def test_persistence(temp_store):
    task = ScheduledTask(id="persist", name="持久化任务", task_type="once",
                         action_type="message", schedule_config={},
                         created_at=datetime.utcnow().isoformat())
    temp_store.add(task)

    # 重新加载应存在
    store2 = TaskStore(filepath=temp_store.filepath)
    assert store2.get("persist") is not None


def test_compute_next_run_relative():
    task = ScheduledTask(id="t", name="t", task_type="once",
                         action_type="message",
                         schedule_config={"time": "+5m"},
                         created_at=datetime.utcnow().isoformat())
    next_run = compute_next_run(task)
    assert next_run is not None


def test_compute_next_run_interval():
    task = ScheduledTask(id="t", name="t", task_type="interval",
                         action_type="message",
                         schedule_config={"interval_seconds": 3600},
                         created_at=datetime.utcnow().isoformat())
    next_run = compute_next_run(task)
    assert next_run is not None


def test_clear(temp_store):
    task = ScheduledTask(id="t1", name="t", task_type="once",
                         action_type="message", schedule_config={},
                         created_at=datetime.utcnow().isoformat())
    temp_store.add(task)
    temp_store.clear()
    assert len(temp_store.list_all()) == 0
