from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..base import Tool
from ..registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[4]


class ReadFileArgs(BaseModel):
    path: str = Field(description="Relative or absolute path within repo")
    max_bytes: int = Field(default=200000, ge=1, le=1000000)


class RepoTools:
    @staticmethod
    def read_file(path: str, max_bytes: int = 200000) -> dict[str, Any]:
        p = Path(path)
        if not p.is_absolute():
            p = ROOT / p
        p = p.resolve()
        if not str(p).startswith(str(ROOT.resolve()) + "/") and p != ROOT.resolve():
            raise ValueError("path outside repo root")
        if not p.is_file():
            raise FileNotFoundError(str(p))
        data = p.read_bytes()
        if len(data) > max_bytes:
            data = data[:max_bytes]
        return {
            "path": str(p),
            "content": data.decode("utf-8", errors="replace"),
            "truncated": len(p.read_bytes()) > max_bytes,
        }


def register_repo_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="files.read",
            description="Read a file from repo (read-only, scoped)",
            func=RepoTools.read_file,
            input_schema=ReadFileArgs,
            risk="read",
            scopes={"*"},
            requires_confirmation=False,
            side_effects=False,
        )
    )
