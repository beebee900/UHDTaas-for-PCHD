"""AHDT Layer 6.5: connectors and coupling (design 03, 3.16; design 04, 4.8).

- `connectors`: every 3.16 connector, generated `SystemToWholeBodyConnector` per twin;
- `manager.build_coupling`: one `ConnectorManager` per HDT from the twin definitions;
- `inbox`: HLC reorder window and the latest payload per incoming connector;
- `policies`: consent pairs, range guard and OPA on every connector;
- `registration`: contract registration in the schema registry;
- `service`: the process-wide service and `GET /v1/persons/{hdt_id}/coupling`.
"""
