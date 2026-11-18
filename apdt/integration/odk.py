"""ODK: the CHW forms as XLSForms and the ODK Central pull client (design 05, 5.2.1).

The forms are defined once here. `python -m apdt.integration.odk` writes them as XLSForm
workbooks (`survey`, `choices` and `settings` sheets, https://xlsform.org/en/) to
`apdt/integration/odk_forms/`. The pull client follows the ODK Central API:

- `POST /v1/sessions` with `{email, password}` → `{token, expiresAt}`; later requests send
  `Authorization: Bearer {token}` (https://docs.getodk.org/central-api-authentication/)
- `GET /v1/projects/{projectId}/forms/{xmlFormId}.svc/Submissions` with `$filter` on
  `__system/submissionDate` and paging by `@odata.nextLink`
  (https://docs.getodk.org/central-api-odata-endpoints/)

Each submission becomes a FHIR QuestionnaireResponse whose linkIds are the form's field
names.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fhir.resources.R4B.questionnaireresponse import QuestionnaireResponse

from apdt.records.episodes import PATIENT_SYSTEM

FORMS_DIR = Path(__file__).parent / "odk_forms"
QUESTIONNAIRE_BASE = "https://atra.health/fhir/Questionnaire/odk-"
CHOICE_SYSTEM = "urn:atra:odk:choices:"
VERSION = "2026101101"


@dataclass(frozen=True)
class Question:
    type: str
    name: str
    label: str
    required: bool = False
    relevant: str = ""


@dataclass(frozen=True)
class Form:
    form_id: str
    title: str
    questions: Sequence[Question]
    choices: Mapping[str, Sequence[tuple[str, str]]] = field(default_factory=dict)


YES_NO = (("yes", "Yes"), ("no", "No"))
PATIENT = Question("text", "hdt_id", "Patient twin id (scan the card)", required=True)
VISIT_DATE = Question("date", "visit_date", "Date of visit", required=True)

FORMS: tuple[Form, ...] = (
    Form("chw_follow_up", "CHW follow-up visit", (
        PATIENT, VISIT_DATE,
        Question("select_one feeling", "feeling",
                 "How does the person feel compared with the last visit?", required=True),
        Question("select_multiple danger", "danger_signs", "Danger signs now", required=True),
        Question("decimal", "temperature_c", "Temperature (degrees Celsius)"),
        Question("select_one yes_no", "referral_needed", "Does the person need referral?",
                 required=True),
        Question("text", "notes", "Notes")),
        {"feeling": (("better", "Better"), ("same", "The same"), ("worse", "Worse")),
         "danger": (("convulsions", "Fits or convulsions"),
                    ("impaired_consciousness", "Very sleepy or hard to wake"),
                    ("respiratory_distress", "Difficult or fast breathing"),
                    ("bleeding", "Bleeding that will not stop"), ("vomiting", "Vomiting"),
                    ("none", "None of these")),
         "yes_no": YES_NO}),
    Form("chw_adherence", "CHW adherence check", (
        PATIENT, VISIT_DATE,
        Question("integer", "doses_missed", "Doses missed since the last visit", required=True),
        Question("select_one reason", "reason_missed", "Main reason doses were missed",
                 required=True, relevant="${doses_missed} > 0"),
        Question("integer", "doses_left", "Doses left in the pack")),
        {"reason": (("forgot", "Forgot"), ("side_effects", "Side effects"),
                    ("no_stock", "No medicine available"), ("felt_better", "Felt better"),
                    ("other", "Other"))}),
    Form("chw_referral", "CHW referral", (
        PATIENT, VISIT_DATE,
        Question("select_one referral_reason", "reason", "Reason for referral", required=True),
        Question("select_one urgency", "urgency", "Urgency", required=True),
        Question("text", "facility", "Facility referred to", required=True),
        Question("text", "notes", "Notes")),
        {"referral_reason": (("danger_sign", "Danger sign"),
                             ("no_improvement", "No improvement"),
                             ("pregnancy", "Pregnancy care"), ("other", "Other")),
         "urgency": (("emergency", "Emergency"), ("urgent", "Urgent"), ("routine", "Routine"))}),
)
BY_ID = {f.form_id: f for f in FORMS}


def write_xlsforms(out: Path = FORMS_DIR) -> list[Path]:
    from openpyxl import Workbook

    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for form in FORMS:
        wb = Workbook()
        survey = wb.active
        survey.title = "survey"
        survey.append(["type", "name", "label::English (en)", "required", "relevant"])
        for q in form.questions:
            survey.append([q.type, q.name, q.label, "yes" if q.required else "", q.relevant])
        choices = wb.create_sheet("choices")
        choices.append(["list_name", "name", "label::English (en)"])
        for list_name, options in form.choices.items():
            for name, label in options:
                choices.append([list_name, name, label])
        settings = wb.create_sheet("settings")
        settings.append(["form_title", "form_id", "version", "default_language"])
        settings.append([form.title, form.form_id, VERSION, "English (en)"])
        path = out / f"{form.form_id}.xlsx"
        # A fixed timestamp keeps the workbook bytes stable between builds.
        wb.properties.created = wb.properties.modified = datetime(2026, 10, 11)
        wb.save(path)
        paths.append(path)
    return paths


def _answers(q: Question, value: Any) -> list[dict[str, Any]]:
    kind, _, list_name = q.type.partition(" ")
    if value is None or value == "":
        return []
    if kind == "integer":
        return [{"valueInteger": int(value)}]
    if kind == "decimal":
        return [{"valueDecimal": float(value)}]
    if kind == "date":
        return [{"valueDate": str(value)[:10]}]
    if kind == "select_one":
        return [{"valueCoding": {"system": CHOICE_SYSTEM + list_name, "code": str(value)}}]
    if kind == "select_multiple":
        return [{"valueCoding": {"system": CHOICE_SYSTEM + list_name, "code": v}}
                for v in str(value).split()]
    return [{"valueString": str(value)}]


def to_questionnaire_response(form: Form, submission: Mapping[str, Any]) -> dict[str, Any]:
    items = []
    for q in form.questions:
        if q.name == PATIENT.name:
            continue
        answers = _answers(q, submission.get(q.name))
        if answers:
            items.append({"linkId": q.name, "text": q.label, "answer": answers})
    system = submission.get("__system", {})
    body = {
        "resourceType": "QuestionnaireResponse",
        "id": "odk-" + str(submission["__id"]).removeprefix("uuid:"),
        "identifier": {"system": "urn:atra:odk:instance", "value": str(submission["__id"])},
        "questionnaire": QUESTIONNAIRE_BASE + form.form_id,
        "status": "completed",
        "subject": {"identifier": {"system": PATIENT_SYSTEM,
                                   "value": str(submission[PATIENT.name])}},
        "item": items}
    if system.get("submissionDate"):
        body["authored"] = system["submissionDate"]
    return dict(QuestionnaireResponse.model_validate(body).model_dump(mode="json",
                                                                       exclude_none=True))


class OdkCentralClient:
    def __init__(self, base_url: str, email: str, password: str, *,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.http = httpx.AsyncClient(base_url=base_url.rstrip("/"), transport=transport,
                                      timeout=60)
        self._email, self._password = email, password
        self._token: str | None = None

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _auth(self) -> dict[str, str]:
        if self._token is None:
            resp = await self.http.post("/v1/sessions", json={"email": self._email,
                                                              "password": self._password})
            resp.raise_for_status()
            self._token = str(resp.json()["token"])
        return {"authorization": f"Bearer {self._token}"}

    async def submissions(self, project_id: int, form_id: str, *,
                          since: str | None = None, page_size: int = 250) -> list[dict[str, Any]]:
        params = {"$top": str(page_size)}
        if since:
            params["$filter"] = f"__system/submissionDate gt {since}"
        url: str | None = f"/v1/projects/{project_id}/forms/{form_id}.svc/Submissions"
        out: list[dict[str, Any]] = []
        first = True
        while url:
            resp = await self.http.get(url, params=params if first else None,
                                       headers=await self._auth())
            resp.raise_for_status()
            body = resp.json()
            out += list(body.get("value", []))
            url, first = body.get("@odata.nextLink"), False
        return out

    async def pull(self, project_id: int, form_id: str, *,
                   since: str | None = None) -> list[dict[str, Any]]:
        """New submissions of a CHW form as QuestionnaireResponses."""
        form = BY_ID[form_id]
        return [to_questionnaire_response(form, s)
                for s in await self.submissions(project_id, form_id, since=since)]


if __name__ == "__main__":
    for p in write_xlsforms():
        print(p)
