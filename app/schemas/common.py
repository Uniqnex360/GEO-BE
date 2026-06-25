from pydantic import BaseModel
from typing import Generic, TypeVar, List, Optional

T = TypeVar("T")


class PaginationMeta(BaseModel):
    page: int
    limit: int
    total: int


class ListApiResponse(BaseModel, Generic[T]):
    data: List[T]
    pagination: Optional[PaginationMeta] = None
    message: str = "success"