package population.tools_test

import rego.v1

import data.population.tools

test_service_contributes if tools.allow with input as {"tool": "population.contribute", "service": true}

test_person_cannot_contribute if {
	not tools.allow with input as {"tool": "population.contribute", "service": false, "role": "person"}
}

test_public_health_reads_priors if {
	tools.allow with input as {"tool": "population.priors", "service": false, "role": "public_health_official"}
}
