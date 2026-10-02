from contextlib import AbstractAsyncContextManager
from typing import Protocol

from shared_notifications.capture import SentEmailNotification

from app.contexts.links.application.dto.notification import EmailJobDto


class EmailTransport(Protocol):
    async def send(self, notification: SentEmailNotification) -> None: ...


class DeliveryLease(Protocol):
    job: EmailJobDto | None

    async def complete(self) -> None: ...
    async def fail(self) -> None: ...


class DeliveryQueue(Protocol):
    def claim(self) -> AbstractAsyncContextManager[DeliveryLease]: ...
