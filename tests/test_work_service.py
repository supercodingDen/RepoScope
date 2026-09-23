"""Application policy and canonical request identity checks."""

from decimal import Decimal

import pytest

from contracts.models import RepositoryCreate
from reposcope.application.work import AdmissionPolicy, request_fingerprint
from reposcope.domain.errors import WorkError


def test_validated_defaults_share_canonical_request_identity() -> None:
    first = RepositoryCreate.model_validate_json('{"url":"https://github.com/a/b"}')
    second = RepositoryCreate.model_validate_json(
        '{ "requested_ref": "HEAD", "url": "https://github.com/a/b" }'
    )
    assert request_fingerprint(first) == request_fingerprint(second)
    assert request_fingerprint(first) != request_fingerprint(
        RepositoryCreate(url=first.url, requested_ref="main")
    )


def test_admission_counts_shared_capacity_and_exact_budget() -> None:
    policy = AdmissionPolicy(reservation_usd=Decimal("0.100000"))
    policy.check(99, Decimal("0.900000"), Decimal("3.900000"))
    for pending, daily, project, code in (
        (100, "0", "0", "RATE_LIMITED"),
        (0, "0.900001", "0", "BUDGET_EXCEEDED"),
        (0, "0", "3.900001", "BUDGET_EXCEEDED"),
    ):
        with pytest.raises(WorkError) as error:
            policy.check(pending, Decimal(daily), Decimal(project))
        assert error.value.code == code


@pytest.mark.parametrize("amount", ["-0.1", "NaN", "Infinity", "0.0000001"])
def test_operator_policy_rejects_unsafe_money(amount: str) -> None:
    with pytest.raises(ValueError):
        AdmissionPolicy(reservation_usd=Decimal(amount))
