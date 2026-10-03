import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock
from uuid import uuid7

import pytest

from app.contexts.links.adapters.repositories.sql.notifications import PostgresDeliveryQueue
from app.contexts.links.application.dto.notification import EmailJobDto
from app.contexts.links.application.workflows.notifications import ActivationEmailsWorkflow
from worker.run import WorkerRuntime


class Lease:
    def __init__(self, job):
        self.job = job
        self.complete = AsyncMock()
        self.fail = AsyncMock()


class Queue:
    def __init__(self, lease):
        self.lease = lease
        self.rollback = False

    @asynccontextmanager
    async def claim(self):
        try:
            yield self.lease
        except BaseException:
            self.rollback = True
            raise


async def test_success_and_failure_are_acknowledged_only_after_transport():
    lease = Lease(EmailJobDto(uuid7(), "subscriber@example.com", "reserved", 0))
    queue = Queue(lease)
    smtp = AsyncMock()
    workflow = ActivationEmailsWorkflow(queue, smtp, "https://links.example")
    assert await workflow.run_once()
    lease.complete.assert_awaited_once()
    lease.fail.assert_not_awaited()
    payload = smtp.send.await_args.args[0]
    assert payload.variables["short_url"] == "https://links.example/reserved"
    assert payload.recipient == "subscriber@example.com" and payload.html_body is None
    lease.complete.reset_mock()
    smtp.send.side_effect = OSError("temporary")
    assert await workflow.run_once()
    lease.fail.assert_awaited_once()
    lease.complete.assert_not_awaited()


async def test_cancelled_delivery_rolls_back_the_claim():
    lease = Lease(EmailJobDto(uuid7(), "subscriber@example.com", "reserved", 0))
    queue = Queue(lease)
    smtp = AsyncMock()
    smtp.send.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await ActivationEmailsWorkflow(queue, smtp, "https://links.example").run_once()
    assert queue.rollback
    lease.complete.assert_not_awaited()
    lease.fail.assert_not_awaited()


async def test_empty_queue_does_no_io():
    smtp = AsyncMock()
    assert not await ActivationEmailsWorkflow(
        Queue(Lease(None)), smtp, "https://links.example"
    ).run_once()
    smtp.send.assert_not_awaited()


@pytest.mark.parametrize("row", [None, (uuid7(), "subscriber@example.com", "code123", 3)])
async def test_queue_maps_private_driver_rows_and_updates_only_claimed_job(monkeypatch, row):
    from app.contexts.links.adapters.repositories.sql import notifications

    conn = AsyncMock()

    @asynccontextmanager
    async def transaction():
        yield

    conn.transaction = transaction
    cursor = AsyncMock()
    cursor.fetchone.return_value = row
    conn.execute.return_value = cursor

    @asynccontextmanager
    async def connection(url):
        yield conn

    monkeypatch.setattr(notifications.PostgresConnectionContext, "open", connection)
    queue = PostgresDeliveryQueue("postgresql://worker")
    async with queue.claim() as lease:
        if row:
            assert lease.job.email == row[1] and lease.job.attempts == 3
            await lease.complete()
            await lease.fail()
            assert all(call.args[1] == (row[0],) for call in conn.execute.await_args_list[1:])
        else:
            await lease.complete()
            await lease.fail()
            assert conn.execute.await_count == 1
    await queue.cleanup()


def test_smtp_security_modes_are_mutually_exclusive():
    from app.platform.settings import WorkerSettings

    for security in ("tls", "starttls", "plain"):
        config = WorkerRuntime.transport(WorkerSettings(smtp_security=security))._configuration
        assert config.use_ssl == (security == "tls")
        assert config.starttls == (security == "starttls")


@pytest.mark.parametrize("flush_failure", [False, True])
async def test_worker_failures_retry_without_exposing_recipient(monkeypatch, caplog, flush_failure):
    import worker.run as worker

    configured = worker.WorkerSettings(database_url="postgresql://worker")
    public = worker.PublicSettings(public_base_url="https://links.example")
    monkeypatch.setattr(worker, "SchemaAuthority", Mock())
    workflow = AsyncMock()
    workflow.run_once.side_effect = [OSError("subscriber@example.com"), False]
    monkeypatch.setattr(worker, "ActivationEmailsWorkflow", lambda *args: workflow)
    telemetry = Mock()
    if flush_failure:
        telemetry.force_flush.side_effect = OSError()
    monkeypatch.setattr(worker, "build_telemetry", lambda *args: telemetry)
    monkeypatch.setattr(worker, "PostgresDeliveryQueue", lambda *args: AsyncMock())
    monkeypatch.setattr(
        worker.asyncio, "sleep", AsyncMock(side_effect=[None, asyncio.CancelledError])
    )
    with pytest.raises(OSError if flush_failure else asyncio.CancelledError):
        await worker.WorkerRuntime(configured, public).run()
    assert workflow.run_once.await_count == 2
    telemetry.force_flush.assert_called_once_with()
    telemetry.shutdown.assert_called_once_with()
    assert "subscriber@example.com" not in caplog.text
