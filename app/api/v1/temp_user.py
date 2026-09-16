from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_db
from app.models import (
    TempUesr,
    Tenant,
    Product,
    Chat,
    ChatGEOAuditRecord,
    ChatSearchQuery,
)
from app.services.chat_v2 import run_geo_audit_stream
from app.services.chat_v2.schemas import GEOAuditRequest
from app.services import build_geo_email, send_geo_email
from app.helpers.email import send_email


class TempUserCreate(BaseModel):
    name: str
    company_name: str
    phone_number: str | None = None
    email: EmailStr
    product_url: str


router = APIRouter()


@router.post("/")
async def create_temp_user(
    data: TempUserCreate,
    db: AsyncSession = Depends(get_db),
):

    # Check if temp user already exists
    result = await db.execute(select(TempUesr).where(TempUesr.email == data.email))
    temp_user = result.scalar_one_or_none()

    if temp_user:
        # Get tenant
        tenant_result = await db.execute(
            select(Tenant).where(Tenant.name == temp_user.company_name)
        )

        tenant = tenant_result.scalar_one_or_none()

        if not tenant:
            raise HTTPException(
                status_code=404,
                detail="Tenant not found for this user.",
            )

    else:
        # Get existing tenant
        result = await db.execute(
            select(Tenant).where(Tenant.name == data.company_name)
        )

        tenant = result.scalar_one_or_none()

        # Create tenant
        if not tenant:
            tenant = Tenant(
                name=data.company_name,
                website_url=data.product_url,
            )

            db.add(tenant)
            await db.flush()

        # Create temp user
        temp_user = TempUesr(
            name=data.name,
            company_name=data.company_name,
            phone_number=data.phone_number,
            email=data.email,
            product_url=data.product_url,
        )

        db.add(temp_user)

        await db.commit()
        await db.refresh(temp_user)

        # send welcome email
        _ = await send_email(
            # to="growth@contentlynxe.com",
            # to="delson@uniqnex360.com",
            to="techteam@uniqnex360.com",
            subject="New user Onboarded",
            html=f"""
            <h1>User {data.name}</h1>
            <p>Company: {data.company_name}</p>
            <p>Email: {data.email}</p>
            <p>Product URL: {data.product_url}</p>
            """,
        )

        # send user a welcom email
        _ = await send_email(
            # to=data.email,
            to="techteam@uniqnex360.com",
            subject="New user Onboarded",
            html=f"""
                    <h1>Welcome {data.name}</h1>
                    <p>You will get a your report in shorly!</p>
                    """,
        )

    # Store the ID before running anything that may commit
    tenant_id = tenant.id

    # ---------------------------------------------------------
    # Run GEO audit
    # ---------------------------------------------------------

    payload = GEOAuditRequest(
        # product_url=data.product_url,
        product_name=data.company_name,
        website=data.product_url,
    )

    async for event in run_geo_audit_stream(
        payload=payload,
        db=db,
        tenant_id=tenant_id,
        user_id=None,
    ):
        print(event)

    # ---------------------------------------------------------
    # Get created product
    # ---------------------------------------------------------

    result = await db.execute(
        select(Product)
        .where(Product.tenant_id == tenant_id)
        .order_by(Product.id.desc())
    )

    product = result.scalars().first()

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product was not created.",
        )

    # Convert SQLAlchemy object to JSON
    # ---------------------------------------------------------
    # Get product + all related chat/search data
    # ---------------------------------------------------------

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.chats).selectinload(Chat.search_queries),
        )
        .where(Product.tenant_id == tenant_id)
        .order_by(Product.id.desc())
    )

    product = result.scalars().first()

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product was not created.",
        )

    # Product data
    product_data = {
        column.name: getattr(product, column.name)
        for column in Product.__table__.columns
    }

    # Chat data
    product_data["chats"] = []

    for chat in product.chats:
        chat_data = {
            column.name: getattr(chat, column.name) for column in Chat.__table__.columns
        }

        # Search query data
        chat_data["search_queries"] = [
            {
                column.name: getattr(search_query, column.name)
                for column in ChatSearchQuery.__table__.columns
            }
            for search_query in chat.search_queries
        ]

        product_data["chats"].append(chat_data)

    # GEO audit records
    result = await db.execute(
        select(ChatGEOAuditRecord)
        .where(ChatGEOAuditRecord.tenant_id == tenant_id)
        .order_by(ChatGEOAuditRecord.id.desc())
    )

    geo_audits = result.scalars().all()

    product_data["geo_audits"] = [
        {
            column.name: getattr(audit, column.name)
            for column in ChatGEOAuditRecord.__table__.columns
        }
        for audit in geo_audits
    ]

    html = build_geo_email({"product": product_data})

    await send_email(
        # to=data.email,
        to="techteam@uniqnex360.com",
        subject=f"Report for the product {data.product_url}",
        html=html,
    )

    return {
        "tenant_id": tenant_id,
        "product": product_data,
    }
