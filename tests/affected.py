"""Select the checks that a change since a base commit can affect.

`python -m tests.affected pytest BASE` prints the test files that import a changed module,
directly or through other modules. `mypy` prints the type-checked packages that contain a
changed or dependent module. `k8s` prints `yes` when deploy/k8s changed. A change to
pyproject.toml or the root conftest selects everything.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("atra", "ahdt", "apdt", "population", "channels", "edge", "contracts", "synth",
            "evaluation", "tests")
TYPECHECKED = ("atra", "ahdt", "apdt", "population", "channels", "edge", "contracts", "synth",
               "run.py")
SELECT_ALL = ("pyproject.toml", "tests/conftest.py")


def changed_files(base: str) -> list[str]:
    def git(*args: str) -> list[str]:
        out = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)
        return [line for line in out.stdout.splitlines() if line]

    return sorted(set(git("diff", "--name-only", base))
                  | set(git("ls-files", "--others", "--exclude-standard")))


def module_name(path: Path) -> str:
    parts = path.relative_to(ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def modules() -> dict[str, Path]:
    found = {"run": ROOT / "run.py"}
    for package in PACKAGES:
        for path in (ROOT / package).rglob("*.py"):
            if "__pycache__" not in path.parts:
                found[module_name(path)] = path
    return found


def imports(path: Path, name: str, known: dict[str, Path]) -> set[str]:
    """Known modules that `path` imports, including names given as string literals."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    targets: set[str] = set()
    strings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")
                anchor = anchor[: len(anchor) - node.level + 1]
                base = ".".join([*anchor, base] if base else anchor)
            targets.add(base)
            targets.update(f"{base}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.add(node.value.split(":")[0])
    # Dotted strings name modules loaded by path, such as service entry points.
    found = {s for s in strings if "." in s and s in known}
    for target in targets:
        parts = target.split(".")
        for i in range(1, len(parts) + 1):
            prefix = ".".join(parts[:i])
            if prefix in known:
                found.add(prefix)
    found.discard(name)
    return found


def affected(base: str) -> tuple[bool, set[str], set[str], list[str]]:
    """(select all, changed modules, affected modules, changed files)."""
    files = changed_files(base)
    if any(f.startswith(SELECT_ALL) for f in files):
        return True, set(), set(), files
    known = modules()
    by_dir: dict[Path, set[str]] = defaultdict(set)
    for name, path in known.items():
        if path.name != "__init__.py":
            by_dir[path.parent].add(name)
    changed: set[str] = set()
    for f in files:
        path = ROOT / f
        if path.suffix == ".py":
            # A deleted module counts through its former importers, which the diff also holds.
            if path.exists():
                changed.add(module_name(path) if f != "run.py" else "run")
        else:
            # A data file next to code (params, catalogue YAML) affects the modules beside it.
            changed.update(by_dir.get(path.parent, set()))
    reverse: dict[str, set[str]] = defaultdict(set)
    for name, path in known.items():
        for dep in imports(path, name, known):
            reverse[dep].add(name)
    seen, todo = set(changed), list(changed)
    while todo:
        for user in reverse[todo.pop()]:
            if user not in seen:
                seen.add(user)
                todo.append(user)
    return False, changed, seen, files


def main() -> None:
    mode, base = sys.argv[1], sys.argv[2]
    everything, _, hit, files = affected(base)
    if mode == "pytest":
        if everything:
            print("tests")
            return
        tests = sorted(str(p.relative_to(ROOT)) for n, p in modules().items()
                       if n in hit and p.name.startswith("test_") and "e2e" not in p.parts)
        print(" ".join(tests))
    elif mode == "mypy":
        if everything:
            print(" ".join(TYPECHECKED))
            return
        roots = {n.split(".")[0] for n in hit}
        print(" ".join(t for t in TYPECHECKED if t.removesuffix(".py") in roots))
    elif mode == "k8s":
        print("yes" if any(f.startswith("deploy/k8s/") for f in files) else "")
    else:
        raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    main()
