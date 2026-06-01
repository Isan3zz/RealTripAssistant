"""
agent/base.py — Agent 基类

所有 Agent 继承 BaseAgent，声明所需上下文层级。
Supervisor 按需拼接上下文后传入 handle()。
"""

import logging
from abc import ABC
from typing import Any, Optional

from travel_planning_agent.types import AgentRequest, AgentResponse, ContextRequirement

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    所有 Agent 的基类。

    Agent 声明其需要的上下文层级，Supervisor 按需拼接后传入。
    上下文层级（架构总纲 §上下文分层 L0-L6）：
      L0: 系统规则 — 不变的原则和约束
      L1: 用户长期记忆（Phase 3+）
      L2: 当前任务静态约束 — 日期/预算/人数
      L3: 动态工作状态 — 当前阶段/待决策项
      L4: 短期对话历史
      L5: 证据与工具结果
      L6: Agent 专用上下文
    """

    agent_name: str = ""
    context_required: ContextRequirement = ContextRequirement(levels=[0, 2])

    def __init__(self, llm_client):
        self.llm_client = llm_client

    def handle(self, request: AgentRequest) -> AgentResponse:
        """处理 Agent 请求。子类可覆盖此方法实现具体逻辑。"""
        raise NotImplementedError
