"""Registered travel tools public API — lazy resolution to avoid circular imports."""

import sys

__all__ = [
    "TOOLS_DEFINITION",
    "EXTRACTION_TOOLS",
    "RESEARCHER_TOOLS",
    "PLANNER_TOOLS",
    "execute_tool",
    "register_all_tools",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = sys.modules.get(__name__)
    if mod is None:
        raise AttributeError(f"module {__name__!r} not in sys.modules")
    from travel_planning_agent.tool_runtime import (  # noqa: F811
        EXTRACTION_TOOLS,
        PLANNER_TOOLS,
        RESEARCHER_TOOLS,
        TOOLS_DEFINITION,
        execute_tool,
        register_all_tools,
    )
    # 将导入的名称绑定到模块命名空间，后续访问不再触发 __getattr__
    for attr_name in __all__:
        obj = locals().get(attr_name)
        if obj is not None:
            setattr(mod, attr_name, obj)
    return getattr(mod, name)
