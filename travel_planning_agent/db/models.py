"""
db/models.py — SQLAlchemy ORM 模型

对应 Phase 3 规格书 §3 数据库 Schema。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Date, DateTime,
    Text, ForeignKey, Enum as SAEnum, UniqueConstraint,
)
from sqlalchemy import JSON
from sqlalchemy.orm import relationship

from travel_planning_agent.db.session import Base


def _utcnow():
    return datetime.now(timezone.utc)


def _uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(100))
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    preferences = relationship("UserPreference", back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"

    session_id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    title = Column(String(255), default="新建行程")
    status = Column(String(20), default="active")  # active / archived / deleted
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    user = relationship("User", back_populates="sessions")
    trips = relationship("Trip", back_populates="session", cascade="all, delete-orphan")


class Trip(Base):
    __tablename__ = "trips"

    trip_id = Column(String, primary_key=True, default=_uuid)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)

    destination = Column(String(255), nullable=False)
    start_date = Column(Date, nullable=False)
    days = Column("end_date", Integer, nullable=False)  # 天数（DB 列名 end_date，兼容旧数据）
    traveler_count = Column(Integer, default=1)
    elderly_count = Column(Integer, default=0)
    child_count = Column(Integer, default=0)
    budget = Column(Float)
    pace = Column(String(20), default="moderate")  # slow / moderate / fast
    interests = Column(JSON, default=list)

    status = Column(String(20), default="planning")  # planning / completed / failed
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    session = relationship("Session", back_populates="trips")
    plan_versions = relationship("PlanVersion", back_populates="trip", cascade="all, delete-orphan")
    assumptions = relationship("UserAssumption", back_populates="trip", cascade="all, delete-orphan")
    cost_logs = relationship("CostLog", back_populates="trip", cascade="all, delete-orphan")


class PlanVersion(Base):
    __tablename__ = "plan_versions"

    plan_id = Column(String, primary_key=True, default=_uuid)
    trip_id = Column(String, ForeignKey("trips.trip_id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    plan_data = Column(JSON, nullable=False)      # 完整行程 JSON
    verification = Column(JSON)                    # VerificationReport
    diff_previous = Column(JSON)                   # 与上一版本的 Diff
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    trip = relationship("Trip", back_populates="plan_versions")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    pref_id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    pref_key = Column(String(100), nullable=False)
    base_value = Column(JSON, nullable=False)
    conditional_values = Column(JSON)               # [{context, value, confidence}]
    confidence = Column(Float, default=0.5)
    last_updated = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    user = relationship("User", back_populates="preferences")

    __table_args__ = (UniqueConstraint("user_id", "pref_key", name="uq_user_pref"),)


class UserAssumption(Base):
    __tablename__ = "user_assumptions"

    assumption_id = Column(String, primary_key=True, default=_uuid)
    trip_id = Column(String, ForeignKey("trips.trip_id"), nullable=False, index=True)
    level = Column(String(20), nullable=False)       # implicit / explicit
    content = Column(Text, nullable=False)
    status = Column(String(30), default="pending_confirmation")
    impact = Column(String(20), default="high")
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    trip = relationship("Trip", back_populates="assumptions")


class CostLog(Base):
    __tablename__ = "cost_logs"

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    trip_id = Column(String, ForeignKey("trips.trip_id"), nullable=False, index=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=True)
    agent_name = Column(String(50), nullable=False)
    model_name = Column(String(50), nullable=False)
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    estimated_cost = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    trip = relationship("Trip", back_populates="cost_logs")


class SessionContext(Base):
    __tablename__ = "session_contexts"

    session_id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=True, index=True)
    context_data = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class EvidenceRecord(Base):
    __tablename__ = "evidence_records"

    evidence_id = Column(String, primary_key=True)
    trip_id = Column(String, ForeignKey("trips.trip_id"), nullable=True, index=True)
    source = Column(String(100), default="模型知识")
    source_type = Column(String(50), default="model_knowledge")
    confidence = Column(String(20), default="medium")
    claim = Column(Text, default="")
    payload = Column(JSON, default=dict)
    retrieved_at = Column(DateTime(timezone=True), default=_utcnow)


class PlanRunRecord(Base):
    __tablename__ = "plan_runs"

    run_id = Column(String, primary_key=True, default=_uuid)
    trip_id = Column(String, ForeignKey("trips.trip_id"), nullable=True, index=True)
    session_id = Column(String, nullable=True, index=True)
    status = Column(String(30), default="started")
    profile = Column(String(50), default="default")
    input_spec = Column(JSON, default=dict)
    events = Column(JSON, default=list)
    error = Column(Text)
    final_plan_version = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
