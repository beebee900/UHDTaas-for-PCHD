"""AHDT Layer 5: explainable AI (design 04, 4.6).

- `registry`: explainers, their binding to model families, `ExplainerRegistry.bind`
- `explain`: `Explainer.explain` builds an `AHDTExplanation` for a subject
- `causal`: `ProvenanceRecorder` and `CausalGraphBuilder` for the cross-model graph
- `render`, `localise`, `rails`: audience text, localisation and the output rail
- `quality`: faithfulness, robustness and complexity of explanations
"""
