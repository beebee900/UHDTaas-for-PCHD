"""Start the Python services of a profile (design 02, section 2.4).

    python run.py --profile p0                 OPA and all five services, in-process backends
    python run.py --profile p0 --only ahdt,apdt
    python run.py --profile p0 --no-seed       skip the demo episodes

With profile p0, a started APDT gets one open episode for each demo persona (`apdt.demo_seed`).
Each service runs in its own process, as in a deployment. Press Ctrl+C to stop them all.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from atra.config import ROOT, get_settings
from atra.policy import OPAProcess


@dataclass(frozen=True)
class Service:
    name: str
    module: str
    port: int


SERVICES = (
    Service("edge", "edge.app", 8095),
    Service("ahdt", "ahdt.app", 8100),
    Service("population", "population.app", 8110),
    Service("apdt", "apdt.app", 8200),
    Service("channels", "channels.app", 8300),
)
OPA_PORT = 8181


def wait_healthy(url: str, proc: subprocess.Popen[bytes], timeout_s: float = 600) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{url} exited with code {proc.returncode}")
        try:
            if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise TimeoutError(f"{url} did not become healthy")


def seed_demo(host: str, chosen: Sequence[Service]) -> None:
    """Open the demo episodes; a failure is reported and the services keep running."""
    from apdt.demo_seed import seed
    from atra.backends import Backends

    ports = {s.name: s.port for s in chosen}

    async def go() -> None:
        issuer = Backends(get_settings(), "run-seed").issuer
        async with httpx.AsyncClient(base_url=f"http://{host}:{ports['apdt']}",
                                     timeout=120) as apdt, \
                httpx.AsyncClient(base_url=f"http://{host}:{ports.get('ahdt', 0)}",
                                  timeout=60) as ahdt:
            for line in await seed(apdt, ahdt if "ahdt" in ports else None, issuer):
                print(f"seed        {line}", flush=True)

    try:
        asyncio.run(go())
    except (httpx.HTTPError, OSError) as exc:
        print(f"seed failed: {exc}", file=sys.stderr)


def _interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the ATRA services of a profile.")
    parser.add_argument("--profile", default="p0", choices=["p0", "p1", "p2", "p3", "p4"])
    parser.add_argument("--only", default="", help="comma-separated service names")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-seed", action="store_true", help="do not open the demo episodes")
    args = parser.parse_args(argv)

    wanted = {s.strip() for s in args.only.split(",") if s.strip()}
    unknown = wanted - {s.name for s in SERVICES}
    if unknown:
        parser.error(f"unknown services: {', '.join(sorted(unknown))}")
    chosen = [s for s in SERVICES if not wanted or s.name in wanted]

    settings = get_settings()
    env = dict(os.environ, ATRA_PROFILE=args.profile, PYTHONPATH=str(ROOT))
    opa: OPAProcess | None = None
    if settings.backend.policy == "memory":
        opa = OPAProcess(port=OPA_PORT).start()
        env["ATRA_INFRA__OPA"] = opa.url
        print(f"opa         {opa.url}", flush=True)

    procs: list[tuple[Service, subprocess.Popen[bytes]]] = []
    try:
        for svc in chosen:
            env[f"ATRA_SERVICES__{svc.name.upper()}"] = f"http://{args.host}:{svc.port}"
        for svc in chosen:
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", f"{svc.module}:build_app", "--factory",
                 "--host", args.host, "--port", str(svc.port), "--log-level", "warning"],
                cwd=ROOT, env=env)
            procs.append((svc, proc))
        for svc, proc in procs:
            wait_healthy(f"http://{args.host}:{svc.port}", proc)
            print(f"{svc.name:<11} http://{args.host}:{svc.port}", flush=True)
        if args.profile == "p0" and not args.no_seed and any(s.name == "apdt" for s in chosen):
            seed_demo(args.host, chosen)
        print("all services are healthy; press Ctrl+C to stop", flush=True)
        signal.signal(signal.SIGTERM, _interrupt)
        while all(proc.poll() is None for _, proc in procs):
            time.sleep(1)
        stopped = [svc.name for svc, proc in procs if proc.poll() is not None]
        print(f"stopped unexpectedly: {', '.join(stopped)}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, TimeoutError) as exc:
        print(f"start failed: {exc}", file=sys.stderr)
        return 1
    finally:
        for _, proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for _, proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        if opa is not None:
            opa.stop()


if __name__ == "__main__":
    sys.exit(main())
