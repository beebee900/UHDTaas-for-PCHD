"""WFDB records: header files and format 16 signal files (PhysioNet WFDB Applications Guide,
pages `header(5)` and `signal(5)`, read 2026-10-10).

Header record line: `name nsig fs nsamp [HH:MM:SS DD/MM/YYYY]`. Signal line: `file format
gain(baseline)/units adc_res adc_zero init checksum block_size description`; the fields after
the format are optional and bound in that order. Format 16 stores each sample as a 16-bit
two's-complement value, least significant byte first, frames interleaved across the signals
of one file. Physical value = (sample - baseline) / gain; the baseline defaults to the ADC
zero and the gain to 200 (DEFGAIN). The reader parses any header; only format 16 signals are
read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import numpy.typing as npt

DEFGAIN = 200.0
_GAIN = re.compile(r"^(?P<gain>[-+0-9.eE]+)(?:\((?P<baseline>-?\d+)\))?(?:/(?P<units>\S+))?$")


class WfdbError(ValueError):
    pass


@dataclass(frozen=True)
class Signal:
    file: str
    fmt: int
    gain: float = DEFGAIN
    baseline: int = 0
    units: str = "mV"
    adc_res: int = 0
    adc_zero: int = 0
    init: int = 0
    checksum: int = 0
    block_size: int = 0
    description: str = ""


@dataclass(frozen=True)
class Header:
    name: str
    fs: float
    n_samples: int
    signals: tuple[Signal, ...]
    start: datetime | None = None
    comments: tuple[str, ...] = ()

    def text(self) -> str:
        line = f"{self.name} {len(self.signals)} {self.fs:g} {self.n_samples}"
        if self.start:
            line += f" {self.start:%H:%M:%S} {self.start.day}/{self.start.month}/{self.start.year}"
        out = [line]
        for s in self.signals:
            out.append(f"{s.file} {s.fmt} {s.gain:g}({s.baseline})/{s.units} {s.adc_res} "
                       f"{s.adc_zero} {s.init} {s.checksum} {s.block_size} {s.description}"
                       .rstrip())
        out += [f"# {c}" for c in self.comments]
        return "\n".join(out) + "\n"


def parse_header(text: str) -> Header:
    lines = [ln.strip() for ln in text.splitlines()]
    comments = tuple(ln.lstrip("#").strip() for ln in lines if ln.startswith("#"))
    body = [ln for ln in lines if ln and not ln.startswith("#")]
    if not body:
        raise WfdbError("empty header")
    rec = body[0].split()
    if "/" in rec[0]:
        raise WfdbError("multi-segment records are not supported")
    nsig = int(rec[1])
    fs = float(rec[2].split("/")[0]) if len(rec) > 2 else 250.0
    nsamp = int(rec[3]) if len(rec) > 3 else 0
    start = None
    if len(rec) > 5 and rec[5] != "0/0/0":
        d, m, y = (int(x) for x in rec[5].split("/"))
        hh, mm, ss = (int(float(x)) for x in rec[4].split(":"))
        start = datetime(y, m, d, hh, mm, ss)
    signals = []
    for ln in body[1:1 + nsig]:
        f = ln.split(maxsplit=8)
        digits = re.match(r"\d+", f[1]) if len(f) > 1 else None
        fmt = int(digits.group()) if digits else 0
        gain, baseline, units = DEFGAIN, None, "mV"
        if len(f) > 2:
            g = _GAIN.match(f[2])
            if not g:
                raise WfdbError(f"bad gain field {f[2]!r}")
            gain = float(g["gain"]) or DEFGAIN
            baseline = int(g["baseline"]) if g["baseline"] else None
            units = g["units"] or "mV"
        ints = [int(x) for x in f[3:8]]
        adc_res, adc_zero, init, checksum, block = (ints + [0] * 5)[:5]
        signals.append(Signal(f[0], fmt, gain, adc_zero if baseline is None else baseline,
                              units, adc_res, adc_zero, init, checksum, block,
                              f[8] if len(f) > 8 else ""))
    if len(signals) != nsig:
        raise WfdbError(f"header names {nsig} signals but has {len(signals)} lines")
    return Header(rec[0], fs, nsamp, tuple(signals), start, comments)


def checksum(samples: npt.ArrayLike) -> int:
    """The 16-bit signed sum of the samples."""
    s = int(np.asarray(samples, dtype=np.int64).sum()) & 0xFFFF
    return s - 0x10000 if s >= 0x8000 else s


def write_format16(samples: npt.ArrayLike) -> bytes:
    """Frames x signals ADC values as a format 16 file."""
    return np.asarray(samples, dtype="<i2").tobytes()


def read_format16(header: Header, data: bytes) -> npt.NDArray[np.float64]:
    """Physical values, frames x signals, for a record whose signals share one format 16 file."""
    if {s.fmt for s in header.signals} != {16} or len({s.file for s in header.signals}) != 1:
        raise WfdbError("only single-file format 16 records are read")
    n = len(header.signals)
    adc = np.frombuffer(data, dtype="<i2").astype(np.int64)
    if adc.size % n:
        raise WfdbError("the signal file does not hold whole frames")
    frames = adc.reshape(-1, n)
    if header.n_samples and frames.shape[0] != header.n_samples:
        raise WfdbError(f"expected {header.n_samples} frames, read {frames.shape[0]}")
    for i, s in enumerate(header.signals):
        if s.checksum and checksum(frames[:, i]) != s.checksum:
            raise WfdbError(f"checksum mismatch on signal {i}")
    gains = np.array([s.gain for s in header.signals])
    base = np.array([s.baseline for s in header.signals])
    out: npt.NDArray[np.float64] = (frames - base) / gains
    return out
