"""
代码执行工具（沙箱模式）

在受限沙箱中执行 Python 代码片段，使用白名单内置函数，
排除危险函数如 open/exec/eval/__import__。
"""
import io
import sys
import traceback
from tools.base import Tool, ToolResult

# 安全的白名单内置函数
_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "ascii": ascii,
    "bin": bin, "bool": bool, "bytearray": bytearray, "bytes": bytes,
    "chr": chr, "complex": complex, "dict": dict, "divmod": divmod,
    "enumerate": enumerate, "filter": filter, "float": float,
    "format": format, "frozenset": frozenset, "hex": hex,
    "id": id, "int": int, "isinstance": isinstance, "issubclass": issubclass,
    "iter": iter, "len": len, "list": list, "map": map, "max": max,
    "min": min, "next": next, "object": object, "oct": oct, "ord": ord,
    "pow": pow, "print": print, "range": range, "repr": repr,
    "reversed": reversed, "round": round, "set": set, "slice": slice,
    "sorted": sorted, "str": str, "sum": sum, "tuple": tuple,
    "type": type, "zip": zip,
}


class CodeExecutorTool(Tool):
    """Python 代码执行工具（沙箱模式）"""

    name = "execute_python"
    description = "执行 Python 代码，适用于数学计算、数据处理、格式转换等任务"
    parameters = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "要执行的 Python 代码",
            },
        },
        "required": ["code"],
    }

    async def execute(self, code: str) -> ToolResult:
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            exec_globals = {"__builtins__": _SAFE_BUILTINS}
            exec(code, exec_globals)
            output = sys.stdout.getvalue()
            return ToolResult(success=True, output=output or "(无输出)")
        except Exception as e:
            error_trace = traceback.format_exc()
            return ToolResult(success=False, error=error_trace)
        finally:
            sys.stdout = old_stdout
