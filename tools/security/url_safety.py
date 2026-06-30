"""
URL 安全验证器 — 防止 SSRF 攻击

验证 URL 是否安全，阻止：
- 内网地址（loopback、RFC1918、link-local）
- 云元数据端点（AWS/GCP/Azure/阿里云）
- IPv6 内网地址
- DNS 解析后的隐藏内网 IP
"""
import socket
import ipaddress
import logging
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 阻止的 CIDR 段
BLOCKED_CIDR = [
    "127.0.0.0/8",       # Loopback
    "10.0.0.0/8",        # RFC1918
    "172.16.0.0/12",     # RFC1918
    "192.168.0.0/16",    # RFC1918
    "169.254.0.0/16",    # Link-local
    "0.0.0.0/8",         # "This" network
    "100.64.0.0/10",     # Carrier-grade NAT (CGNAT)
    "198.18.0.0/15",     # Benchmarking
    "::1/128",           # IPv6 loopback
    "fc00::/7",          # IPv6 unique local
    "fe80::/10",         # IPv6 link-local
    "::ffff:0:0/96",     # IPv4-mapped IPv6
]

# 云元数据端点
CLOUD_METADATA_IPS = {
    "169.254.169.254",   # AWS / GCP / Azure
    "100.100.100.200",   # 阿里云
    "100.100.100.204",   # 阿里云 (新加坡)
}


class URLCheckResult:
    """URL 安全检查结果"""
    safe: bool = False
    reason: str = ""
    resolved_ip: Optional[str] = None

    def __init__(self, safe: bool, reason: str = "", resolved_ip: str = None):
        self.safe = safe
        self.reason = reason
        self.resolved_ip = resolved_ip


def check_url(url: str) -> URLCheckResult:
    """
    检查 URL 是否安全。

    Args:
        url: 要检查的 URL

    Returns:
        URLCheckResult
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return URLCheckResult(False, "无法解析主机名")

        # 检查是否已经是 IP 地址
        try:
            ip = ipaddress.ip_address(host)
            return _check_ip(ip)
        except ValueError:
            pass  # 是域名，需要 DNS 解析

        # DNS 解析
        try:
            ips = socket.getaddrinfo(host, None)
            if not ips:
                return URLCheckResult(False, f"DNS 解析失败: {host}")

            # 检查所有解析出的 IP
            for addr_info in ips:
                ip_str = addr_info[4][0]
                try:
                    ip = ipaddress.ip_address(ip_str)
                    result = _check_ip(ip)
                    if not result.safe:
                        result.resolved_ip = ip_str
                        return result
                except ValueError:
                    continue

            return URLCheckResult(True, resolved_ip=ips[0][4][0])

        except socket.gaierror:
            return URLCheckResult(False, f"DNS 解析失败: {host}")

    except Exception as e:
        logger.warning(f"URL 检查异常: {e}")
        return URLCheckResult(False, f"URL 检查异常: {e}")


def _check_ip(ip) -> URLCheckResult:
    """检查 IP 是否安全"""
    ip_str = str(ip)

    # 云元数据端点
    if ip_str in CLOUD_METADATA_IPS:
        return URLCheckResult(False, f"禁止访问云元数据端点: {ip_str}")

    # 阻止的内网 CIDR
    for cidr in BLOCKED_CIDR:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
            if ip in network:
                return URLCheckResult(False, f"禁止访问内网地址: {ip_str} ({cidr})")
        except ValueError:
            continue

    return URLCheckResult(True, resolved_ip=ip_str)


def validate_url_safe(url: str, raise_on_error: bool = False) -> bool:
    """
    便捷函数：检查 URL 是否安全（返回 bool）。

    Args:
        url: 要检查的 URL
        raise_on_error: 不安全的 URL 是否抛出异常

    Returns:
        URL 是否安全

    Raises:
        ValueError: 当 raise_on_error=True 且 URL 不安全时
    """
    result = check_url(url)
    if not result.safe and raise_on_error:
        raise ValueError(f"不安全的 URL: {result.reason}")
    return result.safe
