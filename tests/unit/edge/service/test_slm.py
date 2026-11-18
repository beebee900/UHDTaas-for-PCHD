"""The edge assistant with the deterministic `OfflineSLM` (design 04, 4.2.1 tier 2)."""

from datetime import timedelta

import pytest

from edge.alerts import Alert
from edge.devices.decode.observations import HEART_RATE, SPO2
from edge.preprocess import Preprocessor
from edge.slm import EdgeAssistant, LlamaCppSLM, OfflineSLM, prompts
from tests.unit.edge.service.support import HDT, START
from tests.unit.edge.service.test_preprocess import reading


class Recording(OfflineSLM):
    def __init__(self):
        self.calls = []

    def chat(self, messages, *, max_tokens):
        self.calls.append((messages, max_tokens))
        return super().chat(messages, max_tokens=max_tokens)


def day_windows():
    pre = Preprocessor(window_s=60.0)
    payloads = [reading(SPO2, v, "%", START + timedelta(seconds=20 * i))
                for i, v in enumerate((96, 94, 97, 95, 93, 98))]
    payloads.append(reading(HEART_RATE, 72, "/min", START))
    return pre.process(payloads, START + timedelta(minutes=5)).features


ALERT = Alert("a-1", HDT, "rule", "pulmonary_oedema_spo2", "emergency", START, "spo2", 89.0,
              "%")


def test_prompts_define_both_tasks():
    p = prompts()
    assert set(p) == {"summary", "triage"}
    assert all({"system", "user", "max_tokens"} <= set(t) for t in p.values())


def test_daily_summary_states_the_window_facts():
    slm = Recording()
    text = EdgeAssistant(slm).daily_summary(HDT, START.date(), day_windows(), [ALERT])
    assert text == ("heart_rate: mean 72 /min, lowest 72, highest 72, 1 readings. "
                    "spo2: mean 95.5 %, lowest 93, highest 98, 6 readings. "
                    "ATRA emergency alert: spo2 89 % at 08:00 UTC.")
    ((messages, max_tokens),) = slm.calls
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == prompts()["summary"]["system"]
    assert f"Facts for {HDT} on {START.date().isoformat()}:" in messages[1]["content"]
    assert max_tokens == prompts()["summary"]["max_tokens"]


def test_summary_without_readings_and_triage():
    assistant = EdgeAssistant(OfflineSLM())
    assert assistant.daily_summary(HDT, START.date(), []) == "no readings."
    assert assistant.triage(ALERT) == "ATRA emergency alert: spo2 89 % at 08:00 UTC."


def test_llama_cpp_needs_the_model_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        LlamaCppSLM(tmp_path / "qwen2.5-0.5b-instruct-q4_k_m.gguf")
