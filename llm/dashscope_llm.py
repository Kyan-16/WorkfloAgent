"""
DashScope LLM 实现

支持阿里云通义千问系列模型：
- qwen-turbo / qwen-plus / qwen-max / qwen3-max
- 以及所有 DashScope 兼容模型

注意：Generation.call() 是同步调用，通过 asyncio.to_thread 抛到线程池执行，
避免阻塞事件循环。
"""
import asyncio
import json
import logging
from typing import Optional, AsyncIterator

from llm.base import LLMBase, LLMResponse, ChatMessage
from utils.token_bucket import consume_llm_token

logger = logging.getLogger(__name__)


class DashScopeLLM(LLMBase):
    """
    DashScope LLM 实现

    使用阿里云 DashScope SDK 调用通义千问系列模型。

    配置示例 (settings.yaml):
        llm:
          provider: "dashscope"
          model: "qwen-max"
          api_key: "sk-xxxx"
    """

    async def generate(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        """非流式调用 DashScope API（在线程池执行，不阻塞事件循环）"""
        temp, tokens = self._get_params(temperature, max_tokens)

        try:
            from dashscope import Generation

            # 构建请求参数
            formatted_messages = [m.to_dict() for m in messages]
            call_kwargs = {
                "model": self.model,
                "messages": formatted_messages,
                "result_format": "message",
                "temperature": temp,
                "max_tokens": tokens,
                "top_p": self.top_p,
                "api_key": self.api_key,
            }

            # 添加工具定义（Function Calling）
            if tools:
                call_kwargs["tools"] = tools

            # 令牌桶限流
            if not consume_llm_token(tokens=1, timeout=30.0):
                raise TimeoutError("LLM API 调用被限流（等待超时）")

            # 在线程池中执行同步 API 调用
            response = await asyncio.to_thread(Generation.call, **call_kwargs)

            # 兼容不同版本的状态码获取方式
            status_code = getattr(response, "status_code", None) or getattr(
                response, "status", None
            )

            if status_code == 200:
                choice = response.output.choices[0]
                message = choice.message
                content = message.content or ""
                finish_reason = getattr(choice, "finish_reason", "stop")

                # 提取 tool_calls
                tool_calls = []
                raw_tool_calls = getattr(message, "tool_calls", None)
                if raw_tool_calls:
                    for tc in raw_tool_calls:
                        tool_calls.append({
                            "id": getattr(tc, "id", ""),
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        })
                    finish_reason = "tool_calls"

                # 提取 token 使用量
                usage = getattr(response, "usage", None)
                prompt_tokens = getattr(usage, "input_tokens", 0) if usage else 0
                completion_tokens = getattr(usage, "output_tokens", 0) if usage else 0

                return LLMResponse(
                    content=content,
                    tool_calls=tool_calls,
                    model=self.model,
                    finish_reason=finish_reason,
                    tokens_used=prompt_tokens + completion_tokens,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            else:
                error_msg = getattr(response, "message", str(response))
                logger.error(f"DashScope API 调用失败: {error_msg}")
                raise RuntimeError(f"DashScope API 调用失败: {error_msg}")

        except ImportError:
            logger.error("dashscope 未安装，请运行: pip install dashscope")
            raise
        except Exception as e:
            logger.error(f"DashScope 调用异常: {e}", exc_info=True)
            raise

    async def stream(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[str]:
        """流式调用 DashScope API（在线程池收集后异步 yield）"""
        temp, tokens = self._get_params(temperature, max_tokens)

        try:
            from dashscope import Generation

            formatted_messages = [m.to_dict() for m in messages]
            call_kwargs = {
                "model": self.model,
                "messages": formatted_messages,
                "result_format": "message",
                "temperature": temp,
                "max_tokens": tokens,
                "top_p": self.top_p,
                "api_key": self.api_key,
                "stream": True,
            }
            if tools:
                call_kwargs["tools"] = tools

            # 在线程池中收集所有流式块，避免阻塞事件循环
            def _collect_chunks():
                chunks = []
                response = Generation.call(**call_kwargs)
                for chunk in response:
                    chunk_status = getattr(chunk, "status_code", None) or getattr(
                        chunk, "status", None
                    )
                    if chunk_status == 200 and chunk.output and chunk.output.choices:
                        delta = chunk.output.choices[0].message.content
                        if delta:
                            chunks.append(delta)
                return chunks

            chunks = await asyncio.to_thread(_collect_chunks)
            for chunk in chunks:
                yield chunk

        except ImportError:
            raise RuntimeError("dashscope SDK 未安装")
        except Exception as e:
            logger.error(f"DashScope 流式调用异常: {e}", exc_info=True)
            raise
