"""
Ticket Repository —— 工单持久化的单一入口。

基于 SQLAlchemy（SQLite 开发 / MySQL 生产），替代旧 JSON 文件 TicketStore。
所有工单 CRUD 操作统一走这里，保证数据一致性。
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List

from ticket_agent.database import session_scope
from ticket_agent.database.models import TicketRecord
from ticket_agent.models.ticket import Ticket, TicketStatus, TicketCategory

logger = logging.getLogger(__name__)


class TicketRepository:
    """工单数据仓库 —— 唯一的数据访问入口"""

    def create(self, ticket: Ticket) -> Ticket:
        """
        创建工单。

        自动设置：
          - created_at / updated_at 时间戳
          - priority 默认为 "normal"
          - sla_deadline 根据优先级计算（urgent=4h / high=8h / normal=24h / low=48h）
        """
        try:
            now = datetime.now(timezone.utc)
            from ticket_agent.sla.config import get_sla_deadline
            sla_deadline = get_sla_deadline("normal", now)
            with session_scope() as session:
                record = TicketRecord(
                    ticket_id=ticket.ticket_id,
                    user_id=ticket.user_id or "anonymous",
                    user_name=ticket.user_id or "anonymous",
                    content=ticket.content,
                    category=ticket.category.value if ticket.category else "",
                    status=ticket.status.value if ticket.status else "待处理",
                    priority="normal",
                    agent_response=ticket.agent_response or "",
                    trace_id=ticket.trace_id or "",
                    created_at=now,
                    updated_at=now,
                    sla_deadline=sla_deadline,
                )
                session.add(record)
            logger.info(f"工单已创建: {ticket.ticket_id}")
        except Exception as e:
            logger.warning(f"工单创建失败（不影响处理流程）: {e}")
        return ticket

    def get(self, ticket_id: str) -> Optional[Ticket]:
        """根据 ticket_id 查询工单"""
        try:
            with session_scope() as session:
                record = session.query(TicketRecord).filter(
                    TicketRecord.ticket_id == ticket_id
                ).first()
                if not record:
                    return None
                return self._record_to_ticket(record)
        except Exception as e:
            logger.error(f"查询工单失败: {e}")
            return None

    def update(self, ticket_id: str, **kwargs) -> Optional[Ticket]:
        """更新工单字段"""
        try:
            with session_scope() as session:
                record = session.query(TicketRecord).filter(
                    TicketRecord.ticket_id == ticket_id
                ).first()
                if not record:
                    return None
                for key, value in kwargs.items():
                    if hasattr(record, key):
                        setattr(record, key, value)
                record.updated_at = datetime.now(timezone.utc)
            return self.get(ticket_id)
        except Exception as e:
            logger.warning(f"工单更新失败: {e}")
            return self.get(ticket_id)

    def list_all(self, limit: int = 20, offset: int = 0) -> List[Ticket]:
        """获取工单列表，按时间倒序"""
        try:
            with session_scope() as session:
                records = (
                    session.query(TicketRecord)
                    .order_by(TicketRecord.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                    .all()
                )
                return [self._record_to_ticket(r) for r in records]
        except Exception as e:
            logger.error(f"查询工单列表失败: {e}")
            return []

    def list_by_user(self, user_id: str, limit: int = 10) -> List[Ticket]:
        """查询某用户的工单"""
        try:
            with session_scope() as session:
                records = (
                    session.query(TicketRecord)
                    .filter(TicketRecord.user_id == user_id)
                    .order_by(TicketRecord.created_at.desc())
                    .limit(limit)
                    .all()
                )
                return [self._record_to_ticket(r) for r in records]
        except Exception as e:
            logger.error(f"查询用户工单失败: {e}")
            return []

    def batch_update(self, ticket_ids: list[str], **kwargs) -> int:
        """
        批量更新工单字段，返回更新的记录数。

        用于批量操作端点（批量关闭/分配/转人工），
        单事务包装，任一失败整个回滚。
        """
        try:
            with session_scope() as session:
                count = session.query(TicketRecord).filter(
                    TicketRecord.ticket_id.in_(ticket_ids)
                ).update(kwargs, synchronize_session=False)
            logger.info(f"批量更新 {count} 个工单: {list(kwargs.keys())}")
            return count
        except Exception as e:
            logger.error(f"批量更新失败: {e}")
            return 0

    @staticmethod
    def _record_to_ticket(record: TicketRecord) -> Ticket:
        """ORM 记录 → 领域模型转换"""
        category_enum = None
        if record.category:
            try:
                category_enum = TicketCategory(record.category)
            except ValueError:
                pass

        status_enum = TicketStatus.PENDING
        if record.status:
            try:
                status_enum = TicketStatus(record.status)
            except ValueError:
                pass

        return Ticket(
            ticket_id=record.ticket_id,
            user_id=record.user_id,
            content=record.content,
            category=category_enum,
            status=status_enum,
            assignee=record.assigned_name or "",
            created_at=record.created_at.isoformat() if record.created_at else "",
            updated_at=record.updated_at.isoformat() if record.updated_at else "",
            agent_response=record.agent_response or "",
            trace_id=record.trace_id or "",
        )


# 全局单例
_repo: Optional[TicketRepository] = None


def get_ticket_repository() -> TicketRepository:
    """获取全局 Repository 实例"""
    global _repo
    if _repo is None:
        _repo = TicketRepository()
    return _repo


def reset_ticket_repository():
    """重置全局单例（测试用）"""
    global _repo
    _repo = None
