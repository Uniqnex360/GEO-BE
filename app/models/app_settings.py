from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class AppSettings(BaseModel):
    """Table for application settings"""

    __tablename__ = "appsettings"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)

    # LLM Provider API Keys
    openai_api_key: Mapped[str] = mapped_column(Text, nullable=True)
    anthropic_api_key: Mapped[str] = mapped_column(Text, nullable=True)
    google_api_key: Mapped[str] = mapped_column(Text, nullable=True)  # Gemini
    groq_api_key: Mapped[str] = mapped_column(Text, nullable=True)
    deepseek_api_key: Mapped[str] = mapped_column(Text, nullable=True)
    perplexity_api_key: Mapped[str] = mapped_column(Text, nullable=True)
    xai_api_key: Mapped[str] = mapped_column(Text, nullable=True)  # Grok

    # Optional relationship
    tenant = relationship("Tenant", back_populates="app_settings")
