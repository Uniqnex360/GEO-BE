"""chat v2

Revision ID: 8cb67ffc77de
Revises: 0266f9f7743a
Create Date: 2026-07-06 11:57:32.582423
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "8cb67ffc77de"
down_revision: Union[str, Sequence[str], None] = "0266f9f7743a"
branch_labels = None
depends_on = None


def upgrade():

    # ---------------------------
    # Create enum FIRST
    # ---------------------------

    llm_enum = postgresql.ENUM("GPT", "GEMINI", "CLAUDE", name="llmmodels")

    llm_enum.create(op.get_bind(), checkfirst=True)

    # ---------------------------
    # GEO AUDITS
    # ---------------------------

    op.create_table(
        "geo_audits",
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("product_identifier", sa.String(255), nullable=True),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column(
            "audit_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
    )

    op.create_index(
        "ix_geo_audits_product_identifier", "geo_audits", ["product_identifier"]
    )

    op.create_index("ix_geo_audits_tenant_id", "geo_audits", ["tenant_id"])

    # ---------------------------
    # CHAT SEARCH QUERY
    # ---------------------------

    op.add_column(
        "chat_search_queries", sa.Column("chat_context", sa.String(255), nullable=True)
    )

    op.add_column(
        "chat_search_queries", sa.Column("brand_name", sa.String(255), nullable=True)
    )

    op.alter_column(
        "chat_search_queries",
        "raw_api_response",
        existing_type=sa.VARCHAR(),
        nullable=True,
    )

    # ---------------------------
    # CHATS
    # ---------------------------

    op.add_column(
        "chats",
        sa.Column("model_choice", llm_enum, nullable=False, server_default="GPT"),
    )

    op.add_column(
        "chats",
        sa.Column(
            "competitor_analytics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    op.drop_column("chats", "model_used")

    # remove default after old rows are populated
    op.alter_column("chats", "model_choice", server_default=None)

    # ---------------------------
    # PRODUCTS
    # ---------------------------

    op.add_column(
        "products",
        sa.Column("model_choice", llm_enum, nullable=False, server_default="GPT"),
    )

    op.add_column(
        "products", sa.Column("description_analysis", postgresql.JSONB, nullable=True)
    )

    op.add_column(
        "products", sa.Column("features_analysis", postgresql.JSONB, nullable=True)
    )

    op.add_column(
        "products", sa.Column("attributes_analysis", postgresql.JSONB, nullable=True)
    )

    op.add_column("products", sa.Column("assets", postgresql.JSONB, nullable=True))

    op.add_column(
        "products", sa.Column("faqs_analysis", postgresql.JSONB, nullable=True)
    )

    op.add_column(
        "products", sa.Column("reviews_analysis", postgresql.JSONB, nullable=True)
    )

    op.alter_column("products", "model_choice", server_default=None)


def downgrade():

    op.drop_column("products", "reviews_analysis")
    op.drop_column("products", "faqs_analysis")
    op.drop_column("products", "assets")
    op.drop_column("products", "attributes_analysis")
    op.drop_column("products", "features_analysis")
    op.drop_column("products", "description_analysis")
    op.drop_column("products", "model_choice")

    op.add_column("chats", sa.Column("model_used", sa.String(50), nullable=False))

    op.drop_column("chats", "competitor_analytics")
    op.drop_column("chats", "model_choice")

    op.drop_column("chat_search_queries", "brand_name")
    op.drop_column("chat_search_queries", "chat_context")

    op.drop_index("ix_geo_audits_tenant_id")

    op.drop_index("ix_geo_audits_product_identifier")

    op.drop_table("geo_audits")

    llm_enum = postgresql.ENUM("GPT", "GEMINI", "CLAUDE", name="llmmodels")

    llm_enum.drop(op.get_bind(), checkfirst=True)
