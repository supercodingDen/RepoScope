# Contributing

Read AGENTS.md and docs/spec.md before making changes. Use focused branches and English conventional commit messages. Describe the behavior change, reason, tests, and known limits in pull requests.

Install the supported interpreter and uv, then run `uv sync --frozen --all-groups`. The lockfile pins transitive dependencies. Update dependencies intentionally, run the full affected checks, and review the lockfile diff.

Contract changes start in contracts/models.py, followed by examples, semantic tests, schema export, and OpenAPI validation. A wire-breaking change needs a new major contract version or an explicit migration plan. Broker producers and consumers must share schema-version fixtures.

Required T01 checks: schema export drift, JSON Schema/OpenAPI validation, pytest, mypy strict, Ruff lint and format. Runtime integration and deployment checks arrive with their implementation tasks. Never submit secrets, private code, benchmark data of unclear provenance, or fabricated results.

Use decimal/integer money, cancellation-aware async clients, bounded resources, and typed adapters. Provider calls belong only to explicitly enabled live profiles. Avoid unbounded retries, blanket exception swallowing, and type-checking suppressions that hide unsafe interfaces.
