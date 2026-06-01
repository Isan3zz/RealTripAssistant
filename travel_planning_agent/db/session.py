"""
db/session.py — SQLAlchemy 引擎与会话管理

支持 SQLite（开发）和 PostgreSQL（生产），通过 config.db_url 切换。
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from travel_planning_agent.config import settings

db_url = settings.effective_db_url()

# SQLite 需要 connect_args 来支持多线程
connect_args = {}
if db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(db_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_db():
    """FastAPI 依赖注入：获取数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """创建所有表（开发环境用，生产用 alembic migrate）。"""
    import travel_planning_agent.db.models  # noqa: F401 - ensure model metadata is registered
    Base.metadata.create_all(bind=engine)
