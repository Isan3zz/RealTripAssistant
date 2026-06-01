"""
types.py — 所有数据类型定义

Phase 1: 基础类型（Constraints, Segment, PlanState 等）
Phase 2: Agent 通信协议、Pin、Assumption、PlanDiff、VerificationReport、状态扩展

遵循架构总纲附录中的完整数据模型设计。
"""

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional


# ═══════════════════════════════════════════════════════
#  Phase 1 基础枚举
# ═══════════════════════════════════════════════════════

class TripStatus(Enum):
    DRAFT = "draft"
    PLANNING = "planning"
    COMPLETED = "completed"
    FAILED = "failed"


class SegmentType(Enum):
    ACTIVITY = "activity"
    TRANSPORT = "transport"
    MEAL = "meal"
    ACCOMMODATION = "accommodation"


class PlanPhase(Enum):
    """状态机阶段——Phase 1 (5 状态) + Phase 2 新增 (6 状态) = 11 状态"""
    # Phase 1 状态
    INIT = "init"
    INTAKE = "intake"
    PLANNING = "planning"
    RULE_CHECK = "rule_check"
    REVISE = "revise"
    OUTPUT = "output"
    DONE = "done"
    FAILED = "failed"
    # Phase 2 新增状态
    CLARIFYING = "clarifying"
    RESEARCHING = "researching"
    SEMANTIC_CHECK = "semantic_check"
    RISK_CHECKING = "risk_checking"
    AWAITING_USER = "awaiting_user"
    FINALIZING = "finalizing"


class ModuleType(Enum):
    """时间段模块类型"""
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


# 每个模块的时间窗口（左闭右开）
MODULE_WINDOWS: dict[ModuleType, tuple[str, str]] = {
    ModuleType.MORNING:    ("06:00", "12:00"),
    ModuleType.AFTERNOON:  ("12:00", "18:00"),
    ModuleType.EVENING:    ("18:00", "00:00"),
}


class PaceType(Enum):
    SLOW = "slow"
    MODERATE = "moderate"
    FAST = "fast"


# ═══════════════════════════════════════════════════════
#  Phase 2 新增枚举
# ═══════════════════════════════════════════════════════

class EvidenceSource(Enum):
    """证据来源类型"""
    API = "api"
    MODEL_KNOWLEDGE = "model_knowledge"
    USER_PROVIDED = "user_provided"


class CheckType(Enum):
    """校验类型"""
    DETERMINISTIC = "deterministic"
    SEMANTIC = "semantic"
    RISK = "risk"


class AssumptionLevel(Enum):
    IMPLICIT = "implicit"
    EXPLICIT = "explicit"


class AssumptionStatus(Enum):
    PENDING = "pending_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REPLACED = "replaced"


class DegradeLevel(Enum):
    """分级降级策略等级"""
    L1_RETRY = "retry"
    L2_DEGRADE = "degrade"
    L3_ASK_USER = "ask_user"
    L4_FAIL = "fail"


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Task:
    """
    规划任务，每个任务对应一个规划子步骤。
    任务链会渲染到 context_summary 的 L3，让 LLM 知道当前进度和边界。
    """
    task_id: str
    desc: str
    status: TaskStatus = TaskStatus.PENDING
    acceptance: str = ""
    depends_on: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════
#  Phase 1 基础数据类（不变）
# ═══════════════════════════════════════════════════════

@dataclass
class Traveler:
    age_group: str
    note: str = ""


@dataclass(init=False)
class Constraints:
    destination: str
    start_date: date
    days: int
    travelers: list[Traveler]
    budget: float
    origin: str = ""
    pace: str = "moderate"
    preferences_detail: str = ""  # 自由文本偏好（如"10点左右的高铁、一等座、靠窗"）
    transport_mode: str = ""  # "高铁" / "动车" / "飞机" / "自驾" / ""（未指定）
    interests: list[str] = field(default_factory=list)

    def __init__(
        self,
        destination: str,
        start_date: date,
        days: Optional[int] = None,
        travelers: Optional[list[Traveler]] = None,
        budget: float = 0.0,
        origin: str = "",
        pace: str = "moderate",
        preferences_detail: str = "",
        transport_mode: str = "",
        interests: Optional[list[str]] = None,
        end_date: Optional[int] = None,
    ):
        # `end_date` was used by early specs/tests to mean trip length.
        # Keep accepting it while normalizing runtime code on `days`.
        self.destination = destination
        self.start_date = start_date
        self.days = days if days is not None else (end_date if end_date is not None else 1)
        self.travelers = travelers or [Traveler(age_group="adult")]
        self.budget = float(budget or 0.0)
        self.origin = origin or ""
        self.pace = pace or "moderate"
        self.preferences_detail = preferences_detail or ""
        self.transport_mode = transport_mode or ""
        self.interests = interests or []

    @property
    def end_date(self) -> int:
        """Backward-compatible alias used by early tests/specs."""
        return self.days


