from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy import ForeignKey, String, Integer, Boolean, Float, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class Chat(BaseModel):
    """Main model tracking the lifecycle and final generated insights of a GEO session."""

    __tablename__ = "chats"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("products.id"), nullable=True
    )

    # Inputs captured
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_url: Mapped[str] = mapped_column(String(512), nullable=False)
    extra_context: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    model_used: Mapped[str] = mapped_column(
        String(50), nullable=False, default="gpt-5-nano"
    )

    # Outputs captured
    final_optimization_report: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # 1-to-Many Relationship to individual parsed search query records
    search_queries: Mapped[List["ChatSearchQuery"]] = relationship(
        "ChatSearchQuery", back_populates="chat", cascade="all, delete-orphan"
    )
    product = relationship("Product", back_populates="chats")


class ChatSearchQuery(BaseModel):
    """
    Normalized model isolating performance metrics, completely dynamic platform counts,
    and variance tracking against historical benchmark records.
    """

    __tablename__ = "chat_search_queries"

    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    query_text: Mapped[str] = mapped_column(String(512), nullable=False)

    # Extracted visibility metrics
    product_found: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    share_of_voice: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_websites_found: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    citation_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Completely Dynamic Platform Breakdown maps (e.g., {"reddit": 3, "amazon": 6, "youtube": 1})
    # This prevents future schema migrations when platform tracking requirements change.
    platform_breakdown: Mapped[Dict[str, int]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    # Performance tracking variance calculated against historical product benchmarks
    # Stores differential metrics (e.g., {"sov_delta": +5.2, "rank_delta": -1})
    best_metrics_variance: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    # Source Trace records
    raw_api_response: Mapped[str] = mapped_column(String, nullable=False)
    citing_sources: Mapped[List[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    competitors_mentioned: Mapped[List[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    query_optimization_tips: Mapped[str] = mapped_column(String, nullable=False)

    # Inverse relation mapping
    chat: Mapped["Chat"] = relationship("Chat", back_populates="search_queries")
