"""
模型配置交互式向导

提供命令行交互，让用户选择 LLM Provider 并配置 API Key。

使用方式：
    python -m ticket_agent.setup

支持的 Provider：
    1. DeepSeek   — deepseek-chat, deepseek-reasoner
    2. 通义千问    — qwen-plus, qwen-max, qwen3-*
    3. Kimi       — moonshot-v1-8k, moonshot-v1-32k
    4. ChatGPT    — gpt-4o, gpt-4o-mini, gpt-4-turbo
    5. 智谱 GLM   — glm-4, glm-4-plus
    6. Claude     — claude-3-5-sonnet, claude-3-haiku
    7. Gemini     — gemini-2.0-flash, gemini-2.0-pro
    8. 零一万物    — yi-large, yi-medium
    9. Doubao     — doubao-pro, doubao-lite
"""
import os
import sys
from pathlib import Path
from typing import Optional

# Provider 展示信息
PROVIDER_INFO = [
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
        "api_key_var": "DEEPSEEK_API_KEY",
        "base_url_var": "DEEPSEEK_BASE_URL",
        "default_base_url": "https://api.deepseek.com/v1",
        "signup_url": "https://platform.deepseek.com/api_keys",
        "description": "性价比极高，国内直连速度快",
    },
    {
        "id": "dashscope",
        "name": "通义千问 (DashScope)",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo", "qwen3-max"],
        "default_model": "qwen-plus",
        "api_key_var": "DASHSCOPE_API_KEY",
        "base_url_var": "",
        "default_base_url": "",
        "signup_url": "https://help.aliyun.com/zh/model-studio/developer-api-key",
        "description": "阿里云出品，中文理解强，免费额度多",
    },
    {
        "id": "kimi",
        "name": "Kimi (Moonshot)",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k"],
        "default_model": "moonshot-v1-8k",
        "api_key_var": "MOONSHOT_API_KEY",
        "base_url_var": "MOONSHOT_BASE_URL",
        "default_base_url": "https://api.moonshot.cn/v1",
        "signup_url": "https://platform.moonshot.cn/console/api-keys",
        "description": "长上下文能力强，适合处理长文档",
    },
    {
        "id": "openai",
        "name": "ChatGPT (OpenAI)",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o3-mini"],
        "default_model": "gpt-4o-mini",
        "api_key_var": "OPENAI_API_KEY",
        "base_url_var": "OPENAI_BASE_URL",
        "default_base_url": "",
        "signup_url": "https://platform.openai.com/api-keys",
        "description": "全球最强综合模型，需科学上网",
    },
    {
        "id": "zhipu",
        "name": "智谱 GLM",
        "models": ["glm-4", "glm-4-plus", "glm-4-air"],
        "default_model": "glm-4-plus",
        "api_key_var": "ZHIPU_API_KEY",
        "base_url_var": "ZHIPU_BASE_URL",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "signup_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "description": "清华团队，中文能力强",
    },
    {
        "id": "claude",
        "name": "Claude (Anthropic)",
        "models": ["claude-3-5-sonnet", "claude-3-haiku", "claude-opus"],
        "default_model": "claude-3-5-sonnet",
        "api_key_var": "ANTHROPIC_API_KEY",
        "base_url_var": "ANTHROPIC_BASE_URL",
        "default_base_url": "",
        "signup_url": "https://console.anthropic.com/",
        "description": "代码能力顶级，推理透彻",
    },
    {
        "id": "gemini",
        "name": "Gemini (Google)",
        "models": ["gemini-2.0-flash", "gemini-2.0-pro"],
        "default_model": "gemini-2.0-flash",
        "api_key_var": "GEMINI_API_KEY",
        "base_url_var": "GEMINI_BASE_URL",
        "default_base_url": "",
        "signup_url": "https://aistudio.google.com/apikey",
        "description": "Google 出品，免费额度慷慨",
    },
    {
        "id": "yi",
        "name": "零一万物 (Yi)",
        "models": ["yi-large", "yi-medium"],
        "default_model": "yi-large",
        "api_key_var": "YI_API_KEY",
        "base_url_var": "YI_BASE_URL",
        "default_base_url": "https://api.lingyiwanwu.com/v1",
        "signup_url": "https://platform.lingyiwanwu.com/api-keys",
        "description": "李开复团队，中文优秀",
    },
    {
        "id": "doubao",
        "name": "Doubao (火山引擎)",
        "models": ["doubao-pro", "doubao-lite"],
        "default_model": "doubao-pro",
        "api_key_var": "DOUBAO_API_KEY",
        "base_url_var": "DOUBAO_BASE_URL",
        "default_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "signup_url": "https://console.volcengine.com/ark/",
        "description": "字节跳动出品，性价比高",
    },
]


def list_providers() -> list[dict]:
    """获取所有 Provider 信息列表"""
    return PROVIDER_INFO


def get_provider_by_id(provider_id: str) -> Optional[dict]:
    """按 ID 查找 Provider"""
    for p in PROVIDER_INFO:
        if p["id"] == provider_id:
            return p
    return None


