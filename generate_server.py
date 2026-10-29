import os

base_dir = "/Users/eduardosanchez/venta_pos_VM-main"
server_dir = os.path.join(base_dir, "server")

dirs = [
    "models", "schemas", "routers", "services", "middleware", "migrations"
]

for d in dirs:
    os.makedirs(os.path.join(server_dir, d), exist_ok=True)

files = {}

files["server/requirements.txt"] = """fastapi
uvicorn[standard]
sqlalchemy[asyncio]
asyncpg
alembic
python-jose[cryptography]
passlib[bcrypt]
pydantic
pydantic-settings
python-multipart
httpx
"""

files["server/config.py"] = """from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/vmpos"
    SECRET_KEY: str = "supersecretkey"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    APP_NAME: str = "VmPOS"
    APP_VERSION: str = "4.0.0"

    class Config:
        env_file = ".env"

settings = Settings()
"""

files["server/database.py"] = """from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=True)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def get_db():
    async with SessionLocal() as session:
        yield session
"""

files["server/models/__init__.py"] = """from .usuario import Usuario
from .permiso import PermisoUsuario
from .terminal import Terminal
from .sesion import Sesion
from .categoria import Categoria
from .producto import Producto
from .servicio import Servicio
from .proveedor import Proveedor
from .cliente import Cliente
from .venta import Venta, DetalleVenta, Pago
from .inventario import MovimientoInventario
from .nomina import Comision, Liquidacion, Asistencia
from .finanzas import CuentaPorCobrar, Abono, CuentaPorPagar, Gasto
from .auditoria import AuditLog
"""

files["server/models/usuario.py"] = """from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float
from sqlalchemy.sql import func
from ..database import Base

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    apellidos = Column(String, nullable=False)
    documento = Column(String, unique=True, index=True, nullable=False)
    usuario = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    rol = Column(String, nullable=False) # Administrador/Vendedor/Operario
    tipo_remuneracion = Column(String, nullable=False) # Fija/Porcentual
    salario_diario = Column(Float, default=0.0)
    porcentaje_comision = Column(Float, default=0.0)
    estado = Column(String, default='Activo') # Activo/Inactivo
    fecha_registro = Column(DateTime(timezone=True), server_default=func.now())
    ultimo_acceso = Column(DateTime(timezone=True), nullable=True)
"""

files["server/models/permiso.py"] = """from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, UniqueConstraint
from ..database import Base

class PermisoUsuario(Base):
    __tablename__ = "permisos_usuarios"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    permiso = Column(String, nullable=False)
    concedido = Column(Boolean, default=False)
    __table_args__ = (UniqueConstraint('usuario_id', 'permiso', name='_usuario_permiso_uc'),)
"""

files["server/models/terminal.py"] = """from sqlalchemy import Column, Integer, String
from ..database import Base

class Terminal(Base):
    __tablename__ = "terminales"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, unique=True, nullable=False)
    descripcion = Column(String, nullable=True)
    estado = Column(String, default="Activo")
"""

files["server/models/sesion.py"] = """from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from ..database import Base

class Sesion(Base):
    __tablename__ = "sesiones"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    terminal_id = Column(Integer, ForeignKey("terminales.id"), nullable=False)
    token = Column(String, unique=True, index=True, nullable=False)
    inicio = Column(DateTime(timezone=True), nullable=False)
    expira = Column(DateTime(timezone=True), nullable=False)
    activa = Column(Boolean, default=True)
"""

files["server/models/categoria.py"] = """from sqlalchemy import Column, Integer, String
from ..database import Base

class Categoria(Base):
    __tablename__ = "categorias"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    tipo = Column(String, nullable=False) # Producto/Servicio/Ambos
    estado = Column(String, default="Activo")
"""

