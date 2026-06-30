"""
配置数据类 - 使用 dataclass 定义所有配置结构
"""
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class LLMConfig:
    """LLM 模型配置"""
    provider: str = "dashscope"
    model: str = "qwen-plus"
    api_key: str = ""
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float = 0.9
    timeout: int = 60
    extra_models: dict = field(default_factory=dict)


@dataclass
class RAGConfig:
    """RAG 检索增强配置"""
    enabled: bool = False
    embedding_provider: str = "dashscope"
    embedding_model: str = "text-embedding-v3"
    embedding_api_key: str = ""
    embedding_dimension: int = 1024
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_grpc_port: int = 6334
    qdrant_use_grpc: bool = True
    collection_name: str = "agent_docs"
    top_k: int = 5
    score_threshold: float = 0.5


@dataclass
class MemoryConfig:
    """记忆系统配置"""
    backend: str = "local"
    max_history: int = 20
    redis_url: str = "redis://localhost:6379/0"
    redis_prefix: str = "agent:memory:"
    ttl_seconds: int = 86400


@dataclass
class AgentConfig:
    """Agent 配置"""
    use_langgraph: bool = False
    max_tool_rounds: int = 5
    rag_top_k: int = 5
    memory_window_size: int = 10

    # 各 Agent 角色独立模型（可选，为空则使用全局 LLM）
    classifier_model: str = ""    # 如 "gpt-4o-mini"（分类用小模型省钱）
    executor_model: str = ""      # 如 "qwen-plus"（执行用性价比模型）
    evolution_model: str = ""     # 如 "deepseek-chat"（进化用）
    summarizer_model: str = ""    # 如 "qwen-plus"（总结用）


@dataclass
class EmbeddingConfig:
    """Embedding 配置"""
    provider: str = "dashscope"
    model: str = "text-embedding-v2"
    api_key: str = ""


@dataclass
class CrossEncoderConfig:
    """Cross-encoder 重排配置"""
    enabled: bool = False
    mode: str = "llm"
    model_name: str = ""


@dataclass
class MonitoringConfig:
    """监控配置"""
    prometheus_enabled: bool = True
    trace_enabled: bool = True
    trace_file: str = "traces/agent_runs.jsonl"


@dataclass
class StorageConfig:
    """存储配置"""
    database_url: str = "sqlite:///data/ticket_agent.db"
    upload_dir: str = "uploads"
    max_upload_size: int = 20 * 1024 * 1024


@dataclass
class ServerConfig:
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    cors_origins: List[str] = field(default_factory=lambda: ["*"])


@dataclass
class Settings:
    """全局配置（顶层聚合）"""
    app_name: str = "WorkfloAgent"
    version: str = "1.0.0"
    env: str = "development"

    llm: LLMConfig = field(default_factory=LLMConfig)
    rag: RAGConfig = field(default_factory=RAGConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    cross_encoder: CrossEncoderConfig = field(default_factory=CrossEncoderConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    server: ServerConfig = field(default_factory=ServerConfig)

    prompts_dir: str = "prompts"
    log_level: str = "INFO"
