"""Pharmacogenomics (inventory item 14): CPIC genotype to phenotype to recommendation.

Gene rules and drug recommendations are knowledge-base entries. A gene is resolved by
activity score (the sum of allele activity values against phenotype ceilings), by the pair
of allele functions, or, for G6PD, from a measured phenotype. Where CPIC splits a drug's
recommendations by indication, the indication comes from the input or the entry's default.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ahdt.models.base import AlgebraicModel, Inputs, ModelSpec, Params, Port
from ahdt.models.reference import default_kb
from atra import contracts as c
from atra.connectors import DTKind
from atra.kb import KBError


def phenotype(diplotype: str, rule: Mapping[str, Any]) -> str | None:
    if rule["method"] == "phenotype_input":
        return diplotype if diplotype in rule["phenotypes"] else None
    alleles = diplotype.split("/")
    if len(alleles) != 2:
        raise ValueError(f"diplotype must have two alleles: {diplotype}")
    if rule["method"] == "activity_score":
        values = [rule["allele_activity"].get(a) for a in alleles]
        if any(v is None for v in values):
            return None
        score = sum(float(v) for v in values)
        for band in rule["phenotypes"]:
            if "max_score" not in band or score <= band["max_score"]:
                return str(band["phenotype"])
        return None
    functions = sorted(rule["allele_function"].get(a, "unknown") for a in alleles)
    for band in rule["phenotypes"]:
        if sorted(band["functions"]) == functions:
            return str(band["phenotype"])
    return None


class PharmacogenomicsModel(AlgebraicModel):
    spec = ModelSpec(
        model_id="ahdt.whole_body.pharmacogenomics",
        twin=DTKind.WHOLE_BODY, family=c.ModelFamily.SEMANTIC, tier=c.Tier.T2,
        intended_use="Metaboliser phenotypes and CPIC prescribing recommendations",
        inputs=(Port("diplotypes", "{gene:diplotype}", "input:genome"),
                Port("measured_phenotypes", "{gene:phenotype}", "input:lab"),
                Port("drugs", "{name}", "input:medications"),
                Port("indications", "{drug:indication}", "input:medications")),
        outputs=(Port("phenotypes", "{gene:phenotype}"), Port("recommendations", "{list}")),
        explainers=("rules.trace",),
        source="Clinical Pharmacogenetics Implementation Consortium (CPIC) guidelines for "
               "CYP2D6, CYP2C19, CYP2B6 and G6PD; gene rules and recommendations in "
               "kb/pgx.yaml")

    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Inputs) -> dict[str, Any]:
        kb = self.kb or default_kb()
        diplotypes: dict[str, str] = dict(inputs.get("diplotypes", state.get("diplotypes", {})))
        diplotypes.update(inputs.get("measured_phenotypes", {}))
        indications: Mapping[str, str] = inputs.get("indications", {})
        phenotypes: dict[str, str] = {}
        for gene, diplotype in diplotypes.items():
            try:
                rule = kb.entry(f"pgx.{gene}").content()
            except KBError:
                continue
            found = phenotype(diplotype, rule)
            if found is not None:
                phenotypes[gene] = found
        recommendations = []
        for drug in inputs.get("drugs", []):
            try:
                entry = kb.entry(f"pgx.drug.{drug}").content()
            except KBError:
                continue
            gene = entry["gene"]
            table = entry.get("recommendations")
            if table is None:
                indication = indications.get(drug, entry["default_indication"])
                table = entry["recommendations_by_indication"].get(indication, {})
            rec = table.get(phenotypes.get(gene, ""))
            if rec is not None:
                recommendations.append(f"{drug}|{gene}|{phenotypes[gene]}|{rec['action']}|"
                                       f"{rec['text']}")
        return {"phenotypes": [f"{g}:{v}" for g, v in sorted(phenotypes.items())],
                "recommendations": recommendations}