files["server/models/producto.py"] = """from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base

class Producto(Base):
    __tablename__ = "productos"
    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String, unique=True, index=True, nullable=False) # 00001
    nombre = Column(String, nullable=False)
    descripcion = Column(String, nullable=True)
    categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=False)
    precio_costo = Column(Float, nullable=False)
    precio_venta = Column(Float, nullable=False)
    stock = Column(Float, default=0)
    stock_minimo = Column(Float, default=0)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=False)
    codigo_barras = Column(String, nullable=True)
    imagen_url = Column(String, nullable=True)
    estado = Column(String, default="Activo")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
"""

files["server/models/servicio.py"] = """from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base

class Servicio(Base):
    __tablename__ = "servicios"
    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String, unique=True, index=True, nullable=False) # S00001
    nombre = Column(String, nullable=False)
    descripcion = Column(String, nullable=True)
    categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=False)
    precio_venta = Column(Float, nullable=False)
    tipo_servicio = Column(String, nullable=False) # Interno/Proveedor
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=True)
    costo_proveedor = Column(Float, default=0.0)
    genera_comision = Column(Boolean, default=False)
    estado = Column(String, default="Activo")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
"""

files["server/models/proveedor.py"] = """from sqlalchemy import Column, Integer, String
from ..database import Base

class Proveedor(Base):
    __tablename__ = "proveedores"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    documento_nit = Column(String, nullable=False)
    telefono = Column(String, nullable=True)
    email = Column(String, nullable=True)
    direccion = Column(String, nullable=True)
    contacto = Column(String, nullable=True)
    estado = Column(String, default="Activo")
"""

files["server/models/cliente.py"] = """from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.sql import func
from ..database import Base

class Cliente(Base):
    __tablename__ = "clientes"
    id = Column(Integer, primary_key=True, index=True)
    documento = Column(String, unique=True, index=True, nullable=False)
    nombre = Column(String, nullable=False)
    email = Column(String, nullable=True)
    telefono = Column(String, nullable=True)
    direccion = Column(String, nullable=True)
    permite_fiado = Column(Boolean, default=False)
    limite_credito = Column(Float, default=0.0)
    estado = Column(String, default="Activo")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
"""

files["server/models/venta.py"] = """from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base

class Venta(Base):
    __tablename__ = "ventas"
    id = Column(Integer, primary_key=True, index=True)
    numero = Column(String, unique=True, index=True, nullable=False) # V-000001
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    terminal_id = Column(Integer, ForeignKey("terminales.id"), nullable=False)
    subtotal = Column(Float, nullable=False)
    descuento = Column(Float, default=0.0)
    total = Column(Float, nullable=False)
    estado = Column(String, default="Completada")
    observaciones = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class DetalleVenta(Base):
    __tablename__ = "detalles_venta"
    id = Column(Integer, primary_key=True, index=True)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=False)
    tipo_item = Column(String, nullable=False) # Producto/Servicio
    item_id = Column(Integer, nullable=False)
    item_codigo = Column(String, nullable=False)
    item_nombre = Column(String, nullable=False)
    precio_original = Column(Float, nullable=False)
    precio_vendido = Column(Float, nullable=False)
    cantidad = Column(Float, nullable=False)
    descuento = Column(Float, default=0.0)
    subtotal = Column(Float, nullable=False)
    costo_unitario = Column(Float, nullable=False)

class Pago(Base):
    __tablename__ = "pagos"
    id = Column(Integer, primary_key=True, index=True)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=False)
    metodo = Column(String, nullable=False) # Efectivo/Transferencia/Fiado
    monto = Column(Float, nullable=False)
    referencia = Column(String, nullable=True)
    recibido = Column(Float, nullable=False)
    cambio = Column(Float, nullable=False)
"""

