"""
Agent 运行轨迹记录。

把一次对话中的 RAG、Memory、LLM、Tool 调用按事件写入 JSONL，
方便离线复盘和问题定位。默认开启，可通过环境变量关闭：

AGENT_TRACE_ENABLED=false
AGENT_TRACE_FILE=traces/agent_runs.jsonl
AGENT_TRACE_MAX_CHARS=12000
"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

# 跨平台文件锁
# 使用锁文件（.lck）实现进程间互斥，防止多 worker 同时写入 trace 文件
_LOCK_SUPPORTED = True
if os.name == "nt":  # Windows
    import msvcrt

    def _acquire_lock(lock_path: Path) -> bool:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            return True
        except (FileExistsError, OSError):
            return False

    def _release_lock(lock_path: Path):
        try:
            lock_path.unlink()
        except OSError:
            pass
else:  # Unix / macOS
    import fcntl

    def _acquire_lock(lock_path: Path) -> bool:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_path._lock_fd = fd  # type: ignore[attr-defined]
            return True
        except (IOError, OSError):
            try:
                os.close(fd)
            except NameError:
                pass
            return False

    def _release_lock(lock_path: Path):
        fd = getattr(lock_path, "_lock_fd", None)
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            except OSError:
                pass
        try:
            lock_path.unlink()
        except OSError:
            pass

from llm.base import ChatMessage, LLMResponse


def _now_ms() -> int:
    return int(time.time() * 1000)


def _trace_enabled() -> bool:
    return os.getenv("AGENT_TRACE_ENABLED", "true").lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _max_chars() -> int:
    raw = os.getenv("AGENT_TRACE_MAX_CHARS", "12000")
    try:
        return max(100, int(raw))
    except ValueError:
        return 12000


def _truncate(value: Any, limit: Optional[int] = None) -> Any:
    """递归裁剪过长字段，避免 trace 文件失控。"""
    limit = limit or _max_chars()
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return value[:limit] + f"\n...[truncated, original_length={len(value)}]"
    if isinstance(value, list):
        return [_truncate(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: _truncate(item, limit) for key, item in value.items()}
    return value


def messages_to_dict(messages: list[ChatMessage]) -> list[dict]:
    return [msg.to_dict() for msg in messages]


def llm_response_to_dict(response: LLMResponse) -> dict:
    return {
        "content": response.content,
        "tool_calls": response.tool_calls,
        "model": response.model,
        "finish_reason": response.finish_reason,
        "tokens_used": response.tokens_used,
        "prompt_tokens": response.prompt_tokens,
        "completion_tokens": response.completion_tokens,
        "metadata": response.metadata,
    }


class AgentTraceRecorder:
    """一次 Agent 运行的事件记录器。"""

    def __init__(
        self,
        agent_type: str,
        session_id: str,
        user_input: str,
        metadata: Optional[dict] = None,
    ):
        self.enabled = _trace_enabled()
        self.trace_id = str(uuid.uuid4())
        self.agent_type = agent_type
        self.session_id = session_id
        self.started_at_ms = _now_ms()
        self.events: list[dict] = []
        self.metadata = metadata or {}

        if self.enabled:
            self.record(
                "run_start",
                {
                    "agent_type": agent_type,
                    "session_id": session_id,
                    "user_input": user_input,
                    "metadata": self.metadata,
                },
            )

    def record(self, event_type: str, payload: Optional[dict] = None):
        if not self.enabled:
            return
        self.events.append(
            {
                "type": event_type,
                "timestamp_ms": _now_ms(),
                "elapsed_ms": _now_ms() - self.started_at_ms,
                "payload": _truncate(payload or {}),
            }
        )

    def finish(self, status: str = "success", response: Optional[dict] = None):
        if not self.enabled:
            return
        self.record("run_end", {"status": status, "response": response or {}})
        self._write()

    def fail(self, error: Exception):
        if not self.enabled:
            return
        self.record(
            "run_error",
            {
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )
        self.finish(status="error")

    def _write(self):
        trace_file = Path(os.getenv("AGENT_TRACE_FILE", "traces/agent_runs.jsonl"))
        trace_file.parent.mkdir(parents=True, exist_ok=True)

        # 文件大小轮转：超过阈值时归档
        max_bytes = int(os.getenv("AGENT_TRACE_MAX_FILE_SIZE", str(50 * 1024 * 1024)))  # 默认 50MB
        if trace_file.exists() and trace_file.stat().st_size > max_bytes:
            self._rotate(trace_file)

        record = {
            "trace_id": self.trace_id,
            "agent_type": self.agent_type,
            "session_id": self.session_id,
            "started_at_ms": self.started_at_ms,
            "finished_at_ms": _now_ms(),
            "events": self.events,
        }

        # 进程间文件锁（防止多 worker 并发写入交叉错乱）
        lock_file = trace_file.with_suffix(".jsonl.lck")
        locked = False
        try:
            locked = _acquire_lock(lock_file)
        except Exception:
            pass  # 不支持锁的场景直接写

        try:
            with trace_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        finally:
            if locked:
                _release_lock(lock_file)

    @staticmethod
    def _rotate(path: Path):
        """轮转 trace 文件，保留最多 5 个备份"""
        for i in range(4, 0, -1):
            old = path.with_suffix(f".{i}.jsonl")
            if old.exists():
                if i == 4:
                    old.unlink()
                else:
                    old.rename(path.with_suffix(f".{i + 1}.jsonl"))
        path.rename(path.with_suffix(".1.jsonl"))
