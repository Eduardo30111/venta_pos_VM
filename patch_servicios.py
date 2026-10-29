import asyncio, sys, re
sys.path.append(".")
from server.database import engine
from sqlalchemy import text

async def main():
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE servicios ALTER COLUMN categoria_id DROP NOT NULL;"))
        print("DB PATCHED FOR SERVICIOS")

asyncio.run(main())
