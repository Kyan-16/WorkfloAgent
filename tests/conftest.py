"""
测试配置 — 支持 stub / real 双模

--run-real 标志用于运行需要真实 LLM 的集成测试。
"""
import pytest


def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line(
        "markers",
        "real_llm: mark test as requiring a real LLM (use with --run-real)",
    )


def pytest_addoption(parser):
    parser.addoption(
        "--run-real",
        action="store_true",
        default=False,
        help="运行需要真实 LLM 的端到端测试",
    )


@pytest.fixture
def llm_mode(request) -> str:
    """返回当前 LLM 测试模式（stub / real）"""
    if request.config.getoption("--run-real"):
        return "real"
    return "stub"
