"""
模型配置和切换路由

提供运行时 AI 模型切换、Provider 列表查询、配置管理等接口。
"""
import logging

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from ticket_agent.api.deps import get_coordinator
from ticket_agent.auth import get_current_user, require_manager, CurrentUser
from llm.provider_map import resolve_model, create_llm_from_model
from llm.factory import create_llm
from ticket_agent.setup import list_providers, get_provider_by_id
from ticket_agent.models.config_store import get_model_config_store, ModelConfig

logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["模型配置"])


class SwitchModelRequest(BaseModel):
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    agent_role: str = ""
    list_only: bool = False


class ProviderInfoResponse(BaseModel):
    id: str
    name: str
    models: list[str]
    default_model: str
    description: str
    signup_url: str


class SwitchModelResponse(BaseModel):
    success: bool
    message: str
    current_model: str = ""
    available_providers: list[ProviderInfoResponse] = []


@router.post("/switch_model", summary="切换 AI 模型")
async def switch_model(
    req: SwitchModelRequest,
    current_user: CurrentUser = Depends(require_manager),
):
    """运行时切换 AI 模型，无需重启服务。"""
    if req.list_only:
        providers = list_providers()
        return SwitchModelResponse(
            success=True,
            message=f"可用 Provider: {len(providers)} 个",
            available_providers=[
                ProviderInfoResponse(
                    id=p["id"], name=p["name"], models=p["models"],
                    default_model=p["default_model"],
                    description=p["description"], signup_url=p["signup_url"],
                ) for p in providers
            ],
        )

    coord = get_coordinator()

    if req.model:
        info = resolve_model(req.model)
        provider_name = info.provider
        model_name = req.model
        api_key = req.api_key or info.api_key
        base_url = req.base_url or info.base_url or ""
    elif req.provider:
        provider_name = req.provider
        model_name = req.model or ""
        api_key = req.api_key
        base_url = req.base_url
    else:
        raise HTTPException(status_code=400, detail="请指定 model 或 provider")

    if not api_key:
        raise HTTPException(status_code=400, detail="API Key 不能为空")

    config = {"provider": provider_name, "model": model_name, "api_key": api_key}
    if base_url:
        config["base_url"] = base_url

    try:
        new_llm = create_llm(config)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"模型创建失败: {e}")

    if req.agent_role == "classifier":
        coord.classifier.llm = new_llm
        msg = f"分类 Agent 模型已切换: {model_name}"
    elif req.agent_role == "executor":
        coord.executor.llm = new_llm
        msg = f"执行 Agent 模型已切换: {model_name}"
    else:
        coord.llm = new_llm
        coord.classifier.llm = new_llm
        coord.executor.llm = new_llm
        msg = f"全部 Agent 模型已切换: {model_name}"

    logger.info(f"模型切换: {msg} (by {current_user.user_id})")
    return SwitchModelResponse(success=True, message=msg, current_model=model_name)


@router.get("/providers", summary="列出可用 AI Provider")
async def list_available_providers():
    """列出所有支持的 AI Provider 及其模型"""
    providers = list_providers()
    return SwitchModelResponse(
        success=True,
        message=f"可用 Provider: {len(providers)} 个",
        available_providers=[
            ProviderInfoResponse(
                id=p["id"], name=p["name"], models=p["models"],
                default_model=p["default_model"],
                description=p["description"], signup_url=p["signup_url"],
            ) for p in providers
        ],
    )


class ConfigureModelRequest(BaseModel):
    provider_id: str
    model: str
    api_key: str
    base_url: str = ""
    label: str = ""
    test_only: bool = False


class ModelStatusResponse(BaseModel):
    success: bool
    current_model: str = ""
    current_provider: str = ""
    configs: list = []
    available_providers: list = []


@router.get("/api/models/status", summary="获取模型配置状态")
async def get_model_status(
    current_user: CurrentUser = Depends(get_current_user),
):
    """获取当前模型状态和所有已保存的配置"""
    store = get_model_config_store()
    active = store.get_active()
    configs = store.load_all()
    providers = list_providers()

    return ModelStatusResponse(
        success=True,
        current_model=active.model if active else "未配置",
        current_provider=active.provider_id if active else "",
        configs=[{"provider_id": c.provider_id, "model": c.model,
                   "label": c.label, "is_active": c.is_active,
                   "api_key_masked": c.api_key[:8] + "..." + c.api_key[-4:] if len(c.api_key) > 12 else "",
                   "base_url": c.base_url} for c in configs],
        available_providers=[
            {"id": p["id"], "name": p["name"], "models": p["models"],
             "default_model": p["default_model"],
             "description": p["description"], "signup_url": p["signup_url"]}
            for p in providers
        ],
    )


@router.post("/api/models/configure", summary="配置 AI 模型")
async def configure_model(
    req: ConfigureModelRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """配置 AI 模型并立即生效，无需重启。"""
    provider_info = get_provider_by_id(req.provider_id)
    if not provider_info:
        raise HTTPException(status_code=400, detail=f"不支持的 Provider: {req.provider_id}")

    if not req.api_key:
        raise HTTPException(status_code=400, detail="API Key 不能为空")

    info = resolve_model(req.model)
    try:
        llm_instance = create_llm({
            "provider": info.provider,
            "model": req.model,
            "api_key": req.api_key,
            "base_url": req.base_url or info.base_url or "",
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"模型创建失败: {e}")

    if req.test_only:
        return {"success": True, "message": "连接测试通过"}

    label = req.label or provider_info["name"]
    config = ModelConfig(
        provider_id=req.provider_id,
        model=req.model,
        api_key=req.api_key,
        base_url=req.base_url,
        label=label,
        is_active=True,
    )

    store = get_model_config_store()

    try:
        coord = get_coordinator()
        coord.llm = llm_instance
        coord.classifier.llm = llm_instance
        coord.executor.llm = llm_instance
        logger.info(f"前端配置模型: {label} ({req.model}) by {current_user.user_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"模型切换失败: {e}")

    store.upsert(config)
    store.set_active(req.provider_id)

    return {
        "success": True,
        "message": f"已切换至 {label} ({req.model})",
        "current_model": req.model,
    }


@router.post("/api/models/switch/{provider_id}", summary="切换到已保存的模型配置")
async def switch_to_saved_config(
    provider_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """切换到已保存的模型配置（从本地存储读取完整 API Key，无需前端回传）。"""
    store = get_model_config_store()
    configs = store.load_all()

    target = None
    for c in configs:
        if c.provider_id == provider_id:
            target = c
            break

    if not target:
        raise HTTPException(status_code=404, detail=f"未找到 {provider_id} 的已保存配置")
    if not target.api_key:
        raise HTTPException(status_code=400, detail=f"{target.label} 的 API Key 为空，请重新配置")

    info = resolve_model(target.model)
    try:
        llm_instance = create_llm({
            "provider": info.provider,
            "model": target.model,
            "api_key": target.api_key,
            "base_url": target.base_url or info.base_url or "",
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"模型创建失败: {e}")

    try:
        coord = get_coordinator()
        coord.llm = llm_instance
        coord.classifier.llm = llm_instance
        coord.executor.llm = llm_instance
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"模型切换失败: {e}")

    store.set_active(provider_id)
    logger.info(f"已切换到已保存配置: {target.label} ({target.model}) by {current_user.user_id}")

    return {
        "success": True,
        "message": f"已切换至 {target.label} ({target.model})",
        "current_model": target.model,
    }
