"""
安全控制模块

防止 AI Agent 权限过大导致的安全问题：
1. 工具分级：自动执行 / 需确认 / 禁止
2. 速率限制：每会话每分钟最大工具调用次数
3. 操作审计：所有工具调用记录日志
4. 内容校验：AI 生成内容入库前检查
"""
from ticket_agent.security.tool_guard import ToolGuard, ToolPermission, SecurityAudit
