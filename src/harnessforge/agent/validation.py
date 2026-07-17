"""Pre-execution parameter validation for tool calls.

A production harness validates tool arguments against the tool's declared schema
*before* executing, rather than letting a malformed call blow up inside the tool
and surface as an opaque crash. On failure we return a precise, structured error
that the model can read and repair on the next turn ("missing required field
'command'"), which is the arg-level half of malformed-output recovery.

Uses the standard `jsonschema` validator against the same input_schema the model
is shown in tool_descriptions.yaml — one source of truth, no reinvented checks.
"""

from __future__ import annotations

from typing import Any

import jsonschema
from jsonschema import Draft7Validator


def build_schema_map(tool_descriptions: dict[str, Any]) -> dict[str, dict]:
    """name -> input_schema, from the evolvable tool_descriptions component."""
    return {t["name"]: t.get("input_schema", {}) for t in tool_descriptions.get("tools", [])}


def validate_tool_input(schema: dict | None, tool_input: dict[str, Any]) -> str | None:
    """Return a human/model-readable error string, or None if the input is valid.

    Collects *all* violations (not just the first) so the model can fix them in one
    repair turn instead of ping-ponging.
    """
    if not schema:
        return None  # no schema declared -> nothing to validate against
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(tool_input), key=lambda e: list(e.path))
    if not errors:
        return None
    parts = []
    for e in errors:
        loc = ".".join(str(p) for p in e.path) or "(root)"
        parts.append(f"{loc}: {e.message}")
    return "Invalid tool arguments — " + "; ".join(parts)


def schema_is_wellformed(schema: dict) -> bool:
    """Guard against an evolved tool_descriptions component shipping a broken schema."""
    try:
        Draft7Validator.check_schema(schema)
        return True
    except jsonschema.SchemaError:
        return False
