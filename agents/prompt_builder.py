"""
模块化系统提示词构建器

每次构建按顺序组装独立模块：
  Identity → Memory → Knowledge → Tooling → Runtime → Response

支持动态注入三层记忆上下文和 Token 预算管理。
"""
from typing import Optional
from dataclasses import dataclass, field

from llm.token_estimator import estimate_text_tokens, should_trim


@dataclass
class PromptSection:
    """提示词段"""
    name: str
    content: str
    priority: int = 10  # 排序权重（越小越靠前）


_SECTION_PRIORITIES = {
    "identity": 10,
    "memory": 20,
    "knowledge": 30,
    "tools": 40,
    "rules": 50,
    "runtime": 60,
    "response_format": 70,
}


class PromptBuilder:
    """
    模块化系统提示词构建器。

    支持按优先级组装多个独立模块，
    可选注入记忆上下文和 Token 预算裁剪。

    使用示例：
        builder = PromptBuilder(base_prompt="你是一个智能工单助手。")
        builder.add_memory("【核心记忆】\\n- 检查 DNS 配置")
        builder.add_knowledge("【知识库】\\n电脑蓝屏排障步骤...")
        builder.add_tools(tool_descriptions)

        system_prompt = builder.build()
        # system_prompt = "你是一个智能工单助手。\\n\\n---\\n\\n## 核心记忆\\n..."
    """

    def __init__(self, base_prompt: str = "你是一个智能工单处理助手。"):
        self.base_prompt = base_prompt
        self.sections: list[PromptSection] = []
        self._max_total_tokens: Optional[int] = None

    def set_max_tokens(self, max_tokens: int):
        """设置 system prompt 最大 token 预算"""
        self._max_total_tokens = max_tokens

    def _add_section(self, name: str, content: str, priority: int = None):
        if not content or not content.strip():
            return
        if priority is None:
            priority = _SECTION_PRIORITIES.get(name, 50)
        self.sections.append(PromptSection(name=name, content=content.strip(), priority=priority))

    def add_identity(self, content: str):
        """添加身份/角色设定"""
        self._add_section("identity", content)

    def add_memory(self, content: str):
        """添加记忆上下文"""
        self._add_section("memory", content)

    def add_knowledge(self, content: str):
        """添加知识库参考"""
        self._add_section("knowledge", content)

    def add_tools(self, tool_descriptions: str):
        """添加工具描述"""
        self._add_section("tools", tool_descriptions)

    def add_rules(self, content: str):
        """添加规则约束"""
        self._add_section("rules", content)

    def add_response_format(self, content: str):
        """添加输出格式要求"""
        self._add_section("response_format", content)

    def build(self) -> str:
        """
        组装完整系统提示词。

        如果设置了 max_tokens，会从低优先级的段开始裁剪，
        确保总 token 数不超过预算。
        """
        parts = [self.base_prompt]

        # 按优先级排序
        sorted_sections = sorted(self.sections, key=lambda s: s.priority)

        for section in sorted_sections:
            if section.content.strip():
                parts.append(f"\n## {section.name}\n{section.content.strip()}")

        full_prompt = "\n\n---\n\n".join(parts)

        # Token 预算裁剪
        if self._max_total_tokens is not None:
            current_tokens = estimate_text_tokens(full_prompt)
            if current_tokens > self._max_total_tokens:
                full_prompt = self._trim_to_budget(full_prompt)

        return full_prompt

    def _trim_to_budget(self, prompt: str, max_iterations: int = 10) -> str:
        """
        递归裁剪到 token 预算内。

        策略：
        1. 先裁剪低优先级的段
        2. 对过长的段截断末尾
        """
        if not self.sections or max_iterations <= 0:
            return prompt[:self._max_total_tokens * 4] if self._max_total_tokens else prompt

        current_tokens = estimate_text_tokens(prompt)
        if current_tokens <= self._max_total_tokens:
            return prompt

        # 找到优先级最高的段落进行裁剪
        sorted_sections = sorted(self.sections, key=lambda s: s.priority, reverse=True)

        for section in sorted_sections:
            section_tokens = estimate_text_tokens(section.content)
            if section_tokens > 100:  # 只裁剪较长的段落
                # 截断 20%
                trim_len = int(len(section.content) * 0.8)
                section.content = section.content[:trim_len]
                break

        # 重新构建并递归
        return PromptBuilder._build_with_sections(
            self.base_prompt, self.sections, self._max_total_tokens, max_iterations - 1
        )

    @staticmethod
    def _build_with_sections(base: str, sections: list, budget: int, iterations: int) -> str:
        """静态重新构建（用于递归）"""
        builder = PromptBuilder(base_prompt=base)
        builder.set_max_tokens(budget)
        builder.sections = sections
        return builder._trim_to_budget(builder.build(), iterations)

    def clear(self):
        """清空所有自定义段（保留 base_prompt）"""
        self.sections.clear()
