"""
上下文管理 + 幻觉防护

为 Agent 提供两个关键能力：
1. 上下文窗口管理：按模型估算 token，超 80% 自动裁剪
2. 幻觉防护：检查回答是否基于参考资料，给出置信度评估
"""
import logging
import re
from typing import Optional

from llm.token_estimator import (
    estimate_message_tokens,
    get_model_context_window,
    get_context_usage_ratio,
)
from llm.base import ChatMessage

logger = logging.getLogger(__name__)

# 触发裁剪的阈值（上下文使用率）
TRIM_THRESHOLD = 0.8

# 保留的最小消息数（保证至少有一轮对话）
MIN_MESSAGES_AFTER_TRIM = 4


# ════════════════════════════════════════════════════════════
# 1. 上下文窗口管理
# ════════════════════════════════════════════════════════════

def trim_context(
    messages: list,
    model_name: Optional[str] = None,
    threshold: float = TRIM_THRESHOLD,
) -> list:
    """
    裁剪消息列表，确保上下文不超过模型窗口。

    策略：
    1. 保留 system prompt（不可裁剪）
    2. 保留最新的用户消息
    3. 从中间的对话历史开始裁剪（优先丢弃较早的）
    4. 至少保留 MIN_MESSAGES_AFTER_TRIM 条

    Args:
        messages: ChatMessage 列表
        model_name: 模型名称（用于获取窗口大小）
        threshold: 触发裁剪的阈值（默认 80%）

    Returns:
        裁剪后的消息列表
    """
    if not messages:
        return messages

    ratio = get_context_usage_ratio(
        [m.to_dict() if hasattr(m, 'to_dict') else m for m in messages],
        model_name,
    )
    if ratio < threshold:
        return messages  # 未超阈值，不需要裁剪

    model_window = get_model_context_window(model_name)
    logger.warning(
        f"上下文超阈值: {ratio:.1%} (窗口: {model_window}), 开始裁剪..."
    )

    # 分离 system 和普通消息
    system_msgs = [m for m in messages if m.role == "system"]
    other_msgs = [m for m in messages if m.role != "system"]

    # 保留最后 N 条非 system 消息
    n = max(MIN_MESSAGES_AFTER_TRIM, len(other_msgs) // 2)
    trimmed = other_msgs[-n:]

    # 重新估算
    final = system_msgs + trimmed
    final_ratio = get_context_usage_ratio(
        [m.to_dict() if hasattr(m, 'to_dict') else m for m in final],
        model_name,
    )
    if final_ratio >= threshold:
        # 仍超阈值，进一步裁剪 — 只保留最后 2 轮
        ultra_trimmed = other_msgs[-(MIN_MESSAGES_AFTER_TRIM):]
        final = system_msgs + ultra_trimmed
        logger.warning(f"紧急裁剪: 仅保留 {len(ultra_trimmed)} 条非 system 消息")

    logger.info(f"上下文裁剪完成: {len(messages)} → {len(final)} 条消息")
    return final


def add_context_budget_warning(
    messages: list,
    model_name: Optional[str] = None,
) -> Optional[str]:
    """
    检查上下文预算，返回告警消息（如果有）。

    当使用率超过 60% 时返回温和提醒。
    """
    dict_messages = [m.to_dict() if hasattr(m, 'to_dict') else m for m in messages]
    ratio = get_context_usage_ratio(dict_messages, model_name)
    if ratio > 0.9:
        return "⚠️ 注意：当前对话已接近上下文上限，请尽量简洁地回答。"
    return None


# ════════════════════════════════════════════════════════════
# 2. 幻觉防护 — 回答真实性检查
# ════════════════════════════════════════════════════════════

class HallucinationGuard:
    """
    幻觉防护守卫。

    在 Agent 生成回答后，检查：
    1. 是否引用了提供的参考资料
    2. 是否有明确的"我不知道"声明
    3. 回答中不包含未经 RAG 支撑的具体断言
    """

    # 可疑模式：声称知道但实际可能编造
    _VAGUE_CLAIMS = [
        "据我所知", "根据我的了解", "根据我的知识",
        "根据相关资料", "根据最新数据", "根据行业标准",
        "一般情况下", "通常情况下", "理论上",
    ]

    # 安全承认不知道的模式
    _HONEST_DECLARATIONS = [
        "我不知道", "无法确定", "无法回答", "没有相关信息",
        "我不确定", "建议您", "需要进一步", "请咨询",
        "建议咨询", "暂无", "不在我的知识范围内",
    ]

    @classmethod
    def check_response(cls, response: str, rag_context: str = "") -> dict:
        """
        检查 LLM 回答是否存在幻觉风险。

        Args:
            response: LLM 生成的回答
            rag_context: RAG 检索到的参考资料（用于验证引用）

        Returns:
            {
                "safe": bool,           # 是否安全
                "risk": "low"|"medium"|"high",  # 风险等级
                "warnings": list[str],  # 具体警告
                "suggestion": str,      # 改进建议
            }
        """
        warnings = []
        suggestion = ""

        # 检查 1：是否明确承认不知道
        has_honest = any(kw in response for kw in cls._HONEST_DECLARATIONS)

        # 检查 2：是否使用模糊声称
        has_vague = any(kw in response for kw in cls._VAGUE_CLAIMS)
        if has_vague:
            warnings.append("使用了模糊声称表述，可能缺乏可靠依据")

        # 检查 3：是否引用了 RAG 参考资料（关键词重叠检查）
        has_citation = False
        if rag_context:
            # 提取回答和参考资料中的关键词
            resp_keywords = set(re.findall(r'[\u4e00-\u9fff\w]{2,}', response))
            rag_keywords = set(re.findall(r'[\u4e00-\u9fff\w]{2,}', rag_context))
            # 如果回答中包含了参考资料中 30% 以上的关键词，认为有引用
            if len(rag_keywords) > 0:
                overlap = len(resp_keywords & rag_keywords)
                citation_ratio = overlap / len(rag_keywords)
                has_citation = citation_ratio > 0.3

        if rag_context and not has_citation and not has_honest:
            warnings.append("回答未引用提供的参考资料，可能存在编造风险")

        # 检查 4：是否有具体的数据/数字断言（没有引用时风险更高）
        has_numbers = bool(re.search(r'\d+%|\d+\.\d+|\d+万|\d+亿', response))
        if has_numbers and not rag_context and not has_honest:
            warnings.append("回答包含具体数字断言，但缺乏参考资料支撑")

        # 综合评估风险
        if has_honest:
            risk = "low"
            suggestion = "回答已承认不确定性，安全。"
        elif warnings:
            risk = "medium"
            suggestion = '建议补充"请以实际查询结果为准"之类的免责声明。'
        else:
            risk = "low"
            suggestion = "回答看起来基于 RAG 参考资料。"
            return {"safe": True, "risk": risk, "warnings": [], "suggestion": suggestion}

        safe = risk == "low"

        return {"safe": safe, "risk": risk, "warnings": warnings, "suggestion": suggestion}

    @classmethod
    def safety_prompt_suffix(cls) -> str:
        """
        返回追加到 system prompt 的幻觉防护指令。
        """
        return (
            "\n\n【重要】回答原则：\n"
            "1. 只回答你确定有依据的问题。\n"
            '2. 如果不确定，请明确说"我不知道"或"建议咨询对应部门"。\n'
            "3. 不要编造具体的数字、比例、金额。\n"
            "4. 基于【参考资料】中的信息回答，不要自行添加参考资料中没有的内容。"
        )


# ════════════════════════════════════════════════════════════
# 3. 集成便捷函数
# ════════════════════════════════════════════════════════════

def enhance_system_prompt(system_prompt: str) -> str:
    """为 system prompt 追加幻觉防护指令"""
    if "回答原则" in system_prompt:
        return system_prompt  # 已添加过，避免重复
    return system_prompt + HallucinationGuard.safety_prompt_suffix()


async def check_and_report_hallucination(
    response: str,
    rag_context: str,
    session_id: str = "",
) -> dict:
    """
    检查回答并记录结果。

    可在 Agent 生成回答后调用。
    """
    result = HallucinationGuard.check_response(response, rag_context)
    if result["warnings"]:
        logger.warning(
            f"[幻觉防护] session={session_id} "
            f"risk={result['risk']} "
            f"warnings={'; '.join(result['warnings'])}"
        )
    return result
