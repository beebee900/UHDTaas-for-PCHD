"""Model cards of the four population models that run on simulators (design 03, 3.4).

Run `python -m population.cards` to write one card per model to
`docs/governance/model_cards/`.
"""

from __future__ import annotations

from pathlib import Path

from ahdt.models.cards import CARDS_DIR, render
from ahdt.models.params import ParamSet, Source
from atra import contracts as c
from atra.connectors import DTKind
from population import demography, epidemic, trial

HEART = "ahdt.cardiovascular.heart_chambers_and_valves"
COVASIM = ("Kerr CC, Stuart RM, Mistry D, Abeysuriya RG, Rosenfeld R, Hart G, et al. "
           "Covasim: an agent-based model of COVID-19 dynamics and interventions. PLoS "
           "Comput Biol. 2021;17(7):e1009149. doi:10.1371/journal.pcbi.1009149")


def _ports(items: dict[str, str]) -> list[c.ModelIO]:
    return [c.ModelIO(name=name, unit=unit) for name, unit in items.items()]


def _inputs(items: dict[str, str], origin: str = "input:scenario") -> list[c.ModelInput]:
    return [c.ModelInput(name=name, unit=unit, **{"from": origin})
            for name, unit in items.items()]


def _entry(model_id: str, use: str, paramset: ParamSet, *, inputs: dict[str, str],
           outputs: dict[str, str], depends_on: list[c.ModelRef] | None = None,
           source: str | None = None) -> c.ModelRegistryEntry:
    return c.ModelRegistryEntry(
        model_id=model_id, version="1.0.0", twin=DTKind.POPULATION,
        family=c.ModelFamily.SIMULATION, tier=c.Tier.T2, anatomy=None,
        inputs=_inputs(inputs), outputs=_ports(outputs), intended_use=use,
        explainers=["counterfactual.scenario"], depends_on=depends_on or [],
        source=source or paramset.citation())


def cards() -> dict[str, str]:
    malaria = epidemic.params()
    public_health = malaria.model_copy(update={
        "model_id": "ahdt.population.public_health",
        "sources": [*malaria.sources, Source(id="kerr2021", citation=COVASIM)]})
    prevalence = {"mean_prevalence": "1", "peak_prevalence": "1", "rainy_prevalence": "1",
                  "dry_prevalence": "1"}
    entries = [
        (_entry("ahdt.population.epidemiological",
                "Malaria prevalence through the year under bed net, vaccine and treatment "
                "coverage",
                malaria, inputs={"bednet_coverage": "1", "vaccine_coverage": "1",
                                 "treatment_coverage": "1"},
                outputs={**prevalence, "annual_eir": "/a", "mean_reproductive_number": "1"}),
         malaria,
         "Seasonal Ross-Macdonald model for one region. The mosquito density is calibrated to "
         "the kb prevalence of malaria in Lagos, so the baseline reproduces that prevalence "
         "by construction."),
        (_entry("ahdt.population.public_health",
                "Effect of testing, contact tracing, vaccination, bed nets and treatment on "
                "an epidemic",
                public_health,
                inputs={"test_prob": "1", "trace_prob": "1", "vaccine_coverage": "1",
                        "bednet_coverage": "1", "treatment_coverage": "1"},
                outputs={**prevalence, "new_infections": "{persons}/d",
                         "cum_infections": "{persons}"}),
         public_health,
         "The malaria scenarios use the parameters listed. The respiratory scenarios run "
         "Covasim 4 with its default COVID-19 parameters on a population of 2000 agents."),
        (_entry("ahdt.population.in_silico_trial",
                "Paired comparison of an antihypertensive scenario on a virtual cohort of "
                "twins",
                trial.params(),
                inputs={"subjects": "{persons}", "seed": "1"},
                outputs={"control_mean_sbp": "mm[Hg]", "treated_mean_sbp": "mm[Hg]",
                         "mean_difference": "mm[Hg]", "controlled_share_control": "1",
                         "controlled_share_treated": "1", "responder_share_10mmhg": "1"},
                depends_on=[c.ModelRef(model_id=HEART, version="1.0.0")],
                source=f"{trial.params().citation()}; the heart model {HEART}"),
         trial.params(),
         "The virtual cohort is drawn around the published heart parameters and an assumed "
         "resistance distribution. Differences between arms are model results, not trial "
         "evidence."),
        (_entry("ahdt.population.demographic",
                "Population by age group and sex over the next 20 years",
                demography.params(), inputs={"base_population": "{persons}", "steps": "1"},
                outputs={"total": "{persons}", "dependency_ratio": "1"}),
         demography.params(),
         "Cohort-component projection in five-year steps from assumed Lagos-like rates."),
    ]
    return {e.model_id: render(e, ps, note) for e, ps, note in entries}


def write_cards(directory: Path = CARDS_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for model_id, text in cards().items():
        path = directory / f"{model_id}.md"
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def main() -> None:
    print(f"wrote {len(write_cards())} population model cards")


if __name__ == "__main__":
    main()
