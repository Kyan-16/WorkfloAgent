"""
SQLAlchemy ORM 模型

表结构：
  departments  - 部门（IT / HR / 财务 / 运维）
  users        - 用户（员工 / 工程师 / 经理 / 管理员）
  ticket_records - 工单记录（带部门归属和处理人）
  approvals    - 审批记录（请假审批、报销审批等）
"""
import datetime

from sqlalchemy import (
    Column, Integer, String, Text, Enum, Boolean,
    DateTime, ForeignKey, JSON, Float,
)
from sqlalchemy.orm import relationship

from ticket_agent.database import Base


class Department(Base):
    """部门"""
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)          # IT / HR / 财务 / 运维
    description = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    users = relationship("User", back_populates="department")
    tickets = relationship("TicketRecord", back_populates="department")


class User(Base):
    """用户"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), unique=True, nullable=False)        # 登录名: zhangsan
    name = Column(String(50), nullable=False)                        # 显示名: 张三
    role = Column(Enum("employee", "engineer", "manager", "admin", name="user_role"),
                  nullable=False, default="employee")
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    email = Column(String(100), default="")
    phone = Column(String(20), default="")
    avatar = Column(String(200), default="")
    hashed_password = Column(String(255), default="")                # bcrypt 哈希密码
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    department = relationship("Department", back_populates="users")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "role": self.role,
            "department_id": self.department_id,
            "department_name": self.department.name if self.department else "",
            "email": self.email,
            "phone": self.phone,
            "is_active": self.is_active,
        }


class TicketRecord(Base):
    """工单记录（扩展原有 Ticket 模型，增加流转字段）"""
    __tablename__ = "ticket_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(String(50), unique=True, nullable=False, index=True)

    # 提交人
    user_id = Column(String(50), nullable=False)                     # 提交人
    user_name = Column(String(50), default="")

    # 内容
    content = Column(Text, nullable=False)
    category = Column(String(20), default="")                        # IT / HR / 财务 / 运维 / 其他

    # 状态流转
    status = Column(String(20), default="待处理")                     # 待处理 / 处理中 / 已解决 / 已关闭 / 已转人工
    priority = Column(String(10), default="normal")                  # low / normal / high / urgent

    # 部门归属（Agent 分类后自动路由）
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)  # 当前处理人
    assigned_name = Column(String(50), default="")                   # 处理人姓名

    # 处理信息
    agent_response = Column(Text, default="")
    trace_id = Column(String(100), default="")

    # 处理记录
    resolution = Column(Text, default="")                            # 工程师处理说明/解决方案

    # 是否需审批
    needs_approval = Column(Boolean, default=False)
    approval_status = Column(String(20), default="")                 # pending / approved / rejected

    # 时间
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)

    # SLA 字段
    sla_deadline = Column(DateTime, nullable=True)      # 目标解决截止时间（创建时按优先级自动计算）
    sla_breached = Column(Boolean, default=False)       # 是否已超时（读取时实时计算，重写时持久化）

    department = relationship("Department", back_populates="tickets")
    assignee = relationship("User", foreign_keys=[assigned_to])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "content": self.content,
            "category": self.category,
            "status": self.status,
            "priority": self.priority,
            "department_id": self.department_id,
            "department_name": self.department.name if self.department else "",
            "assigned_to": self.assigned_to,
            "assigned_name": self.assigned_name,
            "resolution": self.resolution,
            "agent_response": self.agent_response,
            "trace_id": self.trace_id,
            "needs_approval": self.needs_approval,
            "approval_status": self.approval_status,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else "",
            "closed_at": self.closed_at.isoformat() if self.closed_at else "",
            "sla_deadline": self.sla_deadline.isoformat() if self.sla_deadline else "",
            "sla_breached": self._is_sla_breached(),
        }

    def _is_sla_breached(self) -> bool:
        if not self.sla_deadline or self.status in ("已解决", "已关闭"):
            return False
        deadline = self.sla_deadline
        now = datetime.datetime.now(datetime.timezone.utc)
        if deadline.tzinfo is None:
            now = now.replace(tzinfo=None)
        return now > deadline


class Approval(Base):
    """审批记录"""
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(String(50), nullable=False, index=True)       # 关联工单
    approver_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 审批人
    approver_name = Column(String(50), default="")
    status = Column(String(20), default="pending")                   # pending / approved / rejected
    comment = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "approver_id": self.approver_id,
            "approver_name": self.approver_name,
            "status": self.status,
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }


class FeedbackRecord(Base):
    """反馈记录"""
    __tablename__ = "feedback_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    feedback_id = Column(String(50), unique=True, nullable=False, index=True)
    ticket_id = Column(String(50), nullable=False, index=True)
    user_id = Column(String(50), default="")
    rating = Column(Integer, default=3)
    feedback_type = Column(String(20), default="neutral")
    comment = Column(Text, default="")
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class PatternRecord(Base):
    """处理模式记录"""
    __tablename__ = "pattern_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    pattern_id = Column(String(50), unique=True, nullable=False, index=True)
    category = Column(String(20), default="")
    problem_summary = Column(Text, default="")
    solution = Column(Text, default="")
    keywords = Column(Text, default="[]")
    confidence = Column(Integer, default=0)
    frequency = Column(Integer, default=1)
    source_tickets = Column(Text, default="[]")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class ReviewRecord(Base):
    """复盘记录"""
    __tablename__ = "review_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    review_id = Column(String(50), unique=True, nullable=False, index=True)
    ticket_id = Column(String(50), default="", index=True)
    category = Column(String(20), default="")
    classification_score = Column(Integer, default=0)
    rag_hit_rate = Column(Integer, default=0)
    response_quality = Column(Integer, default=0)
    overall_score = Column(Integer, default=0)
    suggestions = Column(Text, default="")
    follow_up_needed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class AccuracyRecord(Base):
    """分类准确率记录"""
    __tablename__ = "accuracy_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    record_id = Column(String(50), unique=True, nullable=False, index=True)
    ticket_id = Column(String(50), default="")
    agent_category = Column(String(20), default="")
    human_category = Column(String(20), default="")
    correct = Column(Boolean, default=False)
    confidence = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class KnowledgeGapRecord(Base):
    """知识缺口记录"""
    __tablename__ = "knowledge_gap_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    gap_id = Column(String(50), unique=True, nullable=False, index=True)
    category = Column(String(20), default="")
    source_tickets = Column(Text, default="[]")
    suggested_title = Column(String(200), default="")
    suggested_content = Column(Text, default="")
    keywords = Column(Text, default="[]")
    frequency = Column(Integer, default=0)
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
