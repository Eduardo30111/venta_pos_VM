import asyncio
import sys
sys.path.append(".")
from server.database import Base, engine
from server import models

async def main():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("EXITO POSTGRES")
    except Exception as e:
        print(f"ERROR POSTGRES: {e}")

asyncio.run(main())
