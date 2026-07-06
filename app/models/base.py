from datetime import datetime, UTC
from enum import Enum as PyEnum

from sqlalchemy import Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BaseModel(Base):
    """base model for entire app"""

    __abstract__ = True

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # time related fields
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # delete and active status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class LLMModels(str, PyEnum):
    """Tracking Enum for allowed GEO execution engines."""

    # OpenAI
    GPT = "gpt-5-nano"
    # Google Gemini
    GEMINI = "gemini-2.5-flash-lite"
    # Anthropic
    CLAUDE = "claude-3-5-haiku"
