from pydantic import BaseModel


class PaginatedResponse[T](BaseModel):
    total: int
    page: int
    page_size: int
    has_next: bool
    items: list[T]
