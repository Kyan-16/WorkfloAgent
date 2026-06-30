"""
API 共享依赖

持有全局 Coordinator 和 EvolutionExecutor 引用，供各路由模块和外部模块使用。

设计意图：避免循环导入。
- feedback_loop.py / config_store.py 也从这里导入 get_coordinator
- 不会导入任何应用模块（除了 fastapi）
"""
from fastapi import HTTPException

_coordinator = None
_evolution_executor = None


def get_coordinator():
    """获取全局 coordinator 实例"""
    global _coordinator
    if _coordinator is None:
        raise HTTPException(status_code=503, detail="Coordinator 未初始化")
    return _coordinator


def set_coordinator(coordinator):
    """设置全局 coordinator"""
    global _coordinator
    _coordinator = coordinator


def get_evolution_executor():
    """获取全局 evolution executor 实例"""
    global _evolution_executor
    if _evolution_executor is None:
        raise HTTPException(status_code=503, detail="EvolutionExecutor 未初始化")
    return _evolution_executor


def set_evolution_executor(executor):
    """设置全局 evolution executor"""
    global _evolution_executor
    _evolution_executor = executor
