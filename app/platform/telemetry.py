"""Runtime owns provider identity, export and lifecycle."""

from shared_observability.telemetry import ConfiguredTelemetryFactory, TelemetryService

from app.platform.settings import Settings


def build_telemetry(config: Settings, role: str) -> TelemetryService:
    return ConfiguredTelemetryFactory.build(
        {
            "telemetry_export_driver": config.telemetry_export_driver,
            "telemetry_otlp_endpoint": config.telemetry_otlp_endpoint,
            "telemetry_otlp_timeout_seconds": config.telemetry_otlp_timeout_seconds,
            "telemetry_metric_export_interval_millis": (
                config.telemetry_metric_export_interval_millis
            ),
            "telemetry_service_name": "plazia-links",
            "telemetry_service_version": "0.2.0",
            "telemetry_service_namespace": "plazia",
            "telemetry_deployment_environment_name": config.environment,
        },
        instrumentation_scope=f"links.{role}",
    )
