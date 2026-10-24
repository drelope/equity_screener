from __future__ import annotations

from scripts import agent_runner as runner


def main(argv: list[str] | None = None, artifacts_dir=None) -> int:
    return runner.main(argv, artifacts_dir=artifacts_dir)


if __name__ == "__main__":
    raise SystemExit(main())
