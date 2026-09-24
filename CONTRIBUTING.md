# Contributing

Read AGENTS.md and docs/spec.md before making changes. Use focused branches and English conventional commit messages. Describe the behavior change, reason, tests, and known limits in pull requests.

Install the supported interpreter and uv, then run `uv sync --frozen --all-groups`. The lockfile pins transitive dependencies. Update dependencies intentionally, run the full affected checks, and review the lockfile diff.

Contract changes start in contracts/models.py, followed by examples, semantic tests, schema export, and OpenAPI validation. A wire-breaking change needs a new major contract version or an explicit migration plan. Broker producers and consumers must share schema-version fixtures.

Required checks: schema export drift, JSON Schema/OpenAPI validation, pytest, mypy strict, Ruff lint and format. Run `uv run --frozen python scripts/smoke_test.py` after changing runtime, migrations, Compose, or dependency boundaries; it uses isolated disposable volumes. Never submit secrets, private code, benchmark data of unclear provenance, or fabricated results. See [development](docs/development.md) and the [current status](docs/project-status.md) for what has actually been verified.

Use decimal/integer money, cancellation-aware async clients, bounded resources, and typed adapters. Provider calls belong only to explicitly enabled live profiles. Avoid unbounded retries, blanket exception swallowing, and type-checking suppressions that hide unsafe interfaces.

Use English in source, documentation, issues, and commit messages. Keep third-party license material and provenance when adding a dependency or fixture. RepoScope source is [Apache-2.0](LICENSE); see [NOTICE](NOTICE), [third-party notices](docs/third-party-notices.md), the [code of conduct](CODE_OF_CONDUCT.md), and the [security policy](SECURITY.md). Before opening a public issue, remove tokens, private source, and sensitive vulnerability details.
