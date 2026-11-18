package apdt.routes_test

import rego.v1

import data.apdt.routes

mo := {
	"route": "apdt.diagnosis.differential", "role": "medical_officer", "service": false,
	"tenant_id": "fac-a", "claims": {"tenant_id": "fac-a"},
}

test_medical_officer_same_tenant if routes.allow with input as mo

test_other_tenant_denied if {
	not routes.allow with input as object.union(mo, {"tenant_id": "fac-b"})
}

test_nurse_cannot_read_differential if {
	not routes.allow with input as object.union(mo, {"role": "nurse"})
}

test_patient_own_consent if {
	inp := {
		"route": "apdt.consent.get", "role": "patient", "service": false, "tenant_id": "fac-a",
		"hdt_id": "hdt-0123456789ab", "claims": {"hdt_id": "hdt-0123456789ab"},
	}
	routes.allow with input as inp
}

test_patient_extracts_own_questionnaire if {
	inp := {
		"route": "questionnaires.extract", "role": "patient", "service": false,
		"tenant_id": "fac-a", "hdt_id": "hdt-0123456789ab",
		"claims": {"hdt_id": "hdt-0123456789ab"},
	}
	routes.allow with input as inp
}

test_patient_cannot_populate_for_another if {
	inp := {
		"route": "questionnaires.populate", "role": "patient", "service": false,
		"tenant_id": "fac-a", "hdt_id": "hdt-0123456789ab",
		"claims": {"hdt_id": "hdt-ffffffffffff"},
	}
	not routes.allow with input as inp
}

proxy := {
	"route": "episodes.read", "role": "proxy", "service": false, "tenant_id": "fac-a",
	"hdt_id": "hdt-0123456789ab", "claims": {"proxy_for": ["hdt-0123456789ab"]},
}

test_proxy_reads_the_episode_of_their_person if routes.allow with input as proxy

test_proxy_cannot_read_another_person if {
	not routes.allow with input as object.union(proxy, {"hdt_id": "hdt-ffffffffffff"})
}

test_patient_lists_episodes if {
	routes.allow with input as {
		"route": "episodes.list", "role": "patient", "service": false,
		"tenant_id": "fac-a", "claims": {"hdt_id": "hdt-0123456789ab"},
	}
}

test_patient_cannot_list_facility_patients if {
	not routes.allow with input as {
		"route": "patients.list", "role": "patient",
		"service": false, "tenant_id": "fac-a", "claims": {"hdt_id": "hdt-0123456789ab"},
	}
}

test_patient_reads_a_blank_questionnaire if {
	routes.allow with input as {
		"route": "questionnaires.read", "role": "patient", "service": false,
		"tenant_id": "fac-a", "hdt_id": null, "claims": {"hdt_id": "hdt-0123456789ab"},
	}
}

test_proxy_must_name_their_person if {
	not routes.allow with input as object.union(proxy, {"route": "episodes.list", "hdt_id": null})
}

test_each_role_enters_its_own_record if {
	routes.allow with input as object.union(mo, {"route": "record.diagnosis"})
	routes.allow with input as object.union(mo, {"route": "record.dispense", "role": "pharmacist"})
	routes.allow with input as object.union(mo, {"route": "record.administration", "role": "nurse"})
	routes.allow with input as object.union(mo, {"route": "record.read", "role": "nurse"})
}

test_record_entries_are_role_bound if {
	not routes.allow with input as object.union(mo, {"route": "record.diagnosis", "role": "nurse"})
	not routes.allow with input as object.union(mo, {"route": "record.dispense"})
	not routes.allow with input as object.union(mo, {"route": "record.administration", "role": "pharmacist"})
	not routes.allow with input as object.union(mo, {"route": "record.read", "role": "patient"})
}

worklist := object.union(mo, {"route": "worklists.read", "worklist_role": "medical_officer"})

test_each_role_reads_its_own_worklist if {
	routes.allow with input as worklist
	routes.allow with input as object.union(worklist, {"role": "nurse", "worklist_role": "nurse"})
}

test_a_role_cannot_read_another_roles_worklist if {
	not routes.allow with input as object.union(worklist, {"role": "nurse"})
	not routes.allow with input as object.union(worklist, {"worklist_role": "pharmacist"})
	not routes.allow with input as object.union(worklist, {"worklist_role": null})
}
