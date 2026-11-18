"""Africa's Talking adapter, menu engine, outbox, IVR and directory of the channels service."""

import json
import xml.etree.ElementTree as ET

import httpx
import pytest

from atra.backends.memory import DyonEventBus
from atra.provenance import AuditLog
from channels.africastalking import AfricasTalkingSms, SmsError, VoiceResponse, ussd_reply
from channels.directory import demo_directory
from channels.menu import default_menu
from channels.outbox import Outbox, SimulatedSms
from channels.speech import PromptCache, ToneSynthesiser

DOCS = {
    "ussd": "https://developers.africastalking.com/docs/ussd/handle_sessions",
    "sms_bulk": "https://developers.africastalking.com/docs/sms/sending/bulk",
    "sms_notifications": "https://developers.africastalking.com/docs/sms/notifications",
    "voice_calls": "https://developers.africastalking.com/docs/voice/handle_calls",
    "voice_get_digits": "https://developers.africastalking.com/docs/voice/actions/get_digits",
    "voice_play": "https://developers.africastalking.com/docs/voice/actions/play",
    "voice_actions": "https://developers.africastalking.com/docs/voice/actions/overview",
    "python_sdk": "https://github.com/AfricasTalkingLtd/africastalking-python",
}
# The sample reply of the bulk SMS docs (DOCS["sms_bulk"]), verbatim.
BULK_REPLY = {"SMSMessageData": {"Message": "Sent to 1/1 Total Cost: KES 0.8000", "Recipients": [{
    "statusCode": 101, "number": "+254711XXXYYY", "status": "Success", "cost": "KES 0.8000",
    "messageId": "ATPid_SampleTxnId123"}]}}
PHONE = "+2340000000001"
KEY = b"k" * 32


async def test_bulk_sms_request_and_reply():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=BULK_REPLY)

    sms = AfricasTalkingSms("sandbox", "test-key", sender_id="ATRA",
                            transport=httpx.MockTransport(handler))
    [result] = await sms.send(["+254711XXXYYY"], "Hello")
    await sms.aclose()
    req = seen[0]
    assert str(req.url) == "https://api.sandbox.africastalking.com/version1/messaging/bulk"
    assert req.headers["apiKey"] == "test-key" and req.headers["accept"] == "application/json"
    assert json.loads(req.content) == {"username": "sandbox", "phoneNumbers": ["+254711XXXYYY"],
                                       "message": "Hello", "enqueue": 1, "senderId": "ATRA"}
    assert result.accepted and result.message_id == "ATPid_SampleTxnId123"


async def test_bulk_sms_rejection_and_errors():
    reply = {"SMSMessageData": {"Message": "Sent to 0/1 Total Cost: 0", "Recipients": [{
        "cost": "0", "messageId": "None", "number": "+2348XXXXXXX",
        "status": "DoNotDisturbRejection", "statusCode": 409}]}}
    sms = AfricasTalkingSms("atra", "k", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=reply)))
    [result] = await sms.send(["+2348XXXXXXX"], "x")
    assert not result.accepted and result.message_id is None
    down = AfricasTalkingSms("atra", "k", transport=httpx.MockTransport(
        lambda r: httpx.Response(500)))
    with pytest.raises(SmsError):
        await down.send(["+2348XXXXXXX"], "x")


def test_ussd_and_voice_replies():
    assert ussd_reply("Hi", end=False) == "CON Hi" and ussd_reply("Bye", end=True) == "END Bye"
    xml = (VoiceResponse().get_digits(prompt_text="Press 1 & 2", num_digits=1, timeout_s=20,
                                      finish_on_key="#").say("Bye").xml())
    root = ET.fromstring(xml)
    gd = root.find("GetDigits")
    assert gd.get("numDigits") == "1" and gd.get("finishOnKey") == "#"
    assert gd.find("Say").text == "Press 1 & 2" and root.find("Say").text == "Bye"
    assert ET.fromstring(VoiceResponse().play("http://x/a.wav").xml()).find("Play").get(
        "url") == "http://x/a.wav"


