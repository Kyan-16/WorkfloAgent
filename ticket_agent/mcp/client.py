"""
MCP 客户端 — 纯 Python JSON-RPC 2.0 实现

支持 stdio 传输协议，对接任意 MCP Server。
懒加载 + 幂等连接 + 状态追踪。

使用示例：
    client = MCPClient(
        name="calculator",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-calculator"],
    )
    await client.connect()
    tools = await client.list_tools()
    result = await client.call_tool("add", {"a": 1, "b": 2})
    await client.close()
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class MCPToolDef:
    """MCP 工具定义"""
    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)


class MCPClient:
    """
    MCP 客户端（stdio 传输）

    :param name: 客户端名称
    :param command: 启动命令
    :param args: 命令参数
    :param env: 环境变量
    """

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] = None,
        env: dict = None,
    ):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}

        self._process: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._connected = False
        self._lock = asyncio.Lock()

    async def connect(self):
        """启动 MCP 服务器子进程并建立连接"""
        async with self._lock:
            if self._connected:
                return

        logger.info(f"MCP 客户端 '{self.name}' 正在连接: {self.command} {' '.join(self.args)}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                self.command, *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**self.env} if self.env else None,
            )

            self._reader_task = asyncio.create_task(self._read_loop())
            self._connected = True

            # 发送初始化请求
            result = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "WorkfloAgent-MCP", "version": "1.0.0"},
            })

            logger.info(f"MCP 客户端 '{self.name}' 已连接 (server: {result.get('serverInfo', {})})")

        except Exception as e:
            logger.error(f"MCP 客户端 '{self.name}' 连接失败: {e}")
            await self.close()
            raise

    async def _read_loop(self):
        """持续读取 MCP 响应的后台任务"""
        try:
            while self._process and self._process.stdout and not self._process.stdout.at_eof():
                line = await self._process.stdout.readline()
                if not line:
                    break

                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue

                try:
                    msg = json.loads(line_str)
                    req_id = msg.get("id")

                    if req_id is not None and req_id in self._pending:
                        future = self._pending.pop(req_id)
                        if not future.done():
                            if "error" in msg:
                                future.set_exception(
                                    RuntimeError(msg["error"].get("message", "MCP 错误"))
                                )
                            else:
                                future.set_result(msg.get("result", {}))
                except json.JSONDecodeError:
                    logger.debug(f"MCP 非 JSON 输出: {line_str[:200]}")

        except Exception as e:
            logger.warning(f"MCP 读取循环异常 ({self.name}): {e}")

    async def _send_request(self, method: str, params: dict = None) -> dict:
        """发送 JSON-RPC 请求"""
        if not self._connected or not self._process:
            raise RuntimeError(f"MCP 客户端 '{self.name}' 未连接")

        async with self._lock:
            self._request_id += 1
            req_id = self._request_id
            request = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params or {},
            }
            future = asyncio.get_event_loop().create_future()
            self._pending[req_id] = future

            if self._process.stdin:
                self._process.stdin.write((json.dumps(request) + "\n").encode())
                await self._process.stdin.drain()

        try:
            response = await asyncio.wait_for(future, timeout=30.0)
            return response
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise TimeoutError(f"MCP 请求超时: {method}")

    async def list_tools(self) -> list[MCPToolDef]:
        """列出 MCP 服务器提供的工具"""
        result = await self._send_request("tools/list")
        return [MCPToolDef(**t) for t in result.get("tools", [])]

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """调用 MCP 工具"""
        result = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        return result

    async def close(self):
        """关闭连接，终止子进程"""
        async with self._lock:
            self._connected = False

        # 取消读取任务
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        # 终止进程
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self._process.kill()
                    await self._process.wait()
                except ProcessLookupError:
                    pass
            self._process = None

        # 清理所有 pending futures
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

        logger.info(f"MCP 客户端 '{self.name}' 已关闭")

    @property
    def is_connected(self) -> bool:
        return self._connected
