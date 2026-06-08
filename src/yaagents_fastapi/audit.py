# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AimpathyMinds

"""AuditEmitter contract — WI-4yaa.SG-04.

``AuditEvent`` dataclass + ``AuditEmitter`` Protocol + ``NoopEmitter``.

Contract is **Profile-aligned** (ADR PI4-yaa-0001): fields map to the
Profile §X-Correlation-ID + §trace block semantics.  This is a *SDK
extension*, not a Profile-mandated normative surface.

Supports-YAAgents-Profile: v0.3
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class AuditEvent:
    """Structured audit payload (ADR PI4-yaa-0001 §Decision).

    All string fields default to ``""`` so callers may omit context that is
    not available for a given operation (e.g. ``resource_id`` on non-resource
    operations, ``tenant_id`` when running without the gateway).

    ``timestamp`` is populated automatically via ``datetime.utcnow`` when the
    caller omits it — the emitter SHOULD NOT override it.

    ``attributes`` is a freeform bag of extra context; emitters SHOULD NOT log
    secret or credential values placed here.
    """

    event_type: str
    tenant_id: str = ""
    actor_id: str = ""
    request_id: str = ""
    correlation_id: str = ""
    operation: str = ""
    resource_id: str = ""
    outcome: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    attributes: dict[str, str] = field(default_factory=dict)


class AuditEmitter(Protocol):
    """Structural protocol for audit-event sinks (ADR PI4-yaa-0001 §Decision).

    Any class with an ``async def emit(self, event: AuditEvent) -> None``
    method satisfies this protocol without explicit inheritance (structural /
    duck typing).  The default implementation is :class:`NoopEmitter`.

    To wire a custom sink, pass it to
    :meth:`~yaagents_fastapi.context.AgenticContext.audit_emit` or set
    ``ctx.audit_emitter`` directly.

    The optional OTLP sink is available via::

        pip install yaagents-fastapi[otel]

    and exposes ``yaagents_fastapi.otel.OtelEmitter``.
    """

    async def emit(self, event: AuditEvent) -> None:
        """Emit one audit event.  Implementations MUST NOT raise."""
        ...


class NoopEmitter:
    """Default audit sink — discards every event silently.  Zero dependencies.

    Used when no emitter is configured so SDK operations remain no-ops for
    callers that do not need audit emission.
    """

    async def emit(self, event: AuditEvent) -> None:  # noqa: ARG002
        pass
