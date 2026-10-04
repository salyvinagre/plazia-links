"""Links-owned bounded signals on the shared passive telemetry boundary."""

from shared_observability import MessagingSpanDefinition, MetricDefinition
from shared_observability.telemetry import TelemetryMetricKind

ENQUEUE = MessagingSpanDefinition("postgresql", "create", "create", "activation_emails")
PROCESS = MessagingSpanDefinition("postgresql", "process", "process", "activation_emails")
ENQUEUE_DURATION = MetricDefinition(
    "links.activation.enqueue.duration", TelemetryMetricKind.histogram, "s"
)
PROCESS_DURATION = MetricDefinition(
    "links.activation.process.duration", TelemetryMetricKind.histogram, "s"
)
SMTP_DURATION = MetricDefinition(
    "links.activation.provider.duration", TelemetryMetricKind.histogram, "s"
)
OUTCOME = MetricDefinition("links.activation.outcome", TelemetryMetricKind.counter)
PENDING = MetricDefinition("links.activation.pending", TelemetryMetricKind.gauge)
DEAD = MetricDefinition("links.activation.dead", TelemetryMetricKind.gauge)
OLDEST = MetricDefinition("links.activation.oldest_eligible", TelemetryMetricKind.gauge, "s")
LEASES = MetricDefinition("links.activation.leases", TelemetryMetricKind.gauge)
VISIT_FAILURE = MetricDefinition("links.visits.recording_failure", TelemetryMetricKind.counter)
