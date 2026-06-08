# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AimpathyMinds

"""Tests for AuditEvent + AuditEmitter + NoopEmitter + AgenticContext.audit_emit
— WI-4yaa.SG-04.

AC:
- AuditEvent dataclass preserves all 10 fields (including defaults).
- NoopEmitter.emit() is a no-op (no exception; returns None).
- AgenticContext.audit_emit() constructs AuditEvent from live context and
  delegates to audit_emitter (NoopEmitter round-trip).
- @agentic_operation() accepts audit_emitter parameter; falls back to
  NoopEmitter when None.
- [otel] extra declared in pyproject.toml; core install does not require it.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from yaagents_fastapi import (
    AgenticContext,
    AgenticResponses,
    AuditEmitter,
    AuditEvent,
    NoopEmitter,
    agentic_operation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class CaptureEmitter:
    """Test-only emitter: records every event for assertion."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


class ErrorEmitter:
    """Test-only emitter: always raises — verifies audit_emit swallows it."""

    async def emit(self, event: AuditEvent) -> None:
        msg = "deliberate test error"
        raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# AuditEvent — dataclass serialisation
# ---------------------------------------------------------------------------


def test_audit_event_all_10_fields_set() -> None:
    """AuditEvent preserves all 10 fields when explicitly provided."""
    ts = datetime(2026, 6, 1, 12, 0, 0)
    event = AuditEvent(
        event_type="agentic.response.written",
        tenant_id="tenant-abc",
        actor_id="user-123",
        request_id="req-001",
        correlation_id="corr-xyz",
        operation="POST /campaigns/{id}/optimizations",
        resource_id="campaign-99",
        outcome="created",
        timestamp=ts,
        attributes={"env": "prod", "version": "0.4.0"},
    )
    d = dataclasses.asdict(event)
    assert d["event_type"] == "agentic.response.written"
    assert d["tenant_id"] == "tenant-abc"
    assert d["actor_id"] == "user-123"
    assert d["request_id"] == "req-001"
    assert d["correlation_id"] == "corr-xyz"
    assert d["operation"] == "POST /campaigns/{id}/optimizations"
    assert d["resource_id"] == "campaign-99"
    assert d["outcome"] == "created"
    assert d["timestamp"] == ts
    assert d["attributes"] == {"env": "prod", "version": "0.4.0"}


def test_audit_event_defaults_are_empty_strings() -> None:
    """All optional string fields default to ''."""
    event = AuditEvent(event_type="agentic.test")
    assert event.tenant_id == ""
    assert event.actor_id == ""
    assert event.request_id == ""
    assert event.correlation_id == ""
    assert event.operation == ""
    assert event.resource_id == ""
    assert event.outcome == ""
    assert event.attributes == {}


def test_audit_event_timestamp_auto_populated() -> None:
    """timestamp is auto-populated via default_factory when omitted."""
    before = datetime.utcnow()
    event = AuditEvent(event_type="agentic.test")
    after = datetime.utcnow()
    assert before <= event.timestamp <= after


def test_audit_event_field_count() -> None:
    """AuditEvent has exactly 10 declared dataclass fields."""
    fields = dataclasses.fields(AuditEvent)
    assert len(fields) == 10


# ---------------------------------------------------------------------------
# NoopEmitter — no-op contract
# ---------------------------------------------------------------------------


def test_noop_emitter_returns_none() -> None:
    """NoopEmitter.emit() completes without error and returns None."""
    emitter = NoopEmitter()
    event = AuditEvent(event_type="agentic.test")
    result = asyncio.run(emitter.emit(event))
    assert result is None


def test_noop_emitter_zero_value_event() -> None:
    """NoopEmitter handles a zero-value AuditEvent without panic."""
    emitter = NoopEmitter()
    event = AuditEvent(event_type="")
    asyncio.run(emitter.emit(event))  # no exception


def test_noop_emitter_is_protocol_compatible() -> None:
    """NoopEmitter satisfies AuditEmitter Protocol at runtime (structural check)."""
    emitter: AuditEmitter = NoopEmitter()
    assert hasattr(emitter, "emit")


# ---------------------------------------------------------------------------
# AgenticContext — audit_emitter field
# ---------------------------------------------------------------------------


def test_agentic_context_defaults_to_noop_emitter() -> None:
    """AgenticContext.audit_emitter defaults to NoopEmitter."""
    ctx = AgenticContext()
    assert isinstance(ctx.audit_emitter, NoopEmitter)


def test_agentic_context_audit_emitter_replaceable() -> None:
    """audit_emitter can be replaced with a custom sink."""
    cap = CaptureEmitter()
    ctx = AgenticContext()
    ctx.audit_emitter = cap
    assert ctx.audit_emitter is cap


# ---------------------------------------------------------------------------
# AgenticContext.audit_emit() — round-trip
# ---------------------------------------------------------------------------