@dataclass
class TripSpec:
    """Product-facing normalized trip request."""
    origin: str
    destination: str
    start_date: date
    days: int
    travelers: list[Traveler]
    budget: float
    pace: str = "moderate"
    transport_preference: str = ""
    lodging_preference: str = ""
    food_preference: str = ""
    must_have: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    accessibility: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_constraints(cls, constraints: "Constraints") -> "TripSpec":
        return cls(
            origin=constraints.origin,
            destination=constraints.destination,
            start_date=constraints.start_date,
            days=constraints.days,
            travelers=constraints.travelers,
            budget=constraints.budget,
            pace=constraints.pace,
            transport_preference=constraints.transport_mode,
            must_have=list(constraints.interests),
        )

    def to_constraints(self) -> "Constraints":
        preferences = []
        if self.lodging_preference:
            preferences.append(f"住宿偏好：{self.lodging_preference}")
        if self.food_preference:
            preferences.append(f"餐饮偏好：{self.food_preference}")
        if self.must_have:
            preferences.append("必须包含：" + "、".join(self.must_have))
        if self.avoid:
            preferences.append("避免：" + "、".join(self.avoid))
        return Constraints(
            origin=self.origin,
            destination=self.destination,
            start_date=self.start_date,
            days=self.days,
            travelers=self.travelers,
            budget=self.budget,
            pace=self.pace,
            transport_mode=self.transport_preference,
            preferences_detail="；".join(preferences),
            interests=list(self.must_have),
        )


@dataclass
class Cost:
    amount: float
    currency: str = "CNY"


@dataclass
class Location:
    name: str
    city: str
    lat: Optional[float] = None
    lng: Optional[float] = None


@dataclass
class Evidence:
    evidence_id: str
    source: str = "模型知识"
    url: Optional[str] = None
    retrieved_at: str = ""
    url_reachable: Optional[bool] = None
    url_checked_at: Optional[str] = None
    claim: str = ""
    # Phase 2 新增
    confidence: str = "high"        # "high" / "medium" / "low"
    source_type: str = "model_knowledge"  # "api" / "model_knowledge" / "user_provided"


@dataclass
class Segment:
    segment_id: str
    type: SegmentType = SegmentType.ACTIVITY
    title: str = ""
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[Location] = None
    estimated_cost: Optional[Cost] = None
    tags: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    note: str = ""
    module: str = ""  # "morning" / "afternoon" / "evening"，模块化规划用


@dataclass
class ItineraryDay:
    day_id: str
    day_number: int
    theme: str = ""
    day_note: str = ""  # 每日备注（天气/出行建议等，Planner 生成）
    segments: list[Segment] = field(default_factory=list)


@dataclass
class RuleResult:
    rule_id: str
    name: str
    result: str              # "PASS" / "FAIL"
    severity: str = "high"
    detail: str = ""
    affected_segments: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════
#  Phase 2 Agent 通信协议
# ═══════════════════════════════════════════════════════

@dataclass
class ContextRequirement:
    """Agent 声明所需上下文层级"""
    levels: list[int]


@dataclass
class AgentRequest:
    """所有 Agent 的标准输入格式"""
    request_id: str
    agent: str
    context: dict
    params: dict
    context_summary: str = ""
    timeout_ms: int = 30000


@dataclass
class AgentResponse:
    """所有 Agent 的标准输出格式"""
    request_id: str
    status: str              # "success" / "failed" / "degraded"
    data: dict
    error: Optional[str] = None
    tokens_used: int = 0
    source_note: str = ""    # "api_result" / "model_knowledge" / "user_input"


@dataclass
class PlanningContext:
    """Layered L0-L6 context passed to agents."""
    layers: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.layers)


@dataclass
class ToolResult:
    """Standard result envelope for all product-grade tools."""
    status: str
    data: Any = None
    evidence: list[dict] = field(default_factory=list)
    source_type: str = "model_knowledge"
    confidence: str = "medium"
    retrieved_at: str = ""
    error: Optional[str] = None
    cache_hit: bool = False


@dataclass
class ResearchTask:
    """A concrete, executable research task."""
    task_type: str
    tool_name: str
    args: dict[str, Any]
    reason: str = ""
    priority: int = 5
    reuse_key: str = ""


@dataclass
class ResearchPlan:
    """Structured plan for what the researcher should verify."""
    tasks: list[ResearchTask] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"tasks": [asdict(task) for task in self.tasks]}


