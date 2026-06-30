"""
Tool 基类 + ToolResult 单元测试
"""
import json
import pytest
from tools.base import Tool, ToolResult


class TestToolResult:
    """ToolResult 数据类测试"""

    def test_success_default(self):
        result = ToolResult()
        assert result.success is True
        assert result.output is None
        assert result.error is None

    def test_success_with_output(self):
        result = ToolResult(success=True, output={"key": "value"})
        assert result.success is True
        assert result.output == {"key": "value"}

    def test_failure(self):
        result = ToolResult(success=False, error="出错了")
        assert result.success is False
        assert result.error == "出错了"

    def test_to_str_success_dict(self):
        result = ToolResult(success=True, output={"msg": "ok"})
        text = result.to_str()
        parsed = json.loads(text)
        assert parsed["msg"] == "ok"

    def test_to_str_success_str(self):
        result = ToolResult(success=True, output="hello")
        assert result.to_str() == "hello"

    def test_to_str_failure(self):
        result = ToolResult(success=False, error="失败")
        assert "[工具执行失败]" in result.to_str()
        assert "失败" in result.to_str()

    def test_to_str_none_output(self):
        result = ToolResult(success=True, output=None)
        assert result.to_str() == "None"

    def test_to_str_list_output(self):
        result = ToolResult(success=True, output=[1, 2, 3])
        text = result.to_str()
        assert "1" in text
        assert "2" in text


# ---- 测试用 Tool 子类 ----

class SimpleTool(Tool):
    name = "simple_tool"
    description = "一个简单的测试工具"
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "名称"},
        },
        "required": ["name"],
    }

    async def execute(self, name: str = "world") -> ToolResult:
        return ToolResult(success=True, output=f"Hello, {name}!")


class FailingTool(Tool):
    name = "failing_tool"
    description = "总是失败的工具"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> ToolResult:
        raise ValueError("故意失败")


class TestTool:
    """Tool 基类测试"""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        tool = SimpleTool()
        result = await tool.execute(name="测试")
        assert result.success is True
        assert result.output == "Hello, 测试!"

    @pytest.mark.asyncio
    async def test_execute_default_param(self):
        tool = SimpleTool()
        result = await tool.execute()
        assert result.output == "Hello, world!"

    @pytest.mark.asyncio
    async def test_safe_execute_catches_exception(self):
        tool = FailingTool()
        result = await tool.safe_execute()
        assert result.success is False
        assert "failing_tool 执行失败" in result.error

    def test_get_function_schema(self):
        tool = SimpleTool()
        schema = tool.get_function_schema()
        assert schema["name"] == "simple_tool"
        assert schema["description"] == "一个简单的测试工具"
        assert schema["parameters"]["type"] == "object"
        assert "name" in schema["parameters"]["properties"]

    def test_get_function_schema_empty_params(self):
        class NoParamTool(Tool):
            name = "no_param"
            description = "无参数工具"
            parameters = None

            async def execute(self) -> ToolResult:
                return ToolResult(success=True)

        tool = NoParamTool()
        schema = tool.get_function_schema()
        assert schema["name"] == "no_param"
        # None 时自动降级为默认结构
        assert schema["parameters"]["type"] == "object"

    def test_name_and_description_required(self):
        """确保每个 Tool 子类必须定义 name 和 description"""
        with pytest.raises(TypeError):
            # abstract class can't be instantiated
            Tool()
