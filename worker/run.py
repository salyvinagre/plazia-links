"""Run a bounded activation email or retention job."""

import asyncio
from argparse import ArgumentParser

from shared_notifications.email_smtp import SmtpEmailTransport, SmtpEmailTransportConfiguration

from app.contexts.links.adapters.repositories.sql.notifications import PostgresDeliveryQueue
from app.contexts.links.application.workflows.notifications import ActivationEmailsWorkflow
from app.platform.logging import get_logger, setup_logging
from app.platform.persistence.schema import SchemaAuthority
from app.platform.settings import PublicSettings, WorkerSettings
from app.platform.telemetry import build_telemetry


class WorkerRuntime:
    """Own worker composition and telemetry for one job invocation."""

    def __init__(self, settings: WorkerSettings, origin: PublicSettings) -> None:
        setup_logging()
        settings.validate_runtime()
        origin.validate_public_origin(production=settings.environment in {"production", "prod"})
        url = settings.database_url.get_secret_value()
        SchemaAuthority(url).check(runtime="worker")
        self._queue = PostgresDeliveryQueue(url)
        transport = self.transport(settings)
        self._telemetry = build_telemetry(settings, "worker")
        self._workflow = ActivationEmailsWorkflow(
            self._queue, transport, origin.public_base_url, self._telemetry
        )

    @staticmethod
    def transport(settings: WorkerSettings) -> SmtpEmailTransport:
        return SmtpEmailTransport(
            configuration=SmtpEmailTransportConfiguration(
                host=settings.smtp_host,
                port=settings.smtp_port,
                from_address=settings.smtp_from,
                from_name=settings.smtp_from_name,
                username=settings.smtp_user,
                password=settings.smtp_password.get_secret_value(),
                timeout_seconds=settings.smtp_timeout,
                starttls=settings.smtp_security == "starttls",
                use_ssl=settings.smtp_security == "tls",
            )
        )

    async def run(self, *, cleanup: bool = False) -> None:
        try:
            async with asyncio.timeout(90):
                if cleanup:
                    await self._queue.cleanup()
                    return
                try:
                    await self._queue.sample(self._telemetry)
                except Exception as error:
                    get_logger(__name__).warning(
                        "Activation queue sample failed",
                        extra={"error_type": type(error).__name__},
                    )
                for _ in range(16):
                    if not await self._workflow.run_once():
                        break
        finally:
            try:
                self._telemetry.force_flush()
            finally:
                self._telemetry.shutdown()


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--cleanup", action="store_true")
    options = parser.parse_args()
    try:
        asyncio.run(WorkerRuntime(WorkerSettings(), PublicSettings()).run(cleanup=options.cleanup))
    except Exception as error:
        get_logger(__name__).error("Links job failed", extra={"error_type": type(error).__name__})
        raise SystemExit(1) from None
