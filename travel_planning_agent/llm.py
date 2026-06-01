"""
llm.py — LLM 客户端抽象层

定义 LLM 调用接口，提供 OpenAI 协议兼容实现。
支持任意 base_url + api_key + model_name 组合，可对接 OpenAI、Claude、通义千问等
几乎所有主流 LLM API（通过 one-api / litellm 等网关）。

Phase 1 使用单模型，Phase 4 将引入 Model Router。
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from travel_planning_agent.config import settings
from travel_planning_agent.core.tool_calling_service import ToolCallingService

logger = logging.getLogger(__name__)


# ── 返回值类型 ────────────────────────────────────────

@dataclass
class LLMResult:
    """LLM 调用结果"""
    success: bool
    data: Optional[dict] = None
    text: str = ""
    error: Optional[str] = None
    tokens_used: int = 0
    tool_calls_log: list[dict] = None  # 工具调用摘要 [{"tool":"..","input":"..","result":".."}]


# ── LLM 客户端接口 ────────────────────────────────────

class LLMClient(Protocol):
    """LLM 客户端接口协议"""
    def generate(self, system_prompt: str, user_message: str, tools: list[dict] = None) -> LLMResult:
        """生成初始行程"""
        ...

    def generate_with_context(self, system_prompt: str, messages: list[dict], tools: list[dict] = None) -> LLMResult:
        """带上下文生成（用于修订场景）"""
        ...


# ── OpenAI 协议实现 ──────────────────────────────────

class OpenAICompatibleClient:
    """
    基于 OpenAI 协议兼容的 LLM 客户端。

    支持任意兼容 OpenAI Chat Completions API 的服务：
    - OpenAI:          base_url="https://api.openai.com/v1"
    - Anthropic(openai 协议): base_url= 需走第三方网关
    - 通义千问:        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    - one-api:         base_url="http://localhost:3000/v1"
    - liteLLM:         base_url="http://localhost:8000/v1"
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model
        self._client: Optional[Any] = None

    def _get_client(self):
        """延迟初始化 OpenAI 客户端。"""
        if self._client is None:
            if not self.api_key:
                raise ValueError(
                    "LLM_API_KEY 未设置。请在 .env 文件中配置。"
                )
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    base_url=self.base_url,
                    api_key=self.api_key,
                )
            except ImportError:
                raise ImportError("缺少 openai 包，请执行: pip install openai")
        return self._client

    def generate(self, system_prompt: str, user_message: str, tools: list[dict] = None) -> LLMResult:
        """
        调用 LLM 生成行程。

        处理 tool calling 循环：
        1. 发送系统提示 + 用户消息
        2. 如果 LLM 调用工具 → 执行工具 → 返回结果
        3. 重复直到 LLM 返回文本
        4. 解析 JSON 文本

        tools: 传入 TOOLS_DEFINITION 则启用工具调用，否则 LLM 不调工具
        """
        try:
            client = self._get_client()
            messages: list[dict] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]
            result = ToolCallingService().run(
                client=client,
                model=self.model,
                messages=messages,
                tools=tools,
                extract_json=self._extract_json,
                summarize_tool_input=_summarize_tool_input,
                compute_max_tokens=_compute_max_tokens,
                max_rounds=25,
            )
            return LLMResult(**result)

        except Exception as e:
            logger.error("LLM 调用失败: %s", str(e))
            return LLMResult(
                success=False,
                error=f"LLM 调用异常: {str(e)}",
            )

    def generate_with_context(self, system_prompt: str, messages: list[dict], tools: list[dict] = None) -> LLMResult:
        """
        带完整对话上下文调用 LLM（用于修订场景）。

        messages 格式：[{"role": "user"/"assistant", "content": "..."}, ...]
        自动在最前面插入 system 消息。

        tools: 传入 TOOLS_DEFINITION 则启用工具调用，否则不调工具
        """
        try:
            client = self._get_client()

            full_messages = [{"role": "system", "content": system_prompt}] + messages

            current_max_tokens = _compute_max_tokens(full_messages)

            response = client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                tools=tools if tools else None,
                max_tokens=current_max_tokens,
            )

            choice = response.choices[0]
            message = choice.message
            tokens_used = 0
            if response.usage:
                tokens_used = (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)

            full_text = message.content or ""
            parsed = self._extract_json(full_text)
            if parsed:
                return LLMResult(
                    success=True,
                    data=parsed,
                    text=full_text,
                    tokens_used=tokens_used,
                )

            return LLMResult(
                success=True,
                text=full_text,
                tokens_used=tokens_used,
            )

        except Exception as e:
            logger.error("LLM revise 调用失败: %s", str(e))
            return LLMResult(
                success=False,
                error=f"LLM 调用异常: {str(e)}",
            )

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """从 LLM 返回文本中提取 JSON 对象。"""
        if not text:
            return None
        text = text.strip()
        if text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        if "```json" in text:
            try:
                json_str = text.split("```json")[1].split("```")[0].strip()
                return json.loads(json_str)
            except (json.JSONDecodeError, IndexError):
                pass
        if "```" in text:
            try:
                json_str = text.split("```")[1].split("```")[0].strip()
                return json.loads(json_str)
            except (json.JSONDecodeError, IndexError):
                pass
        return None