files["server/models/inventario.py"] = """from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base

class MovimientoInventario(Base):
    __tablename__ = "movimientos_inventario"
    id = Column(Integer, primary_key=True, index=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    tipo = Column(String, nullable=False) # ENTRADA/VENTA/DEVOLUCION/AJUSTE/ANULACION/TRASLADO/MERMA
    cantidad = Column(Float, nullable=False)
    stock_anterior = Column(Float, nullable=False)
    stock_nuevo = Column(Float, nullable=False)
    referencia = Column(String, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    terminal_id = Column(Integer, ForeignKey("terminales.id"), nullable=False)
    observacion = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
"""

files["server/models/nomina.py"] = """from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from ..database import Base

class Comision(Base):
    __tablename__ = "comisiones"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=False)
    detalle_venta_id = Column(Integer, ForeignKey("detalles_venta.id"), nullable=False)
    servicio_id = Column(Integer, ForeignKey("servicios.id"), nullable=False)
    valor_servicio = Column(Float, nullable=False)
    costo_servicio = Column(Float, default=0.0)
    utilidad = Column(Float, nullable=False)
    porcentaje = Column(Float, nullable=False)
    monto_comision = Column(Float, nullable=False)
    estado = Column(String, default="Pendiente") # Pendiente/Liquidada/Anulada
    liquidacion_id = Column(Integer, ForeignKey("liquidaciones.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Liquidacion(Base):
    __tablename__ = "liquidaciones"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    periodo_inicio = Column(DateTime(timezone=True), nullable=False)
    periodo_fin = Column(DateTime(timezone=True), nullable=False)
    total_servicios_vendidos = Column(Float, nullable=False)
    total_comisiones = Column(Float, nullable=False)
    total_salario_fijo = Column(Float, nullable=False)
    total_liquidado = Column(Float, nullable=False)
    estado = Column(String, default="Pendiente") # Pendiente/Liquidado/Anulado
    liquidado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    observaciones = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Asistencia(Base):
    __tablename__ = "asistencias"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha = Column(DateTime, nullable=False)
    estado = Column(String, nullable=False) # Presente/Ausente/Permiso
    registrado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    salario_generado = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint('usuario_id', 'fecha', name='_usuario_fecha_uc'),)
"""

files["server/models/finanzas.py"] = """from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base

class CuentaPorCobrar(Base):
    __tablename__ = "cuentas_por_cobrar"
    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=False)
    monto_original = Column(Float, nullable=False)
    saldo_pendiente = Column(Float, nullable=False)
    estado = Column(String, default="Pendiente")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Abono(Base):
    __tablename__ = "abonos"
    id = Column(Integer, primary_key=True, index=True)
    cuenta_id = Column(Integer, ForeignKey("cuentas_por_cobrar.id"), nullable=False)
    monto = Column(Float, nullable=False)
    metodo = Column(String, nullable=False)
    recibido_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    observacion = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class CuentaPorPagar(Base):
    __tablename__ = "cuentas_por_pagar"
    id = Column(Integer, primary_key=True, index=True)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=False)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=True)
    concepto = Column(String, nullable=False)
    monto = Column(Float, nullable=False)
    estado = Column(String, default="Pendiente") # Pendiente/Pagada
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Gasto(Base):
    __tablename__ = "gastos"
    id = Column(Integer, primary_key=True, index=True)
    concepto = Column(String, nullable=False)
    categoria = Column(String, nullable=False)
    valor = Column(Float, nullable=False)
    tipo = Column(String, nullable=False) # Manual/Liquidacion_Nomina/Pago_Proveedor
    referencia_id = Column(Integer, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    observacion = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
"""

files["server/models/auditoria.py"] = """from sqlalchemy import Column, BigInteger, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from ..database import Base

class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(BigInteger, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    usuario_nombre = Column(String, nullable=False)
    terminal_id = Column(Integer, ForeignKey("terminales.id"), nullable=True)
    terminal_nombre = Column(String, nullable=True)
    accion = Column(String, nullable=False)
    modulo = Column(String, nullable=False)
    tabla_afectada = Column(String, nullable=False)
    registro_id = Column(String, nullable=False)
    valor_anterior = Column(JSON, nullable=True)
    valor_nuevo = Column(JSON, nullable=True)
    descripcion = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
"""

