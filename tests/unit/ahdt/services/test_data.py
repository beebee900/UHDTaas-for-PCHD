from datetime import timedelta

import pytest

from atra import contracts as c
from atra.service import Problem
from tests.contract.fixtures import HDT, PERIOD, T0


class Who:
    class ctx:
        purpose = "public_health"
        actor_id = "ph-1"


async def test_observations_are_returned_per_requested_code(services):
    args = c.ObservationsArgs(hdt_id=HDT, codes=["8310-5", "temperature", "9999-9"],
                              period=PERIOD)
    body = await services.data.observations(args, None)
    c.ObservationsData.model_validate({k: v for k, v in body.items() if k != "_meta"})
    assert len(body["series"]["8310-5"]) == 36 == len(body["series"]["temperature"])
    assert body["series"]["9999-9"] == []
    point = body["series"]["8310-5"][0]
    assert point["unit"] == "Cel" and point["quality"] == "ok"


async def test_aggregation_averages_each_bucket(services):
    args = c.ObservationsArgs(hdt_id=HDT, codes=["8867-4"], aggregate="1h")
    body = await services.data.observations(args, None)
    assert len(body["series"]["8867-4"]) == 36
    args = c.ObservationsArgs(hdt_id=HDT, codes=["8867-4"], aggregate="1h",
                              period={"start": T0, "end": T0 + timedelta(hours=1)})
    assert len((await services.data.observations(args, None))["series"]["8867-4"]) == 2


async def test_as_of_hides_later_ingests(services):
    args = c.ObservationsArgs(hdt_id=HDT, codes=["8310-5"], as_of=T0)
    body = await services.data.observations(args, None)
    assert body["series"]["8310-5"] == []
    assert body["_meta"]["as_of"]


async def test_timeseries_is_thinned_and_keeps_the_ends(services):
    args = c.TimeseriesArgs(hdt_id=HDT, code="8310-5", period=PERIOD, max_points=5)
    body = await services.data.timeseries(args, None)
    c.TimeseriesData.model_validate({k: v for k, v in body.items() if k != "_meta"})
    assert len(body["v"]) == 5
    full = await services.data.timeseries(
        c.TimeseriesArgs(hdt_id=HDT, code="8310-5", period=PERIOD), None)
    assert body["v"][0] == full["v"][0] and body["v"][-1] == full["v"][-1]


async def test_medications_come_from_fhir_statements(services):
    body = await services.data.medications(c.MedicationsArgs(hdt_id=HDT, active_only=True), None)
    c.MedicationsData.model_validate(body)
    med = body["medications"][0]
    assert med["atc"] == "P01BF01" and med["route"] == "oral" and med["dose"] == "80/480 mg"


async def test_genome_reads_the_stored_vcf(services):
    body = await services.data.genome(c.GenomeArgs(hdt_id=HDT, genes=["cyp2b6", "CYP2D6"]), None)
    c.GenomeData.model_validate(body)
    assert [v["gene"] for v in body["variants"]] == ["CYP2B6"]
    v = body["variants"][0]
    assert v["star_allele"] == "*1/*6" and v["genotype"] == "G/T" and v["rsid"] == "rs3745274"
    assert v["phenotype"] == "intermediate metaboliser"


async def test_imaging_lists_stored_studies(services, runtime):
    from tests.contract.test_ahdt_import import dicom_bytes

    pipe = await runtime.pipeline()
    from ahdt.ingest.batch import BatchImporter

    await BatchImporter(pipe).dicom(dicom_bytes(HDT))
    body = await services.data.imaging(c.ImagingArgs(hdt_id=HDT, modality="CR"), None)
    c.ImagingData.model_validate(body)
    assert len(body["studies"]) <= 1


async def test_cohort_k_anonymity_generalises_and_suppresses(services, runtime):
    pipe = await runtime.pipeline()
    await pipe.backends.fhir.create({"resourceType": "Patient", "id": HDT,
                                     "birthDate": "1979-03-02",
                                     "address": [{"state": "Lagos"}]}, partition="ahdt")
    args = c.CohortExtractArgs(hdt_id=HDT, cohort_def={"condition": "61462000"},
                               fields=["age_band", "temperature"], privacy={"k": 2})
    body = await services.cohort.extract(args, Who())
    c.CohortExtractData.model_validate(body)
    report = body["privacy_report"]
    assert report["method"] == "k-anonymity" and report["k"] == 5 and report["requested_k"] == 2
    assert report["input_rows"] == 1 and body["rows"] == [] and report["suppressed"] == 1


async def test_cohort_without_consent_for_the_purpose_is_empty(services):
    class Research(Who):
        class ctx:
            purpose = "research"
            actor_id = "r-1"

    args = c.CohortExtractArgs(hdt_id=HDT, cohort_def={}, fields=["age_band"], privacy={"k": 5})
    body = await services.cohort.extract(args, Research())
    assert body["privacy_report"]["input_rows"] == 0


async def test_differential_privacy_charges_the_budget(services):
    args = c.CohortExtractArgs(hdt_id=HDT, cohort_def={}, fields=["age_band"],
                               privacy={"epsilon": 8.0})
    body = await services.cohort.extract(args, Who())
    report = body["privacy_report"]
    assert report["method"] == "laplace" and report["epsilon_remaining"] == pytest.approx(12.0)
    assert "count" in body["aggregates"] and "rows" not in report
    await services.cohort.extract(args, Who())
    with pytest.raises(Problem) as exc:
        await services.cohort.extract(args, Who())
    assert exc.value.status == 403


async def test_unknown_cohort_keys_are_refused(services):
    args = c.CohortExtractArgs(hdt_id=HDT, cohort_def={"colour": "red"}, fields=["age_band"],
                               privacy={"k": 5})
    with pytest.raises(Problem) as exc:
        await services.cohort.extract(args, Who())
    assert exc.value.status == 422


