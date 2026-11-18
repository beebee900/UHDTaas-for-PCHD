"""Every Cypher statement of the AHDT knowledge layer (design 03, 3.12).

All statements stay inside the in-process subset, so they run unchanged on Neo4j. `READ`
is the allow-list served by `ahdt.data.knowledge`: query id → (statement, parameters the
caller supplies). `hdt_id` is always bound from the call context, never from the caller.
"""

from __future__ import annotations

from collections.abc import Mapping

MERGE_PERSON = "MERGE (a:Person {id: $id}) SET a += $props"
MERGE_SYSTEM = "MERGE (a:System {id: $id}) SET a += $props"
MERGE_ORGAN = "MERGE (a:Organ {id: $id}) SET a += $props"
MERGE_OBSERVATION = "MERGE (a:Observation {id: $id}) SET a += $props"
MERGE_CONDITION = "MERGE (a:Condition {id: $id}) SET a += $props"
MERGE_MEDICATION = "MERGE (a:Medication {id: $id}) SET a += $props"
MERGE_PHENOTYPE = "MERGE (a:Phenotype {id: $id}) SET a += $props"
MERGE_DOCUMENT = "MERGE (a:Document {id: $id}) SET a += $props"
MERGE_SECTION = "MERGE (a:Section {id: $id}) SET a += $props"
MERGE_COMMUNITY = "MERGE (a:Community {id: $id}) SET a += $props"

HAS_SYSTEM = "MATCH (a:Person {id: $a}), (b:System {id: $b}) MERGE (a)-[:HAS_SYSTEM]->(b)"
HAS_ORGAN = "MATCH (a:Person {id: $a}), (b:Organ {id: $b}) MERGE (a)-[:HAS_ORGAN]->(b)"
HAS_OBSERVATION = ("MATCH (a:Person {id: $a}), (b:Observation {id: $b}) "
                   "MERGE (a)-[:HAS_OBSERVATION]->(b)")
OBSERVED_IN = ("MATCH (a:Observation {id: $a}), (b:Organ {id: $b}) "
               "MERGE (a)-[:OBSERVED_IN]->(b)")
HAS_CONDITION = ("MATCH (a:Person {id: $a}), (b:Condition {id: $b}) "
                 "MERGE (a)-[:HAS_CONDITION]->(b)")
AFFECTS = "MATCH (a:Condition {id: $a}), (b:Organ {id: $b}) MERGE (a)-[:AFFECTS]->(b)"
TAKES = "MATCH (a:Person {id: $a}), (b:Medication {id: $b}) MERGE (a)-[:TAKES]->(b)"
INTERACTS_WITH = ("MATCH (a:Medication {id: $a}), (b:Medication {id: $b}) "
                  "MERGE (a)-[:INTERACTS_WITH]->(b)")
HAS_PHENOTYPE = ("MATCH (a:Person {id: $a}), (b:Phenotype {id: $b}) "
                 "MERGE (a)-[:HAS_PHENOTYPE]->(b)")
MENTIONS = "MATCH (a:Section {id: $a}), (b {id: $b}) MERGE (a)-[:MENTIONS]->(b)"
HAS_SECTION = "MATCH (a:Document {id: $a}), (b:Section {id: $b}) MERGE (a)-[:HAS_SECTION]->(b)"
IN_COMMUNITY = "MATCH (a {id: $a}), (b:Community {id: $b}) MERGE (a)-[:IN_COMMUNITY]->(b)"
OWNED_BY_ORGAN = "MATCH (a:Organ {id: $a}), (b:System {id: $b}) MERGE (a)-[:OWNED_BY]->(b)"
OWNED_BY_OBSERVATION = ("MATCH (a:Observation {id: $a}), (b:System {id: $b}) "
                        "MERGE (a)-[:OWNED_BY]->(b)")
OWNED_BY_CONDITION = ("MATCH (a:Condition {id: $a}), (b:System {id: $b}) "
                      "MERGE (a)-[:OWNED_BY]->(b)")
OWNED_BY_MEDICATION = ("MATCH (a:Medication {id: $a}), (b:System {id: $b}) "
                       "MERGE (a)-[:OWNED_BY]->(b)")
OWNED_BY_PHENOTYPE = ("MATCH (a:Phenotype {id: $a}), (b:System {id: $b}) "
                      "MERGE (a)-[:OWNED_BY]->(b)")

PERSON_SYSTEMS = "MATCH (a:Person {id: $hdt_id})-[:HAS_SYSTEM*1..1]->(b:System) RETURN b"
PERSON_CONDITIONS = ("MATCH (a:Person {id: $hdt_id})-[:HAS_CONDITION*1..1]->(b:Condition) "
                     "RETURN b")
PERSON_MEDICATIONS = ("MATCH (a:Person {id: $hdt_id})-[:TAKES*1..1]->(b:Medication) "
                      "RETURN b")
PERSON_PHENOTYPES = ("MATCH (a:Person {id: $hdt_id})-[:HAS_PHENOTYPE*1..1]->(b:Phenotype) "
                     "RETURN b")
PERSON_OBSERVATIONS = ("MATCH (a:Person {id: $hdt_id})-[:HAS_OBSERVATION*1..1]->"
                       "(b:Observation) RETURN b")
PERSON_OBSERVATION_BY_FIELD = ("MATCH (a:Person {id: $hdt_id})-[:HAS_OBSERVATION*1..1]->"
                               "(b:Observation) WHERE b.field = $field RETURN b")
PERSON_ORGANS = "MATCH (a:Person {id: $hdt_id})-[:HAS_ORGAN*1..1]->(b:Organ) RETURN b"
CONDITION_ORGANS = "MATCH (a:Condition {id: $id})-[:AFFECTS*1..1]->(b:Organ) RETURN a, b"
MEDICATION_INTERACTIONS = ("MATCH (a:Medication {id: $id})-[:INTERACTS_WITH*1..1]->"
                           "(b:Medication) RETURN a, b")
FACT_OWNER = "MATCH (a)-[r:OWNED_BY]->(b) WHERE a.id = $id RETURN type(r), b"
SYSTEM_BY_KIND = "MATCH (a:System {kind: $kind}) RETURN a"
COMMUNITIES = "MATCH (a:Community {hdt_id: $hdt_id}) RETURN a"

READ: Mapping[str, tuple[str, tuple[str, ...]]] = {
    "person.systems": (PERSON_SYSTEMS, ()),
    "person.conditions": (PERSON_CONDITIONS, ()),
    "person.medications": (PERSON_MEDICATIONS, ()),
    "person.phenotypes": (PERSON_PHENOTYPES, ()),
    "person.observations": (PERSON_OBSERVATIONS, ()),
    "person.observation": (PERSON_OBSERVATION_BY_FIELD, ("field",)),
    "person.organs": (PERSON_ORGANS, ()),
    "person.communities": (COMMUNITIES, ()),
    "condition.organs": (CONDITION_ORGANS, ("id",)),
    "medication.interactions": (MEDICATION_INTERACTIONS, ("id",)),
    "fact.owner": (FACT_OWNER, ("id",)),
}

# Internal lookup (not in READ): checks that a citation resolves to a node.
NODE_BY_ID = "MATCH (a {id: $id}) RETURN a"