files["server/schemas/common.py"] = """from pydantic import BaseModel
from typing import Generic, TypeVar, List, Optional

T = TypeVar('T')

class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    size: int
    pages: int

class MessageResponse(BaseModel):
    message: str
"""

files["server/schemas/usuario.py"] = """from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    nombre: str
    apellidos: str
    documento: str
    usuario: str
    rol: str
    tipo_remuneracion: str
    salario_diario: Optional[float] = 0.0
    porcentaje_comision: Optional[float] = 0.0
    estado: Optional[str] = 'Activo'

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    nombre: Optional[str] = None
    apellidos: Optional[str] = None
    documento: Optional[str] = None
    usuario: Optional[str] = None
    password: Optional[str] = None
    rol: Optional[str] = None
    tipo_remuneracion: Optional[str] = None
    salario_diario: Optional[float] = None
    porcentaje_comision: Optional[float] = None
    estado: Optional[str] = None

class UserResponse(UserBase):
    id: int
    fecha_registro: datetime
    ultimo_acceso: Optional[datetime] = None

    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    usuario: str
    password: str
    terminal_id: int

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
"""

files["server/schemas/producto.py"] = """from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ProductoBase(BaseModel):
    codigo: str
    nombre: str
    descripcion: Optional[str] = None
    categoria_id: int
    precio_costo: float
    precio_venta: float
    stock: Optional[float] = 0.0
    stock_minimo: Optional[float] = 0.0
    proveedor_id: int
    codigo_barras: Optional[str] = None
    imagen_url: Optional[str] = None
    estado: Optional[str] = "Activo"

class ProductoCreate(ProductoBase):
    pass

class ProductoUpdate(ProductoBase):
    codigo: Optional[str] = None
    nombre: Optional[str] = None
    categoria_id: Optional[int] = None
    precio_costo: Optional[float] = None
    precio_venta: Optional[float] = None
    proveedor_id: Optional[int] = None

class ProductoResponse(ProductoBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
"""

files["server/schemas/servicio.py"] = """from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ServicioBase(BaseModel):
    codigo: str
    nombre: str
    descripcion: Optional[str] = None
    categoria_id: int
    precio_venta: float
    tipo_servicio: str
    proveedor_id: Optional[int] = None
    costo_proveedor: Optional[float] = 0.0
    genera_comision: Optional[bool] = False
    estado: Optional[str] = "Activo"

class ServicioCreate(ServicioBase):
    pass

class ServicioUpdate(ServicioBase):
    codigo: Optional[str] = None
    nombre: Optional[str] = None
    categoria_id: Optional[int] = None
    precio_venta: Optional[float] = None
    tipo_servicio: Optional[str] = None

class ServicioResponse(ServicioBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
"""

files["server/schemas/venta.py"] = """from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class DetalleVentaCreate(BaseModel):
    tipo_item: str
    item_id: int
    item_codigo: str
    item_nombre: str
    precio_original: float
    precio_vendido: float
    cantidad: float
    descuento: Optional[float] = 0.0
    subtotal: float
    costo_unitario: float

class PagoCreate(BaseModel):
    metodo: str
    monto: float
    referencia: Optional[str] = None
    recibido: float
    cambio: float

class VentaCreate(BaseModel):
    cliente_id: Optional[int] = None
    terminal_id: int
    subtotal: float
    descuento: Optional[float] = 0.0
    total: float
    observaciones: Optional[str] = None
    detalles: List[DetalleVentaCreate]
    pagos: List[PagoCreate]

class DetalleVentaResponse(BaseModel):
    id: int
    tipo_item: str
    item_id: int
    item_codigo: str
    item_nombre: str
    precio_original: float
    precio_vendido: float
    cantidad: float
    descuento: float
    subtotal: float

    class Config:
        from_attributes = True

class VentaResponse(BaseModel):
    id: int
    numero: str
    cliente_id: Optional[int] = None
    usuario_id: int
    terminal_id: int
    subtotal: float
    descuento: float
    total: float
    estado: str
    observaciones: Optional[str] = None
    created_at: datetime
    detalles: List[DetalleVentaResponse] = []

    class Config:
        from_attributes = True
"""

