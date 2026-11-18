"""English health dialogues built from the knowledge base (design 06, 6.6).

Four kinds: symptom check-in (finding questions of `kb/findings.yaml`), explanation of a
diagnosis (`kb/conditions.yaml`), reminders (`kb/vaccination_schedule.yaml`,
`kb/support_actions.yaml`) and consent explanation. The text states no clinical fact beyond
the kb names; advice is limited to contacting the care team or the nearest clinic.

Every template also has a Nigerian Pidgin form, written by the author and not checked by a
native speaker. Yoruba, Hausa and Igbo come from translating the English sentences
(`translate.py`).

    python -m evaluation.language.dialogues [--count 360] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import random
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
KB = ROOT / "kb"
OUT = Path(__file__).resolve().parent / "data" / "dialogues_en.jsonl"

PHRASE = {
    "find.fever_history": "fever", "find.cough_2_weeks": "a cough for two weeks or more",
    "find.myalgia": "muscle pain", "find.dyspnoea": "breathlessness",
    "find.urinary_frequency": "frequent urination", "find.low_mood": "low mood",
    "find.anhedonia": "loss of interest in things you enjoy",
    "find.excessive_worry": "worry that you cannot control",
    "find.reduced_fetal_movements": "less movement from your baby",
    "find.polydipsia": "unusual thirst", "find.visual_disturbance": "changes in your sight",
    "find.haemoptysis": "blood in your cough",
}
PHRASE_PCM = {
    "find.fever_history": "fever", "find.cough_2_weeks": "cough wey don reach two weeks or more",
    "find.myalgia": "body pain", "find.dyspnoea": "wahala to breathe",
    "find.urinary_frequency": "to dey piss anyhow", "find.low_mood": "sad heart",
    "find.anhedonia": "say you no dey enjoy things again",
    "find.excessive_worry": "worry wey you no fit control",
    "find.reduced_fetal_movements": "say your baby no dey move like before",
    "find.polydipsia": "too much thirst", "find.visual_disturbance": "change for your eye",
    "find.haemoptysis": "blood for your cough",
}


@dataclass(frozen=True)
class Turn:
    role: str
    en: str
    pcm: str


def load(name: str) -> Any:
    return yaml.safe_load((KB / name).read_text(encoding="utf-8"))


PROPER = {"Plasmodium", "Lassa"}


def _a(text: str) -> str:
    return text[:1].upper() + text[1:]


def _mid(name: str) -> str:
    """The condition name inside a sentence: common nouns lower case, proper names kept."""
    first = name.split(" ")[0]
    return name if first.isupper() or first in PROPER else name[:1].lower() + name[1:]


def checkin(symptom: str, symptom_pcm: str, answer: str, rng: random.Random) -> list[Turn]:
    greeting = rng.choice([
        ("Good morning. I am your health assistant. How are you feeling today?",
         "Good morning. I be your health assistant. How body dey today?"),
        ("Hello. I am your health assistant. I would like to ask a few questions about your "
         "health.",
         "Hello. I be your health assistant. I wan ask you small question about your health."),
    ])
    turns = [Turn("assistant", *greeting),
             Turn("user", "I am not feeling well.", "My body no dey fine."),
             Turn("assistant", f"I am sorry to hear that. Do you have {symptom}?",
                  f"Sorry o. You get {symptom_pcm}?")]
    if answer == "yes":
        turns += [
            Turn("user", f"Yes, I have {symptom}.", f"Yes, I get {symptom_pcm}."),
            Turn("assistant", "Thank you for telling me. How many days have you had it?",
                 "Thank you for telling me. How many days you don get am?"),
            Turn("user", "It started three days ago.", "E start three days ago."),
            Turn("assistant", "I have written this in your record for your care team. If it gets "
                 "worse, go to the nearest clinic or hospital.",
                 "I don write am for your record for your care team. If e worse, go the nearest "
                 "clinic or hospital."),
        ]
    else:
        turns += [
            Turn("user", f"No, I do not have {symptom}.", f"No, I no get {symptom_pcm}."),
            Turn("assistant", "Thank you. I have written that in your record. Please tell me if "
                 "anything changes.",
                 "Thank you. I don write am for your record. Abeg tell me if anything change."),
        ]
    return turns


def explanation(condition: str, rng: random.Random) -> list[Turn]:
    ask = rng.choice([
        (f"What is {condition}?", f"Wetin be {condition}?"),
        (f"My doctor said I have {condition}. What does that mean?",
         f"My doctor talk say I get {condition}. Wetin that one mean?"),
    ])
    return [
        Turn("user", *ask),
        Turn("assistant", f"{_a(condition)} is a health condition that your care team has "
             "recorded for you. Your doctor or nurse can tell you more about it.",
             f"{_a(condition)} na health wahala wey your care team don write for your record. "
             "Your doctor or nurse fit tell you more about am."),
        Turn("user", "What should I do now?", "Wetin I suppose do now?"),
        Turn("assistant", "Take your medicines as your doctor told you and come to your next "
             "appointment. Contact your care team if you have questions.",
             "Take your medicine as your doctor talk and come for your next appointment. "
             "Contact your care team if you get question."),
    ]


def vaccine_reminder(vaccine: str, age: str, rng: random.Random) -> list[Turn]:
    return [
        Turn("assistant", f"Reminder: your child is due for {vaccine} at {age}.",
             f"Reminder: your pikin don reach time for {vaccine} at {age}."),
        Turn("user", "Where can I get it?", "Where I fit get am?"),
        Turn("assistant", "You can get it at your nearest health centre. Bring your child's "
             "immunisation card.",
             "You fit get am for your nearest health centre. Bring your pikin immunisation "
             "card."),
        Turn("user", "Thank you, I will go this week.", "Thank you, I go go this week."),
    ]


def support_reminder(action: str, action_pcm: str, rng: random.Random) -> list[Turn]:
    return [
        Turn("assistant", "I noticed that taking your medicine regularly may be hard. Would you "
             f"like help with this? One option is: {action}.",
             "I notice say to dey take your medicine every time fit hard. You wan make I help "
             f"you? One way na: {action_pcm}."),
        Turn("user", "Yes, please.", "Yes, abeg."),
        Turn("assistant", "I will tell your care team. They will contact you.",
             "I go tell your care team. Dem go contact you."),
    ]


def medicine_reminder(rng: random.Random) -> list[Turn]:
    time = rng.choice([("morning", "morning"), ("evening", "evening")])
    return [
        Turn("assistant", f"Good {time[0]}. It is time to take your medicine.",
             f"Good {time[1]}. Na time to take your medicine."),
        Turn("user", "I have taken it.", "I don take am."),
        Turn("assistant", "Thank you. I have recorded it.", "Thank you. I don record am."),
    ]


def consent(rng: random.Random) -> list[Turn]:
    return [
        Turn("user", "Who can see my health information?",
             "Who fit see my health information?"),
        Turn("assistant", "Only you and the people you allow can see it. Your care team uses it "
             "to look after you.",
             "Na only you and the people wey you allow fit see am. Your care team dey use am "
             "take care of you."),
        Turn("user", "Can I change my mind later?", "I fit change my mind later?"),
        Turn("assistant", "Yes. You can withdraw your consent at any time.",
             "Yes. You fit stop your consent any time."),
    ]


def age_text(dose: Mapping[str, Any]) -> str | None:
    for key, unit in (("age_weeks", "weeks"), ("age_months", "months"), ("age_years", "years")):
        if key in dose:
            n = dose[key]
            return "birth" if key == "age_weeks" and n == 0 else f"{n} {unit}"
    return None


def generate(count: int = 360, seed: int = 0) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    findings = [f for f in load("findings.yaml") if f.get("capture") == "question"]
    conditions = [_mid(c["name"].split(" (")[0]) for c in load("conditions.yaml")]
    doses = {(d["vaccine"], age) for d in load("vaccination_schedule.yaml")[0]["doses"]
             if (age := age_text(d))}
    actions = [(a["label"], PHRASE_PCM.get(a["id"], a["label"].lower()))
               for g in load("support_actions.yaml") for a in g["actions"]]
    out: list[dict[str, Any]] = []
    kinds = ["checkin", "explain", "vaccine", "support", "medicine", "consent"]
    weights = [0.4, 0.2, 0.15, 0.1, 0.1, 0.05]
    for i in range(count):
        kind = rng.choices(kinds, weights)[0]
        if kind == "checkin":
            f = rng.choice(findings)
            name = PHRASE.get(f["id"], f["name"].lower())
            turns = checkin(name, PHRASE_PCM.get(f["id"], name), rng.choice(["yes", "no"]), rng)
            slot = f["id"]
        elif kind == "explain":
            slot = rng.choice(conditions)
            turns = explanation(slot, rng)
        elif kind == "vaccine":
            vaccine, age = rng.choice(sorted(doses))
            slot = vaccine
            turns = vaccine_reminder(vaccine, age, rng)
        elif kind == "support":
            label, pcm = rng.choice(actions)
            slot = label
            turns = support_reminder(label[:1].lower() + label[1:], pcm, rng)
        elif kind == "medicine":
            slot = "medicine"
            turns = medicine_reminder(rng)
        else:
            slot = "consent"
            turns = consent(rng)
        out.append({"id": f"d{i:04d}", "kind": kind, "slot": slot,
                    "turns": [{"role": t.role, "en": t.en, "pcm": t.pcm} for t in turns]})
    return out


def unique_sentences(dialogues: list[dict[str, Any]]) -> list[str]:
    return sorted({t["en"] for d in dialogues for t in d["turns"]})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.language.dialogues")
    parser.add_argument("--count", type=int, default=360)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    dialogues = generate(args.count, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in dialogues) + "\n",
                        encoding="utf-8")
    print(f"{len(dialogues)} dialogues, {len(unique_sentences(dialogues))} unique sentences "
          f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
