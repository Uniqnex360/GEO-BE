import asyncio
from sqlalchemy import text
from app.core.database import engine


async def test():
    print("Starting connection test...")
    

    try:
        async with engine.connect() as conn:
            print("Connected!")

            result = await conn.execute(text("SELECT 1"))

            print("Query result:", result.scalar())

    except Exception as e:
        print("ERROR:", e)


asyncio.run(test())
