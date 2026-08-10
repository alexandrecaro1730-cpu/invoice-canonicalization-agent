"""Business objective: prevent direct dependency drift between package metadata and reproducible runtime/CI lock files.

Technical description: parses exact requirement pins, validates duplicate-free locks, and proves every declared runtime/dev/fixture/build-system dependency is represented by a compatible exact pin.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)$")


def _pins(path: Path) -> dict[str, Version]:
    pins: dict[str, Version] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN_RE.fullmatch(line)
        if not match:
            raise ValueError(f"{path.name} contains a non-exact requirement: {line}")
        name = canonicalize_name(match.group(1))
        if name in pins:
            raise ValueError(f"{path.name} contains duplicate pin: {name}")
        pins[name] = Version(match.group(2))
    return pins


def _validate_requirements(requirements: list[str], pins: dict[str, Version], label: str) -> list[str]:
    failures: list[str] = []
    for raw in requirements:
        requirement = Requirement(raw)
        name = canonicalize_name(requirement.name)
        version = pins.get(name)
        if version is None:
            failures.append(f"{label}: missing exact pin for {requirement.name}")
        elif requirement.specifier and version not in requirement.specifier:
            failures.append(f"{label}: {requirement.name}=={version} violates {requirement.specifier}")
    return failures


def main() -> int:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    build_system = pyproject.get("build-system", {})
    runtime = _pins(ROOT / "requirements-runtime.lock")
    dev = _pins(ROOT / "requirements-dev.lock")
    failures = _validate_requirements(project.get("dependencies", []), runtime, "runtime lock")
    for extra in ("dev", "fixtures"):
        failures.extend(_validate_requirements(project.get("optional-dependencies", {}).get(extra, []), dev, "dev lock"))
    failures.extend(_validate_requirements(project.get("dependencies", []), dev, "dev lock"))
    failures.extend(_validate_requirements(build_system.get("requires", []), dev, "dev/build lock"))
    if failures:
        print("\n".join(failures))
        return 1
    print(f"Lockfile gate passed: {len(runtime)} runtime pins, {len(dev)} CI/dev pins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
