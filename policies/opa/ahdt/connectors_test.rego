package ahdt.connectors_test

import rego.v1

import data.ahdt.connectors

msg(payload, purpose) := {"message": {"contract": "infection_state/v1.0", "purpose": purpose, "payload": payload}}

test_in_range_allowed if connectors.allow with input as msg({"core_temp": 38.5}, "care")

test_out_of_range_denied if not connectors.allow with input as msg({"core_temp": 45}, "care")

test_wrong_purpose_denied if not connectors.allow with input as msg({"core_temp": 38.5}, "research")

test_population_contract_needs_public_health if {
	inp := {"message": {"contract": "cohort_contribution/v1.0", "purpose": "public_health", "payload": {}}}
	connectors.allow with input as inp
}
