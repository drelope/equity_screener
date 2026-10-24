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

    def is_allowed_for_skill(self, skill_name: str) -> bool:
        if not self.scopes:
            return False
        if "*" in self.scopes:
            return True
        return skill_name in self.scopes