@dataclass
class RouteBrief:
    """Compact, structured route duration for verification."""
    mode: str
    duration_minutes: Optional[int] = None
    distance_meters: Optional[int] = None
    walking_distance_meters: Optional[int] = None
    transit_lines: list[str] = field(default_factory=list)
    origin: str = ""
    destination: str = ""
    summary: str = ""


@dataclass
class PlanRun:
    """A single persisted planning run."""
    run_id: str
    status: str
    trip_id: Optional[str] = None
    session_id: Optional[str] = None
    profile: str = "default"
    input_spec: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    error: Optional[str] = None
    final_plan_version: Optional[int] = None


# ═══════════════════════════════════════════════════════
#  Phase 2 Pin / Assumption / PlanDiff 模型
# ═══════════════════════════════════════════════════════

@dataclass
class Pin:
    pin_id: str
    target_type: str           # "segment" / "constraint"
    target_id: str             # segment_id 或 "budget" / "start_date"
    scope: str                 # "entire_trip" / "specific_day"
    day_number: Optional[int] = None
    mutable: bool = False
    reason: str = "user_selected"
    created_at: str = ""


@dataclass
class Assumption:
    assumption_id: str
    level: AssumptionLevel
    content: str
    status: AssumptionStatus = AssumptionStatus.PENDING
    impact: str = "high"          # "high" / "medium" / "low"
    affected_rules: list[str] = field(default_factory=list)


@dataclass
class ChangeItem:
    segment_id: str
    change_type: str             # "modified" / "added" / "removed" / "unchanged"
    field_changes: dict          # {"title": {"old": "A", "new": "B"}}
    reason: str = ""
    impact: dict = field(default_factory=dict)  # {"budget": -120, "walking_km": -1.2}


@dataclass
class PlanDiff:
    diff_id: str
    old_plan_version: int
    new_plan_version: int
    changes: list[ChangeItem]
    pin_integrity: dict          # {"pin_001": {"preserved": true}}


# ═══════════════════════════════════════════════════════
#  Phase 2 校验结果
# ═══════════════════════════════════════════════════════

@dataclass
class SemanticCheckResult:
    check_id: str
    result: str                  # "PASS" / "FAIL" / "WARN"
    detail: str
    affected_days: list[int] = field(default_factory=list)


@dataclass
class RiskCheck:
    risk_id: str
    risk_type: str               # "weather" / "crowd" / "timing"
    severity: str                # "high" / "medium" / "low"
    probability: str             # "high" / "medium" / "low"
    detail: str
    mitigation: str = ""


@dataclass
class VerificationReport:
    """Unified product verification report."""
    verification_id: str
    overall_pass: bool
    rule_checks: list[RuleResult]
    semantic_checks: list[SemanticCheckResult]
    risk_checks: list[RiskCheck]
    correction_requests: list[dict] = field(default_factory=list)
    module_checks: list[dict] = field(default_factory=list)
    whole_plan_checks: list[dict] = field(default_factory=list)
    blocking_failures: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)


# ═══════════════════════════════════════════════════════
#  Phase 2 PlanState（在 Phase 1 基础上扩展）
# ═══════════════════════════════════════════════════════

@dataclass
class PlanState:
    """
    规划状态——整个系统的核心状态数据结构。
    Phase 1 字段 + Phase 2 扩展。
    """
    trip_id: str
    status: TripStatus = TripStatus.DRAFT
    constraints: Optional[Constraints] = None
    days: list[ItineraryDay] = field(default_factory=list)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    validation: Optional[VerificationReport] = None  # Phase 2 升级为 VerificationReport
    revision_count: int = 0
    max_revisions: int = 3
    phase: PlanPhase = PlanPhase.INIT
    error: Optional[str] = None

    # Phase 2 新增字段
    pins: list[Pin] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    plan_version: int = 1
    diff_history: list[PlanDiff] = field(default_factory=list)
    pending_questions: list[str] = field(default_factory=list)  # 待用户确认的问题
    degrade_level: Optional[str] = None  # 当前降级等级
    message_history: list[dict] = field(default_factory=list)  # L4 对话历史 [{"role","content","timestamp"}]
    tasks: list[Task] = field(default_factory=list)  # 任务链（L3，对 LLM 可见）

    # Phase 3 模块化规划队列
    planning_queue: list[dict] = field(default_factory=list)  # [{"day":1,"module":"morning","status":"pending"}, ...]
    module_context: dict[str, dict] = field(default_factory=dict)  # {"1_morning": {"end_time":"12:00", ...}}
    current_module: Optional[str] = None  # 当前正在规划的模块 key，如 "1_morning"
    current_module_retry_count: int = 0  # 当前模块本地重试次数
    current_module_max_retries: int = 2  # 每个模块最大重试次数
