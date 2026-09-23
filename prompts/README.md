# Prompt namespaces during the pivot

solver-system.md and solver-user.md are still loaded by legacy riddle code.
Their contents intentionally retain riddle semantics until those callers migrate.

Combat implementation must add a separate planner prompt/interface described
in [the API](../docs/api.md). Do not rename answer fields to actions inside
the old solver or accidentally send a riddle prompt to a combat planner.
