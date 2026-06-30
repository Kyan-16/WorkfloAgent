"""
飞书集成模块

实现飞书 Bot 与企业工单 Agent 的对接：
1. 用户在飞书中向 Bot 发消息
2. 服务端接收飞书事件回调
3. 调用 Coordinator 处理工单
4. 将结果通过飞书 API 回复用户

钉钉集成模块

实现钉钉机器人与企业工单 Agent 的对接：
1. 用户在钉钉中向机器人发消息
2. 服务端接收钉钉回调
3. 调用 Coordinator 处理工单
4. 将结果通过钉钉 API 回复用户

使用方式：
    # 启动服务
    uvicorn ticket_agent.main:app --reload --port 8000

    # 设置飞书配置（环境变量）
    export FEISHU_APP_ID=cli_xxxxxxxxxxxx
    export FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxx

    # 配置飞书应用的事件回调地址
    # https://open.feishu.cn/app → 事件与回调 → 添加事件 im.message.receive_v1
    # 回调地址: https://your-domain/api/feishu/event
"""
