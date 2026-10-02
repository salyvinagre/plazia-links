"""Durable settlement, privacy, causal parenting and passive exporter failures."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from shared_observability.telemetry import (
    ConfiguredTelemetryFactory,
    InMemoryTelemetrySink,
    TelemetryService,
)
from uuid6 import uuid7

from app.contexts.links.application.dto.notification import EmailJobDto
from app.contexts.links.application.workflows.notifications import ActivationEmailsWorkflow
from app.kernel.api import ApiContract
from tests.unit.test_notifications import Lease, Queue


@pytest.mark.parametrize(
    ("failure", "attempts", "outcome"), [(False, 0, "sent"), (True, 0, "retry"), (True, 4, "dead")]
)
async def test_delivery_metrics_count_only_committed_bounded_outcomes(failure, attempts, outcome):
    sink = InMemoryTelemetrySink()
    telemetry = TelemetryService(sink=sink)
    queue = Queue(Lease(EmailJobDto(uuid7(), "private@example.com", "private-code", attempts)))
    transport = AsyncMock()
    if failure:
        transport.send.side_effect = OSError("private@example.com")
    assert await ActivationEmailsWorkflow(
        queue, transport, "https://links.example", telemetry
    ).run_once()
    records = sink.metric_records()
    terminal = [record for record in records if record.name == "links.activation.outcome"]
    assert len(terminal) == 1 and terminal[0].attributes.to_dict() == {"links.outcome": outcome}
    assert [r.value for r in records if r.name == "links.activation.leases"] == [1, 0]
    assert "private" not in repr(records)

    class FailedCommitQueue(Queue):
        @asynccontextmanager
        async def claim(self):
            yield self.lease
            raise RuntimeError("commit failed")

    before = len(terminal)
    with pytest.raises(RuntimeError, match="commit failed"):
        await ActivationEmailsWorkflow(
            FailedCommitQueue(queue.lease), transport, "https://links.example", telemetry
        ).run_once()
    assert len([r for r in sink.metric_records() if r.name == "links.activation.outcome"]) == before


async def test_consumer_span_keeps_durable_parent_and_provider_span_without_recipient():
    exporter = InMemorySpanExporter()
    telemetry = ConfiguredTelemetryFactory.build(
        {"telemetry_export_driver": "otel", "telemetry_service_name": "plazia-links"},
        trace_exporter=exporter,
    )
    parent = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
    job = EmailJobDto(uuid7(), "private@example.com", "private-code", 0, parent)
    try:
        assert await ActivationEmailsWorkflow(
            Queue(Lease(job)), AsyncMock(), "https://links.example", telemetry
        ).run_once()
        telemetry.force_flush()
        spans = exporter.get_finished_spans()
        consumer = next(s for s in spans if s.kind.name == "CONSUMER")
        provider = next(s for s in spans if s.kind.name == "CLIENT")
        assert consumer.parent.span_id == int("0123456789abcdef", 16)
        assert consumer.context.trace_id == int("0123456789abcdef0123456789abcdef", 16)
        assert provider.parent.span_id == consumer.context.span_id
        assert consumer.attributes["messaging.operation.type"] == "process"
        assert consumer.attributes["messaging.destination.name"] == "activation_emails"
        assert all("private" not in repr(s.attributes) for s in spans)
    finally:
        telemetry.shutdown()


async def test_exporter_failure_cannot_change_delivery_acknowledgement():
    class BrokenSink(InMemoryTelemetrySink):
        def emit_metric(self, record):
            raise RuntimeError("export unavailable")

    queue = Queue(Lease(EmailJobDto(uuid7(), "private@example.com", "private-code", 0)))
    assert await ActivationEmailsWorkflow(
        queue, AsyncMock(), "https://links.example", TelemetryService(sink=BrokenSink())
    ).run_once()
    queue.lease.complete.assert_awaited_once()
    queue.lease.fail.assert_not_awaited()


async def test_http_metrics_use_resolved_route_templates(application, identity_client):
    sink = InMemoryTelemetrySink()
    application.state.telemetry = TelemetryService(sink=sink)
    assert (await identity_client.get("/missing")).status_code == 404
    durations = [r for r in sink.metric_records() if r.name == "http.server.request.duration"]
    assert len(durations) == 1
    attributes = durations[0].attributes.to_dict()
    assert attributes["http.route"] == "/{short_code}"
    assert "missing" not in repr(attributes)


@pytest.mark.parametrize(
    "base",
    [
        "https://links.example/api",
        "https://links.example/api/v2",
        "https://links.example/api/v1/",
        "https://links.example/api/v1?secret=x",
        "https://user:pass@links.example/api/v1",
        "https://links.example/api/v1#fragment",
        "http://links.example/api/v1",
    ],
)
def test_resource_identity_rejects_unversioned_and_ambiguous_bases(base):
    with pytest.raises(ValueError):
        ApiContract.validate_base(base)
    ApiContract.validate_base("https://links.example/api/v1")
    assert ApiContract.resource("links", "lnk_example") == "/api/v1/links/lnk_example"
