"""
操作指南生成器

工单自动处理后，将"问题+解决方案"转为结构化操作指南文档，
存入知识库，方便员工下次自行解决。

流程：
工单自动解决 → LLM 提取步骤 → 生成 Markdown 指南 → 存入知识库
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class GuideGenerator:
    """
    操作指南生成器

    使用示例：
        generator = GuideGenerator(llm=llm)
        doc_id = await generator.generate({
            "category": "IT",
            "content": "VPN连不上，提示超时",
            "solution": "请检查网络连接，重启VPN客户端...",
        })
    """

    def __init__(self, llm=None):
        self.llm = llm
        # 去重缓存：防止同一问题重复生成
        self._recent: set = set()

    async def generate(self, ticket_data: dict) -> Optional[str]:
        """
        生成操作指南并存入知识库

        Args:
            ticket_data: {"category", "content", "solution", "ticket_id"}

        Returns:
            doc_id 或 None（已存在相似指南时跳过）
        """
        category = ticket_data.get("category", "")
        content = ticket_data.get("content", "")
        solution = ticket_data.get("solution", "")

        if not content or not solution:
            return None

        # 跳过转人工的回复（不是真正的解决方案）
        if "转人工" in solution[:50] or len(solution) < 30:
            return None

        # 去重：同分类+问题前20字相同时跳过
        dedup_key = f"{category}:{content[:20]}"
        if dedup_key in self._recent:
            return None
        self._recent.add(dedup_key)
        if len(self._recent) > 100:
            self._recent.clear()

        # 检查知识库是否已有相似文档
        from ticket_agent.knowledge.store import get_knowledge_store
        store = get_knowledge_store()
        existing = store.list_docs(category)
        for doc in existing:
            if self._is_similar(content[:30], doc["content"][:30]):
                logger.debug(f"知识库已有相似文档，跳过生成: {doc['doc_id']}")
                return None

        # 生成指南内容
        if self.llm:
            guide = await self._generate_with_llm(content, solution)
        else:
            guide = self._generate_rule_based(content, solution)

        if not guide:
            return None

        # 安全校验：检查内容是否合规
        from ticket_agent.security.tool_guard import ContentValidator, get_audit
        valid, reason = ContentValidator.validate_guide(guide)
        if not valid:
            get_audit().record("guide_rejected", {"reason": reason, "content": guide[:100]})
            logger.warning(f"操作指南未通过安全校验: {reason}")
            return None

        # 存入知识库
        try:
            doc = store.add_doc(
                content=guide,
                category=category,
                source="Agent 自动生成",
            )
            get_audit().record("guide_created", {"doc_id": doc["doc_id"], "category": category})
            logger.info(f"操作指南已生成并入库: {doc['doc_id']} [{category}]")
            return doc["doc_id"]
        except Exception as e:
            logger.warning(f"操作指南入库失败: {e}")
            return None

    async def _generate_with_llm(self, content: str, solution: str) -> str:
        """用 LLM 生成结构化操作指南"""
        from llm.base import ChatMessage

        prompt = f"""请根据以下工单处理记录，生成一篇结构清晰的操作指南，方便员工自行解决问题。

格式要求：纯文本，简洁明了，不用 Markdown 表格。

用户问题：{content}

解决方案：{solution}

请按以下结构输出：

【问题现象】
（一句话描述问题表现）

【适用场景】
（在什么情况下会出现该问题）

【操作步骤】
1. ...
2. ...
3. ...

【注意事项】
（如果有需要注意的地方）

【适用部门】
（IT/HR/财务/运维）
"""

        try:
            resp = await self.llm.generate([ChatMessage(role="user", content=prompt)])
            return resp.content.strip()
        except Exception as e:
            logger.warning(f"LLM 生成指南失败: {e}")
            return self._generate_rule_based(content, solution)

    def _generate_rule_based(self, content: str, solution: str) -> str:
        """基于规则的轻量指南"""
        clean_solution = solution.replace("您好，", "").replace("已收到", "")
        # 提取步骤
        lines = clean_solution.strip().split("\n")
        steps = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith("[") and len(line) > 4:
                steps.append(line)

        guide = f"""【问题现象】
{content[:80]}

【操作步骤】
{chr(10).join(f'{i+1}. {s}' for i, s in enumerate(steps[:8]))}

【注意事项】
如以上步骤无法解决问题，请重新提交工单联系工程师处理。

【适用部门】
{content[:20]}相关
"""
        return guide.strip()

    @staticmethod
    def _is_similar(a: str, b: str) -> bool:
        """简单判断两个文本是否相似"""
        if not a or not b:
            return False
        # 用共同字符比例判断
        common = sum(1 for c in a if c in b)
        return common / max(len(a), len(b)) > 0.6
