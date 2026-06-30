"""
协调器模块

- LinearCoordinator: 线性编排（流程固定、简单可靠）
- LangGraphCoordinator: LangGraph 状态机编排（条件分支、可观测性强）

两种实现方式供对比，展示不同的编排策略。
"""
from ticket_agent.coordinator.linear import LinearCoordinator
