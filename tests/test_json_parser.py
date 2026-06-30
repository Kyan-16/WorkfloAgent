"""
JSON 解析器测试
"""
from utils.json_parser import parse_json, safe_parse_json


def test_basic_parse():
    r = parse_json('{"a": 1}')
    assert r.success
    assert r.value == {"a": 1}
    assert not r.is_truncated


def test_markdown_code_block():
    r = parse_json('```json\n{"a": 1}\n```')
    assert r.success
    assert r.value == {"a": 1}


def test_trailing_comma():
    r = parse_json('{"a": 1, "b": 2,}')
    assert r.success
    assert r.value == {"a": 1, "b": 2}


def test_detect_truncated_unclosed_brace():
    r = parse_json('{"a": 1, "b": 2')
    assert r.is_truncated  # 检测到截断
    # json_repair 可能成功修复，success 可能为 True


def test_detect_truncated_unclosed_string():
    r = parse_json('{"a": "hello')
    assert r.is_truncated


def test_detect_truncated_trailing_comma():
    r = parse_json('{"a": 1,')
    assert r.is_truncated


def test_empty_input():
    r = parse_json("")
    assert not r.success
    assert r.error == "输入为空"


def test_safe_parse_json_compat():
    """兼容旧 API"""
    v = safe_parse_json('{"a": 1}')
    assert v == {"a": 1}

    v = safe_parse_json("invalid", default={"fallback": True})
    assert v == {"fallback": True}


def test_whitespace_input():
    r = parse_json("  ")
    assert not r.success
    assert r.error == "输入为空"


def test_array_parse():
    r = parse_json('[1, 2, 3]')
    assert r.success
    assert r.value == [1, 2, 3]


def test_truncated_array():
    r = parse_json('[1, 2, 3')
    assert r.is_truncated
