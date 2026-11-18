package ahdt.tools_test

import rego.v1

import data.ahdt.tools

consent := {"purposes": ["care"], "refused_tools": ["ahdt.data.genome"]}

base := {"tool": "ahdt.data.observations", "role": "medical_officer", "purpose": "care",
	"hdt_id": "hdt-0123456789ab", "consent": consent, "claims": {}, "args": {}}

test_medical_officer_allowed if tools.allow with input as base

test_role_without_tool_denied if {
	not tools.allow with input as object.union(base, {"role": "lab_scientist", "tool": "ahdt.model.simulate"})
}

test_withheld_tool_denied if {
	not tools.allow with input as object.union(base, {"tool": "ahdt.data.genome"})
}

test_purpose_not_consented if {
	not tools.allow with input as object.union(base, {"purpose": "research"})
}

test_person_other_twin_denied if {
	inp := object.union(base, {"role": "person", "claims": {"hdt_id": "hdt-ffffffffffff"}})
	not tools.allow with input as inp
}

test_person_own_twin_allowed if {
	tools.allow with input as object.union(base, {"role": "person", "claims": {"hdt_id": "hdt-0123456789ab"}})
}

test_unforked_simulation_denied if {
	inp := object.union(base, {"tool": "ahdt.model.simulate", "args": {"fork": false}})
	not tools.allow with input as inp
}
