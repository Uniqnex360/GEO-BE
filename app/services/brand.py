from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.models import Brand, User


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
    async def list_brands(
        db: AsyncSession,
        user: dict,
        tenant_id: int,
        page: int = 1,
        limit: int = 24,
        search: str = None,
    ):
        """list brands"""

        query = (
            select(Brand)
            .where(Brand.tenant_id == tenant_id, Brand.is_deleted == False)
            .order_by(Brand.created_at.desc())
        )

        count_query = select(func.count(Brand.id)).where(
            Brand.tenant_id == tenant_id, Brand.is_deleted == False
        )

        if search:
            query = query.where(Brand.name.ilike(f"%{search}%"))

            count_query = count_query.where(Brand.name.ilike(f"%{search}%"))

        offset = (page - 1) * limit

        query = query.offset(offset).limit(limit)

        result = await db.execute(query)
        brands = result.scalars().all()
        total_result = await db.execute(count_query)
        total = total_result.scalar()

        return brands, total

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
