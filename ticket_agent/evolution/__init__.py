"""
自进化系统

借鉴 CowAgent 的 Self-Evolution 设计，让工单系统能从日常处理中持续学习：

1. TicketReviewer – 自动复盘已解决的工单，评估处理质量
2. AccuracyTracker – 追踪分类准确率（当人类纠正 Agent 分类时记录）
3. KnowledgeGapDetector – 发现知识库缺口（零结果工单 → 建议新增文档）
4. EvolutionExecutor – 后台进化执行器（Review Agent + 快照回滚）
5. EvolutionTrigger – 进化触发条件判断

使用方式：
    executor = EvolutionExecutor(llm=llm)
    await executor.try_evolve(topic="...", content="...", current_memory="...")
"""
from ticket_agent.evolution.reviewer import TicketReviewer, get_review_store
from ticket_agent.evolution.accuracy_tracker import AccuracyTracker, get_accuracy_store
from ticket_agent.evolution.knowledge_gap import KnowledgeGapDetector, get_gap_store
from ticket_agent.evolution.executor import EvolutionExecutor
from ticket_agent.evolution.trigger import EvolutionTrigger
from ticket_agent.evolution.prompts import EvolutionPrompts
