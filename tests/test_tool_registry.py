"""
ToolRegistry 注册中心单元测试
"""
import pytest
from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry


class TestToolRegistry:
    """ToolRegistry 注册、查找、执行测试"""

    def test_empty_registry(self):
        registry = ToolRegistry()
        assert len(registry) == 0
        assert registry.list_tools() == []

    def test_register_instance(self):
        registry = ToolRegistry()
        from tests.test_tool_base import SimpleTool
        registry.register(SimpleTool())
        assert len(registry) == 1
        assert "simple_tool" in registry

    def test_register_class(self):
        """装饰器风格注册"""
        registry = ToolRegistry()

        @registry.register
        class DecoratedTool(Tool):
            name = "decorated"
            description = "装饰器注册的工具"
            parameters = {"type": "object", "properties": {}}

            async def execute(self) -> ToolResult:
                return ToolResult(success=True, output="ok")

        assert "decorated" in registry
        assert len(registry) == 1

    def test_add_method(self):
        registry = ToolRegistry()
        from tests.test_tool_base import SimpleTool
        registry.add(SimpleTool())
        assert "simple_tool" in registry

    def test_register_duplicate_overwrites(self):
        registry = ToolRegistry()

        class ToolA(Tool):
            name = "tool_x"
            description = "原版"
            parameters = {"type": "object", "properties": {}}
            async def execute(self) -> ToolResult:
                return ToolResult(success=True, output="A")

        class ToolB(Tool):
            name = "tool_x"
            description = "新版"
            parameters = {"type": "object", "properties": {}}
            async def execute(self) -> ToolResult:
                return ToolResult(success=True, output="B")

        registry.register(ToolA())
        registry.register(ToolB())
        assert len(registry) == 1  # 覆盖

    def test_get_nonexistent(self):
        registry = ToolRegistry()
        assert registry.get("no_such_tool") is None

    def test_get_function_schemas(self):
        registry = ToolRegistry()

        class Tool1(Tool):
            name = "tool1"
            description = "工具1"
            parameters = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
            async def execute(self, a: str) -> ToolResult:
                return ToolResult(success=True)

        class Tool2(Tool):
            name = "tool2"
            description = "工具2"
            parameters = {"type": "object", "properties": {"b": {"type": "integer"}}, "required": []}
            async def execute(self, b: int = 0) -> ToolResult:
                return ToolResult(success=True)

        registry.register(Tool1())
        registry.register(Tool2())
        schemas = registry.get_function_schemas()
        assert len(schemas) == 2
        names = {s["name"] for s in schemas}
        assert names == {"tool1", "tool2"}

    @pytest.mark.asyncio
    async def test_call_success(self):
        registry = ToolRegistry()
        from tests.test_tool_base import SimpleTool
        registry.register(SimpleTool())
        result = await registry.call("simple_tool", name="Alice")
        assert result.success is True
        assert result.output == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_call_nonexistent(self):
        registry = ToolRegistry()
        result = await registry.call("ghost_tool")
        assert result.success is False
        assert "不存在" in result.error

    @pytest.mark.asyncio
    async def test_call_from_llm_response(self):
        registry = ToolRegistry()
        from tests.test_tool_base import SimpleTool
        registry.register(SimpleTool())

        tool_call = {
            "id": "call_001",
            "function": {
                "name": "simple_tool",
                "arguments": '{"name": "LLM"}',
            },
        }
        result = await registry.call_from_llm_response(tool_call)
        assert result.success is True
        assert result.output == "Hello, LLM!"

    @pytest.mark.asyncio
    async def test_call_from_llm_response_invalid_json(self):
        registry = ToolRegistry()
        from tests.test_tool_base import SimpleTool
        registry.register(SimpleTool())

        tool_call = {
            "id": "call_002",
            "function": {
                "name": "simple_tool",
                "arguments": "invalid json{{{",
            },
        }
        result = await registry.call_from_llm_response(tool_call)
        assert result.success is False

    def test_list_tools(self):
        registry = ToolRegistry()
        from tests.test_tool_base import SimpleTool
        registry.register(SimpleTool())
        assert registry.list_tools() == ["simple_tool"]
