import asyncio, sys
sys.path.append(".")
from server.database import engine
from sqlalchemy import text

async def main():
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE productos ALTER COLUMN categoria_id DROP NOT NULL;"))
        await conn.execute(text("ALTER TABLE productos ALTER COLUMN proveedor_id DROP NOT NULL;"))
        print("DB PATCHED")

asyncio.run(main())
