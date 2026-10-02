"""Durable work stays pending until transport acknowledgement and transaction commit."""

import asyncio
import logging
from time import perf_counter

from shared_notifications.capture import SentEmailNotification
from shared_observability.telemetry import TelemetryService
from shared_observability.tracing import finish_span, start_client_span

from app.contexts.links.application.ports.notifications import DeliveryQueue, EmailTransport
from app.contexts.links.application.telemetry import (
    LEASES,
    OUTCOME,
    PROCESS,
    PROCESS_DURATION,
    SMTP_DURATION,
)


class ActivationEmailsWorkflow:
    def __init__(
        self,
        queue: DeliveryQueue,
        transport: EmailTransport,
        public_origin: str,
        telemetry: TelemetryService | None = None,
    ) -> None:
        self._queue, self._transport = queue, transport
        self._origin = public_origin.rstrip("/")
        self._telemetry = telemetry

    async def run_once(self) -> bool:
        started = perf_counter()
        async with self._queue.claim() as lease:
            job = lease.job
            if job is None:
                return False
            url = f"{self._origin}/{job.short_code}"
            notification = SentEmailNotification(
                recipient=job.email,
                subject="Your link is ready",
                template="links.activation",
                variables={"short_url": url},
                text_body=(
                    f"The link you asked about is now active.\n\nOpen it here: {url}\n\n"
                    "You requested this one-time activation email on Plazia Links."
                ),
            )
            carrier = {
                key: value
                for key, value in (("traceparent", job.traceparent), ("tracestate", job.tracestate))
                if value
            }
            if self._telemetry is not None:
                self._telemetry.metrics.emit(LEASES, value=1)
            try:
                with PROCESS.start(
                    self._telemetry, carrier=carrier or None, instrumentation_name=__name__
                ):
                    smtp_started = perf_counter()
                    outcome = "sent"
                    with start_client_span(
                        self._telemetry, name="send smtp", instrumentation_name=__name__
                    ) as span:
                        try:
                            await self._transport.send(notification)
                        except asyncio.CancelledError as error:
                            outcome = "cancelled"
                            finish_span(span, error=error)
                            raise
                        except Exception as error:
                            outcome = "dead" if job.attempts >= 4 else "retry"
                            finish_span(span, error=error)
                            logging.getLogger(__name__).warning(
                                "Activation email attempt failed",
                                extra={"error_type": type(error).__name__},
                            )
                        finally:
                            if self._telemetry is not None:
                                self._telemetry.metrics.emit(
                                    SMTP_DURATION,
                                    value=perf_counter() - smtp_started,
                                    attributes={"links.outcome": outcome},
                                )
                    if outcome == "sent":
                        await lease.complete()
                    else:
                        await lease.fail()
            finally:
                if self._telemetry is not None:
                    self._telemetry.metrics.emit(LEASES, value=0)
        # Terminal metrics reflect successful durable settlement, never an uncommitted ACK.
        if self._telemetry is not None:
            self._telemetry.metrics.emit(
                PROCESS_DURATION,
                value=perf_counter() - started,
                attributes={"links.outcome": outcome},
            )
            self._telemetry.metrics.emit(OUTCOME, value=1, attributes={"links.outcome": outcome})
        return True
