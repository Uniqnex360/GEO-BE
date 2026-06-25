from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.core.security import hash_password


class UserService:
    """service class to create user"""

    @staticmethod
    async def create_user(db: AsyncSession, data):
        # check duplicate
        result = await db.execute(select(User).where(User.email == data.email))
        if result.scalar_one_or_none():
            raise ValueError("Email already exists")

        user = User(
            tenant_id=data.tenant_id,
            email=data.email,
            hashed_password=hash_password(data.password),
            timezone=data.timezone,
            is_super_admin=data.is_super_admin,
            role=data.role,
        )

        db.add(user)
        await db.commit()
        await db.refresh(user)

        return user

    @staticmethod
    async def list_users(
        db: AsyncSession,
        is_super_admin: bool = False,
        tenant_id: int | None = None,
        page: int = 1,
        limit: int = 24,
    ):
        if is_super_admin:
            print(" i am working")
            query = select(User).options(selectinload(User.tenant))
            count_query = select(func.count(User.id))
        else:
            print('Iam working')
            query = (
                select(User)
                .where(User.tenant_id == tenant_id)
                .options(selectinload(User.tenant))
            )
            count_query = select(func.count(User.id)).where(User.tenant_id == tenant_id)

        # -------------------
        # pagination
        # -------------------
        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit)

        # -------------------
        # execute
        # -------------------
        result = await db.execute(query)
        users = result.scalars().all()

        total_result = await db.execute(count_query)
        total = total_result.scalar()

        return users, total
