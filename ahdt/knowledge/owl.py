"""The AHDT organ–system ontology `ahdt/ontology/ahdt.owl` (design 04, 4.4.1).

Written from the twin registry so that it cannot drift from it:
- one `System` subclass per twin, pairwise disjoint
- one `Organ` subclass per owned instance (UBERON id or `atra:` local id), with the axiom
  `ownedBy some <System>`; `ownedBy` is functional, so an organ owned by two twins makes
  the ontology inconsistent
- the SWRL rule: an observation made in an organ is attributed to the organ's owner

`check()` runs HermiT through owlready2 and returns the inferred owner of a sample
observation for every organ, which the tests compare with the registry.

    python -m ahdt.knowledge.owl write       regenerate ahdt/ontology/ahdt.owl
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import owlready2 as owl

from ahdt.registry import Registry, load_registry
from atra.config import ROOT

OWL_PATH = ROOT / "ahdt" / "ontology" / "ahdt.owl"
BASE = "https://atra.health/ontology/ahdt.owl#"
OBO = "http://purl.obolibrary.org/obo/"
RULE = "Observation(?o), observedIn(?o, ?g), ownedBy(?g, ?s) -> attributedTo(?o, ?s)"
JAVA_MEMORY_MB = 600


def _class_name(kind: str) -> str:
    return "".join(part.capitalize() for part in kind.split("_")) + "System"


def _organ_iri(instance: str) -> str:
    if instance.startswith("UBERON:"):
        return OBO + instance.replace(":", "_", 1)
    return BASE + instance.replace(":", "_")


def build(registry: Registry | None = None, labels: Mapping[str, str] | None = None
          ) -> tuple[Any, Any]:
    """A fresh owlready2 world holding the ontology; returns (world, ontology)."""
    registry = registry or load_registry()
    world = owl.World()
    onto = world.get_ontology(BASE.rstrip("#"))
    with onto:
        class System(owl.Thing):
            pass

        class Organ(owl.Thing):
            pass

        class Observation(owl.Thing):
            pass

        class ownedBy(Organ >> System, owl.FunctionalProperty):  # type: ignore[misc]
            pass

        class observedIn(Observation >> Organ, owl.FunctionalProperty):  # type: ignore[misc]
            pass

        class attributedTo(Observation >> System):  # type: ignore[misc]
            pass

        systems = {}
        for kind in sorted(registry.twins, key=lambda k: k.value):
            cls = owl.types.new_class(_class_name(kind.value), (System,))
            cls.label = [registry.twins[kind].name]
            systems[kind] = cls
        owl.AllDisjoint(list(systems.values()))
        organs: dict[str, Any] = {}
        for kind, twin in registry.twins.items():
            for instance in twin.owns_instances:
                if instance not in organs:
                    organ = owl.types.new_class(instance.replace(":", "_"), (Organ,))
                    organ.iri = _organ_iri(instance)
                    organ.label = [labels.get(instance, instance) if labels else instance]
                    organs[instance] = organ
                organs[instance].is_a.append(ownedBy.some(systems[kind]))
        owl.Imp().set_as_rule(RULE)
    return world, onto


def write(path: Path = OWL_PATH) -> Path:
    labels: dict[str, str] = {}
    try:
        from ahdt.knowledge.ontology import Ontologies

        store = Ontologies()
        for twin in load_registry().twins.values():
            for instance in twin.owns_instances:
                if (label := store.label(instance)) is not None:
                    labels[instance] = label
    except OSError:
        pass
    _, onto = build(labels=labels)
    path.parent.mkdir(parents=True, exist_ok=True)
    onto.save(file=str(path), format="rdfxml")
    return path


def check(path: Path = OWL_PATH) -> dict[str, str]:
    """Run HermiT. Returns organ instance → inferred owning System class name.

    Raises `owlready2.OwlReadyInconsistentOntologyError` when the ontology is inconsistent.
    """
    owl.reasoning.JAVA_MEMORY = JAVA_MEMORY_MB
    world = owl.World()
    onto = world.get_ontology(path.as_uri()).load()
    registry = load_registry()
    with onto:
        observation = onto.search_one(iri=BASE + "Observation")
        observed_in = onto.search_one(iri=BASE + "observedIn")
        owned_by = onto.search_one(iri=BASE + "ownedBy")
        samples = {}
        for kind, twin in registry.twins.items():
            system_cls = onto.search_one(iri=BASE + _class_name(kind.value))
            owner = system_cls(f"owner_{kind.value}")
            for instance in twin.owns_instances:
                organ_cls = world[_organ_iri(instance)]
                organ = organ_cls(f"organ_{instance.replace(':', '_')}")
                setattr(organ, owned_by.python_name, owner)
                obs = observation(f"obs_{instance.replace(':', '_')}")
                setattr(obs, observed_in.python_name, organ)
                samples[instance] = obs
        owl.sync_reasoner_hermit(world, infer_property_values=True, debug=0)
    attributed = onto.search_one(iri=BASE + "attributedTo")
    out = {}
    for instance, obs in samples.items():
        owners = getattr(obs, attributed.python_name)
        out[instance] = owners[0].is_a[0].name if owners else ""
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ahdt.knowledge.owl")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("write")
    sub.add_parser("check")
    args = parser.parse_args(argv)
    if args.cmd == "write":
        print(f"wrote {write()}")
    else:
        for instance, owner in sorted(check().items()):
            print(f"{instance}: {owner}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
