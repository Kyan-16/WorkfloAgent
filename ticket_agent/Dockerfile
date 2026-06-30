# ============================================================
# 企业工单智能处理 Agent — 生产级 Docker 镜像
# 构建：docker build -t ticket-agent -f ticket_agent/Dockerfile .
# ============================================================
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（可选：MySQL 客户端、健康检查工具）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖（利用 Docker 缓存层）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 创建运行时数据目录
RUN mkdir -p data traces

# 非 root 用户运行（安全加固）
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# 启动服务（带 --proxy-headers 支持反向代理）
CMD ["uvicorn", "ticket_agent.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