# ── Mock 客户端（用于测试） ───────────────────────────

class MockLLMClient:
    """Mock LLM 客户端，返回预设行程数据。"""

    def __init__(self, mock_data: Optional[dict] = None):
        self.mock_data = mock_data or self._default_mock_data()

    def generate(self, system_prompt: str, user_message: str, tools: list[dict] = None) -> LLMResult:
        return LLMResult(
            success=True,
            data=self.mock_data,
            text=json.dumps(self.mock_data, ensure_ascii=False),
            tokens_used=100,
        )

    def generate_with_context(self, system_prompt: str, messages: list[dict], tools: list[dict] = None) -> LLMResult:
        return self.generate(system_prompt, "")

    @staticmethod
    def _default_mock_data() -> dict:
        return {
            "days": [
                {
                    "day_number": 1,
                    "theme": "抵达与适应",
                    "segments": [
                        {
                            "type": "transport",
                            "title": "抵达杭州",
                            "start_time": "08:00",
                            "end_time": "10:00",
                            "location": {"name": "杭州东站", "city": "杭州"},
                            "estimated_cost": {"amount": 500, "currency": "CNY"},
                            "tags": ["transport"],
                            "evidence": [{"source": "模型知识", "claim": "高铁/飞机可达"}],
                        },
                        {
                            "type": "meal",
                            "title": "午餐",
                            "start_time": "12:00",
                            "end_time": "13:00",
                            "location": {"name": "酒店附近餐厅", "city": "杭州"},
                            "estimated_cost": {"amount": 200, "currency": "CNY"},
                            "tags": ["food"],
                            "evidence": [{"source": "模型知识", "claim": "当地餐饮"}],
                        },
                        {
                            "type": "activity",
                            "title": "西湖漫步",
                            "start_time": "14:00",
                            "end_time": "17:00",
                            "location": {"name": "西湖", "city": "杭州"},
                            "estimated_cost": {"amount": 0, "currency": "CNY"},
                            "tags": ["natural", "senior_friendly"],
                            "evidence": [{"source": "模型知识", "claim": "西湖免费开放"}],
                        },
                    ],
                },
                {
                    "day_number": 2,
                    "theme": "文化探索",
                    "segments": [
                        {
                            "type": "activity",
                            "title": "灵隐寺",
                            "start_time": "09:00",
                            "end_time": "11:00",
                            "location": {"name": "灵隐寺", "city": "杭州"},
                            "estimated_cost": {"amount": 75, "currency": "CNY"},
                            "tags": ["cultural"],
                            "evidence": [{"source": "模型知识", "claim": "开放时间 07:00-18:00"}],
                        },
                        {
                            "type": "meal",
                            "title": "午餐",
                            "start_time": "11:30",
                            "end_time": "12:30",
                            "location": {"name": "寺庙附近", "city": "杭州"},
                            "estimated_cost": {"amount": 150, "currency": "CNY"},
                            "tags": ["food"],
                            "evidence": [{"source": "模型知识", "claim": "当地餐饮"}],
                        },
                        {
                            "type": "activity",
                            "title": "浙江省博物馆",
                            "start_time": "14:00",
                            "end_time": "16:00",
                            "location": {"name": "浙江省博物馆", "city": "杭州"},
                            "estimated_cost": {"amount": 0, "currency": "CNY"},
                            "tags": ["cultural", "indoor"],
                            "evidence": [{"source": "模型知识", "claim": "免费开放，周一闭馆"}],
                        },
                    ],
                },
            ],
        }


def _summarize_tool_input(tool_name: str, tool_input: dict) -> str:
    """工具参数 → 一行摘要。"""
    if tool_name == "search_poi":
        return f"{tool_input.get('destination','')}/{tool_input.get('category','')}"
    if tool_name == "get_weather_forecast":
        return f"{tool_input.get('city','')} {tool_input.get('date','')}"
    return json.dumps(tool_input, ensure_ascii=False)[:80]


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中英文混合按字符/2）。"""
    if not text:
        return 0
    return max(1, len(text) // 2)


def _compute_max_tokens(messages: list[dict]) -> int:
    """
    根据输入内容动态计算 max_tokens。
    保底 4096，输入越大输出预算越多，上限 16384。
    """
    total_chars = 0
    for m in messages:
        c = m.get("content", "") or ""
        if isinstance(c, str):
            total_chars += len(c)

    input_tokens = max(1, total_chars // 2)
    budget = max(8192, min(input_tokens, 16384))
    return budget


def create_llm_client(mock: bool = False) -> LLMClient:
    """创建 LLM 客户端（工厂方法）。"""
    if mock:
        return MockLLMClient()

    if not settings.llm_api_key:
        logger.warning("LLM_API_KEY 未设置，回退到 Mock 模式")
        return MockLLMClient()

    return OpenAICompatibleClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )
