"""Africa's Talking adapter: SMS sending, and the USSD, SMS and voice callback formats.

From the Africa's Talking developer docs (read 2026-10-11) and the africastalking-python
SDK (MIT, `Service.py`, `SMS.py`):

- Bulk SMS: `POST https://api.africastalking.com/version1/messaging/bulk` (sandbox host
  `api.sandbox.africastalking.com`), JSON `{username, phoneNumbers, message, senderId,
  enqueue}`, headers `apiKey`, `Accept: application/json`. The reply is
  `{SMSMessageData: {Message, Recipients: [{statusCode, number, status, cost, messageId}]}}`;
  status codes 100 Processed, 101 Sent and 102 Queued are accepted.
- USSD callback: form fields `sessionId`, `phoneNumber`, `networkCode`, `serviceCode`,
  `text` (empty first, then all inputs joined by `*`); the reply is plain text that starts
  with `CON` (more input) or `END` (session over).
- SMS callbacks: incoming `date, from, id, linkId?, text, to, cost?`; delivery reports
  `id, status, phoneNumber, networkCode, failureReason?, retryCount?`.
- Voice callback: `isActive` (1 during the call, 0 in the final request), `sessionId`,
  `direction`, `callerNumber`, `destinationNumber`, `dtmfDigits`, `recordingUrl`,
  `durationInSeconds`, `currencyCode`, `amount`. The reply is XML `<Response>` with actions
  such as `Say`, `Play url=` and `GetDigits` (`numDigits`, `timeout`, `finishOnKey`,
  `callbackUrl`), with `Say` or `Play` nested in `GetDigits` as its prompt.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from xml.sax.saxutils import escape, quoteattr

import httpx

PRODUCTION = "https://api.africastalking.com"
SANDBOX = "https://api.sandbox.africastalking.com"
ACCEPTED = frozenset({100, 101, 102})
FINAL_DELIVERY = frozenset({"Rejected", "Success", "Failed", "AbsentSubscriber", "Expired"})


@dataclass(frozen=True)
class SmsResult:
    number: str
    status_code: int
    status: str
    message_id: str | None

    @property
    def accepted(self) -> bool:
        return self.status_code in ACCEPTED


class SmsError(RuntimeError):
    pass


class AfricasTalkingSms:
    def __init__(self, username: str, api_key: str, *, sender_id: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        base = SANDBOX if username == "sandbox" else PRODUCTION
        self.username, self.sender_id = username, sender_id
        self.http = httpx.AsyncClient(base_url=base, transport=transport, timeout=30, headers={
            "apiKey": api_key, "Accept": "application/json"})

    async def aclose(self) -> None:
        await self.http.aclose()

    async def send(self, numbers: Sequence[str], message: str) -> list[SmsResult]:
        body: dict[str, object] = {"username": self.username, "phoneNumbers": list(numbers),
                                   "message": message, "enqueue": 1}
        if self.sender_id:
            body["senderId"] = self.sender_id
        try:
            resp = await self.http.post("/version1/messaging/bulk", json=body)
            resp.raise_for_status()
            data = resp.json()["SMSMessageData"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise SmsError(str(exc)) from exc
        return [SmsResult(str(r["number"]), int(r["statusCode"]), str(r["status"]),
                          None if r.get("messageId") in (None, "None") else str(r["messageId"]))
                for r in data.get("Recipients", [])]


def ussd_reply(text: str, *, end: bool) -> str:
    return ("END " if end else "CON ") + text


class VoiceResponse:
    """Builds the XML reply of a voice callback."""

    def __init__(self) -> None:
        self._parts: list[str] = []

    def say(self, text: str) -> VoiceResponse:
        self._parts.append(f"<Say>{escape(text)}</Say>")
        return self

    def play(self, url: str) -> VoiceResponse:
        self._parts.append(f"<Play url={quoteattr(url)}/>")
        return self

    def get_digits(self, *, prompt_text: str | None = None, prompt_url: str | None = None,
                   num_digits: int | None = None, timeout_s: int = 30,
                   finish_on_key: str | None = None,
                   callback_url: str | None = None) -> VoiceResponse:
        attrs = [f'timeout="{timeout_s}"']
        if num_digits is not None:
            attrs.append(f'numDigits="{num_digits}"')
        if finish_on_key:
            attrs.append(f"finishOnKey={quoteattr(finish_on_key)}")
        if callback_url:
            attrs.append(f"callbackUrl={quoteattr(callback_url)}")
        prompt = (f"<Play url={quoteattr(prompt_url)}/>" if prompt_url
                  else f"<Say>{escape(prompt_text or '')}</Say>")
        self._parts.append(f"<GetDigits {' '.join(attrs)}>{prompt}</GetDigits>")
        return self

    def xml(self) -> str:
        return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(self._parts) + \
            "</Response>"
