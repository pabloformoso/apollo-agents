"""Coverage for the tool-schema builders + helpers in agent/run.py.

These are pure functions that convert tool Python signatures + docstrings into
the Anthropic / OpenAI tool-schema shapes the agent loop sends. No LLM, no I/O.
"""
from __future__ import annotations

import inspect

from agent.run import (
    _python_type_to_json,
    _parse_arg_docs,
    _build_properties,
    _build_anthropic_schemas,
    _build_openai_schemas,
    _wants_catalog,
)


class TestPythonTypeToJson:
    def test_known_types_map(self):
        def f(a: str, b: int, c: float, d: bool):  # noqa: ANN
            ...
        params = inspect.signature(f).parameters
        assert _python_type_to_json(params["a"].annotation) == "string"
        assert _python_type_to_json(params["b"].annotation) == "integer"
        assert _python_type_to_json(params["c"].annotation) == "number"
        assert _python_type_to_json(params["d"].annotation) == "boolean"

    def test_empty_annotation_defaults_to_string(self):
        assert _python_type_to_json(inspect.Parameter.empty) == "string"

    def test_unknown_type_defaults_to_string(self):
        assert _python_type_to_json(dict) == "string"


class TestParseArgDocs:
    def test_extracts_args_section(self):
        doc = (
            "Summary line.\n\n"
            "Args:\n"
            "    genre: The genre folder name.\n"
            "    duration_min: Minutes to fill.\n\n"
            "Returns: something.\n"
        )
        out = _parse_arg_docs(doc)
        assert out == {
            "genre": "The genre folder name.",
            "duration_min": "Minutes to fill.",
        }

    def test_no_args_section_returns_empty(self):
        assert _parse_arg_docs("Just a summary, no args.") == {}

    def test_stops_at_dedented_section(self):
        doc = "Args:\n    a: first\nReturns:\n    not an arg\n"
        out = _parse_arg_docs(doc)
        assert "a" in out
        assert "Returns" not in out


def _sample_tool(genre: str, duration_min: int, context_variables: dict) -> str:
    """Build a set.

    Args:
        genre: Genre folder.
        duration_min: Length in minutes.
    """
    return ""


def _sample_optional(name: str = "x", context_variables: dict | None = None) -> str:
    """Optional-arg tool.

    Args:
        name: The name.
    """
    return ""


class TestBuildProperties:
    def test_skips_context_variables_and_marks_required(self):
        props, required = _build_properties(_sample_tool)
        assert "context_variables" not in props
        assert props["genre"] == {"type": "string", "description": "Genre folder."}
        assert props["duration_min"]["type"] == "integer"
        assert set(required) == {"genre", "duration_min"}

    def test_default_arg_not_required(self):
        props, required = _build_properties(_sample_optional)
        assert "name" in props
        assert required == []  # name has a default → optional


class TestBuildSchemas:
    def test_anthropic_schema_shape(self):
        schemas = _build_anthropic_schemas([_sample_tool])
        assert len(schemas) == 1
        s = schemas[0]
        assert s["name"] == "_sample_tool"
        assert s["description"] == "Build a set."
        assert s["input_schema"]["type"] == "object"
        assert "genre" in s["input_schema"]["properties"]
        assert set(s["input_schema"]["required"]) == {"genre", "duration_min"}

    def test_openai_schema_shape(self):
        schemas = _build_openai_schemas([_sample_tool])
        assert len(schemas) == 1
        s = schemas[0]
        assert s["type"] == "function"
        assert s["function"]["name"] == "_sample_tool"
        assert s["function"]["description"] == "Build a set."
        assert s["function"]["parameters"]["type"] == "object"

    def test_empty_tool_list(self):
        assert _build_anthropic_schemas([]) == []
        assert _build_openai_schemas([]) == []


class TestWantsCatalog:
    def test_detects_catalog_keywords(self):
        assert _wants_catalog("I added new songs to the folder")
        assert _wants_catalog("please sync the catalog")
        assert _wants_catalog("there are new tracks")

    def test_rejects_unrelated(self):
        assert not _wants_catalog("build me a 60 minute lofi set")
