from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..base import Tool
from ..registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[4]

SECRET_NAMES = {".env", "ObbCredentials.json"}
SECRET_PREFIXES = (".env.",)


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
        if not p.is_relative_to(ROOT.resolve()):
            raise ValueError("path outside repo root")
        if p.name in SECRET_NAMES or p.name.startswith(SECRET_PREFIXES):
            raise ValueError(f"refusing to read secret file {p.name!r}")
        if not p.is_file():
            raise FileNotFoundError(str(p))
        data = p.read_bytes()
        truncated = len(data) > max_bytes
        if truncated:
            data = data[:max_bytes]
        return {
            "path": str(p),
            "content": data.decode("utf-8", errors="replace"),
            "truncated": truncated,
        }


def register_repo_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="files.read",
            description="Read a tracked repository file (read-only, secret-safe)",
            func=RepoTools.read_file,
            input_schema=ReadFileArgs,
            risk="read",
            scopes={"*"},
            requires_confirmation=False,
            side_effects=False,
        )
    )
