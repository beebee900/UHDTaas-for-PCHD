# APDT routes and MCP tools: role x tenant (design 07, 7.1.3). Route-level SMART scope
# rules are added with the full route table.
package apdt.routes

import rego.v1

default allow := false

allow if count(deny) == 0

decision := {"allow": allow, "reasons": sort([r | some r in deny])}

clinicians := {
	"medical_officer", "radiologist", "pharmacist", "nurse", "lab_scientist",
	"community_health_worker", "therapist",
}

patient_roles := {"patient", "proxy"}

decision_roles := {"medical_officer", "pharmacist", "nurse", "radiologist", "lab_scientist"}

governance := {"clinical_safety_officer", "administrator"}

route_roles := {
	"episodes.create": {"medical_officer", "nurse", "community_health_worker"},
	"episodes.list": (clinicians | patient_roles),
	"episodes.read": (clinicians | patient_roles),
	"episodes.close": {"medical_officer"},
	"episodes.resources": clinicians,
	"goals.diagnosis": {"medical_officer"},
	"goals.treatment": {"medical_officer", "pharmacist"},
	"goals.care": {"medical_officer", "nurse"},
	"record.read": clinicians,
	"record.diagnosis": {"medical_officer"},
	"record.dispense": {"pharmacist"},
	"record.administration": {"nurse"},
	"runs.read": clinicians,
	"runs.resume": (decision_roles | patient_roles),
	"recommendations.read": (clinicians | patient_roles),
	"bundles.read": (clinicians | patient_roles),
	"unified_view.read": clinicians,
	"ahdt_panel.read": clinicians,
	"consent.read": (clinicians | patient_roles),
	"consent.write": ({"medical_officer"} | patient_roles),
	"preferences.write": patient_roles,
	"messages.create": patient_roles,
	"worklists.read": clinicians,
	"patients.list": clinicians,
	"intake.catalogue": clinicians,
	"alerts.ack": clinicians,
	"referrals.create": {"medical_officer"},
	"audit.read": ({"medical_officer"} | governance),
	"questionnaires.read": (clinicians | patient_roles),
	"questionnaires.populate": (clinicians | patient_roles),
	"questionnaires.extract": (clinicians | patient_roles),
	"apdt.episode.summary": clinicians,
	"apdt.diagnosis.differential": {"medical_officer", "radiologist", "lab_scientist"},
	"apdt.treatment.options": {"medical_officer", "pharmacist"},
	"apdt.explain": (clinicians | patient_roles),
	"apdt.consent.get": (clinicians | patient_roles),
}

deny contains msg if {
	not input.service
	allowed := object.get(route_roles, input.route, set())
	not input.role in allowed
	msg := sprintf("role %s may not use %s", [input.role, input.route])
}

deny contains "the user belongs to another facility" if {
	not input.service
	input.role in clinicians
	input.claims.tenant_id != input.tenant_id
}

deny contains "a clinician may read only the worklist of their own role" if {
	not input.service
	input.route == "worklists.read"
	object.get(input, "worklist_role", null) != input.role
}

# Routes that serve blank templates and hold no personal data.
template_routes := {"questionnaires.read"}

deny contains "a patient may see only their own record" if {
	not input.service
	input.role == "patient"
	not input.route in template_routes
	input.hdt_id
	input.claims.hdt_id != input.hdt_id
}

deny contains "the proxy does not act for this person" if {
	not input.service
	input.role == "proxy"
	not input.route in template_routes
	not input.hdt_id in object.get(input.claims, "proxy_for", [])
}
