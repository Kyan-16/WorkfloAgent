"""
数据库连接管理

使用 SQLAlchemy 支持 MySQL，兼容 SQLite 开发模式。
"""
import os
import logging
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger(__name__)

Base = declarative_base()

_engine = None
_SessionLocal = None


def get_db_url() -> str:
    """获取数据库连接 URL，按优先级：环境变量 > 默认 SQLite"""
    db_url = os.getenv("DATABASE_URL", "")
    if db_url:
        return db_url

    # MySQL 配置（通过独立环境变量）
    mysql_host = os.getenv("MYSQL_HOST", "localhost")
    mysql_port = os.getenv("MYSQL_PORT", "3306")
    mysql_user = os.getenv("MYSQL_USER", "root")
    mysql_pass = os.getenv("MYSQL_PASSWORD", "")
    mysql_db = os.getenv("MYSQL_DATABASE", "ticket_agent")

    if mysql_user and mysql_pass:
        return f"mysql+pymysql://{mysql_user}:{mysql_pass}@{mysql_host}:{mysql_port}/{mysql_db}?charset=utf8mb4"

    # 默认 SQLite（开发用）
    return "sqlite:///data/ticket_agent.db"


def init_db(db_url: Optional[str] = None):
    """初始化数据库连接和表结构"""
    global _engine, _SessionLocal

    url = db_url or get_db_url()
    logger.info(f"数据库连接: {url.split('@')[-1] if '@' in url else 'sqlite'}")

    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    _engine = create_engine(url, connect_args=connect_args, echo=False, pool_pre_ping=True)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    # 导入所有模型以确保表被创建
    from ticket_agent.database.models import Department, User, TicketRecord, Approval, FeedbackRecord, PatternRecord, ReviewRecord, AccuracyRecord, KnowledgeGapRecord
    Base.metadata.create_all(bind=_engine)
    _run_migrations(_engine)
    logger.info("数据库表结构已就绪")


def _run_migrations(engine):
    """增量迁移：为已有表添加新列（不破坏现有数据）"""
    import sqlalchemy as sa
    from sqlalchemy import inspect

    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("ticket_records")}

    with engine.connect() as conn:
        if "resolution" not in columns:
            conn.execute(sa.text("ALTER TABLE ticket_records ADD COLUMN resolution TEXT DEFAULT ''"))
            logger.info("迁移: ticket_records 添加 resolution 列")
        if "closed_at" not in columns:
            conn.execute(sa.text("ALTER TABLE ticket_records ADD COLUMN closed_at TIMESTAMP NULL"))
            logger.info("迁移: ticket_records 添加 closed_at 列")
        if "sla_deadline" not in columns:
            conn.execute(sa.text("ALTER TABLE ticket_records ADD COLUMN sla_deadline TIMESTAMP NULL"))
            logger.info("迁移: ticket_records 添加 sla_deadline 列")
        if "sla_breached" not in columns:
            conn.execute(sa.text("ALTER TABLE ticket_records ADD COLUMN sla_breached BOOLEAN DEFAULT 0"))
            logger.info("迁移: ticket_records 添加 sla_breached 列")
        conn.commit()


def get_session():
    """获取数据库会话"""
    if _SessionLocal is None:
        init_db()
    return _SessionLocal()


@contextmanager
def session_scope():
    """事务上下文管理器，自动提交/回滚"""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def is_mysql() -> bool:
    """判断当前是否使用 MySQL"""
    if _engine is None:
        return False
    return "mysql" in str(_engine.url)


def close_db():
    """关闭数据库连接池"""
    global _engine, _session_factory
    if _engine:
        try:
            _engine.dispose()
            logger.info("数据库连接池已关闭")
        except Exception as e:
            logger.warning(f"数据库关闭异常: {e}")
        _engine = None
        _session_factory = None
