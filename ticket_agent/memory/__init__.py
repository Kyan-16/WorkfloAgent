"""
记忆系统

三层记忆架构：
1. 短期记忆：当前会话上下文（LocalMemory / RedisMemory）
2. 工单模式记忆：从已解决工单中提取的"问题-方案"模式
3. 三层持久记忆：Daily 总结 + Core 记忆（Deep Dream 蒸馏）

核心入口：
- MemoryManager（三层记忆统一入口）
- PatternExtractor（工单模式提取）
- ConversationStore（SQLite 会话持久化）
"""
from ticket_agent.memory.pattern_extractor import (
    PatternExtractor,
    PatternStore,
    TicketPattern,
    get_pattern_store,
)
from ticket_agent.memory.manager import MemoryManager
from ticket_agent.memory.storage import MemoryStore, get_memory_store
from ticket_agent.memory.conversation_store import ConversationStore
from ticket_agent.memory.summarizer import generate_daily_summary, deep_dream
