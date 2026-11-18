from ahdt.models.cards import CARDS_DIR, card
from ahdt.models.catalogue import default_catalogue
from ahdt.models.validation import VALIDATORS
from population import cards as population_cards

EXTERNAL = (
    "ahdt.cardiovascular.conduction_system_and_cardiomyocyte_electrophysiology",
    "ahdt.cardiovascular.aorta", "ahdt.endocrine.beta_cell_mass_dynamics",
    "ahdt.hepatobiliary.hepatocyte_metabolism_and_detoxification",
    "ahdt.endocrine.cortisol_metabolism_and_excretion", "ahdt.endocrine.gonadal_hormones",
    "ahdt.reproductive.menstrual_and_fertility_cycle",
    "ahdt.immune_lymphatic.t_cell_b_cell_and_macrophage", "ahdt.social.mobility",
    "ahdt.whole_body.whole_body_pbpk", "ahdt.whole_body.biomechanical_and_kinematic",
    "ahdt.musculoskeletal.skeletal_muscle_and_biomechanics",
)
POPULATION = ("ahdt.population.epidemiological", "ahdt.population.public_health",
              "ahdt.population.in_silico_trial", "ahdt.population.demographic")


def test_every_external_model_is_registered_with_a_check():
    catalogue = default_catalogue()
    for model_id in EXTERNAL:
        assert model_id in catalogue
        assert model_id in VALIDATORS


def test_cards_exist_for_every_external_and_population_model():
    for model_id in (*EXTERNAL, *POPULATION):
        text = (CARDS_DIR / f"{model_id}.md").read_text(encoding="utf-8")
        assert text.startswith(f"# {model_id}")
        assert "## Sources" in text


def test_external_cards_are_current():
    catalogue = default_catalogue()
    for model_id in EXTERNAL:
        stored = (CARDS_DIR / f"{model_id}.md").read_text(encoding="utf-8")
        current = card(catalogue[model_id], None)
        assert current.split("## Inputs")[1] == stored.split("## Inputs")[1]


def test_population_cards_are_current():
    for model_id, text in population_cards.cards().items():
        assert (CARDS_DIR / f"{model_id}.md").read_text(encoding="utf-8") == text
