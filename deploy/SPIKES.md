# Day-0 Spikes

Each spike checks one risky integration before the work packages that depend on it start (design 08, WP00 step 3). A spike that fails switches its work package to the fallback named in design 01.

| Spike | Result | Finding | Test or fallback |
|---|---|---|---|
| MCP SDK 2.3 server inside FastAPI | Passed | The low-level `mcp.server.lowlevel.Server`, served by `streamable_http_app(stateless_http=True, json_response=True)` and mounted under FastAPI with its session manager in the app lifespan. The ported `MCPBackend` (`streamable_http_client` with an `httpx2` client carrying the `X-*` headers) calls every AHDT tool. | `tests/contract/test_ahdt_tools.py::test_gateway_reaches_every_tool_over_mcp` |
| MCP structured output | Passed after a schema change | The SDK client validates `structured_content` against the tool's `outputSchema`. The `_meta` block of design 03 (3.6) is therefore part of every output schema (`atra.schemagen.output_schema`). | Same test |
| a2a-sdk 1.2 server inside FastAPI | Passed | `create_agent_card_routes` and `create_jsonrpc_routes` in a Starlette sub-app mounted at `/a2a/<agent>/`; `SendMessage` with a data part returns a data message. | `tests/contract/test_ahdt_tools.py::test_agent_cards` |
| gRPC (`grpcio` 1.81) beside the FastAPI app | Passed | `grpc.aio` server started in the AHDT lifespan; ingest is idempotent per key. | `tests/contract/test_ahdt_grpc.py` |
| OPA 1.21 as a local process (p0 policy backend) | Passed | `opa run --server` over `policies/opa`; 18 `opa test` cases pass; clients fail closed. | `tests/unit/atra/test_policy_connection.py` |
| MLflow 3.17 as the p0 model registry | Changed | Import takes 4.5 s and creating a new SQLite store about 60 s on this laptop. The p0 registry is therefore a JSON file with MLflow's stages (`FileModelRegistry`); the MLflow backend serves p3 and the registration run. | Measured 2026-10-09 |
| `ospsuite` on Linux via R and `rpy2` | Not run | Not run on the laptop or VM: no R, no docker. | Fallback in use: Python generic PBPK (`tests/unit/ahdt/models/external/test_sbml_pbpk.py`) |
| TimeSHAP with numpy 2.2 and pandas 2.2 | Failed | timeshap 1.0.4 installs but does not import with shap 0.52 (run 2026-10-12). | Fallback in use: SHAP on windowed features |
| openCARP image, 1 s tissue simulation | Passed | v20.0 AppImage (54 MB, no root, no FUSE) ran TT2006 single-cell and 2D tissue on the laptop. | `tests/unit/ahdt/models/external/test_opencarp.py` |
| Langfuse smallest self-hosted set | Not run | Image pulls need approval. | |
| htsget-rs image and configuration | Not run | Image pull needs approval. | |
| OpenMRS RefApp 3 SMART launch | Not run | Image pulls need approval. | |
| `pythonfmu` build and FMPy run of a 2-state ODE | Passed | pythonfmu 0.7.0 built FMI 2.0 FMUs of the cardiovascular, respiratory and renal models and FMPy 0.3.32 ran them. An FMU embeds Python: a second instantiation in one process fails and `freeInstance` corrupts the host heap, so each co-simulation runs in its own process. | `tests/unit/ahdt/models/external/test_cosim.py` |
| Microsoft GraphRAG over a 20-page PDF via Ollama Cloud | Not run | Full-scope install (VM) and the Ollama key (P2). | |
