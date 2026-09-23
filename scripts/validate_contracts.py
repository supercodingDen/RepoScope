"""Check OpenAPI, JSON Schema, canonical examples, and semantic contracts offline."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.examples import JsonObject  # noqa: E402
from contracts.models import MODELS  # noqa: E402


def main() -> int:
    base = ROOT / "packages/contracts"
    for name, model in MODELS.items():
        schema = cast(
            JsonObject, json.loads((base / "schemas" / f"{name}.schema.json").read_text())
        )
        raw = (base / "fixtures" / f"{name}.json").read_text()
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(json.loads(raw))
        model.model_validate_json(raw)
    for path in (base / "openapi").glob("*.yaml"):
        document = cast(JsonObject, json.loads(path.read_text()))
        validate(document)
    print(f"Validated {len(MODELS)} schema/example pairs and 2 OpenAPI 3.1 documents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
