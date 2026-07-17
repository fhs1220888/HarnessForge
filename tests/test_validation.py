from harnessforge.agent.validation import (
    build_schema_map,
    schema_is_wellformed,
    validate_tool_input,
)

BASH_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string"},
        "timeout_s": {"type": "integer"},
    },
    "required": ["command"],
}


def test_valid_input_passes():
    assert validate_tool_input(BASH_SCHEMA, {"command": "ls", "timeout_s": 30}) is None


def test_missing_required_field_reports_it():
    err = validate_tool_input(BASH_SCHEMA, {"timeout_s": 30})
    assert err is not None and "command" in err


def test_wrong_type_reports_it():
    err = validate_tool_input(BASH_SCHEMA, {"command": "ls", "timeout_s": "soon"})
    assert err is not None and "timeout_s" in err


def test_collects_multiple_errors():
    # missing 'command' AND wrong type for timeout_s -> both surfaced in one message
    err = validate_tool_input(BASH_SCHEMA, {"timeout_s": "soon"})
    assert "command" in err and "timeout_s" in err


def test_no_schema_means_no_validation():
    assert validate_tool_input(None, {"anything": 1}) is None
    assert validate_tool_input({}, {"anything": 1}) is None


def test_build_schema_map_from_tool_descriptions():
    td = {"tools": [
        {"name": "bash", "input_schema": BASH_SCHEMA},
        {"name": "finish", "input_schema": {"type": "object"}},
    ]}
    m = build_schema_map(td)
    assert set(m) == {"bash", "finish"}
    assert m["bash"] == BASH_SCHEMA


def test_schema_wellformedness_guard():
    assert schema_is_wellformed(BASH_SCHEMA)
    assert not schema_is_wellformed({"type": "not-a-real-type"})


def test_real_harness_schemas_are_wellformed():
    # every tool schema shipped in the baseline harness must be valid JSON Schema
    from pathlib import Path

    import yaml

    td = yaml.safe_load(
        (Path(__file__).parents[1] / "harness" / "tool_descriptions.yaml").read_text())
    for tool in td["tools"]:
        assert schema_is_wellformed(tool["input_schema"]), tool["name"]
