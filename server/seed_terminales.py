import asyncio
from database import engine, Base
from models.terminal import Terminal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

async def create_terminals():
    async with AsyncSession(engine) as session:
        # Check if terminals exist
        result = await session.execute(select(Terminal).where(Terminal.nombre == 'CAJA-01'))
        t1 = result.scalars().first()
        if not t1:
            session.add(Terminal(nombre='CAJA-01', descripcion='Caja Principal (Servidor)'))
            
        result2 = await session.execute(select(Terminal).where(Terminal.nombre == 'CAJA-02'))
        t2 = result2.scalars().first()
        if not t2:
            session.add(Terminal(nombre='CAJA-02', descripcion='Caja Secundaria'))
            
        await session.commit()

if __name__ == "__main__":
    asyncio.run(create_terminals())
