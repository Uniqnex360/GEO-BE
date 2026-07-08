from io import BytesIO
from pydantic import BaseModel
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query


from app.core.database import get_db
from app.core.security import validate_jwt_token
from app.core.permission import require_super_admin
from app.models import MetaTable


class CategoryListRequest(BaseModel):
    search: str = ""
    offset: int = 0
    limit: int = 50


router = APIRouter()

BATCH_SIZE = 500


@router.post("/bulk-upload/")
async def bulk_upload_meta_data(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_super_admin),
):
    try:
        contents = await file.read()
        workbook = load_workbook(BytesIO(contents), data_only=True)
        sheet = workbook.active

        rows = list(sheet.iter_rows(min_row=2, values_only=True))  # Skip header

        if not rows:
            raise HTTPException(status_code=400, detail="Excel file is empty")

        objects = []

        for row in rows:
            if not any(row):
                continue

            objects.append(
                MetaTable(
                    industry_name=row[0],
                    taxonomy=row[1],
                    category_name=row[2],
                )
            )

        inserted = 0
        skipped = 0

        for i in range(0, len(objects), BATCH_SIZE):
            batch = objects[i : i + BATCH_SIZE]

            try:
                db.add_all(batch)
                await db.commit()
                inserted += len(batch)

            except IntegrityError:
                await db.rollback()

                # Insert one-by-one so duplicate rows are skipped
                for obj in batch:
                    try:
                        db.add(obj)
                        await db.commit()
                        inserted += 1
                    except IntegrityError:
                        await db.rollback()
                        skipped += 1

        return {
            "message": "Bulk upload completed.",
            "inserted": inserted,
            "skipped_duplicates": skipped,
            "total_rows": len(objects),
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/category/list")
async def get_category_meta_list(
    search: str = Query(None, description="Search category"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    stmt = select(MetaTable.category_name).distinct()

    if search:
        stmt = stmt.where(MetaTable.category_name.ilike(f"%{search}%"))

    stmt = stmt.order_by(MetaTable.category_name).offset(offset).limit(limit + 1)

    result = await db.execute(stmt)
    categories = result.scalars().all()

    has_more = len(categories) > limit

    if has_more:
        categories.pop()

    return {
        "items": [
            {
                "id": category,
                "identity": category,
            }
            for category in categories
        ],
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
    }


@router.get("/industry/list")
async def get_industry_meta_list(
    search: str = Query(None, description="Search category"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    stmt = select(MetaTable.industry_name).distinct()

    if search:
        stmt = stmt.where(MetaTable.industry_name.ilike(f"%{search}%"))

    stmt = stmt.order_by(MetaTable.industry_name).offset(offset).limit(limit + 1)

    result = await db.execute(stmt)
    industries = result.scalars().all()

    has_more = len(industries) > limit

    if has_more:
        industries.pop()

    return {
        "items": [
            {
                "id": industry,
                "identity": industry,
            }
            for industry in industries
        ],
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
    }
