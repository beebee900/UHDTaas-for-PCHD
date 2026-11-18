"""AHDT Layer 6 services (design 04, 4.7): the handlers behind every tool of the gateway."""

from __future__ import annotations

from dataclasses import dataclass

from ahdt.services.cognitive import CognitiveService
from ahdt.services.cohort import CohortService
from ahdt.services.data import DataService
from ahdt.services.model import ModelService
from ahdt.services.runtime import Runtime
from ahdt.services.xai import XaiTools
from atra.service import ToolHandler


@dataclass
class Services:
    runtime: Runtime
    data: DataService
    cohort: CohortService
    model: ModelService
    xai: XaiTools
    cognitive: CognitiveService

    def handlers(self) -> dict[str, ToolHandler]:
        return {**self.data.handlers(), **self.cohort.handlers(), **self.model.handlers(),
                **self.xai.handlers(), **self.cognitive.handlers()}


def build_services(runtime: Runtime, *, localise_with_model: bool = True) -> Services:
    model = ModelService(runtime)
    return Services(runtime, DataService(runtime), CohortService(runtime), model,
                    XaiTools(runtime, model, localise_with_model=localise_with_model),
                    CognitiveService(runtime))
