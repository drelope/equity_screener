from __future__ import annotations

from .base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_all(self) -> list[Tool]:
        return list(self._tools.values())

    def tools_for_skill(self, skill_name: str, allowed: list[str] | None = None) -> list[Tool]:
        allowed_set = set(allowed or [])
        out: list[Tool] = []
        for tool in self._tools.values():
            if allowed_set and tool.name not in allowed_set:
                continue
            if not tool.is_allowed_for_skill(skill_name):
                continue
            out.append(tool)
        return out
