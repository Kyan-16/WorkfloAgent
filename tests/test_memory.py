"""
Memory 模块单元测试
"""
import pytest

from memory.local_memory import LocalMemory
from memory.base import MemoryMessage


@pytest.mark.asyncio
async def test_local_memory_add_and_get():
    """测试基本添加和获取"""
    memory = LocalMemory(max_messages=10)
    await memory.add("s1", "user", "你好")
    await memory.add("s1", "assistant", "你好！")

    history = await memory.get_history("s1", limit=10)
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[0].content == "你好"
    assert history[1].role == "assistant"
    assert history[1].content == "你好！"


@pytest.mark.asyncio
async def test_local_memory_window():
    """测试滑动窗口裁剪"""
    memory = LocalMemory(max_messages=3)
    for i in range(5):
        await memory.add("s1", "user", f"msg{i}")

    history = await memory.get_history("s1", limit=10)
    assert len(history) == 3
    assert history[0].content == "msg2"


@pytest.mark.asyncio
async def test_local_memory_get_limit():
    """测试 get_history limit 参数"""
    memory = LocalMemory(max_messages=100)
    for i in range(10):
        await memory.add("s1", "user", f"msg{i}")

    history = await memory.get_history("s1", limit=3)
    assert len(history) == 3
    assert history[0].content == "msg7"


@pytest.mark.asyncio
async def test_local_memory_empty_session():
    """测试空会话"""
    memory = LocalMemory()
    history = await memory.get_history("nonexistent", limit=10)
    assert history == []


@pytest.mark.asyncio
async def test_local_memory_clear():
    """测试清除会话"""
    memory = LocalMemory()
    await memory.add("s1", "user", "你好")
    await memory.clear("s1")
    history = await memory.get_history("s1", limit=10)
    assert history == []


@pytest.mark.asyncio
async def test_local_memory_multiple_sessions():
    """测试多个会话隔离"""
    memory = LocalMemory()
    await memory.add("s1", "user", "会话1的消息")
    await memory.add("s2", "user", "会话2的消息")

    h1 = await memory.get_history("s1", limit=10)
    h2 = await memory.get_history("s2", limit=10)

    assert len(h1) == 1
    assert len(h2) == 1
    assert h1[0].content == "会话1的消息"
    assert h2[0].content == "会话2的消息"


@pytest.mark.asyncio
async def test_local_memory_concurrent_safety():
    """测试并发安全性（多个协程同时写入）"""
    import asyncio
    memory = LocalMemory(max_messages=100)

    async def writer(name: str, count: int):
        for i in range(count):
            await memory.add("concurrent", "user", f"{name}_{i}")

    # 启动 5 个并发写入器
    tasks = [writer(f"w{i}", 20) for i in range(5)]
    await asyncio.gather(*tasks)

    history = await memory.get_history("concurrent", limit=200)
    assert len(history) == 100  # 受 max_messages 限制
    # 验证没有消息丢失或损坏
    contents = [msg.content for msg in history]
    assert all("_" in c for c in contents)
