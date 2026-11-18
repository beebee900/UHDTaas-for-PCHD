# AHDT actuator commands: autonomy level, consent, parameter limits and clinician approval
# (design 04, 4.1.2 and design 03, 3.14). Data: data.ahdt.actuators from edge/actuators.
package ahdt.actuation

import rego.v1

rank := {"never": 0, "inform": 1, "recommend": 2, "prepare_for_signature": 3, "act_with_approval": 4, "act": 5}

actuator := data.ahdt.actuators.actuators[input.actuator]

required_level := data.ahdt.actuators.action_classes[actuator.class].level

approvers := object.get(actuator, "approvers", data.ahdt.actuators.approvers)

tool := sprintf("ahdt.act.%s", [input.actuator])

granted := object.get(input, "granted", "never")

effective := granted if {
	not input.person_level
}

effective := lowest if {
	input.person_level
	levels := [granted, input.person_level]
	ranks := [object.get(rank, l, 0) | some l in levels]
	some lowest in levels
	object.get(rank, lowest, 0) == min(ranks)
}

approval_required if required_level == "act_with_approval"

approval_required if effective == "act_with_approval"

approved if {
	input.approval.approved == true
	input.approval.role in approvers
}

default allow := false

allow if {
	count(deny) == 0
	not approval_required
}

allow if {
	count(deny) == 0
	approval_required
	approved
}

default needs_approval := false

needs_approval if {
	count(deny) == 0
	approval_required
	not input.approval
}

decision := {
	"allow": allow,
	"needs_approval": needs_approval,
	"level": effective,
	"reasons": sort([r | some r in deny]),
}

deny contains msg if {
	not data.ahdt.actuators.actuators[input.actuator]
	msg := sprintf("unknown actuator '%v'", [input.actuator])
}

deny contains msg if {
	actuator
	object.get(rank, effective, 0) < rank.act_with_approval
	msg := sprintf("autonomy level %s is below act_with_approval for %s", [effective, actuator.class])
}

deny contains "no consent on record for this person" if not input.consent

deny contains msg if {
	input.consent
	not input.purpose in input.consent.purposes
	msg := sprintf("purpose '%v' not consented", [input.purpose])
}

deny contains msg if {
	tool in object.get(input.consent, "refused_tools", [])
	msg := sprintf("the person has withheld %s", [tool])
}

deny contains msg if {
	some name in actuator.required
	not name in object.keys(object.get(input, "params", {}))
	msg := sprintf("parameter %s is required", [name])
}

deny contains msg if {
	some name, _ in input.params
	actuator
	not actuator.limits[name]
	msg := sprintf("parameter %s is not accepted by %s", [name, input.actuator])
}

deny contains msg if {
	some name, value in input.params
	bounds := actuator.limits[name].range
	not in_range(value, bounds)
	msg := sprintf("%s=%v outside [%v, %v]", [name, value, bounds[0], bounds[1]])
}

deny contains msg if {
	some name, value in input.params
	bounds := actuator.limits[name].text
	not text_in_range(value, bounds)
	msg := sprintf("%s must be text of %v to %v characters", [name, bounds[0], bounds[1]])
}

deny contains msg if {
	some name, value in input.params
	choices := actuator.limits[name].choice
	not value in choices
	msg := sprintf("%s=%v is not one of %v", [name, value, choices])
}

deny contains "an insulin bolus needs bolus_u" if {
	input.actuator == "insulin_pump"
	input.params.kind == "bolus"
	not "bolus_u" in object.keys(input.params)
}

deny contains "a basal rate needs basal_u_per_h" if {
	input.actuator == "insulin_pump"
	input.params.kind == "basal"
	not "basal_u_per_h" in object.keys(input.params)
}

deny contains msg if {
	input.approval
	not input.approval.role in approvers
	msg := sprintf("role %v may not approve %s", [input.approval.role, input.actuator])
}

deny contains "the clinician declined the command" if {
	input.approval.role in approvers
	input.approval.approved == false
}

in_range(value, bounds) if {
	is_number(value)
	value >= bounds[0]
	value <= bounds[1]
}

text_in_range(value, bounds) if {
	is_string(value)
	count(value) >= bounds[0]
	count(value) <= bounds[1]
}
