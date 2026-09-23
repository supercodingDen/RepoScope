"""Contract tests that require no network, credentials, database, or application."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from contracts.examples import EXAMPLES, GEN, RESULT, RUN, TIME, JsonObject, JsonValue
from contracts.models import ERROR_STATUS, MODELS, Problem, RunEvent
from scripts.export_contracts import generated_files, openapi_document, responses

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", list(MODELS))
def test_examples_round_trip_without_loss(name: str) -> None:
    model = MODELS[name]
    value = model.model_validate_json(json.dumps(EXAMPLES[name]))
    reconstructed = model.model_validate_json(value.model_dump_json())
    assert reconstructed == value
    Draft202012Validator(model.model_json_schema(), format_checker=FormatChecker()).validate(
        json.loads(value.model_dump_json())
    )


@pytest.mark.parametrize("name", list(MODELS))
def test_unknown_fields_are_rejected(name: str) -> None:
    value: JsonObject = {**EXAMPLES[name], "unexpected": "do not accept"}
    with pytest.raises(ValidationError):
        MODELS[name].model_validate_json(json.dumps(value))


@pytest.mark.parametrize(
    ("name", "field", "value"),
    [
        ("RepositoryCreate", "url", "http://169.254.169.254/latest/meta-data"),
        ("RepositoryCreate", "url", "https://github.com.evil.example/owner/repo"),
        ("RepositoryCreate", "url", "https://user:password@github.com/owner/repo"),
        ("RepositoryCreate", "requested_ref", "--upload-pack=command"),
        ("RepositoryCreate", "requested_ref", "main..other"),
        ("SearchRequest", "top_k", 0),
        ("SearchRequest", "top_k", 21),
        ("SearchRequest", "top_k", "10"),
        ("SearchRequest", "top_k", True),
        ("SearchRequest", "query", ""),
        ("SearchRequest", "path_prefix", "../private"),
        ("SearchRequest", "path_prefix", "/etc"),
        ("SearchRequest", "path_prefix", "C:\\private"),
        ("RunCreate", "question", "a" * 4001),
        ("GetFileTool", "end_line", 9),
        ("GetFileTool", "end_line", 210),
        ("GetFileTool", "path", "../secret"),
        ("FileResult", "path", "../secret"),
        ("FileResult", "path", "/etc/passwd"),
        ("FileResult", "path", "C:\\secret"),
        ("FileResult", "path", "src/\x00file.py"),
        ("FileResult", "end_line", 9),
        ("FileResult", "end_line", 210),
        ("JobView", "commit_sha", None),
        ("JobView", "progress_percent", 99),
        ("JobView", "failure_code", "unexpected"),
        ("JobView", "created_at", "2026-09-16T12:00:00"),
        ("RunView", "status", "failed"),
        ("RunView", "result", None),
        ("RunResult", "citations", []),
        ("RunResult", "estimated_cost_usd", 0.1),
        ("RunResult", "model", "unapproved-expensive-model"),
        ("IngestRequested", "schema_version", 2),
        ("IngestRequested", "aggregate_id", RUN),
        ("AgentRequested", "event_type", "repo.ingest.requested"),
        ("RunEvent", "sequence", 0),
    ],
)
def test_unsafe_or_inconsistent_values_fail(name: str, field: str, value: JsonValue) -> None:
    changed: JsonObject = {**EXAMPLES[name], field: value}
    with pytest.raises(ValidationError):
        MODELS[name].model_validate_json(json.dumps(changed))


@pytest.mark.parametrize("code", list(ERROR_STATUS))
def test_error_mapping_is_consistent(code: str) -> None:
    example: JsonObject = {**EXAMPLES["Problem"], "code": code, "status": ERROR_STATUS[code]}
    problem = Problem.model_validate_json(json.dumps(example))
    assert problem.status == ERROR_STATUS[problem.code]
    example["status"] = 418
    with pytest.raises(ValidationError):
        Problem.model_validate_json(json.dumps(example))


@pytest.mark.parametrize("status", ["queued", "running", "succeeded", "failed"])
def test_all_lifecycle_states_have_consistent_examples(status: str) -> None:
    job: JsonObject = {
        **EXAMPLES["JobView"],
        "status": status,
        "progress_percent": 100 if status == "succeeded" else 10,
        "failure_code": "SOURCE_UNAVAILABLE" if status == "failed" else None,
    }
    run: JsonObject = {
        **EXAMPLES["RunView"],
        "status": status,
        "result": RESULT if status == "succeeded" else None,
        "failure_code": "PROVIDER_TIMEOUT" if status == "failed" else None,
    }
    MODELS["JobView"].model_validate_json(json.dumps(job))
    MODELS["RunView"].model_validate_json(json.dumps(run))


@pytest.mark.parametrize(
    "data",
    [
        {"kind": "run.started", "model": "mock"},
        {"kind": "tool.started", "tool": "search_code", "step": 1},
        {"kind": "tool.completed", "tool": "search_code", "step": 1},
        {"kind": "run.completed", "result": RESULT},
        {"kind": "run.failed", "code": "PROVIDER_TIMEOUT", "message": "The provider timed out."},
    ],
)
def test_sse_variants_are_typed(data: JsonObject) -> None:
    event: JsonObject = {"run_id": RUN, "sequence": 1, "occurred_at": TIME, "data": data}
    validated = RunEvent.model_validate_json(json.dumps(event))
    assert validated.sequence == 1


def test_mixed_generation_search_is_rejected() -> None:
    value = deepcopy(EXAMPLES["SearchResponse"])
    results = value["results"]
    assert isinstance(results, list)
    first = results[0]
    assert isinstance(first, dict)
    first["generation_id"] = RUN
    with pytest.raises(ValidationError):
        MODELS["SearchResponse"].model_validate_json(json.dumps(value))


def test_mixed_generation_run_is_rejected() -> None:
    value = deepcopy(EXAMPLES["RunView"])
    value["generation_id"] = RUN
    assert RUN != GEN
    with pytest.raises(ValidationError):
        MODELS["RunView"].model_validate_json(json.dumps(value))


def test_generated_contracts_match_source() -> None:
    for relative, expected in generated_files().items():
        assert json.loads((ROOT / relative).read_text()) == expected, relative


def test_business_routes_require_auth_and_write_idempotency() -> None:
    document = openapi_document(internal=False)
    assert document["security"] == [{"BearerAuth": []}]
    paths = document["paths"]
    assert isinstance(paths, dict)
    assert len(paths) == 9
    for path, operations in paths.items():
        assert isinstance(operations, dict)
        for op in operations.values():
            assert isinstance(op, dict)
            if path.startswith("/v1/"):
                assert op.get("security") != []
            if path in {"/v1/repositories", "/v1/runs"}:
                parameters = op["parameters"]
                assert isinstance(parameters, list)
                assert any(
                    isinstance(item, dict)
                    and item.get("name") == "Idempotency-Key"
                    and item.get("required") is True
                    for item in parameters
                )


def test_internal_contract_has_no_public_business_or_retrieval_routes() -> None:
    document = openapi_document(internal=True)
    paths = document["paths"]
    assert isinstance(paths, dict)
    assert set(paths) == {"/healthz", "/readyz", "/metrics"}


def test_openapi_preserves_every_error_code_example() -> None:
    documented = responses("RepositoryAccepted", "202")
    for code, status in ERROR_STATUS.items():
        response = documented[str(status)]
        assert isinstance(response, dict)
        content = response["content"]
        assert isinstance(content, dict)
        media = content["application/problem+json"]
        assert isinstance(media, dict)
        examples = media["examples"]
        assert isinstance(examples, dict)
        item = examples[code]
        assert isinstance(item, dict)
        problem = Problem.model_validate_json(json.dumps(item["value"]))
        assert problem.status == status
        assert problem.code == code
