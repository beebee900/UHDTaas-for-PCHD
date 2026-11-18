# Population twin tools (design 03, 3.15): services read priors and norms for care;
# public-health roles read them de-identified; only services contribute.
package population.tools

import rego.v1

default allow := false

allow if count(deny) == 0

decision := {"allow": allow, "reasons": sort([r | some r in deny])}

readers := {"public_health_official", "researcher", "administrator", "medical_officer"}

deny contains "only service clients may contribute" if {
	input.tool == "population.contribute"
	not input.service
}

deny contains msg if {
	input.tool in {"population.priors", "population.norms"}
	not input.service
	not input.role in readers
	msg := sprintf("role %s may not read population statistics", [input.role])
}
