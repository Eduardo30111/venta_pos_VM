import asyncio
import sys
sys.path.append(".")
from server.database import Base
from server import models
from sqlalchemy import create_engine

engine = create_engine("sqlite:///:memory:", echo=True)
try:
    Base.metadata.create_all(engine)
    print("EXITO CREANDO TABLAS")
except Exception as e:
    print(f"ERROR: {e}")
