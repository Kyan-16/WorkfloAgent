"""
工具熔断器测试
"""
import pytest

from tools.circuit_breaker import ToolCircuitBreaker


def test_initial_state():
    b = ToolCircuitBreaker()
    ok, msg = b.check_call("test", "{}")
    assert ok
    assert msg == ""


def test_consecutive_failures_block():
    """连续失败 3 次应阻塞"""
    b = ToolCircuitBreaker()
    for i in range(3):
        ok, _ = b.check_call("test", '{"a": 1}')
        assert ok  # 前 3 次允许
        b.record_failure("test", '{"a": 1}')

    # 第 4 次应被阻塞
    ok, msg = b.check_call("test", '{"a": 1}')
    assert not ok
    assert "陷入循环" in msg


def test_success_loop_block():
    """成功 5 次相同参数应阻塞"""
    b = ToolCircuitBreaker()
    b.SUCCESS_LOOP_BLOCK = 3  # 调低阈值加速测试

    for i in range(3):
        ok, _ = b.check_call("test", '{"a": 1}')
        assert ok
        b.record_success("test", '{"a": 1}')

    # 应被阻塞
    ok, msg = b.check_call("test", '{"a": 1}')
    assert not ok


def test_different_args_not_blocked():
    """不同参数不应被阻塞"""
    b = ToolCircuitBreaker()
    for i in range(3):
        b.record_failure("test", '{"a": 1}')

    # 不同参数应仍允许
    ok, msg = b.check_call("test", '{"b": 2}')
    assert ok


def test_soft_stop():
    """总失败 6 次触发软停止"""
    b = ToolCircuitBreaker()
    b.TOTAL_FAILURES_SOFT = 3  # 调低阈值

    for i in range(3):
        b.check_call("test", f'{{"i": {i}}}')
        b.record_failure("test", f'{{"i": {i}}}')

    ok, msg = b.check_call("test", '{"new": 1}')
    assert not ok
    assert "失败次数过多" in msg


def test_hard_breaker():
    """总失败 8 次触发致命熔断"""
    b = ToolCircuitBreaker()
    b.TOTAL_FAILURES_HARD = 3  # 调低阈值

    for i in range(3):
        b.check_call("test", f'{{"i": {i}}}')
        b.record_failure("test", f'{{"i": {i}}}')

    ok, msg = b.check_call("test", '{"new": 1}')
    assert not ok
    assert "非常抱歉" in msg


def test_stats():
    b = ToolCircuitBreaker()
    b.record_success("tool1", "{}")
    b.record_failure("tool2", "{}")

    stats = b.stats
    assert stats["total_calls"] == 2
    assert stats["total_failures"] == 1
    assert not stats["is_hard_breaked"]


def test_reset():
    b = ToolCircuitBreaker()
    b.record_failure("test", "{}")
    b.reset()
    assert b.stats["total_calls"] == 0
    assert b.stats["total_failures"] == 0

    ok, msg = b.check_call("test", "{}")
    assert ok
