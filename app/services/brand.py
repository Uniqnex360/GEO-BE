import math
from typing import Dict, Any, List, Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, case, Float, cast, Numeric
from sqlalchemy.sql.expression import nulls_last

from fastapi import HTTPException, status

from app.models import Brand, User, Product, Chat, ChatSearchQuery


class BrandService:
    """Service class for brand related operations"""

    @staticmethod
    async def _save(db: AsyncSession):
        """commit helper"""

        try:
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def _get_brand(
        db: AsyncSession,
        brand_id: int,
    ):
        """fetch brand"""

        result = await db.execute(
            select(Brand).where(Brand.id == brand_id, Brand.is_deleted == False)
        )

        brand = result.scalar_one_or_none()

        if not brand:
            raise ValueError("Brand not found")

        return brand

    @staticmethod
    async def _brand_duplication_validation(
        db: AsyncSession,
        tenant_id: int,
        name: str,
        brand_id: int = None,
    ):
        """duplicate validation"""

        query = select(Brand).where(
            Brand.tenant_id == tenant_id,
            Brand.name == name,
            Brand.is_deleted == False,
        )

        if brand_id:
            query = query.where(Brand.id != brand_id)

        result = await db.execute(query)

        if result.scalar_one_or_none():
            raise ValueError("Brand already exists")

    @staticmethod
    async def create_brand(
        db: AsyncSession,
        data: dict,
        user: dict,
        tenant_id: int,
    ):
        """create brand"""

        name = data.get("name")

        if not tenant_id:
            raise ValueError("tenant_id is required")

        if not name:
            raise ValueError("name is required")

        await BrandService._brand_duplication_validation(
            db=db, tenant_id=tenant_id, name=name
        )

        brand_obj = Brand(
            tenant_id=tenant_id,
            name=name,
            domain=data.get("domain"),
            industry=data.get("industry"),
            country=data.get("country"),
            competitor=data.get("competitor"),
            created_by=int(user.get("sub")),
        )

        db.add(brand_obj)

        await BrandService._save(db)
        await db.refresh(brand_obj)

        return brand_obj

    @staticmethod
    async def update_brand(
        db: AsyncSession,
        brand_id: int,
        data: dict,
        user: dict,
    ):
        """update brand"""

        brand = await BrandService._get_brand(db=db, brand_id=brand_id)

        new_name = data.get("name", brand.name)

        await BrandService._brand_duplication_validation(
            db=db, tenant_id=brand.tenant_id, name=new_name, brand_id=brand.id
        )

        fields = ["name", "domain", "industry", "country"]

        for field in fields:
            value = data.get(field)

            if value is not None:
                setattr(brand, field, value)

        brand.last_updated_by = int(user.get("sub"))

        await BrandService._save(db)

        await db.refresh(brand)

        return brand

    @staticmethod
    async def soft_delete_brand(
        db: AsyncSession,
        brand_id: int,
        user: User,
    ):
        """activate / deactivate"""

        brand = await BrandService._get_brand(db=db, brand_id=brand_id)

        brand.is_active = not brand.is_active

        brand.last_updated_by = user.id

        await BrandService._save(db)

        return brand

    @staticmethod
    async def delete_brand(
        db: AsyncSession,
        brand_id: int,
        user: dict,
    ):
        """logical delete"""

        brand = await BrandService._get_brand(db=db, brand_id=brand_id)

        brand.is_deleted = True
        brand.deleted_by = int(user.get("sub"))

        await BrandService._save(db)

        return True

    @staticmethod
    async def meta_list(
        db: AsyncSession,
        user: dict,
        tenant_id: int,
    ):
        """Return brands metadata for dropdowns"""

        query = select(Brand.id, Brand.name).order_by(Brand.name.asc())

        query = query.where(
            Brand.tenant_id == tenant_id,
            Brand.is_deleted == False,
        )

        result = await db.execute(query)

        brands = result.all()

        return [{"id": brand.id, "value": brand.name} for brand in brands]

    @staticmethod
    async def list_brands(
        db: AsyncSession,
        user: dict,
        tenant_id: int,
        page: int = 1,
        limit: int = 24,
        search: Optional[str] = None,
        sort_by: Optional[str] = "created_at",
        sort_order: Optional[str] = "desc",
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:

        # 1. Permission check
        is_super_admin = user.get("is_super_admin", False)
        if not is_super_admin and user.get("tenant_id") != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You do not have permissions for this tenant's data.",
            )

        # 2. Aggregation Calculations
        found_numeric = case((ChatSearchQuery.product_found.is_(True), 1.0), else_=0.0)

        mention_rate_expr = func.round(
            cast(func.coalesce(func.avg(found_numeric) * 100.0, 0.0), Numeric), 1
        )

        visibility_expr = func.round(
            cast(
                func.coalesce(
                    func.avg(cast(ChatSearchQuery.share_of_voice, Numeric)), 0.0
                ),
                Numeric,
            ),
            1,
        )

        products_count_expr = func.count(func.distinct(Product.id))

        # 3. Create Aggregation Subquery
        agg_subquery = (
            select(
                Brand.id.label("brand_id"),
                visibility_expr.label("visibility_score"),
                mention_rate_expr.label("mention_rate"),
                products_count_expr.label("products_count"),
            )
            .outerjoin(
                Product,
                (Product.brand_id == Brand.id) & (Product.is_deleted.is_(False)),
            )
            .outerjoin(Chat, Chat.product_id == Product.id)
            .outerjoin(ChatSearchQuery, ChatSearchQuery.chat_id == Chat.id)
            .where(Brand.tenant_id == tenant_id, Brand.is_deleted.is_(False))
            .group_by(Brand.id)
        ).subquery("agg")

        # 4. Outer Query joining Brand with calculated metrics
        stmt = select(
            Brand,
            agg_subquery.c.visibility_score,
            agg_subquery.c.mention_rate,
            agg_subquery.c.products_count,
        ).join(agg_subquery, Brand.id == agg_subquery.c.brand_id)

        # 5. Search Filter
        if search and search.strip():
            clean_search = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    Brand.name.ilike(clean_search),
                    Brand.industry.ilike(clean_search),
                )
            )

        # 6. Clean Outer Sorting
        is_desc = (sort_order or "").lower() == "desc"

        print("sorty by", sort_by)

        if sort_by == "name":
            sort_col = func.lower(Brand.name)
        elif sort_by == "country":
            # Safe extraction for array/json country
            sort_col = func.lower(func.coalesce(Brand.countries[0], ""))
        elif sort_by == "industry":
            sort_col = func.lower(func.coalesce(Brand.industry, ""))
        elif sort_by in ["visibility", "visibility_score"]:
            sort_col = agg_subquery.c.visibility_score
        elif sort_by in ["mention_rate", "mentionRate"]:
            sort_col = agg_subquery.c.mention_rate
        elif sort_by in ["products_count", "productsCount"]:
            sort_col = agg_subquery.c.products_count
        else:
            sort_col = Brand.created_at

        # Apply order with nulls_last
        if is_desc:
            stmt = stmt.order_by(sort_col.desc().nulls_last())
        else:
            stmt = stmt.order_by(sort_col.asc().nulls_last())

        # 7. Total Count Query
        count_query = select(func.count(func.distinct(Brand.id))).where(
            Brand.tenant_id == tenant_id, Brand.is_deleted.is_(False)
        )
        if search and search.strip():
            clean_search = f"%{search.strip()}%"
            count_query = count_query.where(
                or_(
                    Brand.name.ilike(clean_search),
                    Brand.industry.ilike(clean_search),
                )
            )

        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        # 8. Pagination & Execution
        offset = (page - 1) * limit
        stmt = stmt.offset(offset).limit(limit)

        result = await db.execute(stmt)
        rows = result.all()

        # 9. Format Output
        brand_list = []
        for brand, visibility_score, mention_rate, products_count in rows:
            # Resolve country string or list cleanly
            country_val = "-"
            if hasattr(brand, "countries") and brand.countries:
                if isinstance(brand.countries, list):
                    country_val = ", ".join(brand.countries)
                else:
                    country_val = str(brand.countries)

            brand_dict = {
                "id": brand.id,
                "name": brand.name,
                "website_url": getattr(brand, "website_url", None),
                "industry": getattr(brand, "industry", None),
                "country": country_val,
                "countries": getattr(brand, "countries", []),
                "description": getattr(brand, "description", None),
                "created_at": brand.created_at,
                "updated_at": getattr(brand, "updated_at", None),
                "productsCount": products_count or 0,
                "visibilityScore": float(visibility_score or 0.0),
                "mentionRate": float(mention_rate or 0.0),
            }
            brand_list.append(brand_dict)

        pagination = {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": math.ceil(total / limit) if limit > 0 else 1,
        }

        return brand_list, pagination
