"""Registration of the APDT Layer 4 models and their `depends_on` pins."""

from __future__ import annotations

from ahdt.models.catalogue import build_catalogue
from ahdt.models.ml.inventory import ITEMS
from apdt.models.registry import BY_ID, MODELS, dependents_of, register_all
from atra.backends.memory import FileModelRegistry


def test_pins_resolve_to_ahdt_models() -> None:
    known = {m.model_id for m in build_catalogue().values()} | {i.spec.model_id for i in ITEMS}
    for m in MODELS:
        for dep, version in m.depends_on:
            assert dep in known, (m.model_id, dep)
            assert version


def test_model_ids_are_unique_and_apdt() -> None:
    ids = [m.model_id for m in MODELS]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("apdt.") for i in ids)


async def test_registration_in_the_backend() -> None:
    registry = FileModelRegistry()
    entries = await register_all(registry)
    assert len(entries) == len(MODELS)
    listed = {e.model_id for e in await registry.list()}
    assert set(BY_ID) == listed
    dosing = await registry.get("apdt.treatment.dosing")
    assert dosing.twin == "apdt" and len(dosing.depends_on) == 3


def test_dependents_of_an_ahdt_model() -> None:
    assert "apdt.treatment.dosing" in dependents_of("ahdt.renal_urinary.kidney_and_renal_function")
    assert dependents_of("ahdt.whole_body.early_warning") == ["apdt.care.early_warning"]


async def test_registration_validates_and_writes_cards(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from evaluation.models.apdt.register import register

    registry = FileModelRegistry()
    statuses = await register(registry, root=tmp_path / "none", cards_dir=tmp_path / "cards")
    by = {s.model_id: s for s in statuses}
    for model_id in ("apdt.diagnosis.differential_bn", "apdt.treatment.options",
                     "apdt.treatment.safety"):
        assert by[model_id].state == "validated"
    entry = await registry.get("apdt.treatment.options")
    assert entry.validation is not None and entry.validation.value == 1.0
    card = (tmp_path / "cards" / "apdt.treatment.options.md").read_text()
    assert "first_option_concordance" in card and "| tx." in card
    assert by["apdt.care.pathways"].state == "registered"
    assert "not validated yet" in (tmp_path / "cards" / "apdt.care.pathways.md"
                                   ).read_text()
