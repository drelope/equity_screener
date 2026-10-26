from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    func: Callable[..., Any]
    input_schema: type | None = None
    output_schema: type | None = None
    risk: Literal["read", "write", "heavy"] = "read"
    scopes: set[str] = field(default_factory=set)  # skill names or {"*"}
    requires_confirmation: bool = False
    side_effects: bool = False

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("tool name must be non-empty")
        if not self.scopes:
            raise ValueError(f"tool {self.name!r} must declare at least one scope")
        if self.risk != "read" and not self.side_effects:
            raise ValueError(f"tool {self.name!r}: non-read tools must declare side_effects=True")

    def is_allowed_for_skill(self, skill_name: str) -> bool:
        if "*" in self.scopes:
            return True
        return skill_name in self.scopes
