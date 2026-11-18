package ahdt.actuation_test

import rego.v1

import data.ahdt.actuation

consent := {"purposes": ["care"], "refused_tools": []}

haptic := {"actuator": "haptic", "granted": "act", "purpose": "care", "consent": consent, "params": {"pattern": "pulse", "duration_ms": 400}}

bolus := {"actuator": "insulin_pump", "granted": "act_with_approval", "purpose": "care", "consent": consent, "params": {"kind": "bolus", "bolus_u": 2}}

with_params(base, params) := object.union(object.remove(base, ["params"]), {"params": params})

test_haptic_allowed if {
	actuation.allow with input as haptic
	not actuation.needs_approval with input as haptic
}

test_below_act_with_approval_denied if {
	d := actuation.decision with input as object.union(haptic, {"granted": "recommend"})
	not d.allow
	"autonomy level recommend is below act_with_approval for notification" in d.reasons
}

test_person_lowering_wins if {
	d := actuation.decision with input as object.union(haptic, {"person_level": "inform"})
	not d.allow
	d.level == "inform"
}

test_person_cannot_raise if {
	d := actuation.decision with input as object.union(bolus, {"person_level": "act"})
	d.level == "act_with_approval"
	d.needs_approval
}

test_lowered_to_approval_needs_approval if {
	d := actuation.decision with input as object.union(haptic, {"person_level": "act_with_approval"})
	not d.allow
	d.needs_approval
}

test_bolus_needs_approval if {
	d := actuation.decision with input as bolus
	not d.allow
	d.needs_approval
	d.reasons == []
}

test_bolus_approved_by_medical_officer if {
	actuation.allow with input as object.union(bolus, {"approval": {"role": "medical_officer", "approved": true}})
}

test_bolus_approval_by_nurse_refused if {
	d := actuation.decision with input as object.union(bolus, {"approval": {"role": "nurse", "approved": true}})
	not d.allow
	"role nurse may not approve insulin_pump" in d.reasons
}

test_rehab_robot_therapist_may_approve if {
	inp := {"actuator": "rehab_robot", "granted": "act_with_approval", "purpose": "care", "consent": consent, "params": {"assistance_pct": 40, "duration_min": 20}, "approval": {"role": "therapist", "approved": true}}
	actuation.allow with input as inp
}

test_declined_denied if {
	d := actuation.decision with input as object.union(bolus, {"approval": {"role": "medical_officer", "approved": false}})
	"the clinician declined the command" in d.reasons
}

test_bolus_over_limit_denied if {
	d := actuation.decision with input as with_params(bolus, {"kind": "bolus", "bolus_u": 40})
	not d.needs_approval
	"bolus_u=40 outside [0.05, 25]" in d.reasons
}

test_bolus_without_dose_denied if {
	d := actuation.decision with input as with_params(bolus, {"kind": "bolus"})
	"an insulin bolus needs bolus_u" in d.reasons
}

test_unknown_parameter_denied if {
	d := actuation.decision with input as with_params(haptic, {"pattern": "pulse", "volume": 3})
	"parameter volume is not accepted by haptic" in d.reasons
}

test_missing_parameter_denied if {
	d := actuation.decision with input as with_params(haptic, {"duration_ms": 400})
	"parameter pattern is required" in d.reasons
}

test_choice_denied if {
	d := actuation.decision with input as with_params(haptic, {"pattern": "buzz"})
	not d.allow
}

test_sms_text_too_long_denied if {
	inp := {"actuator": "sms", "granted": "act", "purpose": "care", "consent": consent, "params": {"body": concat("", [x | some _ in numbers.range(1, 460); x := "a"])}}
	d := actuation.decision with input as inp
	"body must be text of 1 to 459 characters" in d.reasons
}

test_no_consent_denied if {
	d := actuation.decision with input as object.remove(haptic, ["consent"])
	"no consent on record for this person" in d.reasons
}

test_withheld_actuator_denied if {
	d := actuation.decision with input as object.union(haptic, {"consent": {"purposes": ["care"], "refused_tools": ["ahdt.act.haptic"]}})
	"the person has withheld ahdt.act.haptic" in d.reasons
}

test_purpose_not_consented_denied if {
	d := actuation.decision with input as object.union(haptic, {"purpose": "research"})
	"purpose 'research' not consented" in d.reasons
}

test_unknown_actuator_denied if {
	d := actuation.decision with input as object.union(haptic, {"actuator": "defibrillator"})
	"unknown actuator 'defibrillator'" in d.reasons
}
