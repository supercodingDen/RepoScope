"""Unsafe source identities fail at admission before any durable work is created."""

from __future__ import annotations

import pytest

from tests.test_work_http import TestRepository, client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("url", "https://github.com/owner/."),
        ("url", "https://github.com/owner/.."),
        ("url", "https://github.com/owner/repo.git"),
        ("url", "https://github.com/owner/repo.GIT"),
        ("url", "file:///server/source"),
        ("url", "D:/server/source"),
        ("requested_ref", "branch."),
        ("requested_ref", "refs/heads/.hidden"),
    ],
)
async def test_invalid_source_admission_has_no_side_effects(field: str, value: str) -> None:
    repository = TestRepository()
    body = {"url": "https://github.com/pallets/itsdangerous", "requested_ref": "HEAD"}
    body[field] = value
    async with client(repository) as http:
        response = await http.post(
            "/v1/repositories",
            json=body,
            headers={
                "Authorization": "Bearer test-token",
                "Idempotency-Key": "source-admission-test",
            },
        )
    assert response.status_code == 422
    assert repository.calls == 0
