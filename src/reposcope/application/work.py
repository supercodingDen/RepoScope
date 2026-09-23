"""Submission identity, policy and orchestration through a typed persistence port."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from contracts.models import (
    Contract,
    JobView,
    RepositoryAccepted,
    RepositoryCreate,
    RunAccepted,
    RunCreate,
    RunView,
)
from reposcope.domain.errors import WorkError


@dataclass(frozen=True, slots=True)
class AdmissionPolicy:
    """Operator-owned exact budgets; mock submissions reserve no paid usage."""

    pending_limit: int = 100
    reservation_usd: Decimal = Decimal("0.000000")
    request_limit_usd: Decimal = Decimal("0.100000")
    daily_limit_usd: Decimal = Decimal("1.000000")
    project_limit_usd: Decimal = Decimal("4.000000")

    def __post_init__(self) -> None:
        for amount in (
            self.reservation_usd,
            self.request_limit_usd,
            self.daily_limit_usd,
            self.project_limit_usd,
        ):
            if (
                not amount.is_finite()
                or amount < 0
                or amount > Decimal("999999999999.999999")
                or amount != amount.quantize(Decimal("0.000001"))
            ):
                raise ValueError("Budgets must be nonnegative numeric(18,6) amounts.")
        if not 1 <= self.pending_limit <= 100:
            raise ValueError("Pending limit must be between one and 100.")

    def check(self, pending: int, daily: Decimal, project: Decimal, *, run: bool = True) -> None:
        """Evaluate facts read while the repository holds its admission lock."""
        if pending >= self.pending_limit:
            raise WorkError("RATE_LIMITED")
        if run and (
            self.reservation_usd > self.request_limit_usd
            or daily + self.reservation_usd > self.daily_limit_usd
            or project + self.reservation_usd > self.project_limit_usd
        ):
            raise WorkError("BUDGET_EXCEEDED")


@dataclass(frozen=True, slots=True)
class Submission:
    """Server-owned identity and time shared by an atomic submission."""

    principal_id: UUID
    key: str
    fingerprint: str
    trace_id: UUID
    now: datetime


class WorkRepository(Protocol):
    """Durable transaction boundary; replay must precede fresh admission checks."""

    async def create_repository(
        self, request: RepositoryCreate, submission: Submission, policy: AdmissionPolicy
    ) -> RepositoryAccepted: ...

    async def create_run(
        self, request: RunCreate, submission: Submission, policy: AdmissionPolicy
    ) -> RunAccepted: ...

    async def get_job(self, principal_id: UUID, job_id: UUID) -> JobView: ...

    async def get_run(self, principal_id: UUID, run_id: UUID) -> RunView: ...


def request_fingerprint(request: Contract) -> str:
    """Hash validated JSON including defaults, independent of input formatting."""
    canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class WorkService:
    """Apply server-owned submission identity and delegate atomic persistence."""

    def __init__(self, repository: WorkRepository, policy: AdmissionPolicy | None = None) -> None:
        self.repository = repository
        self.policy = policy or AdmissionPolicy()

    def _submission(self, request: Contract, principal: UUID, key: str, trace: UUID) -> Submission:
        if not 1 <= len(key) <= 128 or any(not 33 <= ord(char) <= 126 for char in key):
            raise WorkError("VALIDATION_ERROR")
        return Submission(principal, key, request_fingerprint(request), trace, datetime.now(UTC))

    async def create_repository(
        self, request: RepositoryCreate, principal: UUID, key: str, trace: UUID
    ) -> RepositoryAccepted:
        return await self.repository.create_repository(
            request, self._submission(request, principal, key, trace), self.policy
        )

    async def create_run(
        self, request: RunCreate, principal: UUID, key: str, trace: UUID
    ) -> RunAccepted:
        return await self.repository.create_run(
            request, self._submission(request, principal, key, trace), self.policy
        )

    async def get_job(self, principal: UUID, job_id: UUID) -> JobView:
        return await self.repository.get_job(principal, job_id)

    async def get_run(self, principal: UUID, run_id: UUID) -> RunView:
        return await self.repository.get_run(principal, run_id)
