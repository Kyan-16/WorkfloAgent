"""
content_tools 单元测试
"""
import os
import json
import pytest
from tools.base import ToolResult
from tools.registry import ToolRegistry


# ===== TextGeneratorTool =====

class TestTextGeneratorTool:
    """TextGeneratorTool 测试"""

    def test_schema(self):
        from ticket_agent.tools.content_tools import TextGeneratorTool
        tool = TextGeneratorTool()
        schema = tool.get_function_schema()
        assert schema["name"] == "generate_text"
        props = schema["parameters"]["properties"]
        assert "topic" in props
        assert "style" in props
        assert "length" in props
        assert "format" in props
        assert schema["parameters"]["required"] == ["topic"]

    def test_param_enums(self):
        from ticket_agent.tools.content_tools import TextGeneratorTool
        tool = TextGeneratorTool()
        props = tool.parameters["properties"]
        assert props["style"]["enum"] == ["正式", "幽默", "简洁", "详细"]
        assert props["length"]["enum"] == ["短", "中", "长"]
        assert props["format"]["enum"] == ["纯文本", "Markdown"]

    @pytest.mark.asyncio
    async def test_without_llm_returns_error(self):
        from ticket_agent.tools.content_tools import TextGeneratorTool
        tool = TextGeneratorTool()
        result = await tool.execute(topic="测试")
        assert result.success is False
        assert "未注入 LLM" in result.error

    @pytest.mark.asyncio
    async def test_with_mock_llm(self):
        from ticket_agent.tools.content_tools import TextGeneratorTool
        from llm.base import LLMBase, LLMResponse

        class MockLLM(LLMBase):
            async def generate(self, messages, **kw):
                return LLMResponse(content="# 测试内容\n\n这是生成的文本。", model="mock")
            async def stream(self, messages, **kw):
                yield "mock"

        tool = TextGeneratorTool(llm=MockLLM("mock", "key"))
        result = await tool.execute(topic="AI发展", style="正式", length="短", format="Markdown")
        assert result.success is True
        assert "测试内容" in result.output["content"]
        assert result.output["topic"] == "AI发展"
        assert result.output["style"] == "正式"
        assert result.output["format"] == "Markdown"


# ===== ImageGeneratorTool =====

class TestImageGeneratorTool:
    """ImageGeneratorTool 测试"""

    def test_schema(self):
        from ticket_agent.tools.content_tools import ImageGeneratorTool
        tool = ImageGeneratorTool()
        schema = tool.get_function_schema()
        assert schema["name"] == "generate_image"
        props = schema["parameters"]["properties"]
        assert "prompt" in props
        assert "style" in props
        assert "size" in props
        assert schema["parameters"]["required"] == ["prompt"]

    def test_param_enums(self):
        from ticket_agent.tools.content_tools import ImageGeneratorTool
        tool = ImageGeneratorTool()
        props = tool.parameters["properties"]
        assert props["style"]["enum"] == ["写实", "卡通", "插画", "水墨"]

    @pytest.mark.asyncio
    async def test_mock_mode_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("IMAGE_API_KEY", raising=False)
        from ticket_agent.tools.content_tools import ImageGeneratorTool
        tool = ImageGeneratorTool()
        result = await tool.execute(prompt="一只猫", style="卡通", size="512x512")
        assert result.success is True
        output = result.output
        assert output["mode"] == "simulated"
        assert "image.mock.service" in output["image_url"]
        assert output["prompt"] == "[卡通风格] 一只猫"
        assert "模拟模式" in output.get("notice", "")

    @pytest.mark.asyncio
    async def test_default_params(self, monkeypatch):
        monkeypatch.delenv("IMAGE_API_KEY", raising=False)
        from ticket_agent.tools.content_tools import ImageGeneratorTool
        tool = ImageGeneratorTool()
        result = await tool.execute(prompt="山水画")
        assert result.success is True
        assert result.output["style"] == "写实"
        assert result.output["size"] == "1024x1024"


# ===== ReportGeneratorTool =====

