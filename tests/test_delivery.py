"""Delivery policy rejects unsafe values and bounds retries."""

from __future__ import annotations

import pytest

from reposcope.domain.delivery import DeliveryPolicy, PermanentFailure, retry_delay


def test_delivery_defaults_and_backoff_are_bounded() -> None:
    policy = DeliveryPolicy()
    assert policy.lease_seconds == 60 and policy.heartbeat_seconds == 15
    assert policy.concurrency == 2 and policy.max_deliver == 20
    assert all(1 <= retry_delay(attempt) <= 30 for attempt in range(1, 100))


@pytest.mark.parametrize("changes", [{"concurrency": 3}, {"max_deliver": 0}, {"lease_seconds": 0}])
def test_delivery_policy_rejects_unbounded_configuration(changes: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        DeliveryPolicy(**changes)


def test_failure_codes_cannot_contain_secrets_or_exception_text() -> None:
    with pytest.raises(ValueError):
        PermanentFailure("https://secret:password@example.com")
