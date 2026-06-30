"""
MCP 协议支持

将工单系统的能力暴露为 MCP (Model Context Protocol) Server，
让其他 AI Agent（如 Claude Code、Dify、Coze 等）可以直接调用工单工具。

暴露的工具：
1. get_ticket_status - 查询工单状态
2. update_ticket - 更新工单字段
3. create_ticket - 创建新工单
4. escalate_ticket - 转人工
5. search_knowledge - 搜索知识库
"""