class TestReportGeneratorTool:
    """ReportGeneratorTool 测试"""

    def test_schema(self):
        from ticket_agent.tools.content_tools import ReportGeneratorTool
        tool = ReportGeneratorTool()
        schema = tool.get_function_schema()
        assert schema["name"] == "generate_report"
        props = schema["parameters"]["properties"]
        assert "title" in props
        assert "report_type" in props
        assert "data_source" in props
        assert "include_chart" in props
        assert schema["parameters"]["required"] == ["title"]

    def test_param_enums(self):
        from ticket_agent.tools.content_tools import ReportGeneratorTool
        tool = ReportGeneratorTool()
        props = tool.parameters["properties"]
        assert props["report_type"]["enum"] == ["pdf", "excel"]
        assert props["data_source"]["enum"] == ["全部工单", "本周", "本月"]

    def test_compute_stats(self):
        """测试内部统计逻辑（纯函数）"""
        from ticket_agent.tools.content_tools import ReportGeneratorTool
        from ticket_agent.models.ticket import Ticket, TicketCategory, TicketStatus

        tool = ReportGeneratorTool()
        tickets = [
            Ticket(content="A", user_id="u1", category=TicketCategory.IT, status=TicketStatus.PENDING),
            Ticket(content="B", user_id="u1", category=TicketCategory.IT, status=TicketStatus.PENDING),
            Ticket(content="C", user_id="u2", category=TicketCategory.HR, status=TicketStatus.RESOLVED),
        ]
        stats = tool._compute_stats(tickets)
        assert stats["total"] == 3
        assert stats["category_stats"]["IT"] == 2
        assert stats["category_stats"]["HR"] == 1
        assert stats["status_stats"]["待处理"] == 2
        assert stats["status_stats"]["已解决"] == 1
        assert stats["top_user"] == "u1"
        assert stats["top_user_count"] == 2

    def test_compute_stats_empty(self):
        from ticket_agent.tools.content_tools import ReportGeneratorTool
        tool = ReportGeneratorTool()
        stats = tool._compute_stats([])
        assert stats["total"] == 0
        assert stats["category_stats"] == {}
        assert stats["status_stats"] == {}
        assert stats["generated_at"] is not None

    @pytest.mark.asyncio
    async def test_empty_db_returns_valid_report(self, monkeypatch):
        """数据库不可用时应友好降级"""
        from unittest.mock import MagicMock

        mock_repo = MagicMock()
        mock_repo.list_all.return_value = []
        monkeypatch.setattr(
            "ticket_agent.repository.get_ticket_repository",
            lambda: mock_repo,
        )
        from ticket_agent.tools.content_tools import ReportGeneratorTool
        tool = ReportGeneratorTool()
        # 使用 Excel 格式（不依赖 Unicode 字体），用 ASCII 标题
        result = await tool.execute(title="Test Report", report_type="excel")
        assert result.success is True
        assert result.output["report_type"] == "excel"
        assert "file_path" in result.output

    @pytest.mark.asyncio
    async def test_empty_db_pdf_fallback_gracefully(self, monkeypatch):
        """PDF 格式在无 Unicode 字体时也不应崩溃"""
        from unittest.mock import MagicMock

        mock_repo = MagicMock()
        mock_repo.list_all.return_value = []
        monkeypatch.setattr(
            "ticket_agent.repository.get_ticket_repository",
            lambda: mock_repo,
        )
        from ticket_agent.tools.content_tools import ReportGeneratorTool
        tool = ReportGeneratorTool()
        result = await tool.execute(title="ASCII Report", report_type="pdf")
        assert result.success is True


# ===== 注册函数 =====

class TestRegisterContentTools:
    """register_content_tools 测试"""

    def test_register_all(self):
        registry = ToolRegistry()
        from ticket_agent.tools.content_tools import register_content_tools
        register_content_tools(registry)
        registered = registry.list_tools()
        assert "generate_text" in registered
        assert "generate_image" in registered
        assert "generate_report" in registered

    def test_register_with_llm(self):
        from llm.base import LLMBase, LLMResponse

        class MockLLM(LLMBase):
            async def generate(self, messages, **kw):
                return LLMResponse(content="ok", model="mock")
            async def stream(self, messages, **kw):
                yield "ok"

        registry = ToolRegistry()
        from ticket_agent.tools.content_tools import register_content_tools
        register_content_tools(registry, llm=MockLLM("mock", "key"))
        text_tool = registry.get("generate_text")
        assert text_tool is not None
        assert text_tool.llm is not None
