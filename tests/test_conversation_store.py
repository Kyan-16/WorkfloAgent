"""
SQLite 会话持久化存储测试
"""
import os
import tempfile
import pytest

from ticket_agent.memory.conversation_store import ConversationStore


@pytest.fixture
def temp_store():
    """临时数据库的 ConversationStore 实例"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_conversations.db")
        store = ConversationStore(db_path=db_path)
        yield store


def test_create_and_get_session(temp_store):
    assert temp_store.create_session("session_1", channel_type="web")
    sessions = temp_store.get_active_sessions(hours=24)
    assert any(s["id"] == "session_1" for s in sessions)


def test_add_and_get_messages(temp_store):
    temp_store.add_message("s1", "user", "你好")
    temp_store.add_message("s1", "assistant", "你好！有什么可以帮你的？")

    messages = temp_store.get_messages("s1", limit=10)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "你好"
    assert messages[1]["role"] == "assistant"


def test_get_messages_empty_session(temp_store):
    messages = temp_store.get_messages("nonexistent", limit=10)
    assert messages == []


def test_get_messages_limit(temp_store):
    for i in range(10):
        temp_store.add_message("s1", "user", f"msg{i}")

    messages = temp_store.get_messages("s1", limit=3)
    assert len(messages) == 3


def test_add_message_with_metadata(temp_store):
    temp_store.add_message("s1", "user", "你好", metadata={"source": "web", "ip": "127.0.0.1"})
    messages = temp_store.get_messages("s1", limit=10)
    assert messages[0]["metadata"]["source"] == "web"
    assert messages[0]["metadata"]["ip"] == "127.0.0.1"


def test_add_message_with_tool_calls(temp_store):
    temp_store.add_message(
        "s1", "assistant", "",
        tool_calls=[{"id": "call_1", "function": {"name": "test_tool"}}],
    )
    messages = temp_store.get_messages("s1", limit=10)
    assert len(messages[0]["tool_calls"]) == 1
    assert messages[0]["tool_calls"][0]["function"]["name"] == "test_tool"


def test_delete_session(temp_store):
    temp_store.add_message("s1", "user", "你好")
    assert temp_store.delete_session("s1")
    messages = temp_store.get_messages("s1", limit=10)
    assert messages == []


def test_update_session_activity(temp_store):
    temp_store.create_session("s1")
    temp_store.update_session_activity("s1")
    sessions = temp_store.get_active_sessions(hours=24)
    assert any(s["id"] == "s1" for s in sessions)


def test_get_active_sessions(temp_store):
    temp_store.create_session("old_session", channel_type="web")
    sessions = temp_store.get_active_sessions(hours=24)
    assert len(sessions) >= 1
