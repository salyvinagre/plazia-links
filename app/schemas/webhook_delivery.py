from datetime import datetime

from pydantic import BaseModel, JsonValue


class WebhookDeliveryResponse(BaseModel):
    id: str
    webhook_id: str
    event: str
    payload: dict[str, JsonValue]
    status: str
    response_code: int | None = None
    response_body: str | None = None
    attempt: int
    next_retry_at: datetime | None = None
    created_at: datetime
    delivered_at: datetime | None = None

    model_config = {"from_attributes": True}


class WebhookDeliveryListResponse(BaseModel):
    deliveries: list[WebhookDeliveryResponse]
    total: int
    page: int
    page_size: int
    has_next: bool
