# Public data namespaces

Current files in this directory are legacy riddle exports and historical
fixtures. Do not reinterpret or overwrite them as combat.

Planned combat exports use data/combat/v1/ with explicit schema, network,
contract identity, generated tick and evidence fields. See
[the API](../../../docs/api.md) and [migration plan](../../../docs/pivot-plan.md).
An export is a view; contract state and confirmed actions decide combat.

Combat deployment must update the frontend data adapter and visible mode label
together. Missing/lagging data is unknown, never proof of no opponent action.