files["server/middleware/auth.py"] = """from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional

from ..config import settings
from ..database import get_db
from ..models.usuario import Usuario

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido")

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    payload = verify_token(token)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido")
    
    result = await db.execute(select(Usuario).where(Usuario.id == int(user_id)))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return user

def require_permission(permiso: str):
    async def permission_checker(current_user: Usuario = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        from ..models.permiso import PermisoUsuario
        if current_user.rol == "Administrador":
            return current_user
        
        result = await db.execute(
            select(PermisoUsuario).where(
                PermisoUsuario.usuario_id == current_user.id,
                PermisoUsuario.permiso == permiso,
                PermisoUsuario.concedido == True
            )
        )
        if not result.scalars().first():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permiso denegado")
        return current_user
    return permission_checker
"""

files["server/middleware/audit.py"] = """from sqlalchemy.ext.asyncio import AsyncSession
from ..models.auditoria import AuditLog

async def log_audit(db: AsyncSession, usuario_id: int, usuario_nombre: str, terminal_id: int, terminal_nombre: str, accion: str, modulo: str, tabla_afectada: str, registro_id: str, valor_anterior: dict = None, valor_nuevo: dict = None, descripcion: str = None, ip_address: str = None):
    audit_entry = AuditLog(
        usuario_id=usuario_id,
        usuario_nombre=usuario_nombre,
        terminal_id=terminal_id,
        terminal_nombre=terminal_nombre,
        accion=accion,
        modulo=modulo,
        tabla_afectada=tabla_afectada,
        registro_id=registro_id,
        valor_anterior=valor_anterior,
        valor_nuevo=valor_nuevo,
        descripcion=descripcion,
        ip_address=ip_address
    )
    db.add(audit_entry)
    await db.commit()
"""

files["server/routers/auth.py"] = """from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime
from ..database import get_db
from ..schemas.usuario import LoginRequest, TokenResponse, UserResponse
from ..models.usuario import Usuario
from ..middleware.auth import verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Usuario).where(Usuario.usuario == request.usuario))
    user = result.scalars().first()
    
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales invalidas")
    
    if user.estado != 'Activo':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo")
        
    access_token = create_access_token(data={"sub": str(user.id), "terminal_id": request.terminal_id})
    
    user.ultimo_acceso = datetime.utcnow()
    await db.commit()
    
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/logout")
async def logout(current_user: Usuario = Depends(get_current_user)):
    return {"message": "Sesion cerrada exitosamente"}

@router.get("/me", response_model=UserResponse)
async def me(current_user: Usuario = Depends(get_current_user)):
    return current_user
"""

