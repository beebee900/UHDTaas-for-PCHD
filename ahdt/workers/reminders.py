"""Reminder and questionnaire workflows (design 04, 4.7.5).

A reminder waits its delay, then sends through the notification router. A questionnaire
sends its prompt at each scheduled hour. Both stop quietly when consent does not allow the
message.
"""

from __future__ import annotations

from ahdt.services.notify import NotificationRouter, Recipient
from atra.backends.base import WorkflowBackend, WorkflowContext

REMINDER = "reminder"
QUESTIONNAIRE = "questionnaire"


def register(workflows: WorkflowBackend, router: NotificationRouter) -> None:
    async def send(hdt_id: str, recipient: str, channel: str, text: str, instrument: str
                   ) -> str:
        used = await router.send(hdt_id, recipient, channel=channel,  # type: ignore[arg-type]
                                 text=text, instrument=instrument)
        return used or "withheld"

    async def reminder(ctx: WorkflowContext, hdt_id: str, text: str, delay_h: float,
                       recipient: Recipient = "person", channel: str = "app") -> str:
        await ctx.sleep(delay_h * 3600.0)
        return str(await ctx.activity(send, hdt_id, recipient, channel, text, ""))

    async def questionnaire(ctx: WorkflowContext, hdt_id: str, instrument: str,
                            at_h: list[float], channel: str = "app") -> list[str]:
        sent, elapsed = [], 0.0
        for hour in sorted(at_h):
            await ctx.sleep((hour - elapsed) * 3600.0)
            elapsed = hour
            sent.append(str(await ctx.activity(
                send, hdt_id, "person", channel, f"Questionnaire {instrument}", instrument)))
        return sent

    workflows.register(REMINDER, reminder)
    workflows.register(QUESTIONNAIRE, questionnaire)
