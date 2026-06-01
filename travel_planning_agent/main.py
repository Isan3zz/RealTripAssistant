"""
main.py — FastAPI 服务入口

启动 RealTrip Assistant API 服务。
Phase 1 提供：
- GET /health — 健康检查
- POST /plan — 创建旅行规划
"""

import logging

import uvicorn

from travel_planning_agent.config import settings


def _setup_logging():
    """配置日志系统。"""
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    """启动 FastAPI 服务。"""
    _setup_logging()

    if not settings.llm_api_key:
        logging.warning("LLM_API_KEY 未设置，将使用 Mock 模式（返回预设行程）")

    print(f"启动 RealTrip Assistant API 服务...")
    print(f"地址: http://{settings.host}:{settings.port}")
    print(f"文档: http://{settings.host}:{settings.port}/docs")
    print()

    uvicorn.run(
        "travel_planning_agent.api.app:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
