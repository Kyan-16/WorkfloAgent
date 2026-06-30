"""
MCP Server - 工单系统工具暴露

启动方式：
    # 方式一：独立启动
    python -m ticket_agent.mcp.server

    # 方式二：通过 FastAPI 挂载（集成到主服务）
    # 在 main.py 中 import 并挂载

协议标准：Model Context Protocol (MCP)
允许 Claude、Dify、Coze 等 AI Agent 直接调用工单工具。
"""
import json
import logging
import os
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 尝试导入 MCP SDK
try:
    from mcp.server import Server, NotificationOptions
    from mcp.server.models import InitializationOptions
    from mcp.types import (
        Tool as MCPTool,
        TextContent,
        CallToolResult,
    )
    HAS_MCP = True
except ImportError:
    HAS_MCP = False
    logger.warning("mcp SDK 未安装（pip install mcp），MCP Server 不可用")


# ─── 工具定义 ───

MCP_TOOL_DEFINITIONS = [
    {
        "name": "get_ticket_status",
        "description": "根据工单ID查询工单当前状态和处理进度",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "工单ID，如 TK-20240101-XXXXXX",
                }
            },
            "required": ["ticket_id"],
        },
    },
    {
        "name": "update_ticket",
        "description": "更新工单的指定字段，如状态、处理人、优先级等",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string", "description": "工单ID"},
                "field": {
                    "type": "string",
                    "description": "要更新的字段名：status/assignee/priority/description",
                },
                "value": {"type": "string", "description": "字段的新值"},
            },
            "required": ["ticket_id", "field", "value"],
        },
    },
    {
        "name": "create_ticket",
        "description": "创建一个新工单，Agent 会自动分类和处理",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "工单内容描述"},
                "user_id": {"type": "string", "description": "用户标识"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "escalate_ticket",
        "description": "将工单转交人工客服处理",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string", "description": "工单ID"},
                "reason": {"type": "string", "description": "转人工原因"},
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high", "urgent"],
                    "description": "优先级",
                },
            },
            "required": ["ticket_id", "reason"],
        },
    },
    {
        "name": "search_knowledge",
        "description": "在知识库中搜索与问题相关的解决方案文档",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "category": {
                    "type": "string",
                    "enum": ["IT", "HR", "财务", "运维", ""],
                    "description": "知识库分类，为空则全库搜索",
                },
            },
            "required": ["query"],
        },
    },
]


