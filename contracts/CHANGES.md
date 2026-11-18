# Contract changes

Every change to a frozen contract after WP01 is listed here with its version (design 03).

## 2026-10-11, WP17 (connectors)

- Added `schemas/connectors/connector_envelope.v1.0.schema.json`: the wire shape of a
  connector message (`atra.connection.ConnectorEnvelope`).
- Added `schemas/connectors/dead_letter_record.v1.0.schema.json`: the record published to
  `<topic>.dlq` (`atra.connection.DeadLetterRecord`).
- Added `GET /v1/persons/{hdt_id}/coupling` to `openapi/ahdt.yaml` (`CouplingMatrix`).

No existing contract changed.
