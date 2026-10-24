from __future__ import annotations

import time
from typing import Any

from .base import Tool


class ToolExecutionError(Exception):
    pass


class ToolExecutor:
    def __init__(self, audit_log=None) -> None:
        self.audit_log = audit_log

    def execute(self, tool: Tool, args: dict[str, Any], *, confirm: bool = False) -> Any:
        if tool.requires_confirmation and not confirm:
            raise ToolExecutionError(f"tool {tool.name} requires confirmation")
        input_model = tool.input_schema
        if input_model is not None:
            try:
                parsed = input_model.model_validate(args)
                args = parsed.model_dump()
            except Exception as exc:
                raise ToolExecutionError(f"invalid args for {tool.name}: {exc}") from exc
        start = time.time()
        try:
            result = tool.func(**args)
        except Exception as exc:
            if self.audit_log is not None:
                self.audit_log.write(f"[tool] {tool.name} failed: {exc}\n")
            raise ToolExecutionError(f"{tool.name} failed: {exc}") from exc
        duration = time.time() - start
        if self.audit_log is not None:
            self.audit_log.write(f"[tool] {tool.name} ok ({duration:.3f}s)\n")
        output_model = tool.output_schema
        if output_model is not None and result is not None:
            try:
                parsed = output_model.model_validate(result)
                return parsed
            except Exception:
                return result
        return result
