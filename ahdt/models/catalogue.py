"""The Layer 4 models and the organ instances they hold (design 04, 4.5).

The catalogue builds every mechanistic (T2) and reference-state (T3) model, maps each
shared organ instance to its primary model, registers the models with their validation
results, and creates a person's instances on AHDT creation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from ahdt.models.base import Layer4Base
from ahdt.models.cardiovascular.baroreflex import BaroreflexModel
from ahdt.models.cardiovascular.heart import HeartModel
from ahdt.models.cardiovascular.vasculature import VasculatureModel
from ahdt.models.digestive.absorption import AbsorptionModel
from ahdt.models.digestive.nutrition import NutritionModel
from ahdt.models.endocrine.glucose_insulin import GlucoseInsulinModel, MinimalModel
from ahdt.models.endocrine.hormone_kinetics import HormoneKineticsModel
from ahdt.models.endocrine.hpa import HpaModel
from ahdt.models.endocrine.pineal import PinealModel
from ahdt.models.external.agent_models import ImmuneResponseModel, MobilityModel
from ahdt.models.external.aorta import AortaModel
from ahdt.models.external.opencarp import CardiacElectrophysiologyModel
from ahdt.models.external.opensim_gait import BiomechanicalKinematicModel, SkeletalMuscleModel
from ahdt.models.external.pbpk import WholeBodyPbpkModel
from ahdt.models.external.sbml_models import (
    BetaCellMassModel,
    CortisolDispositionModel,
    GonadalHormonesModel,
    HepatocyteGlucoseModel,
    MenstrualCycleModel,
)
from ahdt.models.haematological.erythropoiesis import ErythropoiesisModel
from ahdt.models.haematological.platelets import PlateletModel
from ahdt.models.hepatobiliary.clearance import LiverClearanceModel
from ahdt.models.immune_lymphatic.infection import InfectionResponseModel
from ahdt.models.immune_lymphatic.inflammation import InflammationModel
from ahdt.models.integumentary.heat_stress import HeatStressModel
from ahdt.models.integumentary.thermoregulation import ThermoregulationModel
from ahdt.models.integumentary.wound import WoundHealingModel
from ahdt.models.musculoskeletal.bone import BoneRemodellingModel
from ahdt.models.nervous.neuron import NeuronModel
from ahdt.models.nervous.sleep import SleepModel
from ahdt.models.organs.store import InstanceStore
from ahdt.models.params import MODELS_DIR
from ahdt.models.reference import ReferenceStateModel, load_definitions
from ahdt.models.renal_urinary.acid_base import AcidBaseModel
from ahdt.models.renal_urinary.kidney import KidneyModel
from ahdt.models.respiratory.gas_exchange import GasExchangeModel
from ahdt.models.respiratory.ventilation import VentilationControlModel
from ahdt.models.sensory.decline import SensoryDeclineModel
from ahdt.models.whole_body.avatar import AvatarModel
from ahdt.models.whole_body.early_warning import EarlyWarningModel
from ahdt.models.whole_body.life_course import LifeCourseModel
from ahdt.models.whole_body.maternal_foetal import MaternalFoetalModel
from ahdt.models.whole_body.pharmacogenomics import PharmacogenomicsModel
from ahdt.registry import Registry, load_registry
from atra import contracts as c
from atra.backends.base import ModelRegistryBackend
from atra.kb import KnowledgeBase

T2_MODELS: tuple[type[Layer4Base], ...] = (
    HeartModel, BaroreflexModel, VasculatureModel,
    GasExchangeModel, VentilationControlModel,
    NeuronModel, SleepModel,
    SensoryDeclineModel,
    AbsorptionModel, NutritionModel,
    LiverClearanceModel,
    KidneyModel, AcidBaseModel,
    GlucoseInsulinModel, MinimalModel, HpaModel, PinealModel, HormoneKineticsModel,
    InflammationModel, InfectionResponseModel,
    ErythropoiesisModel, PlateletModel,
    BoneRemodellingModel,
    ThermoregulationModel, HeatStressModel, WoundHealingModel,
    AvatarModel, LifeCourseModel, MaternalFoetalModel, PharmacogenomicsModel,
    EarlyWarningModel,
    CardiacElectrophysiologyModel, AortaModel,
    BetaCellMassModel, HepatocyteGlucoseModel, CortisolDispositionModel,
    GonadalHormonesModel, MenstrualCycleModel,
    ImmuneResponseModel, MobilityModel,
    WholeBodyPbpkModel,
    SkeletalMuscleModel, BiomechanicalKinematicModel,
)

# Inventory items of twins 1 to 13 and Whole-Body that WP14b builds as data-fitted models.
OTHER_WORK_PACKAGES: Mapping[str, str] = {
    "ahdt.cardiovascular.blood_pressure_forecasting": "WP14b",
    "ahdt.cardiovascular.arrhythmia_detection": "WP14b",
    "ahdt.respiratory.spo2_desaturation_detection": "WP14b",
    "ahdt.respiratory.exacerbation_risk": "WP14b",
    "ahdt.nervous.eeg_analysis_and_sleep_staging": "WP14b",
    "ahdt.haematological.anaemia_and_sickle_cell_crisis_risk": "WP14b",
    "ahdt.musculoskeletal.gait_and_fall_risk": "WP14b",
    "ahdt.whole_body.clinical_health_state": "WP14b",
}

# Twins whose T2 and T3 inventory items WP14a builds (design 08, WP14a "Owns").
WP14A_TWINS = ("cardiovascular", "respiratory", "nervous", "sensory", "digestive",
               "hepatobiliary", "renal_urinary", "endocrine", "immune_lymphatic",
               "haematological", "musculoskeletal", "integumentary", "reproductive",
               "whole_body")


def reference_definition_files() -> list[Path]:
    return sorted(MODELS_DIR.glob("*/reference_states.yaml"))


def build_catalogue(kb: KnowledgeBase | None = None) -> dict[str, Layer4Base]:
    models: dict[str, Layer4Base] = {}
    for cls in T2_MODELS:
        model = cls(kb=kb)
        models[model.model_id] = model
    for path in reference_definition_files():
        for definition in load_definitions(path):
            models[definition.model_id] = ReferenceStateModel(definition, kb)
    return models


@lru_cache(maxsize=1)
def default_catalogue() -> dict[str, Layer4Base]:
    return build_catalogue()


def contributors(catalogue: Mapping[str, Layer4Base]) -> dict[str, list[Layer4Base]]:
    """The models whose outputs make up each organ instance's state, primary model first.

    All of an instance's models belong to its owning twin, except a contributor declared
    by another twin's inventory item (the exocrine pancreas facet); the owner writes its
    values, as the store allows only the owner and the assimilation service to write.
    """
    found: dict[str, list[Layer4Base]] = {}
    for model in catalogue.values():
        for anatomy in model.spec.instances:
            found.setdefault(anatomy, []).append(model)
    return found


def primary_models(catalogue: Mapping[str, Layer4Base]) -> dict[str, Layer4Base]:
    """The model that creates each organ instance: the first model that lists it."""
    return {anatomy: models[0] for anatomy, models in contributors(catalogue).items()}


def inventory_items(registry: Registry | None = None) -> list[str]:
    """Inventory item ids of the WP14a twins (the model lists of the twin definitions)."""
    reg = registry or load_registry()
    return [m for kind, twin in reg.twins.items() if kind.value in WP14A_TWINS
            for m in twin.models]


async def register_all(backend: ModelRegistryBackend, catalogue: Mapping[str, Layer4Base],
                       validations: Mapping[str, c.Validation] | None = None,
                       metrics: Mapping[str, Mapping[str, float]] | None = None
                       ) -> list[c.ModelRegistryEntry]:
    entries = []
    for model in catalogue.values():
        validation = (validations or {}).get(model.model_id)
        entry = model.spec.entry(model.paramset, validation)
        await backend.register(entry, metrics=(metrics or {}).get(model.model_id))
        entries.append(entry)
    return entries


async def create_person_instances(store: InstanceStore, hdt_id: str,
                                  catalogue: Mapping[str, Layer4Base],
                                  inputs: Mapping[str, Any] | None = None,
                                  anatomies: Iterable[str] | None = None
                                  ) -> list[c.InstanceRecord]:
    """One instance per owned organ, initialised by its models (design 04, 4.5.1)."""
    found = contributors(catalogue)
    created = []
    owned = anatomies if anatomies is not None else [
        a for twin in store.registry.twins.values() for a in twin.owns_instances]
    for anatomy in owned:
        owner = store.registry.owner_of(anatomy)
        if owner is None:
            raise KeyError(f"{anatomy} has no owning twin")
        models = found.get(anatomy)
        if not models:
            raise KeyError(f"{anatomy} has no model")
        record = models[0].new_record(hdt_id, anatomy, owner, inputs)
        state = dict(record.state)
        for extra in models[1:]:
            p = extra.parameters()
            values = extra.evaluate(p, extra.initial_state(p, inputs or {}), inputs or {})
            for key, value in values.items():
                state.setdefault(key, value)
        record = record.model_copy(update={"state": state})
        created.append(await store.create(record))
    return created
