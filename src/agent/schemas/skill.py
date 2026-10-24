from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MODULE = re.compile(r"^scripts\.[a-z][a-z0-9_]*$")


class SkillFrontmatter(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str
    description: str = Field(min_length=30)
    version: int = Field(ge=1)
    risk: Literal["read", "write", "heavy"]
    owner: str | None = None
    entrypoint: Literal["none", "fixed", "list"] | None = None
    tools: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not SKILL_NAME.match(v):
            raise ValueError("name must be kebab-case")
        return v

    @field_validator("tools")
    @classmethod
    def _validate_tools(cls, v: list[str]) -> list[str]:
        out = []
        for t in v:
            if not isinstance(t, str) or not t.strip():
                raise ValueError("tools must be non-empty strings")
            out.append(t.strip())
        return out


class RunPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    run_id: str
    skill: str
    description: str
    risk: Literal["read", "write", "heavy"]
    entrypoint_mode: str | None = None
    owner: str | None = None
    skill_file: str
    entrypoints: list[list[str]]
    verifiers: list[list[str]]


class PreflightCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str
    ok: bool
    returncode: int | None = None
    dirty: bool | None = None
    stdout: str | None = None
    stderr: str | None = None
    present: bool | None = None
    error: str | None = None


class PreflightReport(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    skill: str
    risk: Literal["read", "write", "heavy"]
    checks: list[PreflightCheck]


class CommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    argv: list[str]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    passed: bool


class VerificationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    run_id: str
    skill: str
    passed: bool
    entrypoint: list[CommandResult]
    verifier: list[CommandResult]
