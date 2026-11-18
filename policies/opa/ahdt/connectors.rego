# AHDT Layer 6.5 connector messages: purpose per contract and range guard (design 03, 3.16).
package ahdt.connectors

import rego.v1

default allow := false

allow if count(deny) == 0

decision := {"allow": allow, "reasons": sort([r | some r in deny])}

contract_name := split(input.message.contract, "/")[0]

deny contains msg if {
	purposes := object.get(data.atra.connector_purposes, contract_name, ["care"])
	not input.message.purpose in purposes
	msg := sprintf("purpose '%s' is not allowed on %s", [input.message.purpose, contract_name])
}

deny contains msg if {
	some field, limits in data.atra.range_guard
	value := input.message.payload[field]
	is_number(value)
	not value >= limits[0]
	msg := sprintf("%s=%v below the safety range [%v, %v]", [field, value, limits[0], limits[1]])
}

deny contains msg if {
	some field, limits in data.atra.range_guard
	value := input.message.payload[field]
	is_number(value)
	not value <= limits[1]
	msg := sprintf("%s=%v above the safety range [%v, %v]", [field, value, limits[0], limits[1]])
}
