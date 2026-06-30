"""
工单执行 Agent

继承 TaskAgent，具备 ReAct 工具调用能力。
根据分类结果和 RAG 检索结果，决定是否执行工具操作。
"""
import logging
from typing import Optional

from agents.task_agent import TaskAgent
from tools.registry import ToolRegistry
from ticket_agent.tools import (
    GetTicketStatusTool,
    UpdateTicketTool,
    NotifyUserTool,
    EscalateToHumanTool,
    SearchKnowledgeTool,
)

logger = logging.getLogger(__name__)

EXECUTOR_SYSTEM_PROMPT = """你是一个企业工单处理执行专家。

## 你的职责
根据用户的问题、工单分类和知识库检索结果，执行适当的操作来帮助用户解决问题。

## 可用工具
1. **get_ticket_status** - 查询工单当前状态
2. **update_ticket** - 更新工单字段（状态、处理人、优先级等）
3. **notify_user** - 通过钉钉/邮件/短信通知用户
4. **escalate_to_human** - 将工单转交人工客服处理
5. **search_knowledge** - 在知识库中搜索解决方案

## 执行流程
1. 首先分析用户的工单内容
2. 根据 [参考资料] 中的知识库信息，判断能否直接回答
3. 如果需要查询或更新工单信息，调用对应工具
4. 如果知识库中有解决方案，直接回复用户
5. 如果无法处理，调用 escalate_to_human 转人工

## 注意事项
- 查询工单状态时，先调用 get_ticket_status
- 更新工单前请确认操作正确
- 通知用户时使用合适的渠道
- 复杂问题或权限不足时，及时转人工
- 所有操作都要有明确的目的和依据
- 如果不确定答案，请说"我需要查询一下"而不是编造
- 不要编造具体的工单编号、金额、日期等数据
- 基于【参考资料】中的信息回答，不要添加参考资料中没有的内容
"""


def build_ticket_tool_registry() -> ToolRegistry:
    """构建工单处理所需的工具注册表"""
    registry = ToolRegistry()
    registry.register(GetTicketStatusTool())
    registry.register(UpdateTicketTool())
    registry.register(NotifyUserTool())
    registry.register(EscalateToHumanTool())
    registry.register(SearchKnowledgeTool())
    return registry


class TicketExecutionAgent(TaskAgent):
    """
    工单执行 Agent

    使用 ReAct 循环（思考→工具调用→观察→再思考→最终回答）
    来自动处理工单操作。
    """

    def __init__(
        self,
        llm,
        memory=None,
        tool_registry: Optional[ToolRegistry] = None,
        max_tool_rounds: int = 5,
    ):
        if tool_registry is None:
            tool_registry = build_ticket_tool_registry()

        super().__init__(
            llm=llm,
            memory=memory,
            tool_registry=tool_registry,
            system_prompt=EXECUTOR_SYSTEM_PROMPT,
            max_tool_rounds=max_tool_rounds,
        )
