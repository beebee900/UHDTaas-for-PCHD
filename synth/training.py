"""Synthetic training data of the T1 models (parameters in `training.yaml`).

The population is WP02's: `synth.population.generate` + `synth.conditions.assign_chronic`
(persons, households, LGA small-world network, sourced chronic priors). Each generator adds
one task's series, events and labels with a seed derived from the person id, so a person's
data do not change with the population size. Tests use a small population; full training
uses the `population` block of `training.yaml`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd
from numpy.typing import NDArray

from ahdt.models.ml.slices import person_slices
from synth.conditions import CHRONIC, assign_chronic
from synth.population import generate

CONFIG = Path(__file__).with_name("training.yaml")
RESPIRATORY = ("cond.asthma", "cond.copd")
type Person = Mapping[str, Any]


@lru_cache(maxsize=1)
def config() -> Mapping[str, Any]:
    import yaml

    data: Mapping[str, Any] = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return data


def rng_for(hdt_id: str, task: str) -> np.random.Generator:
    seed = int.from_bytes(hashlib.sha256(f"{hdt_id}|{task}".encode()).digest()[:8], "big")
    return np.random.default_rng(seed)


def population(n: int | None = None, seed: int | None = None
               ) -> tuple[list[dict[str, Any]], nx.Graph]:
    cfg = config()["population"]
    persons, graph = generate(n or int(cfg["persons"]), seed if seed is not None
                              else int(cfg["seed"]))
    assign_chronic(persons, seed if seed is not None else int(cfg["seed"]))
    return [p.record() for p in persons], graph


def chronic_probability(person: Person) -> dict[str, float]:
    """The WP02 prior probability of each chronic condition for this person."""
    from synth.population import Person as P

    p = P(**{k: v for k, v in person.items() if k != "conditions"})
    return {cond: float(fn(p)) for cond, fn in CHRONIC.items()}


def _with_slices(rows: list[dict[str, Any]], persons: Mapping[str, Person]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    sl = pd.DataFrame([person_slices(persons[h]) | {"hdt_id": h} for h in df.hdt_id.unique()])
    return df.merge(sl, on="hdt_id", how="left")


def _by_id(persons: Sequence[Person]) -> dict[str, Person]:
    return {str(p["hdt_id"]): p for p in persons}


def _ar(rng: np.random.Generator, n: int, phi: float, sd: float) -> NDArray[np.float64]:
    e = rng.normal(0, sd, n)
    out = np.empty(n)
    acc = 0.0
    for i in range(n):
        acc = phi * acc + e[i]
        out[i] = acc
    return out


# -- series -------------------------------------------------------------------------------

def home_bp(persons: Sequence[Person]) -> pd.DataFrame:
    """Twice-daily home SBP/DBP of adults: one row per reading."""
    cfg = config()["home_bp"]
    s, d = cfg["sbp"], cfg["dbp"]
    hours = list(cfg["hours"])
    rows = []
    for p in persons:
        if p["age_years"] < 18:
            continue
        rng = rng_for(p["hdt_id"], "home_bp")
        mu = (s["intercept"] + s["per_year_over_40"] * max(0, p["age_years"] - 40)
              + s["male"] * (p["sex"] == "male")
              + s["hypertension"] * ("cond.hypertension" in p["conditions"])
              + rng.normal(0, s["person_sd"]))
        n = cfg["days"] * len(hours)
        drift = np.repeat(np.cumsum(rng.normal(0, s["drift_sd_per_day"], cfg["days"])),
                          len(hours))
        morning = np.tile([s["morning"] if h < 12 else 0.0 for h in hours], cfg["days"])
        true = mu + drift + morning + _ar(rng, n, s["ar"], s["ar_sd"])
        sbp = true + rng.normal(0, s["noise_sd"], n)
        dbp = d["ratio"] * true + d["offset"] + rng.normal(0, d["noise_sd"], n)
        for i in range(n):
            rows.append({"hdt_id": p["hdt_id"], "t": i, "day": i // len(hours),
                         "hour": hours[i % len(hours)], "sbp": float(sbp[i]),
                         "dbp": float(dbp[i])})
    return _with_slices(rows, _by_id(persons))


def glucose(persons: Sequence[Person]) -> pd.DataFrame:
    """Four capillary glucose readings a day (mmol/L) of adults."""
    cfg = config()["glucose"]
    hours = list(cfg["hours"])
    rows = []
    for p in persons:
        if p["age_years"] < 18:
            continue
        rng = rng_for(p["hdt_id"], "glucose")
        dm = "cond.diabetes_type2" in p["conditions"]
        fasting = (cfg["fasting"]["diabetes" if dm else "normal"]
                   + rng.normal(0, cfg["fasting"]["person_sd"]))
        factor = cfg["diabetes_meal_factor"] if dm else 1.0
        n = cfg["days"] * len(hours)
        rise = np.tile([cfg["meal_rise"].get(h, 0.0) * factor for h in hours], cfg["days"])
        day = np.repeat(rng.normal(0, cfg["day_sd"], cfg["days"]), len(hours))
        g = fasting + rise + day + _ar(rng, n, cfg["ar"], cfg["noise_sd"])
        g = np.clip(g, 2.2, 30.0)
        for i in range(n):
            rows.append({"hdt_id": p["hdt_id"], "t": i, "day": i // len(hours),
                         "hour": hours[i % len(hours)], "glucose": float(g[i])})
    return _with_slices(rows, _by_id(persons))


VITALS = ("respiration_rate", "spo2", "systolic_bp", "pulse", "temperature")


def ward(persons: Sequence[Person]) -> pd.DataFrame:
    """Hourly vital signs of ward stays with the true clinical state of every hour."""
    cfg = config()["ward"]
    states = list(cfg["states"])
    trans = np.array([[cfg["transition_per_hour"][a].get(b, 0.0) for b in states]
                      for a in states])
    trans /= trans.sum(axis=1, keepdims=True)
    rows = []
    for p in persons:
        if p["age_years"] < 16:
            continue
        rng = rng_for(p["hdt_id"], "ward")
        if rng.random() >= cfg["stay_share"]:
            continue
        h = int(cfg["hours"])
        z = np.empty(h, dtype=int)
        z[0] = rng.choice(len(states), p=cfg["start"])
        for t in range(1, h):
            z[t] = rng.choice(len(states), p=trans[z[t - 1]])
        values = {}
        for v in VITALS:
            mean = np.asarray(cfg["means"][v], dtype=float)[z]
            values[v] = mean + _ar(rng, h, cfg["ar"], cfg["sd"][v])
        values["spo2"] = np.clip(values["spo2"], 70, 100)
        problems = rng.poisson([cfg["problems"][states[k]] for k in z])
        for t in range(h):
            rows.append({"hdt_id": p["hdt_id"], "t": t, "state": states[z[t]],
                         "problems": int(problems[t]), "age_years": p["age_years"],
                         **{v: float(values[v][t]) for v in VITALS}})
    return _with_slices(rows, _by_id(persons))


def mental_health(persons: Sequence[Person]) -> pd.DataFrame:
    """Two-weekly PHQ-9 and GAD-7 totals of adults with the true severity state."""
    cfg = config()["mental_health"]
    k = len(cfg["states"])
    stay = float(cfg["stay"])
    trans = np.full((k, k), 0.0)
    for i in range(k):
        nb = [j for j in (i - 1, i + 1) if 0 <= j < k]
        trans[i, i] = stay
        for j in nb:
            trans[i, j] = (1 - stay) / len(nb)
    rows = []
    for p in persons:
        if p["age_years"] < 18:
            continue
        rng = rng_for(p["hdt_id"], "mental_health")
        z = [int(rng.choice(k, p=cfg["start"]))]
        for _ in range(cfg["visits"] - 1):
            z.append(int(rng.choice(k, p=trans[z[-1]])))
        for t, s in enumerate(z):
            rows.append({"hdt_id": p["hdt_id"], "t": t, "state": int(s),
                         "phq9": float(np.clip(round(rng.normal(cfg["phq9_mean"][s], cfg["sd"])),
                                               0, 27)),
                         "gad7": float(np.clip(round(rng.normal(cfg["gad7_mean"][s], cfg["sd"])),
                                               0, 21))})
    return _with_slices(rows, _by_id(persons))


# -- tabular tasks ------------------------------------------------------------------------

def _logit(x: float) -> float:
    return float(1.0 / (1.0 + np.exp(-x)))


def desaturation(persons: Sequence[Person]) -> pd.DataFrame:
    """5-minute oximetry windows summarised as the edge feature window statistics."""
    cfg = config()["desaturation"]
    n = int(cfg["window_s"])
    rows = []
    for p in persons:
        rng = rng_for(p["hdt_id"], "desaturation")
        resp = any(c in p["conditions"] for c in RESPIRATORY)
        base = (cfg["spo2"]["baseline"] + cfg["spo2"]["respiratory"] * resp
                + rng.normal(0, cfg["spo2"]["person_sd"]))
        hr0 = rng.normal(cfg["heart_rate"]["baseline"], cfg["heart_rate"]["sd"])
        for w in range(int(cfg["windows_per_person"])):
            spo2 = base + rng.normal(0, cfg["spo2"]["noise_sd"], n)
            hr = hr0 + rng.normal(0, 2.0, n)
            label = 0
            if rng.random() < cfg["event"]["p"]:
                depth = rng.uniform(*cfg["event"]["depth"])
                dur = int(rng.integers(*cfg["event"]["duration_s"]))
                start = int(rng.integers(0, n - dur))
                spo2[start:start + dur] -= depth
                hr[start:start + dur] += cfg["heart_rate"]["per_point_drop"] * depth
                label = int(depth >= cfg["label_min_drop"]
                            and dur >= cfg["label_min_duration_s"])
            if rng.random() < cfg["artefact"]["p"]:
                depth = rng.uniform(*cfg["artefact"]["depth"])
                dur = int(rng.integers(*cfg["artefact"]["duration_s"]))
                start = int(rng.integers(0, n - dur))
                spo2[start:start + dur] -= depth
            spo2 = np.clip(np.round(spo2), 50, 100)
            rows.append({"hdt_id": p["hdt_id"], "window": w, "label": label,
                         "spo2.mean": float(spo2.mean()), "spo2.min": float(spo2.min()),
                         "spo2.max": float(spo2.max()), "spo2.n": float(n),
                         "heart_rate.mean": float(hr.mean()), "heart_rate.max": float(hr.max())})
    return _with_slices(rows, _by_id(persons))


def exacerbation(persons: Sequence[Person]) -> pd.DataFrame:
    """Weekly asthma/COPD features with an exacerbation in the next 14 days as the label."""
    cfg = config()["exacerbation"]
    b = cfg["logit"]
    rows = []
    for p in persons:
        rng = rng_for(p["hdt_id"], "exacerbation")
        if not (any(c in p["conditions"] for c in RESPIRATORY) or rng.random() < cfg["share"]):
            continue
        prior = int(rng.poisson(0.8))
        adherence = float(rng.beta(4, 2))
        for wk in range(int(cfg["weeks"])):
            viral = int(rng.random() < 0.08)
            pef = float(np.clip(rng.normal(85 - 12 * viral, 10), 30, 110))
            symptoms = int(np.clip(rng.poisson(1 + 2 * viral), 0, 6))
            night = int(np.clip(rng.poisson(0.5 + 1.5 * viral), 0, 7))
            reliever = float(rng.poisson(4 + 8 * viral))
            pm25 = float(max(5.0, rng.normal(45, 15)))
            x = (b["intercept"] + b["pef_deficit_per_10pct"] * max(0.0, 100 - pef) / 10
                 + b["symptom_score"] * symptoms + b["night_waking"] * night
                 + b["reliever_per_10"] * reliever / 10 + b["pm25_per_10"] * pm25 / 10
                 + b["viral"] * viral + b["adherence"] * adherence
                 + b["prior_exacerbations"] * prior)
            rows.append({"hdt_id": p["hdt_id"], "week": wk, "pef_pct_best": pef,
                         "symptom_score": symptoms, "night_waking": night,
                         "reliever_puffs": reliever, "pm25": pm25, "viral_illness": viral,
                         "adherence": adherence, "prior_exacerbations": prior,
                         "age_years": p["age_years"], "label": int(rng.random() < _logit(x))})
    return _with_slices(rows, _by_id(persons))


def sickle_crisis(persons: Sequence[Person]) -> pd.DataFrame:
    """Monthly features of an HbSS cohort drawn from the WP02 persons' demographics.

    HbSS is rare in a population sample, so the cohort takes `cohort` persons and gives each
    the HbSS genotype for this task only.
    """
    cfg = config()["sickle_crisis"]
    b = cfg["logit"]
    rows = []
    for p in list(persons)[: int(cfg["cohort"])]:
        rng = rng_for(p["hdt_id"], "sickle_crisis")
        hb0 = rng.normal(cfg["hb"]["mean"], cfg["hb"]["sd"])
        hbf = float(np.clip(rng.normal(cfg["hbf"]["mean"], cfg["hbf"]["sd"]), 0.5, 35))
        hu = int(rng.random() < 0.3)
        for m in range(int(cfg["months"])):
            infection = int(rng.random() < 0.1)
            dehydration = int(np.clip(rng.poisson(0.6), 0, 3))
            temp = float(rng.normal(36.9 + 1.2 * infection, 0.4))
            hb = float(hb0 + rng.normal(0, 0.5) - 0.6 * infection)
            x = (b["intercept"] + b["hb_below_8"] * max(0.0, 8 - hb)
                 + b["hbf_per_5pct"] * hbf / 5 + b["infection"] * infection
                 + b["dehydration"] * dehydration + b["fever"] * (temp >= 38.0)
                 + b["hydroxyurea"] * hu)
            rows.append({"hdt_id": p["hdt_id"], "month": m, "hb": hb, "hbf": hbf,
                         "infection": infection, "dehydration": dehydration,
                         "temperature": temp, "hydroxyurea": hu,
                         "age_years": p["age_years"], "label": int(rng.random() < _logit(x))})
    return _with_slices(rows, _by_id(persons))


def falls(persons: Sequence[Person]) -> pd.DataFrame:
    """Gait windows of adults over `min_age` with a fall in the next six months as the label."""
    cfg = config()["falls"]
    b = cfg["logit"]
    rows = []
    for p in persons:
        if p["age_years"] < cfg["min_age"]:
            continue
        rng = rng_for(p["hdt_id"], "falls")
        over = p["age_years"] - cfg["min_age"]
        speed = float(max(0.2, rng.normal(cfg["gait_speed"]["intercept"]
                                          + cfg["gait_speed"]["per_year_over_50"] * over,
                                          cfg["gait_speed"]["sd"])))
        cadence = float(rng.normal(cfg["cadence"]["intercept"]
                                   + cfg["cadence"]["per_mps"] * (speed - 1.0),
                                   cfg["cadence"]["sd"]))
        cv = float(max(0.5, rng.normal(cfg["stride_time_cv"]["intercept"]
                                       + cfg["stride_time_cv"]["per_year_over_50"] * over
                                       + cfg["stride_time_cv"]["slow_gait"] * (speed < 1.0),
                                       cfg["stride_time_cv"]["sd"])))
        x = (b["intercept"] + b["gait_speed_below_1"] * max(0.0, 1.0 - speed)
             + b["stride_cv_per_pct"] * cv
             + b["cadence_below_100_per_10"] * max(0.0, 100 - cadence) / 10)
        rows.append({"hdt_id": p["hdt_id"], "gait_speed.mean": speed, "cadence.mean": cadence,
                     "stride_time_cv.mean": cv, "label": int(rng.random() < _logit(x))})
    return _with_slices(rows, _by_id(persons))


def adherence(persons: Sequence[Person]) -> pd.DataFrame:
    """Time from first dispensing to the first refill gap, with censoring at follow-up."""
    cfg = config()["adherence"]
    b = cfg["log_hr"]
    rows = []
    for p in persons:
        if not any(c in p["conditions"] for c in cfg["conditions"]):
            continue
        rng = rng_for(p["hdt_id"], "adherence")
        pills = int(rng.integers(cfg["pills_per_day"][0], cfg["pills_per_day"][1] + 1))
        distance = float(max(0.2, rng.normal(cfg["distance_km"]["mean"],
                                             cfg["distance_km"]["sd"])))
        depression = int(rng.random() < cfg["depression_p"])
        low = int(p["sdoh"]["income_band"] == "low")
        insured = int(bool(p["sdoh"]["nhia_insured"]))
        lin = (b["age_per_decade_under_40"] * max(0, 40 - p["age_years"]) / 10
               + b["pills_per_day"] * pills + b["distance_per_5km"] * distance / 5
               + b["low_income"] * low + b["insured"] * insured + b["depression"] * depression)
        t = float(rng.exponential(1.0 / (cfg["base_hazard_per_d"] * np.exp(lin))))
        follow = float(cfg["follow_up_d"])
        rows.append({"hdt_id": p["hdt_id"], "age_years": p["age_years"],
                     "pills_per_day": pills, "distance_km": distance, "low_income": low,
                     "insured": insured, "depression": depression,
                     "duration_d": min(t, follow), "event": int(t <= follow)})
    return _with_slices(rows, _by_id(persons))


def lifestyle(persons: Sequence[Person]) -> pd.DataFrame:
    """Daily activity, sleep and screen time with injected anomaly days (label)."""
    cfg = config()["lifestyle"]
    rows = []
    for p in persons:
        if p["age_years"] < 12:
            continue
        rng = rng_for(p["hdt_id"], "lifestyle")
        level = {f: rng.normal(v["mean"], v["person_sd"]) for f, v in cfg["fields"].items()}
        for d in range(int(cfg["days"])):
            anomaly = int(d >= 14 and rng.random() < cfg["anomaly"]["p_per_day"])
            row: dict[str, Any] = {"hdt_id": p["hdt_id"], "day": d, "label": anomaly}
            for f, v in cfg["fields"].items():
                x = level[f] + rng.normal(0, v["day_sd"])
                if anomaly:
                    x *= 1.0 + cfg["anomaly"][f]
                row[f] = float(max(0.0, x))
            rows.append(row)
    return _with_slices(rows, _by_id(persons))


def social(persons: Sequence[Person], graph: nx.Graph) -> tuple[pd.DataFrame, nx.Graph]:
    """Node features and the support-availability label of every person in the network."""
    cfg = config()["social"]
    b = cfg["logit"]
    lo, hi = cfg["working_age"]
    by_id = _by_id(persons)
    rows = []
    for p in persons:
        h = str(p["hdt_id"])
        rng = rng_for(h, "social")
        household = [by_id[n] for n, _, k in _edges(graph, h) if k == "household"]
        community = [by_id[n] for n, _, k in _edges(graph, h) if k != "household"]
        working = sum(lo <= q["age_years"] < hi for q in household)
        better_off = sum(q["sdoh"]["income_band"] != "low" for q in community)
        low = int(p["sdoh"]["income_band"] == "low")
        x = (b["intercept"] + b["working_adult_household"] * working
             + b["community_not_low_income"] * better_off + b["own_low_income"] * low
             + b["own_age_over_70"] * (p["age_years"] > 70))
        rows.append({"hdt_id": h, "age_years": p["age_years"],
                     "female": int(p["sex"] == "female"), "low_income": low,
                     "insured": int(bool(p["sdoh"]["nhia_insured"])),
                     "tertiary_education": int(p["sdoh"]["education"] == "tertiary"),
                     "chronic": len(p["conditions"]), "label": int(rng.random() < _logit(x))})
    return _with_slices(rows, by_id), graph


def _edges(graph: nx.Graph, node: str) -> list[tuple[str, str, str]]:
    if node not in graph:
        return []
    return [(str(n), node, str(graph.edges[node, n].get("kind", ""))) for n in graph[node]]
