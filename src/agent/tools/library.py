from __future__ import annotations

from .base import Tool
from .builtins.repo import register_repo_tools
from .registry import ToolRegistry


class ToolResolutionError(ValueError):
    """A skill declared a tool that does not exist or is out of scope."""


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_repo_tools(registry)
    return registry


def resolve_tools(
    registry: ToolRegistry, skill_name: str, declared: list[str] | None
) -> list[Tool]:
    """Resolve a skill's declared tools, denying by default.

    A skill that declares no tools receives none. Every declared name must be
    registered and allowed for the skill's scope; otherwise resolution fails so
    a typo cannot silently grant nothing (or everything).
    """
    declared = list(declared or [])
    if not declared:
        return []

    unknown = [name for name in declared if registry.get(name) is None]
    if unknown:
        raise ToolResolutionError(f"{skill_name}: unknown tool(s) {', '.join(sorted(unknown))}")

    resolved = registry.tools_for_skill(skill_name, declared)
    resolved_names = {tool.name for tool in resolved}
    denied = [name for name in declared if name not in resolved_names]
    if denied:
        raise ToolResolutionError(
            f"{skill_name}: tool(s) not allowed by scope: {', '.join(sorted(denied))}"
        )
    return resolved
