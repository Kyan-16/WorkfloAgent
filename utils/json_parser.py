"""
JSON 容错解析器

处理 LLM 返回的不规范 JSON：
  1. 提取 ```json ... ``` 代码块
  2. 定位 { } 边界
  3. 修复尾随逗号
  4. 检测截断（finish_reason == "length" 导致的不完整 JSON）
  5. 尝试 json_repair 库（若安装）
  6. 返回结构化 ParseResult

使用示例：
    result = safe_parse_json(text)           # 直接返回值（兼容旧 API）
    parsed = parse_json(text)                # 返回 ParseResult（推荐）
    if parsed.success:
        data = parsed.value
"""

import re
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .logger import get_logger

logger = get_logger("utils.json_parser")


@dataclass
class ParseResult:
    """结构化 JSON 解析结果"""
    value: Any = None
    success: bool = False
    is_truncated: bool = False
    error: Optional[str] = None
    original_length: int = 0


def _detect_truncation(text: str) -> bool:
    """
    检测 JSON 是否被截断。

    截断特征：
    - 花括号/方括号未闭合
    - 字符串引号未闭合
    - 以逗号结尾
    - 以不完整的 key/value 结尾
    - 末尾有不完整的转义序列
    """
    text = text.strip()

    if not text:
        return False

    # 检查括号是否匹配
    stack = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in '{[':
            stack.append(ch)
        elif ch == '}':
            if stack and stack[-1] == '{':
                stack.pop()
        elif ch == ']':
            if stack and stack[-1] == '[':
                stack.pop()

    # 括号未闭合 → 截断
    if stack:
        return True

    # 字符串引号未闭合 → 截断
    if in_string:
        return True

    # 以逗号结尾 → 截断（后面应有内容）
    if text.rstrip().endswith(','):
        return True

    return False


def _try_json_repair(text: str) -> Optional[str]:
    """
    尝试使用 json_repair 库修复 JSON。

    json_repair 能处理：
    - 缺少引号的 key
    - 单引号代替双引号
    - 尾随逗号
    - 注释
    - NaN/Infinity
    """
    try:
        from json_repair import repair_json
        repaired = repair_json(text)
        if repaired and repaired != text:
            logger.info("json_repair 成功修复 JSON")
            return repaired
        return None
    except ImportError:
        return None
    except Exception as e:
        logger.debug(f"json_repair 修复失败: {e}")
        return None


def parse_json(text: str) -> ParseResult:
    """
    解析 JSON 并返回结构化结果。

    Args:
        text: LLM 原始输出文本

    Returns:
        ParseResult: 包含解析值、状态、截断检测的结构化结果
    """
    result = ParseResult(original_length=len(text) if text else 0)

    if not text or not text.strip():
        result.error = "输入为空"
        return result

    # Step 1: 检测截断
    result.is_truncated = _detect_truncation(text)
    if result.is_truncated:
        logger.warning(f"检测到截断 JSON (原文长度={len(text)})")

    # Step 2: 尝试直接解析
    try:
        result.value = json.loads(text)
        result.success = True
        return result
    except json.JSONDecodeError:
        pass

    # Step 3: 尝试 json_repair 修复（若已安装）
    try:
        repaired = _try_json_repair(text)
        if repaired:
            result.value = json.loads(repaired)
            result.success = True
            return result
    except (json.JSONDecodeError, Exception):
        pass

    # Step 4: 提取 markdown 代码块
    code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    extracted = None
    if code_block_match:
        block_text = code_block_match.group(1).strip()
        try:
            result.value = json.loads(block_text)
            result.success = True
            return result
        except json.JSONDecodeError:
            extracted = block_text

    # Step 5: 尝试修复代码块中提取的内容
    if extracted:
        try:
            repaired = _try_json_repair(extracted)
            if repaired:
                result.value = json.loads(repaired)
                result.success = True
                return result
        except (json.JSONDecodeError, Exception):
            pass
        text = extracted

    # Step 6: 定位 JSON 边界
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        # 尝试数组
        start = text.find("[")
        end = text.rfind("]")

    if start != -1 and end > start:
        json_str = text[start:end + 1]

        # Step 7: 修复尾随逗号 (,} 或 ,])
        json_str = re.sub(r",\s*([}\]])", r"\1", json_str)

        try:
            result.value = json.loads(json_str)
            result.success = True
            return result
        except json.JSONDecodeError as e:
            result.error = str(e)
            logger.warning(f"JSON 边界提取后仍解析失败: {e}")
            logger.debug(f"提取内容: {json_str[:200]}...")

            # Step 8: 尝试修复边界提取后的内容
            try:
                repaired = _try_json_repair(json_str)
                if repaired:
                    result.value = json.loads(repaired)
                    result.success = True
                    return result
            except (json.JSONDecodeError, Exception):
                pass
    else:
        result.error = "未找到 JSON 边界（{} 或 []）"

    logger.error(f"JSON 解析彻底失败，原文前200字符: {text[:200]}")
    return result


def safe_parse_json(text: str, default: Any = None) -> Any:
    """
    安全解析可能不规范的 JSON 文本（兼容旧 API）。

    这是 parse_json 的简化版本，失败时返回 default。

    Args:
        text: LLM 原始输出文本
        default: 解析失败时的默认返回值

    Returns:
        解析后的 Python 对象，或 default
    """
    result = parse_json(text)
    return result.value if result.success else default
