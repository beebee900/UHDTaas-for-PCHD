"""Policy decisions through Open Policy Agent (design 07, section 7.1.3).

In every profile the decisions come from OPA over the `.rego` files in `policies/opa/`.
In p0 `OPAProcess` runs the OPA binary as a local process; in p2 the OPA container
serves the same files. Every client fails closed: when OPA cannot answer, the decision
is a denial.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from atra.config import ROOT
from atra.connectors import Decision, Message, Policy

POLICY_DIR = ROOT / "policies" / "opa"
OPA_BINARY = ROOT / "var" / "bin" / "opa"


@dataclass(frozen=True)
class PolicyDecision:
    allow: bool
    reasons: tuple[str, ...] = ()
    package: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons)


def _decision_path(package: str) -> str:
    return "/v1/data/" + package.replace(".", "/") + "/decision"


def _parse(package: str, body: Mapping[str, Any]) -> PolicyDecision:
    result = body.get("result")
    if not isinstance(result, Mapping):
        return PolicyDecision(False, (f"policy {package} returned no decision",), package)
    return PolicyDecision(bool(result.get("allow", False)),
                          tuple(str(r) for r in result.get("reasons", [])), package, result)


class PolicyClient:
    """Asynchronous OPA client used by services.

    Without a given client it keeps one connection pool per event loop, so concurrent
    decisions share connections instead of each opening its own.
    """

    def __init__(self, base_url: str, *, timeout_s: float = 2.0,
                 client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._client = client
        self._pooled: tuple[asyncio.AbstractEventLoop, httpx.AsyncClient] | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        loop = asyncio.get_running_loop()
        if self._pooled is None or self._pooled[0] is not loop:
            self._pooled = (loop, httpx.AsyncClient(timeout=self.timeout_s))
        return self._pooled[1]

    async def decide(self, package: str, input_: Mapping[str, Any]) -> PolicyDecision:
        try:
            resp = await self._http().post(self.base_url + _decision_path(package),
                                           json={"input": input_})
            resp.raise_for_status()
            return _parse(package, resp.json())
        except (httpx.HTTPError, ValueError) as exc:
            return PolicyDecision(False, (f"policy service unavailable: {exc}",), package)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        if self._pooled is not None and self._pooled[0] is asyncio.get_running_loop():
            await self._pooled[1].aclose()
        self._pooled = None


class SyncPolicyClient:
    """Blocking OPA client for the supplied `Policy.evaluate` interface, which is synchronous.

    OPA runs on the same host, so a decision takes a few milliseconds.
    """

    def __init__(self, base_url: str, *, timeout_s: float = 1.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_s)

    def decide(self, package: str, input_: Mapping[str, Any]) -> PolicyDecision:
        try:
            resp = self._client.post(self.base_url + _decision_path(package),
                                     json={"input": input_})
            resp.raise_for_status()
            return _parse(package, resp.json())
        except (httpx.HTTPError, ValueError) as exc:
            return PolicyDecision(False, (f"policy service unavailable: {exc}",), package)

    def close(self) -> None:
        self._client.close()


class OPAPolicy(Policy):
    """Connector policy decided by OPA package `ahdt.connectors` (design 07, 7.1.3).

    Added next to the supplied `ConsentPolicy` and `RangeGuardPolicy` on every connector.
    """

    name = "opa"

    def __init__(self, client: SyncPolicyClient, package: str = "ahdt.connectors") -> None:
        self.client = client
        self.package = package

    def evaluate(self, message: Message, direction: str) -> Decision:
        d = self.client.decide(self.package, {
            "direction": direction,
            "message": {"source": message.source, "target": message.target,
                        "contract": message.contract, "purpose": message.purpose,
                        "payload": message.payload, "units": message.units}})
        return Decision(d.allow, d.reason, self.name)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class OPAProcess:
    """OPA server as a local process over `policies/opa` (profile p0)."""

    def __init__(self, *, port: int | None = None, policy_dir: Path = POLICY_DIR,
                 binary: Path | None = None) -> None:
        self.port = port or _free_port()
        self.policy_dir = policy_dir
        found = binary or (OPA_BINARY if OPA_BINARY.exists() else shutil.which("opa"))
        if not found:
            raise FileNotFoundError("OPA binary not found; run `make tools`")
        self.binary = Path(found)
        self._proc: subprocess.Popen[bytes] | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self, *, wait_s: float = 10.0) -> OPAProcess:
        self._proc = subprocess.Popen(
            [str(self.binary), "run", "--server", "--log-level", "error",
             "--addr", f"127.0.0.1:{self.port}", str(self.policy_dir)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                err = self._proc.stderr.read().decode() if self._proc.stderr else ""
                raise RuntimeError(f"OPA exited: {err}")
            try:
                if httpx.get(f"{self.url}/health", timeout=0.5).status_code == 200:
                    return self
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        self.stop()
        raise TimeoutError("OPA did not become healthy")

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def __enter__(self) -> OPAProcess:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


def run_opa_tests(policy_dir: Path = POLICY_DIR) -> subprocess.CompletedProcess[str]:
    """`opa test` over the policy directory; used by `make ci` and the unit tests."""
    binary = OPA_BINARY if OPA_BINARY.exists() else Path(shutil.which("opa") or "opa")
    return subprocess.run([str(binary), "test", str(policy_dir), "--format", "json"],
                          capture_output=True, text=True, check=False)


async def wait_healthy(url: str, *, wait_s: float = 10.0) -> None:
    deadline = time.monotonic() + wait_s
    async with httpx.AsyncClient(timeout=0.5) as client:
        while time.monotonic() < deadline:
            try:
                if (await client.get(f"{url}/health")).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.05)
    raise TimeoutError(f"OPA at {url} did not become healthy")


def policy_data_json(data: Mapping[str, Any]) -> str:
    return json.dumps({"atra": data}, indent=2, sort_keys=True) + "\n"
