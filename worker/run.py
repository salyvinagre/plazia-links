"""Run the durable activation queue independently of API/serverless invocations."""

import asyncio
from time import monotonic

from shared_notifications.email_smtp import SmtpEmailTransport, SmtpEmailTransportConfiguration

from app.contexts.links.adapters.repositories.sql.notifications import PostgresDeliveryQueue
from app.contexts.links.application.workflows.notifications import ActivationEmailsWorkflow
from app.platform.logging import get_logger, setup_logging
from app.platform.persistence.schema import SchemaAuthority
from app.platform.settings import IdentitySettings, settings
from app.platform.telemetry import build_telemetry


def transport() -> SmtpEmailTransport:
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


async def run() -> None:
    setup_logging()
    settings.validate_runtime()
    url = settings.worker_database_url.get_secret_value()
    if not url:
        raise ValueError("PLZL_WORKER_DATABASE_URL is required")
    origin = IdentitySettings()
    origin.validate_public_origin(production=settings.environment in {"production", "prod"})
    SchemaAuthority(url).check(runtime="worker")
    queue = PostgresDeliveryQueue(url)
    smtp = transport()
    telemetry = build_telemetry(settings, "worker")
    workflow = ActivationEmailsWorkflow(queue, smtp, origin.public_base_url, telemetry)
    iterations = 0
    sample_due = 0.0
    try:
        while True:
            if monotonic() >= sample_due:
                try:
                    await queue.sample(telemetry)
                except Exception as error:
                    get_logger(__name__).warning(
                        "Activation queue sample failed", extra={"error_type": type(error).__name__}
                    )
                sample_due = monotonic() + 60
            try:
                worked = await workflow.run_once()
                if iterations % 720 == 0:
                    await queue.cleanup()
                iterations += 1
            except Exception as error:
                get_logger(__name__).error(
                    "Activation delivery iteration failed",
                    extra={"error_type": type(error).__name__},
                )
                worked = False
            if not worked:
                await asyncio.sleep(settings.worker_interval)
    finally:
        telemetry.force_flush()
        telemetry.shutdown()


if __name__ == "__main__":
    asyncio.run(run())
