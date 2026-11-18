"""Detection of the external simulators (design 01, 1.3 and the day-0 spikes).

Each model wrapper asks for its backend. A missing backend raises `BackendMissing` with
the reason, so a caller sees what is absent instead of an invented result.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path

from ahdt.models.external import sources


class BackendMissing(RuntimeError):
    pass


@dataclass(frozen=True)
class BackendStatus:
    name: str
    available: bool
    version: str | None
    detail: str


def _python_package(name: str, dist: str | None = None) -> BackendStatus:
    try:
        importlib.import_module(name)
        version = importlib.metadata.version(dist or name)
    except ImportError as err:
        return BackendStatus(name, False, None, f"import {name} failed: {err}")
    return BackendStatus(name, True, version, "python package")


def roadrunner() -> BackendStatus:
    return _python_package("roadrunner", "libroadrunner")


def opensim() -> BackendStatus:
    return _python_package("opensim")


def mesa() -> BackendStatus:
    return _python_package("mesa", "mesa")


def deepxde() -> BackendStatus:
    return _python_package("deepxde")


def pythonfmu() -> BackendStatus:
    return _python_package("pythonfmu")


def fmpy() -> BackendStatus:
    return _python_package("fmpy", "FMPy")


def ospsuite() -> BackendStatus:
    """The OSP Suite R package needs R and rpy2; the Python generic PBPK is the fallback."""
    if shutil.which("Rscript") is None:
        return BackendStatus("ospsuite", False, None, "R is not installed")
    try:
        importlib.import_module("rpy2")
    except ImportError:
        return BackendStatus("ospsuite", False, None, "rpy2 is not installed")
    return BackendStatus("ospsuite", False, None, "R and rpy2 found; ospsuite not verified")


def opencarp_root() -> Path:
    return sources.directory() / "opencarp" / "openCARP-v20.0-x86_64_AppImage" / "squashfs-root"


def opencarp() -> BackendStatus:
    """openCARP binaries from the pinned AppImage, extracted without FUSE."""
    root = opencarp_root()
    binary = root / "usr" / "bin" / "openCARP"
    if binary.exists():
        return BackendStatus("opencarp", True, "v20.0", str(root))
    return BackendStatus("opencarp", False, None, f"{binary} is missing; run install_opencarp()")


def install_opencarp() -> Path:
    """Extract the pinned openCARP AppImage under var/wp14c/sources/opencarp."""
    import subprocess

    archive = sources.fetch("opencarp-appimage")
    target = sources.directory() / "opencarp"
    if not opencarp().available:
        target.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as tar:
            tar.extractall(target, filter="data")
        image = next(target.rglob("openCARP-*.AppImage"))
        image.chmod(0o755)
        subprocess.run([str(image), "--appimage-extract"], cwd=image.parent, check=True,
                       capture_output=True, timeout=300)
    return opencarp_root()


def require(status: BackendStatus) -> BackendStatus:
    if not status.available:
        raise BackendMissing(f"{status.name}: {status.detail}")
    return status


def report() -> list[BackendStatus]:
    return [roadrunner(), opencarp(), opensim(), ospsuite(), mesa(), deepxde(), pythonfmu(),
            fmpy()]
