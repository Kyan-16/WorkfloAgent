"""
三层记忆存储测试
"""
import os
import tempfile
from datetime import date

import pytest

from ticket_agent.memory.storage import MemoryStore


@pytest.fixture
def temp_store():
    """临时目录的 MemoryStore 实例"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = MemoryStore(base_dir=os.path.join(tmpdir, "memory"))
        yield store


def test_save_and_load_daily(temp_store):
    summary = "今天处理了 IT 工单，涉及网络故障排除"
    filepath = temp_store.save_daily(summary, entry_date=date(2026, 6, 1))
    assert filepath.exists()

    entries = temp_store.load_daily(days=7)
    assert len(entries) >= 1
    assert "IT 工单" in entries[0]["content"]


def test_empty_daily_returns_empty_list(temp_store):
    entries = temp_store.load_daily(days=7)
    assert entries == []


def test_save_and_load_memory(temp_store):
    content = "- 网络故障优先检查 DNS 配置\n- 蓝屏问题收集 dump 文件"
    temp_store.save_memory(content)
    assert temp_store.memory_file.exists()

    loaded = temp_store.load_memory()
    assert "DNS" in loaded
    assert "蓝屏" in loaded


def test_memory_not_exists_returns_empty(temp_store):
    loaded = temp_store.load_memory()
    assert loaded == ""


def test_create_and_rollback_snapshot(temp_store):
    temp_store.save_memory("- 原始记忆内容")

    sid = temp_store.create_snapshot()
    assert sid is not None

    # 修改记忆
    temp_store.save_memory("- 修改后的记忆内容")
    assert "修改后" in temp_store.load_memory()

    # 回滚
    temp_store.rollback(sid)
    assert "原始记忆" in temp_store.load_memory()


def test_evolution_log(temp_store):
    temp_store.log_evolution({"action": "test", "detail": "unit test"})
    temp_store.log_evolution({"action": "deep_dream", "size": 100})

    history = temp_store.get_evolution_history(limit=10)
    assert len(history) == 2
    assert history[0]["action"] == "test"
    assert history[1]["action"] == "deep_dream"


def test_delete_snapshot(temp_store):
    sid = temp_store.create_snapshot()
    temp_store.delete_snapshot(sid)
    with pytest.raises(FileNotFoundError):
        temp_store.rollback(sid)
