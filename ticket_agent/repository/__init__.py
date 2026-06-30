"""Repository 层 —— 数据访问的单一入口"""

from ticket_agent.repository.ticket_repository import TicketRepository, get_ticket_repository

__all__ = ["TicketRepository", "get_ticket_repository"]