def test_audit_emit_noop_roundtrip() -> None:
    """audit_emit() with NoopEmitter completes silently (no exception, no event)."""
    ctx = AgenticContext(
        x_tenant_id="t1",
        x_actor_subject="u1",
        x_correlation_id="corr-1",
        x_request_id="req-1",
    )
    asyncio.run(
        ctx.audit_emit("agentic.response.written", outcome="created")
    )
    # If we reach here without exception, the round-trip passed.


def test_audit_emit_populates_context_fields() -> None:
    """audit_emit() auto-populates tenant, actor, correlation, request IDs."""
    cap = CaptureEmitter()
    ctx = AgenticContext(
        x_tenant_id="tenant-xyz",
        x_actor_subject="actor-abc",
        x_correlation_id="corr-001",
        x_request_id="req-002",
    )
    ctx.audit_emitter = cap

    asyncio.run(
        ctx.audit_emit("agentic.response.written", outcome="success")
    )

    assert len(cap.events) == 1
    ev = cap.events[0]
    assert ev.event_type == "agentic.response.written"
    assert ev.tenant_id == "tenant-xyz"
    assert ev.actor_id == "actor-abc"
    assert ev.correlation_id == "corr-001"
    assert ev.request_id == "req-002"
    assert ev.attributes["outcome"] == "success"


def test_audit_emit_extra_kwargs_land_in_attributes() -> None:
    """Extra kwargs to audit_emit() land in AuditEvent.attributes."""
    cap = CaptureEmitter()
    ctx = AgenticContext()
    ctx.audit_emitter = cap

    asyncio.run(
        ctx.audit_emit("agentic.test", operation="POST /test", resource_id="r-1")
    )

    ev = cap.events[0]
    assert ev.attributes["operation"] == "POST /test"
    assert ev.attributes["resource_id"] == "r-1"


def test_audit_emit_swallows_emitter_exception() -> None:
    """audit_emit() does NOT propagate emitter errors to the caller."""
    ctx = AgenticContext()
    ctx.audit_emitter = ErrorEmitter()  # type: ignore[assignment]

    # Must not raise
    asyncio.run(ctx.audit_emit("agentic.test"))


# ---------------------------------------------------------------------------
# @agentic_operation — audit_emitter parameter
# ---------------------------------------------------------------------------


def test_agentic_operation_accepts_audit_emitter_none() -> None:
    """@agentic_operation() without audit_emitter defaults to NoopEmitter."""

    @agentic_operation(
        resource="Widget",
        operation_kind="mutation",
        responses=AgenticResponses(success=True),
    )
    async def _handler() -> None:
        pass

    stored = getattr(_handler, "__agentic_audit_emitter__", None)
    assert isinstance(stored, NoopEmitter)


def test_agentic_operation_stores_custom_audit_emitter() -> None:
    """@agentic_operation() stores the provided audit_emitter on the function."""
    cap = CaptureEmitter()

    @agentic_operation(
        resource="Widget",
        operation_kind="mutation",
        responses=AgenticResponses(success=True),
        audit_emitter=cap,  # type: ignore[arg-type]
    )
    async def _handler() -> None:
        pass

    stored = getattr(_handler, "__agentic_audit_emitter__", None)
    assert stored is cap


def test_agentic_operation_audit_emitter_fallback_when_none_explicit() -> None:
    """audit_emitter=None explicitly falls back to NoopEmitter."""

    @agentic_operation(
        resource="Widget",
        operation_kind="analysis",
        responses=AgenticResponses(success=True),
        audit_emitter=None,
    )
    async def _handler() -> None:
        pass

    stored = getattr(_handler, "__agentic_audit_emitter__", None)
    assert isinstance(stored, NoopEmitter)


# ---------------------------------------------------------------------------
# Integration: audit_emit via FastAPI request lifecycle
# ---------------------------------------------------------------------------


def test_audit_emit_via_fastapi_dependency() -> None:
    """audit_emit() integrates end-to-end through FastAPI Depends injection."""
    capture = CaptureEmitter()

    app = FastAPI()

    @app.get("/test-audit")
    async def _endpoint(
        ctx: Annotated[AgenticContext, Depends(AgenticContext)],
    ) -> dict[str, str]:
        ctx.audit_emitter = capture
        await ctx.audit_emit("agentic.test", outcome="success")
        return {"ok": "1"}

    client = TestClient(app)
    resp = client.get(
        "/test-audit",
        headers={
            "X-Tenant-ID": "t-fastapi",
            "X-Actor-Subject": "u-fastapi",
            "X-Correlation-ID": "corr-fastapi",
            "X-Request-ID": "req-fastapi",
        },
    )
    assert resp.status_code == 200
    assert len(capture.events) == 1
    ev = capture.events[0]
    assert ev.tenant_id == "t-fastapi"
    assert ev.correlation_id == "corr-fastapi"
    assert ev.attributes["outcome"] == "success"