files["server/routers/usuarios.py"] = """from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from ..database import get_db
from ..models.usuario import Usuario
from ..models.permiso import PermisoUsuario
from ..schemas.usuario import UserCreate, UserUpdate, UserResponse
from ..schemas.common import PaginatedResponse
from ..middleware.auth import get_current_user, hash_password

router = APIRouter(prefix="/usuarios", tags=["usuarios"])

@router.get("", response_model=PaginatedResponse[UserResponse])
async def list_usuarios(page: int = 1, size: int = 10, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Usuario).offset((page - 1) * size).limit(size))
    items = result.scalars().all()
    # Simple count for demo
    total = len(items)
    return PaginatedResponse(items=items, total=total, page=page, size=size, pages=1)

@router.get("/{id}", response_model=UserResponse)
async def get_usuario(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Usuario).where(Usuario.id == id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user

@router.post("", response_model=UserResponse)
async def create_usuario(user: UserCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    db_user = Usuario(
        nombre=user.nombre,
        apellidos=user.apellidos,
        documento=user.documento,
        usuario=user.usuario,
        password_hash=hash_password(user.password),
        rol=user.rol,
        tipo_remuneracion=user.tipo_remuneracion,
        salario_diario=user.salario_diario,
        porcentaje_comision=user.porcentaje_comision,
        estado=user.estado
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

@router.put("/{id}", response_model=UserResponse)
async def update_usuario(id: int, user_update: UserUpdate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Usuario).where(Usuario.id == id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    update_data = user_update.model_dump(exclude_unset=True)
    if "password" in update_data:
        update_data["password_hash"] = hash_password(update_data.pop("password"))
        
    for key, value in update_data.items():
        setattr(user, key, value)
        
    await db.commit()
    await db.refresh(user)
    return user

@router.patch("/{id}/estado", response_model=UserResponse)
async def change_estado(id: int, estado: str, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Usuario).where(Usuario.id == id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    user.estado = estado
    await db.commit()
    await db.refresh(user)
    return user

@router.get("/{id}/permisos")
async def get_permisos(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(PermisoUsuario).where(PermisoUsuario.usuario_id == id))
    return result.scalars().all()

@router.put("/{id}/permisos")
async def update_permisos(id: int, permisos: List[str], db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    # Simple replace logic
    pass # To be implemented fully based on requirements
"""

files["server/routers/terminales.py"] = """from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from pydantic import BaseModel
from ..database import get_db
from ..models.terminal import Terminal
from ..middleware.auth import get_current_user

router = APIRouter(prefix="/terminales", tags=["terminales"])

class TerminalBase(BaseModel):
    nombre: str
    descripcion: str = None
    estado: str = "Activo"

class TerminalResponse(TerminalBase):
    id: int
    class Config:
        from_attributes = True

@router.get("", response_model=List[TerminalResponse])
async def list_terminales(db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    result = await db.execute(select(Terminal))
    return result.scalars().all()

@router.post("", response_model=TerminalResponse)
async def create_terminal(terminal: TerminalBase, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    db_terminal = Terminal(**terminal.model_dump())
    db.add(db_terminal)
    await db.commit()
    await db.refresh(db_terminal)
    return db_terminal

@router.put("/{id}", response_model=TerminalResponse)
async def update_terminal(id: int, terminal_update: TerminalBase, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    result = await db.execute(select(Terminal).where(Terminal.id == id))
    terminal = result.scalars().first()
    if not terminal:
        raise HTTPException(status_code=404, detail="Terminal no encontrada")
    
    for key, value in terminal_update.model_dump(exclude_unset=True).items():
        setattr(terminal, key, value)
        
    await db.commit()
    await db.refresh(terminal)
    return terminal
"""

files["server/main.py"] = """from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import auth, usuarios, terminales
from .database import engine, Base
from .config import settings

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(usuarios.router)
app.include_router(terminales.router)

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/")
async def root():
    return {"app": settings.APP_NAME, "version": settings.APP_VERSION}
"""

files["server/Dockerfile"] = """FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/server

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

files["docker-compose.yml"] = """version: '3.8'

services:
  vmpos-db:
    image: postgres:16-alpine
    container_name: vmpos_db
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: vmpos
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  vmpos-api:
    build:
      context: ./server
      dockerfile: Dockerfile
    container_name: vmpos_api
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:postgres@vmpos-db:5432/vmpos
      - SECRET_KEY=supersecretkey
    depends_on:
      - vmpos-db
    restart: unless-stopped

volumes:
  postgres_data:
"""

for path, content in files.items():
    full_path = os.path.join(base_dir, path)
    with open(full_path, "w") as f:
        f.write(content)
print("Files generated successfully.")
