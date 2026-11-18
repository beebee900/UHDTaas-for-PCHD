"""Training of the T1 models that use synthetic data (they run on the laptop).

    python -m evaluation.models.ahdt.train [model_id ...] [--persons N] [--root DIR]

Run it through `var/bin/heavy`. Training lives outside the service packages because it reads
the synthetic generators, which no service may import.

Each `train_*` function takes a population and an output directory and returns the
`Result` it wrote (`artifacts.py` layout).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd
from numpy.typing import NDArray
from sklearn.metrics import f1_score

from ahdt.models.ml import conformal, forecast, gnn, hmm, online, population, survival
from ahdt.models.ml import tabular as tab
from ahdt.models.ml.artifacts import Result, write_result
from ahdt.models.ml.common import split_of
from ahdt.models.ml.inventory import BY_ID
from evaluation.models.ahdt.fairness import ATTRIBUTES, slice_report
from synth import training as synthetic

type F = NDArray[np.float64]

type Population = tuple[list[dict[str, Any]], nx.Graph]
DATASET = "atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml)"
NEWS2_BANDS = (4, 6)
PROBLEM_BANDS = (1, 2)


def _version(model_id: str) -> str:
    return BY_ID[model_id].spec.version


def _hypoxaemia_threshold() -> float:
    from ahdt.models.reference import default_kb

    return float(default_kb().lookup("threshold.hypoxaemia_child", "below"))


def train_desaturation(pop: Population, out: Path, model_id: str, quick: bool = False) -> Result:
    df = synthetic.desaturation(pop[0])
    feats = ["spo2.mean", "spo2.min", "spo2.max", "spo2.n", "heart_rate.mean",
             "heart_rate.max"]
    task = tab.TabularTask(model_id, _version(model_id), DATASET, feats, edge=tab.EdgeExport(
        "spo2_desaturation", ("normal", "desaturation"), urgency="urgent",
        rule=("spo2.min", _hypoxaemia_threshold())),
        notes=["The rule threshold is kb threshold.hypoxaemia_child (children), applied to "
               "every age until an adult edge threshold is signed off."])
    return tab.train(task, df, out)


def train_falls(pop: Population, out: Path, model_id: str, quick: bool = False) -> Result:
    df = synthetic.falls(pop[0])
    feats = ["gait_speed.mean", "cadence.mean", "stride_time_cv.mean"]
    task = tab.TabularTask(model_id, _version(model_id), DATASET, feats, min_sensitivity=0.8,
                           edge=tab.EdgeExport("fall_risk", ("low", "high"), urgency="routine"))
    return tab.train(task, df, out)


def train_exacerbation(pop: Population, out: Path, model_id: str, quick: bool = False) -> Result:
    df = synthetic.exacerbation(pop[0])
    feats = ["pef_pct_best", "symptom_score", "night_waking", "reliever_puffs", "pm25",
             "viral_illness", "adherence", "prior_exacerbations", "age_years"]
    return tab.train(tab.TabularTask(model_id, _version(model_id), DATASET, feats), df, out)


def train_sickle(pop: Population, out: Path, model_id: str, quick: bool = False) -> Result:
    df = synthetic.sickle_crisis(pop[0])
    feats = ["hb", "hbf", "infection", "dehydration", "temperature", "hydroxyurea",
             "age_years"]
    return tab.train(tab.TabularTask(model_id, _version(model_id), DATASET, feats), df, out)


# -- ward trajectories: NEWS2, deterioration, clinical state -------------------------------

def _news2_scores(ward: pd.DataFrame) -> pd.DataFrame:
    from ahdt.models.reference import default_kb
    from ahdt.models.whole_body.early_warning import news2

    table = default_kb().entry("news2.scoring").content()
    comps = [news2({**r, "consciousness": "alert"}, table)
             for r in ward[list(synthetic.VITALS)].to_dict("records")]
    scores = pd.DataFrame(comps, index=ward.index)
    return ward.assign(news2=scores.sum(axis=1),
                       abnormal=(scores[["respiration_rate", "spo2", "systolic_bp", "pulse",
                                         "temperature"]] > 0).sum(axis=1))


def deterioration_table(ward: pd.DataFrame, window: int) -> pd.DataFrame:
    rows = []
    for _, g in ward.groupby("hdt_id"):
        g = g.sort_values("t").reset_index(drop=True)
        crit = (g.state == "critical").to_numpy()
        for t in range(6, len(g) - window):
            if crit[t]:
                continue
            r = g.loc[t]
            prev = g.loc[t - 6]
            rows.append({"hdt_id": r.hdt_id, "t": t, "news2": r.news2, "age_years": r.age_years,
                         **{v: r[v] for v in synthetic.VITALS},
                         **{f"d6.{v}": r[v] - prev[v] for v in synthetic.VITALS},
                         "label": int(crit[t + 1:t + 1 + window].any()),
                         **{a: r[a] for a in ATTRIBUTES}})
    return pd.DataFrame(rows)


def _ward(pop: Population) -> pd.DataFrame:
    return _news2_scores(synthetic.ward(pop[0]))


def train_deterioration(pop: Population, out: Path, model_id: str, quick: bool = False) -> Result:
    window = int(synthetic.config()["ward"]["deterioration_window_hours"])
    df = deterioration_table(_ward(pop), window)
    feats = ["news2", "age_years", *synthetic.VITALS, *(f"d6.{v}" for v in synthetic.VITALS)]
    return tab.train(tab.TabularTask(model_id, _version(model_id), DATASET, feats), df, out)


def _clinical_obs(g: pd.DataFrame) -> NDArray[np.int64]:
    return np.column_stack([np.digitize(g.news2, NEWS2_BANDS, right=True),
                            np.digitize(g.problems, PROBLEM_BANDS, right=True),
                            np.minimum(g.abnormal, 3)]).astype(np.int64)


def train_clinical_state(pop: Population, out: Path, model_id: str, quick: bool = False) -> Result:
    ward = _ward(pop)
    states = list(synthetic.config()["ward"]["states"])
    seqs = {h: g.sort_values("t") for h, g in ward.groupby("hdt_id")}
    split = {h: split_of(h) for h in seqs}
    train_ids = [h for h in seqs if split[h] == "train"]
    model = hmm.CategoricalHmm.fit(
        states, ["news2_band", "problem_band", "abnormal_vitals"], [3, 3, 4],
        [[states.index(s) for s in seqs[h].state] for h in train_ids],
        [_clinical_obs(seqs[h]) for h in train_ids])
    y, pred, proba, rows = [], [], [], []
    for h in (h for h in seqs if split[h] == "test"):
        g = seqs[h]
        alpha, _ = model.posteriors(_clinical_obs(g))
        y += [states.index(s) for s in g.state]
        pred += list(alpha.argmax(axis=1))
        proba.append(alpha)
        rows += [g.iloc[0][list(ATTRIBUTES)].to_dict()] * len(g)
    yy, pp = np.asarray(y), np.concatenate(proba)
    macro = float(f1_score(yy, pred, average="macro"))
    acc = float((yy == np.asarray(pred)).mean())
    groups = {a: [r[a] for r in rows] for a in ATTRIBUTES}
    report = slice_report(model_id, "multiclass", yy, pp, groups)
    out.mkdir(parents=True, exist_ok=True)
    hmm.save(model, out / "model.json", news2_bands=list(NEWS2_BANDS),
             problem_bands=list(PROBLEM_BANDS))
    result = Result(model_id, _version(model_id), DATASET, "macro_f1_filtered", macro,
                    {"macro_f1_filtered": macro, "accuracy_filtered": acc},
                    report.to_dict(), split={k: sum(v == k for v in split.values())
                                             for k in ("train", "cal", "test")}
                    | {"unit": "ward stay"},
                    notes=["Filtered (forward) posteriors, as used online; NEWS2 from "
                           "kb news2.scoring with every patient alert and on air."])
    write_result(result, out, fairness_md=report.markdown())
    return result


def _fit(quick: bool, epochs: int = 15) -> dict[str, Any]:
    """Training length of a forecaster; `quick` is for tests."""
    return {"epochs": 1, "width": 16} if quick else {"epochs": epochs}


def train_news2_forecast(pop: Population, out: Path, model_id: str, quick: bool = False) -> Result:
    cfg = synthetic.config()["ward"]
    ward = synthetic.ward(pop[0])
    task = forecast.ForecastTask(model_id, _version(model_id), DATASET, list(synthetic.VITALS),
                                 history=int(cfg["history_hours"]),
                                 horizon=int(cfg["horizon_hours"]), **_fit(quick, 20))
    return forecast.train(task, ward, out)


def train_bp_forecast(pop: Population, out: Path, model_id: str, quick: bool = False) -> Result:
    cfg = synthetic.config()["home_bp"]
    per_day = len(cfg["hours"])
    task = forecast.ForecastTask(model_id, _version(model_id), DATASET, ["sbp", "dbp"],
                                 history=int(cfg["history_days"]) * per_day,
                                 horizon=int(cfg["horizon_days"]) * per_day, **_fit(quick))
    return forecast.train(task, synthetic.home_bp(pop[0]), out)


def train_glucose_forecast(pop: Population, out: Path, model_id: str,
                           quick: bool = False) -> Result:
    cfg = synthetic.config()["glucose"]
    per_day = len(cfg["hours"])
    task = forecast.ForecastTask(model_id, _version(model_id), DATASET, ["glucose"],
                                 history=int(cfg["history_days"]) * per_day,
                                 horizon=int(cfg["horizon_days"]) * per_day, **_fit(quick))
    return forecast.train(task, synthetic.glucose(pop[0]), out)


# -- behaviour, social, population ----------------------------------------------------------

def train_mental_health(pop: Population, out: Path, model_id: str, quick: bool = False) -> Result:
    df = synthetic.mental_health(pop[0])
    states = list(synthetic.config()["mental_health"]["states"])
    seqs = {h: g.sort_values("t") for h, g in df.groupby("hdt_id")}
    split = {h: split_of(h) for h in seqs}
    obs = {h: g[["phq9", "gad7"]].to_numpy(dtype=float) for h, g in seqs.items()}
    train_ids = [h for h in seqs if split[h] == "train"]
    model = hmm.GaussianHmm.fit(states, ["phq9", "gad7"],
                                [seqs[h].state.tolist() for h in train_ids],
                                [obs[h] for h in train_ids])

    def next_predictions(kind: str) -> tuple[F, F, list[dict[str, Any]]]:
        y, p, rows = [], [], []
        for h in (h for h in seqs if split[h] == kind):
            o = obs[h]
            for t in range(3, len(o)):
                _, expected = model.next_mean(o[:t])
                y.append(o[t, 0])
                p.append(expected[0])
                rows.append(seqs[h].iloc[0][list(ATTRIBUTES)].to_dict())
        return np.asarray(y), np.asarray(p), rows

    y_cal, p_cal, _ = next_predictions("cal")
    y_test, p_test, rows = next_predictions("test")
    half = conformal.regression_halfwidth(y_cal, p_cal, 0.9)
    covered = conformal.interval_covers(y_test, p_test, half)
    z_true, z_pred = [], []
    for h in (h for h in seqs if split[h] == "test"):
        _, smooth = model.posteriors(obs[h])
        z_true += seqs[h].state.tolist()
        z_pred += list(smooth.argmax(axis=1))
    mae = float(np.abs(y_test - p_test).mean())
    metrics = {"mae_next_phq9": mae, "coverage_90": float(covered.mean()),
               "halfwidth_90": half, "state_macro_f1": float(f1_score(z_true, z_pred,
                                                                       average="macro"))}
    report = slice_report(model_id, "regression", y_test, p_test,
                          {a: [r[a] for r in rows] for a in ATTRIBUTES}, covered=covered)
    out.mkdir(parents=True, exist_ok=True)
    hmm.save(model, out / "model.json", phq9_halfwidth_90=half)
    result = Result(model_id, _version(model_id), DATASET, "mae_next_phq9", mae, metrics,
                    report.to_dict(), split={k: sum(v == k for v in split.values())
                                             for k in ("train", "cal", "test")}
                    | {"unit": "person"})
    write_result(result, out, fairness_md=report.markdown())
    return result


def train_lifestyle(pop: Population, out: Path, model_id: str, quick: bool = False) -> Result:
    fields = list(synthetic.config()["lifestyle"]["fields"])
    return online.train(model_id, _version(model_id), DATASET, synthetic.lifestyle(pop[0]),
                        fields, out)


def train_adherence(pop: Population, out: Path, model_id: str, quick: bool = False) -> Result:
    df = synthetic.adherence(pop[0])
    covs = ["age_years", "pills_per_day", "distance_km", "low_income", "insured",
            "depression"]
    return survival.train(model_id, _version(model_id), DATASET, df, covs, out)


def train_social(pop: Population, out: Path, model_id: str, quick: bool = False) -> Result:
    df, graph = synthetic.social(*pop)
    feats = ["age_years", "female", "low_income", "insured", "tertiary_education", "chronic"]
    return gnn.train(model_id, _version(model_id), DATASET, df, graph, feats, out)


def _person_frame(persons: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    from ahdt.models.ml.slices import person_slices

    return pd.DataFrame([{"hdt_id": p["hdt_id"], "age_years": p["age_years"],
                          **{c: int(c in p["conditions"]) for c in population.CONDITIONS},
                          **person_slices(p)} for p in persons])


def train_cohort(pop: Population, out: Path, model_id: str, quick: bool = False) -> Result:
    persons = _person_frame(pop[0])
    truth = pd.DataFrame([synthetic.chronic_probability(p) for p in pop[0]])
    return population.train_cohort(model_id, _version(model_id), persons, truth, out)


def train_priors(pop: Population, out: Path, model_id: str, quick: bool = False) -> Result:
    from synth.conditions import MONTHS, episodes
    from synth.population import Person

    persons = _person_frame(pop[0])
    objs = [Person(**{k: v for k, v in p.items()}) for p in pop[0]]
    seed = int(synthetic.config()["population"]["seed"])
    sick = {(e.hdt_id, MONTHS[e.onset.month - 1]) for e in episodes(objs, seed)}
    under5 = [p for p in pop[0] if p["age_years"] < 5]
    ep = pd.DataFrame([{"hdt_id": p["hdt_id"], "month": m,
                        population.MALARIA: int((p["hdt_id"], m) in sick)}
                       for p in under5 for m in MONTHS])
    bp = synthetic.home_bp(pop[0]).query("t == 0")[["hdt_id", "sbp"]]
    gl = synthetic.glucose(pop[0]).query("t == 0")[["hdt_id", "glucose"]]
    fields = bp.merge(gl, on="hdt_id").merge(
        persons[["hdt_id", *ATTRIBUTES]], on="hdt_id")
    return population.train_priors(model_id, _version(model_id), persons, ep, fields, out)


TRAINERS: Mapping[str, Callable[[Population, Path, str, bool], Result]] = {
    "ahdt.cardiovascular.blood_pressure_forecasting": train_bp_forecast,
    "ahdt.endocrine.glucose_forecasting": train_glucose_forecast,
    "ahdt.whole_body.news2_component_forecasting": train_news2_forecast,
    "ahdt.respiratory.spo2_desaturation_detection": train_desaturation,
    "ahdt.respiratory.exacerbation_risk": train_exacerbation,
    "ahdt.haematological.anaemia_and_sickle_cell_crisis_risk": train_sickle,
    "ahdt.musculoskeletal.gait_and_fall_risk": train_falls,
    "ahdt.whole_body.deterioration_risk": train_deterioration,
    "ahdt.whole_body.clinical_health_state": train_clinical_state,
    "ahdt.behavioural_cognitive.mental_health_trajectory": train_mental_health,
    "ahdt.behavioural_cognitive.lifestyle": train_lifestyle,
    "ahdt.behavioural_cognitive.adherence": train_adherence,
    "ahdt.social.social_network": train_social,
    "ahdt.population.cohort": train_cohort,
    "ahdt.population.population_priors_and_norms": train_priors,
}


def train(model_ids: Sequence[str], root: Path, *, persons: int | None = None,
          seed: int | None = None, quick: bool = False) -> dict[str, Result]:
    """Train the given laptop models into `root/<model_id>/`. `quick` shortens the
    forecasters' training (tests)."""
    pop = synthetic.population(persons, seed)
    return {m: TRAINERS[m](pop, root / m, m, quick) for m in model_ids}


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from ahdt.models.ml.artifacts import LAPTOP_ROOT

    parser = argparse.ArgumentParser(prog="python -m evaluation.models.ahdt.train")
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--persons", type=int)
    parser.add_argument("--root", type=Path, default=LAPTOP_ROOT)
    args = parser.parse_args(argv)
    results = train(args.ids or list(TRAINERS), args.root, persons=args.persons)
    for model_id, result in results.items():
        print(f"{model_id}: {result.metric} = {result.value:.4g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
