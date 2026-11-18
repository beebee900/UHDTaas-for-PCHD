# AHDT Layer 6 tool authorisation: tool x role x purpose x consent x subject (design 03, 3.6.3 and 3.13).
package ahdt.tools

import rego.v1

default allow := false

allow if count(deny) == 0

decision := {"allow": allow, "reasons": sort([r | some r in deny])}

own_hdt_roles := {"person", "patient"}

deny contains msg if {
	not input.tool in object.get(data.atra.role_tools, input.role, [])
	msg := sprintf("role %s may not use %s", [input.role, input.tool])
}

deny contains msg if {
	not input.consent
	not input.role in {"researcher", "public_health_official"}
	msg := "no consent on record for this person"
}

deny contains msg if {
	input.consent
	not input.purpose in input.consent.purposes
	msg := sprintf("purpose '%s' not consented", [input.purpose])
}

deny contains msg if {
	input.tool in object.get(input.consent, "refused_tools", [])
	msg := sprintf("the person has withheld %s", [input.tool])
}

deny contains msg if {
	input.role in own_hdt_roles
	not input.delegated
	input.claims.hdt_id != input.hdt_id
	msg := "a person may use only their own twin"
}

deny contains msg if {
	input.role == "proxy"
	not input.delegated
	not input.hdt_id in object.get(input.claims, "proxy_for", [])
	msg := "the proxy does not act for this person"
}

deny contains msg if {
	input.role == "carer"
	not input.delegated
	not input.hdt_id in object.get(input.claims, "carer_for", [])
	msg := "the carer has no consent from this person"
}

deny contains msg if {
	input.tool in {"ahdt.model.simulate", "ahdt.model.cosimulate"}
	input.args.fork == false
	msg := "simulation on live model state is not permitted"
}
