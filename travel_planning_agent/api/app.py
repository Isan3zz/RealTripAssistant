"""
api/app.py — FastAPI 应用（Phase 3）

接口分组：
  /api/sessions/*     — 会话管理
  /api/trips/*        — 行程 CRUD
  /api/trips/*/plan   — 规划触发
  /api/trips/*/plans  — 方案管理
  /api/trips/*/export — 导出
  /api/users/*/preferences — 偏好管理
  /api/pins           — 锁定操作
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from travel_planning_agent.config import settings
from travel_planning_agent.api.sessions import router as sessions_router
from travel_planning_agent.api.trips import router as trips_router
from travel_planning_agent.api.plans import router as plans_router
from travel_planning_agent.api.export import router as export_router
from travel_planning_agent.api.preferences import router as preferences_router
from travel_planning_agent.api.chat import router as chat_router
from travel_planning_agent.api.personal import router as personal_router

logger = logging.getLogger(__name__)


# ── 请求/响应模型 ──

class HealthResponse(BaseModel):
    status: str
    version: str
    llm_configured: bool
    db_configured: bool


class PinRequest(BaseModel):
    segment_id: str


class AssumptionRequest(BaseModel):
    assumption_id: str
    confirmed: bool


# ── 生命周期 ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("RealTrip Assistant API v0.3.0 (Phase 3) 启动")
    logger.info("LLM 配置: %s", "已配置" if settings.llm_api_key else "未配置")
    # 尝试初始化数据库（开发环境自动建表，生产用 alembic）
    try:
        from travel_planning_agent.db.session import init_db
        init_db()
        logger.info("数据库表已就绪")
    except Exception as e:
        logger.warning("数据库初始化失败（请检查 PostgreSQL 连接）: %s", e)
    yield
    logger.info("RealTrip Assistant API 关闭")


# ── 应用实例 ──

app = FastAPI(
    title="RealTrip Assistant API",
    description="非交易型智能旅行规划助手 — Phase 3",
    version="0.3.0",
    lifespan=lifespan,
)


# ── 挂载路由 ──

app.include_router(sessions_router)
app.include_router(trips_router)
app.include_router(plans_router)
app.include_router(export_router)
app.include_router(preferences_router)
app.include_router(chat_router)
app.include_router(personal_router)


# ── 内置路由 ──

@app.get("/health", response_model=HealthResponse)
async def health_check():
    db_ok = False
    try:
        from travel_planning_agent.db.session import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        pass

    return HealthResponse(
        status="ok",
        version="0.3.0",
        llm_configured=bool(settings.llm_api_key),
        db_configured=db_ok,
    )


@app.get("/api/pins/{trip_id}")
async def get_pins(trip_id: str):
    """获取行程的锁定项（从文件系统读取）。"""
    from travel_planning_agent.storage import load_state
    state = load_state(trip_id)
    if not state:
        raise HTTPException(404, f"行程 {trip_id} 不存在")
    return {"pins": [{"pin_id": p.pin_id, "target_id": p.target_id, "target_type": p.target_type, "scope": p.scope} for p in state.pins]}


@app.post("/api/pins/{trip_id}")
async def add_pin(trip_id: str, req: PinRequest):
    """锁定行程中的某个 segment。"""
    from travel_planning_agent.storage import load_state, save_state
    from travel_planning_agent.models.pin import create_pin
    state = load_state(trip_id)
    if not state:
        raise HTTPException(404, f"行程 {trip_id} 不存在")
    pin = create_pin(target_type="segment", target_id=req.segment_id)
    state.pins.append(pin)
    save_state(state)
    return {"status": "ok", "pin_id": pin.pin_id}


@app.post("/api/assumptions/{trip_id}")
async def confirm_assumption(trip_id: str, req: AssumptionRequest):
    """确认或拒绝假设。"""
    from travel_planning_agent.storage import load_state, save_state
    from travel_planning_agent.types import AssumptionStatus
    state = load_state(trip_id)
    if not state:
        raise HTTPException(404, f"行程 {trip_id} 不存在")
    for a in state.assumptions:
        if a.assumption_id == req.assumption_id:
            a.status = AssumptionStatus.CONFIRMED if req.confirmed else AssumptionStatus.REJECTED
            save_state(state)
            return {"status": "ok"}
    raise HTTPException(404, f"假设 {req.assumption_id} 不存在")
