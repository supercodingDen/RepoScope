"""Export schemas and API descriptions without starting an application."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.examples import EXAMPLES, JsonObject, JsonValue  # noqa: E402
from contracts.models import ERROR_STATUS, MODELS  # noqa: E402


def ref(name: str) -> JsonObject:
    return {"$ref": f"#/components/schemas/{name}"}


def content(name: str) -> JsonObject:
    return {"application/json": {"schema": ref(name), "example": EXAMPLES[name]}}


def problem_response(code: str) -> JsonObject:
    title = code.replace("_", " ").capitalize()
    example: JsonObject = {
        **EXAMPLES["Problem"],
        "status": ERROR_STATUS[code],
        "code": code,
        "title": title,
        "detail": title + ".",
    }
    return {
        "description": title,
        "content": {"application/problem+json": {"schema": ref("Problem"), "example": example}},
    }


def responses(success: str, status: str = "200") -> JsonObject:
    result: JsonObject = {
        status: {
            "description": "Success",
            "content": content(success),
            "headers": {"X-Request-ID": {"schema": {"type": "string", "format": "uuid"}}},
        }
    }
    for error_status in sorted(set(ERROR_STATUS.values())):
        codes = [code for code, value in ERROR_STATUS.items() if value == error_status]
        examples: JsonObject = {}
        for code in codes:
            examples[code] = {
                "value": {
                    **EXAMPLES["Problem"],
                    "status": error_status,
                    "code": code,
                    "title": code.replace("_", " ").capitalize(),
                    "detail": code.replace("_", " ").capitalize() + ".",
                }
            }
        result[str(error_status)] = {
            "description": "; ".join(codes),
            "content": {
                "application/problem+json": {
                    "schema": ref("Problem"),
                    "examples": examples,
                }
            },
        }
    return result


def operation(
    operation_id: str,
    output: str,
    request: str | None = None,
    *,
    accepted: bool = False,
    path_parameter: str | None = None,
    public: bool = False,
) -> JsonObject:
    op: JsonObject = {
        "operationId": operation_id,
        "responses": responses(output, "202" if accepted else "200"),
    }
    parameters: list[JsonValue] = []
    if request is not None:
        op["requestBody"] = {"required": True, "content": content(request)}
    if accepted:
        parameters.append(
            {
                "name": "Idempotency-Key",
                "in": "header",
                "required": True,
                "schema": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": r"^[!-~]+$",
                },
            }
        )
    if path_parameter:
        parameters.append(
            {
                "name": path_parameter,
                "in": "path",
                "required": True,
                "schema": {"type": "string", "format": "uuid"},
            }
        )
    if parameters:
        op["parameters"] = parameters
    if public:
        op["security"] = []
    return op


def collect_components() -> JsonObject:
    schemas: JsonObject = {}
    for name, model in MODELS.items():
        schema = cast(
            JsonObject, model.model_json_schema(ref_template="#/components/schemas/{model}")
        )
        definitions = schema.pop("$defs", {})
        if not isinstance(definitions, dict):
            raise TypeError("Schema definitions must be an object")
        for key, value in definitions.items():
            if key in schemas and schemas[key] != value:
                raise ValueError(f"Inconsistent component: {key}")
            schemas[key] = value
        if name in schemas and schemas[name] != schema:
            raise ValueError(f"Inconsistent root component: {name}")
        schemas[name] = schema
    return schemas


def openapi_document(*, internal: bool) -> JsonObject:
    paths: JsonObject = {
        "/healthz": {"get": operation("health", "Health", public=True)},
        "/readyz": {"get": operation("readiness", "Health", public=True)},
        "/metrics": {
            "get": {
                "operationId": "metrics",
                "responses": {
                    "200": {
                        "description": "Prometheus metrics",
                        "content": {
                            "text/plain": {
                                "schema": {"type": "string"},
                                "example": "# TYPE reposcope_ready gauge\nreposcope_ready 1\n",
                            }
                        },
                    },
                    "401": problem_response("UNAUTHENTICATED"),
                },
            }
        },
    }
    if not internal:
        paths.update(
            {
                "/v1/repositories": {
                    "post": operation(
                        "createRepository", "RepositoryAccepted", "RepositoryCreate", accepted=True
                    )
                },
                "/v1/jobs/{job_id}": {
                    "get": operation("getJob", "JobView", path_parameter="job_id")
                },
                "/v1/search": {"post": operation("searchCode", "SearchResponse", "SearchRequest")},
                "/v1/runs": {
                    "post": operation("createRun", "RunAccepted", "RunCreate", accepted=True)
                },
                "/v1/runs/{run_id}": {
                    "get": operation("getRun", "RunView", path_parameter="run_id")
                },
            }
        )
        stream = operation("streamRunEvents", "RunEvent", path_parameter="run_id")
        parameters = stream["parameters"]
        if not isinstance(parameters, list):
            raise TypeError("Parameters must be a list")
        parameters.append(
            {
                "name": "Last-Event-ID",
                "in": "header",
                "required": False,
                "schema": {"type": "string", "pattern": r"^[1-9][0-9]*$"},
            }
        )
        stream_responses = cast(JsonObject, stream["responses"])
        frame = "id: 1\nevent: run.started\ndata: " + json.dumps(EXAMPLES["RunEvent"]) + "\n\n"
        stream_responses["200"] = {
            "description": "Replayable SSE; see docs/contracts.md",
            "content": {"text/event-stream": {"schema": {"type": "string"}, "example": frame}},
            "x-event-schema": ref("RunEvent"),
        }
        paths["/v1/runs/{run_id}/events"] = {"get": stream}
    title = "RepoScope Worker Management" if internal else "RepoScope Public API"
    return {
        "openapi": "3.1.0",
        "info": {
            "title": title,
            "version": "1.0.0",
            "description": "T01 contract only. All business endpoints require authentication.",
        },
        "servers": [{"url": "http://127.0.0.1:9090" if internal else "http://127.0.0.1:8000"}],
        "security": [{"BearerAuth": []}],
        "paths": paths,
        "components": {
            "schemas": collect_components(),
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "opaque deployment token",
                }
            },
        },
    }


def generated_files() -> dict[Path, JsonObject]:
    base = Path("packages/contracts")
    files: dict[Path, JsonObject] = {}
    for name, model in MODELS.items():
        schema = cast(JsonObject, model.model_json_schema())
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        files[base / "schemas" / f"{name}.schema.json"] = schema
        files[base / "fixtures" / f"{name}.json"] = EXAMPLES[name]
    files[base / "openapi/public.yaml"] = openapi_document(internal=False)
    files[base / "openapi/internal.yaml"] = openapi_document(internal=True)
    for name, subject in (
        ("IngestRequested", "repo.ingest.requested"),
        ("AgentRequested", "agent.run.requested"),
        ("SourceAcquired", "repo.source.acquired"),
    ):
        files[base / "events" / f"{subject}.v1.schema.json"] = files[
            base / "schemas" / f"{name}.schema.json"
        ]
    for name, tool in (
        ("SearchCodeTool", "search_code"),
        ("GetFileTool", "get_file"),
        ("PinnedScope", "get_repository_summary"),
    ):
        files[base / "tools" / f"{tool}.schema.json"] = files[
            base / "schemas" / f"{name}.schema.json"
        ]
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale: list[str] = []
    files = generated_files()
    for relative, value in files.items():
        path = ROOT / relative
        encoded = json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != encoded:
                stale.append(str(relative))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(encoded, encoding="utf-8", newline="\n")
    if stale:
        print("Contract export is stale: " + ", ".join(stale), file=sys.stderr)
        return 1
    print(f"{'Checked' if args.check else 'Exported'} {len(files)} contract files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
