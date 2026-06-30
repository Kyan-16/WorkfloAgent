"""
三层记忆 — SQLite 会话持久化存储

支持：
- 会话管理的 CRUD
- 消息的追加写入
- Schema 版本迁移
- 按时间/ session_id 检索

与原 ConversationStore 的区别：
- 增加了 channel_type 字段（区分 web/feishu/wecom）
- 增加了 Schema 版本号
- 使用 WAL 模式提升并发性能
"""
import json
import sqlite3
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 2


class ConversationStore:
    """
    SQLite 会话持久化存储

    Schema:
        sessions:
          - id TEXT PRIMARY KEY
          - channel_type TEXT DEFAULT 'web'
          - created_at TEXT
          - last_active TEXT
          - metadata TEXT (JSON)

        messages:
          - id INTEGER PRIMARY KEY AUTOINCREMENT
          - session_id TEXT REFERENCES sessions(id)
          - role TEXT
          - content TEXT
          - created_at TEXT
          - metadata TEXT (JSON)

    Indexes:
        idx_messages_session (session_id, created_at)
        idx_sessions_last_active (last_active)
    """

    def __init__(self, db_path: str = "data/ticket_agent.db"):
        self.db_path = db_path
        self._lock = threading.Lock()

        # 确保目录存在
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接（线程安全）"""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        """初始化数据库 Schema（含版本迁移）"""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()

                # 创建 Schema 版本表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS schema_version (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )
                """)

                # 获取当前版本
                cursor.execute("SELECT MAX(version) FROM schema_version")
                row = cursor.fetchone()
                current_version = row[0] if row[0] else 0

                # 执行迁移
                if current_version < 1:
                    self._migrate_v1(cursor)
                    cursor.execute(
                        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                        (1, datetime.now().isoformat()),
                    )
                    logger.info("Schema 迁移到 v1")

                if current_version < 2:
                    self._migrate_v2(cursor)
                    cursor.execute(
                        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                        (2, datetime.now().isoformat()),
                    )
                    logger.info("Schema 迁移到 v2")

                conn.commit()
            finally:
                conn.close()

    def _migrate_v1(self, cursor: sqlite3.Cursor):
        """v1: 基础表结构"""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                channel_type TEXT NOT NULL DEFAULT 'web',
                created_at TEXT NOT NULL,
                last_active TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, created_at)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_last_active
            ON sessions(last_active)
        """)

    def _migrate_v2(self, cursor: sqlite3.Cursor):
        """v2: 添加 tool_calls 支持"""
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN tool_calls TEXT DEFAULT NULL")
            logger.debug("迁移 v2: 添加 tool_calls 列")
        except sqlite3.OperationalError:
            pass  # 列已存在

    # ── 会话管理 ──

    def create_session(self, session_id: str, channel_type: str = "web",
                       metadata: dict = None) -> bool:
        """创建新会话"""
        now = datetime.now().isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO sessions (id, channel_type, created_at, last_active, metadata)
                       VALUES (?, ?, ?, ?, ?)""",
                    (session_id, channel_type, now, now,
                     json.dumps(metadata or {}, ensure_ascii=False)),
                )
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"创建会话失败: {e}")
                return False
            finally:
                conn.close()

    def update_session_activity(self, session_id: str):
        """更新会话活动时间"""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "UPDATE sessions SET last_active = ? WHERE id = ?",
                    (datetime.now().isoformat(), session_id),
                )
                conn.commit()
            finally:
                conn.close()

    # ── 消息管理 ──

    def add_message(self, session_id: str, role: str, content: str,
                    metadata: dict = None, tool_calls: list = None) -> bool:
        """添加消息"""
        # 确保会话存在
        self.create_session(session_id)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """INSERT INTO messages (session_id, role, content, created_at, metadata, tool_calls)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (session_id, role, content or "", datetime.now().isoformat(),
                     json.dumps(metadata or {}, ensure_ascii=False),
                     json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None),
                )
                conn.execute(
                    "UPDATE sessions SET last_active = ? WHERE id = ?",
                    (datetime.now().isoformat(), session_id),
                )
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"添加消息失败: {e}")
                return False
            finally:
                conn.close()

    def get_messages(self, session_id: str, limit: int = 50) -> list[dict]:
        """获取会话消息列表"""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """SELECT role, content, created_at, metadata, tool_calls
                       FROM messages WHERE session_id = ?
                       ORDER BY created_at ASC LIMIT ?""",
                    (session_id, limit),
                )
                messages = []
                for row in cursor.fetchall():
                    msg = {
                        "role": row["role"],
                        "content": row["content"],
                        "created_at": row["created_at"],
                    }
                    if row["metadata"]:
                        try:
                            msg["metadata"] = json.loads(row["metadata"])
                        except json.JSONDecodeError:
                            msg["metadata"] = {}
                    if row["tool_calls"]:
                        try:
                            msg["tool_calls"] = json.loads(row["tool_calls"])
                        except json.JSONDecodeError:
                            pass
                    messages.append(msg)
                return messages
            finally:
                conn.close()

    def delete_session(self, session_id: str) -> bool:
        """删除会话及所有消息"""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"删除会话失败: {e}")
                return False
            finally:
                conn.close()

    def get_active_sessions(self, hours: int = 24) -> list[dict]:
        """获取最近活跃的会话"""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """SELECT id, channel_type, created_at, last_active, metadata
                       FROM sessions WHERE last_active > ?
                       ORDER BY last_active DESC""",
                    (cutoff,),
                )
                return [dict(row) for row in cursor.fetchall()]
            finally:
                conn.close()