def write_env_file(provider: dict, api_key: str, model: str, base_url: str = ""):
    """
    写入 .env 配置文件。

    写入后所有 API Key 环境变量都会被设置，
    切换模型只需改 LLM_MODEL 一行。
    """
    env_path = Path(".env")

    # 读取现有内容
    existing = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                existing[key.strip()] = value.strip()

    # 更新配置
    existing["LLM_MODEL"] = model
    existing[provider["api_key_var"]] = api_key

    if base_url:
        existing["LLM_BASE_URL"] = base_url

    # 如果 Provider 有专属 base_url，也写入
    if provider.get("base_url_var") and base_url:
        existing[provider["base_url_var"]] = base_url

    # 写入文件
    lines = [
        "# ============================================================",
        f"# WorkfloAgent 配置 — 当前 Provider: {provider['name']}",
        "# ============================================================",
        "",
        "# ── LLM 模型（修改此项即可切换 Provider）──",
        f"LLM_MODEL={model}",
        "",
        "# ── API Key ──",
        f"{provider['api_key_var']}={api_key}",
        "",
    ]

    # 添加 base_url（如果有）
    if base_url and provider.get("base_url_var"):
        lines.append(f"# ── API 地址 ──")
        lines.append(f"{provider['base_url_var']}={base_url}")
        lines.append("")

    # 添加功能开关
    lines.extend([
        "# ── 功能开关 ──",
        "MCP_ENABLED=true",
        "QDRANT_ENABLED=false",
        "PROMETHEUS_ENABLED=true",
        "AGENT_TRACE_ENABLED=true",
        "",
        "# ── 数据库 ──",
        "DATABASE_URL=sqlite:///data/ticket_agent.db",
        "",
    ])

    env_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  ✅ .env 文件已写入: {env_path.absolute()}")


def run_interactive():
    """交互式配置向导"""
    print("=" * 60)
    print("  WorkfloAgent — 模型配置向导")
    print("  选择你要使用的 AI 模型提供商")
    print("=" * 60)
    print()

    # 显示 Provider 列表
    for idx, p in enumerate(PROVIDER_INFO, 1):
        print(f"  {idx}. {p['name']}")
        print(f"     模型: {', '.join(p['models'])}")
        print(f"     特点: {p['description']}")
        print(f"     注册: {p['signup_url']}")
        print()

    # 选择 Provider
    while True:
        try:
            choice = input("  请输入编号 (1-{}): ".format(len(PROVIDER_INFO))).strip()
            idx = int(choice) - 1
            if 0 <= idx < len(PROVIDER_INFO):
                provider = PROVIDER_INFO[idx]
                break
            print(f"  ❌ 请输入 1-{len(PROVIDER_INFO)} 之间的数字")
        except ValueError:
            print("  ❌ 请输入有效数字")

    print(f"\n  --- 你选择了: {provider['name']} ---\n")

    # 选择模型
    print("  可用模型:")
    for i, m in enumerate(provider["models"], 1):
        default_mark = " (推荐)" if m == provider["default_model"] else ""
        print(f"    {i}. {m}{default_mark}")

    model = provider["default_model"]
    if len(provider["models"]) > 1:
        while True:
            try:
                choice = input(f"\n  选择模型 (1-{len(provider['models'])}, 回车默认): ").strip()
                if not choice:
                    break
                idx = int(choice) - 1
                if 0 <= idx < len(provider["models"]):
                    model = provider["models"][idx]
                    break
                print(f"  请输入 1-{len(provider['models'])}")
            except ValueError:
                break  # 回车默认

    print(f"\n  选中模型: {model}")

    # 输入 API Key
    print(f"\n  请到以下地址获取 API Key:")
    print(f"    {provider['signup_url']}")
    api_key = input(f"\n  请输入 {provider['name']} API Key: ").strip()
    while not api_key:
        print("  ❌ API Key 不能为空")
        api_key = input(f"  请输入 {provider['name']} API Key: ").strip()

    # Base URL（如果需要）
    base_url = ""
    if provider.get("default_base_url"):
        print(f"\n  API 地址 (回车使用默认):")
        print(f"    默认: {provider['default_base_url']}")
        base_url = input(f"  自定义地址 (可选): ").strip()
        if not base_url:
            base_url = provider["default_base_url"]

    # 确认
    print(f"\n  ─────────────────────────────────────")
    print(f"  Provider:   {provider['name']}")
    print(f"  模型:       {model}")
    print(f"  API Key:    {api_key[:8]}...{api_key[-4:]}")
    print(f"  API 地址:   {base_url or '(使用默认)'}")
    print(f"  ─────────────────────────────────────")

    confirm = input(f"\n  确认写入配置? (Y/n): ").strip().lower()
    if confirm in ("", "y", "yes"):
        write_env_file(provider, api_key, model, base_url)
        print(f"\n  ✅ 配置完成！现在可以启动项目了：")
        print(f"     python -m ticket_agent")
        print(f"     或")
        print(f"     docker compose up")
    else:
        print("\n  ❌ 已取消，配置未写入")


if __name__ == "__main__":
    run_interactive()
