"""
URL 安全验证器测试
"""
from tools.security.url_safety import check_url, validate_url_safe


def test_public_url_safe():
    """公共 URL 应通过"""
    result = check_url("https://www.baidu.com")
    assert result.safe, f"公共 URL 应安全: {result.reason}"


def test_loopback_blocked():
    """loopback 应被阻止"""
    result = check_url("http://127.0.0.1:8000/api")
    assert not result.safe
    assert "内网地址" in result.reason or "Loopback" in result.reason


def test_localhost_blocked():
    """localhost 应被阻止"""
    result = check_url("http://localhost:8000")
    assert not result.safe


def test_private_ip_blocked():
    """RFC1918 内网地址应被阻止"""
    result = check_url("http://192.168.1.1/admin")
    assert not result.safe

    result = check_url("http://10.0.0.1/config")
    assert not result.safe

    result = check_url("http://172.16.0.1/admin")
    assert not result.safe


def test_cloud_metadata_blocked():
    """云元数据端点应被阻止"""
    result = check_url("http://169.254.169.254/latest/meta-data/")
    assert not result.safe
    assert "云元数据" in result.reason

    result = check_url("http://100.100.100.200/")
    assert not result.safe


def test_link_local_blocked():
    """Link-local 地址应被阻止"""
    result = check_url("http://169.254.1.1/")
    assert not result.safe


def test_validate_url_safe_bool():
    """布尔返回模式"""
    assert not validate_url_safe("http://127.0.0.1:8000")
    assert validate_url_safe("https://www.baidu.com")


def test_validate_url_safe_raise():
    """异常模式"""
    import pytest
    with pytest.raises(ValueError, match="不安全的 URL"):
        validate_url_safe("http://127.0.0.1:8000", raise_on_error=True)

    # 安全的 URL 不应抛异常
    validate_url_safe("https://api.openai.com", raise_on_error=True)


def test_invalid_url():
    """无效 URL 应被拒绝"""
    result = check_url("")
    assert not result.safe

    result = check_url("not-a-url")
    assert not result.safe