class TicketMCPServer:
    """
    工单 MCP Server

    通过 MCP 协议暴露工单工具，供外部 AI Agent 调用。

    使用示例：
        server = TicketMCPServer(coordinator=coordinator)
        await server.run()  # 启动 STDIO 模式的 MCP Server
    """

    def __init__(self, coordinator=None):
        self.coordinator = coordinator
        self._server: Optional[Any] = None

    def _build_server(self) -> Any:
        """构建 MCP Server 实例"""
        if not HAS_MCP:
            raise ImportError("mcp SDK 未安装")

        server = Server("ticket-agent")

        @server.list_tools()
        async def list_tools() -> list[MCPTool]:
            return [
                MCPTool(
                    name=t["name"],
                    description=t["description"],
                    inputSchema=t["inputSchema"],
                )
                for t in MCP_TOOL_DEFINITIONS
            ]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            result = await self._execute_tool(name, arguments)
            return [TextContent(type="text", text=result)]

        return server

    async def _execute_tool(self, name: str, arguments: dict) -> str:
        """执行工具调用"""
        try:
            if name == "get_ticket_status":
                return await self._get_ticket_status(arguments)
            elif name == "update_ticket":
                return await self._update_ticket(arguments)
            elif name == "create_ticket":
                return await self._create_ticket(arguments)
            elif name == "escalate_ticket":
                return await self._escalate_ticket(arguments)
            elif name == "search_knowledge":
                return await self._search_knowledge(arguments)
            else:
                return json.dumps({"success": False, "error": f"未知工具: {name}"})
        except Exception as e:
            logger.error(f"MCP 工具执行失败: {name}: {e}")
            return json.dumps({"success": False, "error": str(e)})

    async def _get_ticket_status(self, args: dict) -> str:
        ticket_id = args.get("ticket_id", "")
        from ticket_agent.repository import get_ticket_repository
        ticket = get_ticket_repository().get(ticket_id)
        if ticket:
            return json.dumps(ticket.to_dict(), ensure_ascii=False)
        # 模拟返回
        return json.dumps({
            "ticket_id": ticket_id,
            "status": "待处理",
            "category": "IT",
            "message": "工单信息（模拟数据）",
        }, ensure_ascii=False)

    async def _update_ticket(self, args: dict) -> str:
        ticket_id = args.get("ticket_id", "")
        field = args.get("field", "")
        value = args.get("value", "")
        from ticket_agent.repository import get_ticket_repository
        result = get_ticket_repository().update(ticket_id, **{field: value})
        if result:
            return json.dumps({"success": True, "ticket_id": ticket_id, "updated": {field: value}}, ensure_ascii=False)
        return json.dumps({"success": False, "error": f"工单 {ticket_id} 不存在"}, ensure_ascii=False)

    async def _create_ticket(self, args: dict) -> str:
        content = args.get("content", "")
        user_id = args.get("user_id", "mcp_user")
        if not content:
            return json.dumps({"success": False, "error": "工单内容不能为空"})
        if self.coordinator:
            result = await self.coordinator.process(user_input=content, user_id=user_id)
            return json.dumps(result, ensure_ascii=False)
        # 无 coordinator 时返回简单结果
        from ticket_agent.models.ticket import Ticket, TicketCategory
        from ticket_agent.repository import get_ticket_repository
        ticket = Ticket(content=content, user_id=user_id)
        get_ticket_repository().create(ticket)
        return json.dumps({
            "success": True,
            "ticket_id": ticket.ticket_id,
            "message": f"工单已创建: {ticket.ticket_id}",
        }, ensure_ascii=False)

    async def _escalate_ticket(self, args: dict) -> str:
        ticket_id = args.get("ticket_id", "")
        reason = args.get("reason", "MCP 请求转人工")
        priority = args.get("priority", "normal")
        from ticket_agent.repository import get_ticket_repository
        get_ticket_repository().update(ticket_id, status="已转人工")
        return json.dumps({
            "success": True,
            "ticket_id": ticket_id,
            "status": "已转人工",
            "reason": reason,
            "priority": priority,
        }, ensure_ascii=False)

    async def _search_knowledge(self, args: dict) -> str:
        query = args.get("query", "")
        category = args.get("category", "")
        from ticket_agent.knowledge.store import get_knowledge_store
        from rag.retriever import KeywordRetriever
        store = get_knowledge_store()
        docs = store.list_docs(category) if category else store.list_docs()
        if not docs:
            return json.dumps({"success": True, "results": [], "count": 0})
        retriever = KeywordRetriever(
            documents=[{"content": d["content"], "metadata": d} for d in docs],
            top_k=5,
        )
        results = await retriever.retrieve(query)
        return json.dumps({
            "success": True,
            "count": len(results),
            "results": [
                {"content": r["content"][:300], "score": r["score"]}
                for r in results
            ],
        }, ensure_ascii=False)

    async def run_stdio(self):
        """通过 STDIO 运行 MCP Server（供 Claude Desktop 等调用）"""
        server = self._build_server()
        async with server.run_stdio():
            logger.info("MCP Server (STDIO) 已启动")
            await asyncio.Event().wait()

    def get_fastapi_app(self, path: str = "/mcp"):
        """
        获取 FastAPI SSE 路由（供主服务挂载）

        使用方式：
            from ticket_agent.mcp.server import TicketMCPServer
            mcp_server = TicketMCPServer(coordinator=coordinator)
            app.mount(path, mcp_server.get_fastapi_app())
        """
        if not HAS_MCP:
            return None
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse

        mcp_app = FastAPI(title="工单 MCP Server")

        @mcp_app.get("/tools")
        async def list_tools():
            return {"tools": MCP_TOOL_DEFINITIONS}

        @mcp_app.post("/call-tool")
        async def call_tool_api(name: str, arguments: dict = {}):
            result = await self._execute_tool(name, arguments or {})
            return JSONResponse(content=json.loads(result))

        return mcp_app


# ─── 独立启动入口 ───

async def main():
    """独立启动 MCP Server"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    from ticket_agent.coordinator.linear import LinearCoordinator
    from llm import create_llm
    from memory import LocalMemory

    llm = create_llm({
        "provider": os.getenv("LLM_PROVIDER", "dashscope"),
        "model": os.getenv("LLM_MODEL", "qwen-plus"),
        "api_key": os.getenv("LLM_API_KEY", ""),
    })
    memory = LocalMemory()
    coordinator = LinearCoordinator(llm=llm, memory=memory)

    server = TicketMCPServer(coordinator=coordinator)
    logger.info("启动 MCP Server (STDIO)...")
    await server.run_stdio()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
