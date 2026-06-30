"""
工单分类 Agent

继承 ChatAgent，对用户输入的工单内容进行意图识别和分类。
输出结构化的分类结果：类别、置信度、是否需要转人工。
"""
import json
import logging
from typing import Optional

from agents.chat_agent import ChatAgent
from llm.base import ChatMessage

logger = logging.getLogger(__name__)

CLASSIFIER_SYSTEM_PROMPT = """你是一个企业工单分类专家。

根据用户提交的问题内容，将工单分类到以下类别之一：

## 类别定义
- **IT**：网络问题、账号权限、软件故障、设备报修、邮箱配置、系统报错
- **HR**：请假申请、薪酬查询、招聘流程、员工关系、入职离职、考勤管理
- **财务**：报销申请、发票查询、预算审批、合同审核、差旅费用
- **运维**：系统告警、服务异常、部署问题、数据库故障、服务器监控
- **其他**：不属于以上类别的工单

## 输出格式（仅返回 JSON，不要额外文字）
```json
{
  "category": "IT | HR | 财务 | 运维 | 其他",
  "confidence": 0.0-1.0,
  "summary": "一句话概括用户问题",
  "needs_human": true/false,
  "reason": "分类依据"
}
```

## 转人工条件（needs_human=true）
- 用户明确要求转人工/找经理/投诉
- 涉及法律、合规、安全事件
- 情绪激动或语言攻击
- 非常紧急（如服务器宕机、数据泄露）
- 无法明确分类到任何类别

## 回答原则
- 只输出 JSON，不要额外文字
- 如果无法确定分类，confidence 给低分（<0.5）并设 needs_human=true
- 不要编造分类依据

请始终输出合法的 JSON 格式。
"""

FEW_SHOT_EXAMPLES = [
    {"role": "user", "content": "我的电脑蓝屏了，开机就蓝屏，工单号 TK-001"},
    {"role": "assistant", "content": '{"category": "IT", "confidence": 0.95, "summary": "电脑蓝屏故障，工单TK-001", "needs_human": false, "reason": "电脑硬件/系统故障属于IT范畴"}', "tool_calls": None},
    {"role": "user", "content": "我要请假三天，下周一到周三，家里有事"},
    {"role": "assistant", "content": '{"category": "HR", "confidence": 0.95, "summary": "员工申请事假3天", "needs_human": false, "reason": "请假申请属于HR范畴"}', "tool_calls": None},
    {"role": "user", "content": "报销上周出差的钱，上海住了两晚，高铁票和住宿费"},
    {"role": "assistant", "content": '{"category": "财务", "confidence": 0.95, "summary": "差旅费用报销申请", "needs_human": false, "reason": "差旅报销属于财务范畴"}', "tool_calls": None},
    {"role": "user", "content": "服务器挂了，线上用户登录不了，赶紧处理！"},
    {"role": "assistant", "content": '{"category": "运维", "confidence": 0.98, "summary": "线上服务异常，用户无法登录", "needs_human": true, "reason": "P0级生产事故，需要立即人工介入"}', "tool_calls": None},
]


class TicketClassifierAgent(ChatAgent):
    """
    工单分类 Agent

    对用户提交的工单进行意图识别和分类，输出结构化分类结果。
    """

    def __init__(self, llm, memory=None):
        super().__init__(
            llm=llm,
            memory=memory,
            system_prompt=CLASSIFIER_SYSTEM_PROMPT,
        )

    async def classify(self, user_input: str, session_id: str = "default") -> dict:
        """
        对用户输入进行分类

        Returns:
            {
                "category": "IT | HR | 财务 | 运维 | 其他",
                "confidence": 0.95,
                "summary": "...",
                "needs_human": false,
                "reason": "..."
            }
        """
        try:
            response = await self.chat(user_input, session_id=session_id, use_rag=False)
            content = response.content.strip()

            # 尝试提取 JSON（兼容有 markdown 代码块的情况）
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            result = json.loads(content)
            # 验证必要字段
            result.setdefault("category", "其他")
            result.setdefault("confidence", 0.0)
            result.setdefault("summary", user_input[:50])
            result.setdefault("needs_human", False)
            result.setdefault("reason", "")
            return result
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"分类结果解析失败: {e}, raw={response.content[:100]}")
            return {
                "category": "其他",
                "confidence": 0.0,
                "summary": user_input[:50],
                "needs_human": True,
                "reason": f"分类解析失败，默认转人工: {str(e)}",
            }