def test_menu_strings_are_plain_ascii_and_complete():
    menu = default_menu()
    for key, entry in menu.strings.items():
        assert "en" in entry, key
        assert all(ord(ch) < 128 for text in entry.values() for ch in text), key
    for item in menu.consent_items:
        assert f"consent.item.{item['id']}" in menu.strings
    assert menu.timeout_s == 180


def test_consent_walk_matches_msc4_choices():
    menu = default_menu()
    genome = [i["id"] for i in menu.consent_items].index("genome")
    answers = ["2" if n == genome else "1" for n in range(len(menu.consent_items))]
    step = menu.walk(["5", "1", *answers], "yo")
    assert not step.end and "Genome" in step.text
    done = menu.walk(["5", "1", *answers, "1"], "yo")
    assert done.action == "consent" and done.language == "yo"
    assert done.data["withheld_categories"] == ["genome"]
    assert {"care", "emergency", "self_management"} <= set(done.data["purposes"])
    assert menu.walk(["5", "1", *answers, "2"], "yo").text == menu.t("consent.cancelled", "yo")
    assert menu.walk(["9"], "en").end


def test_check_in_has_numeric_answers():
    menu = default_menu()
    step = menu.walk(["3"], "en")
    assert step.text.splitlines()[1:] == ["1 Better", "2 The same", "3 Worse"]
    n = len(menu.questions["check_in"])
    done = menu.walk(["3", "3", *["2"] * (n - 1)], "en")
    assert done.action == "check_in" and done.data["answers"]["overall"] == "worse"
    assert menu.walk(["3", "4"], "en").text == menu.t("invalid", "en")


def test_directory_keeps_numbers_out_of_references():
    d = demo_directory(KEY)
    contact = d.by_phone(PHONE)
    assert contact.hdt_id and contact.language == "yo" and PHONE not in contact.ref
    assert d.phone_of(contact.hdt_id) == PHONE
    assert d.phone_of("medical_officer.fac-a")


async def test_outbox_stores_and_forwards_with_audit():
    sim = SimulatedSms()
    sim.online = False
    clock = [0.0]
    audit = AuditLog("channels")
    events = DyonEventBus()
    outbox = Outbox(sim, audit, events, ref=demo_directory(KEY).ref, backoff_s=10,
                    max_attempts=3, clock=lambda: clock[0])
    msg = await outbox.enqueue(PHONE, "Take your medicine", language="en", purpose="care")
    assert msg.status == "queued" and outbox.pending() == [msg]
    assert await outbox.flush() == 0
    sim.online = True
    clock[0] = 11
    assert await outbox.flush() == 1
    assert msg.status == "sent" and sim.inbox[PHONE] == ["Take your medicine"]
    assert outbox.delivery_report(msg.provider_id, "Success").status == "delivered"
    sent = [e for e in events.published if e.event_type == "message.sent"]
    assert [r.outcome for r in audit.query(action="sms.send")] == ["error", "ok"]
    assert audit.verify_chain() == 3
    assert sent and sent[0].payload["to"].startswith("tel-")
    assert PHONE not in json.dumps([r.model_dump(mode="json") for r in audit])


async def test_outbox_gives_up_after_max_attempts():
    sim = SimulatedSms()
    sim.online = False
    clock = [0.0]
    outbox = Outbox(sim, AuditLog("channels"), DyonEventBus(), ref=lambda p: "tel-x",
                    backoff_s=1, max_attempts=2, clock=lambda: clock[0])
    msg = await outbox.enqueue(PHONE, "x", language="en", purpose="care")
    clock[0] = 5
    await outbox.flush()
    assert msg.status == "failed" and msg.attempts == 2


async def test_prompt_cache_makes_stable_wav_prompts():
    cache = PromptCache({"yo": ToneSynthesiser()})
    key = await cache.prompt("yo", "Welcome")
    assert key == await cache.prompt("yo", "Welcome")
    audio, ctype = cache.audio(key)
    assert ctype == "audio/wav" and audio[:4] == b"RIFF"
    assert cache.has_voice("yo") and not cache.has_voice("ha")
