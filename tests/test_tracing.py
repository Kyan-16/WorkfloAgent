"""
Tracing 子系统单元测试
"""
import os
import json
import tempfile
import pytest
from pathlib import Path
from utils.tracing import AgentTraceRecorder, _truncate, _trace_enabled, _max_chars


class TestTracingHelpers:
    """工具函数测试"""

    def test_trace_enabled_default(self, monkeypatch):
        monkeypatch.delenv("AGENT_TRACE_ENABLED", raising=False)
        assert _trace_enabled() is True

    def test_trace_enabled_false(self, monkeypatch):
        monkeypatch.setenv("AGENT_TRACE_ENABLED", "false")
        assert _trace_enabled() is False

    def test_trace_enabled_off(self, monkeypatch):
        monkeypatch.setenv("AGENT_TRACE_ENABLED", "off")
        assert _trace_enabled() is False

    def test_trace_enabled_0(self, monkeypatch):
        monkeypatch.setenv("AGENT_TRACE_ENABLED", "0")
        assert _trace_enabled() is False

    def test_max_chars_default(self):
        assert _max_chars() == 12000

    def test_max_chars_custom(self, monkeypatch):
        monkeypatch.setenv("AGENT_TRACE_MAX_CHARS", "500")
        assert _max_chars() == 500

    def test_max_chars_invalid(self, monkeypatch):
        monkeypatch.setenv("AGENT_TRACE_MAX_CHARS", "abc")
        assert _max_chars() == 12000

    def test_max_chars_min_floor(self, monkeypatch):
        monkeypatch.setenv("AGENT_TRACE_MAX_CHARS", "1")
        assert _max_chars() == 100

    def test_truncate_short_string(self):
        assert _truncate("short", limit=100) == "short"

    def test_truncate_long_string(self):
        long_str = "a" * 1000
        result = _truncate(long_str, limit=100)
        assert len(result) < len(long_str)
        assert "[truncated" in result

    def test_truncate_list(self):
        data = ["a" * 200, "b" * 200]
        result = _truncate(data, limit=50)
        assert isinstance(result, list)
        for item in result:
            assert "[truncated" in item

    def test_truncate_dict(self):
        data = {"key": "x" * 200}
        result = _truncate(data, limit=50)
        assert "[truncated" in result["key"]

    def test_truncate_non_string(self):
        assert _truncate(12345) == 12345
        assert _truncate(None) is None


class TestAgentTraceRecorder:
    """AgentTraceRecorder 测试"""

    def test_disabled_by_env(self, monkeypatch):
        monkeypatch.setenv("AGENT_TRACE_ENABLED", "false")
        recorder = AgentTraceRecorder("test", "s1", "hello")
        assert recorder.enabled is False
        assert len(recorder.events) == 0

    def test_record_event(self, monkeypatch):
        monkeypatch.setenv("AGENT_TRACE_ENABLED", "true")
        recorder = AgentTraceRecorder("test", "s1", "hello")
        assert recorder.enabled is True
        # run_start should be recorded
        assert len(recorder.events) >= 1
        assert recorder.events[0]["type"] == "run_start"

    def test_record_custom_event(self, monkeypatch):
        monkeypatch.setenv("AGENT_TRACE_ENABLED", "true")
        recorder = AgentTraceRecorder("test", "s1", "hello")
        recorder.record("llm_call", {"model": "test"})
        assert recorder.events[-1]["type"] == "llm_call"
        assert recorder.events[-1]["payload"]["model"] == "test"

    def test_finish_writes_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AGENT_TRACE_ENABLED", "true")
        trace_file = tmp_path / "test_traces.jsonl"
        monkeypatch.setenv("AGENT_TRACE_FILE", str(trace_file))

        recorder = AgentTraceRecorder("test", "s1", "hello")
        recorder.finish(status="success", response={"reply": "ok"})

        assert trace_file.exists()
        content = trace_file.read_text(encoding="utf-8")
        assert "trace_id" in content
        assert recorder.trace_id in content

    def test_fail_records_error(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AGENT_TRACE_ENABLED", "true")
        trace_file = tmp_path / "fails.jsonl"
        monkeypatch.setenv("AGENT_TRACE_FILE", str(trace_file))

        recorder = AgentTraceRecorder("test", "s1", "hello")
        recorder.fail(ValueError("something wrong"))

        assert trace_file.exists()
        content = trace_file.read_text(encoding="utf-8")
        assert "ValueError" in content
        assert "something wrong" in content

    def test_writes_valid_json(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AGENT_TRACE_ENABLED", "true")
        trace_file = tmp_path / "valid.jsonl"
        monkeypatch.setenv("AGENT_TRACE_FILE", str(trace_file))

        recorder = AgentTraceRecorder("test", "s1", "hi")
        recorder.record("tool_call", {"tool": "search"})
        recorder.finish()

        lines = trace_file.read_text(encoding="utf-8").strip().split("\n")
        for line in lines:
            record = json.loads(line)  # 抛出异常 = 格式不对
            assert "trace_id" in record
            assert "events" in record

    def test_trace_id_unique(self, monkeypatch):
        monkeypatch.setenv("AGENT_TRACE_ENABLED", "false")
        r1 = AgentTraceRecorder("test", "s1", "a")
        r2 = AgentTraceRecorder("test", "s1", "b")
        assert r1.trace_id != r2.trace_id

    def test_does_not_write_when_disabled(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AGENT_TRACE_ENABLED", "false")
        trace_file = tmp_path / "should_not_exist.jsonl"
        monkeypatch.setenv("AGENT_TRACE_FILE", str(trace_file))

        recorder = AgentTraceRecorder("test", "s1", "hello")
        recorder.finish()

        assert not trace_file.exists()
