import os

base_dir = "/Users/eduardosanchez/venta_pos_VM-main"
server_dir = os.path.join(base_dir, "server")

files = {}

files["server/schemas/proveedor.py"] = """from pydantic import BaseModel
from typing import Optional

class ProveedorBase(BaseModel):
    nombre: str
    documento_nit: str
    telefono: Optional[str] = None
    email: Optional[str] = None
    direccion: Optional[str] = None
    contacto: Optional[str] = None
    estado: Optional[str] = "Activo"

class ProveedorCreate(ProveedorBase):
    pass

class ProveedorUpdate(ProveedorBase):
    nombre: Optional[str] = None
    documento_nit: Optional[str] = None

class ProveedorResponse(ProveedorBase):
    id: int

    class Config:
        from_attributes = True
"""

files["server/schemas/cliente.py"] = """from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ClienteBase(BaseModel):
    documento: str
    nombre: str
    email: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    permite_fiado: Optional[bool] = False
    limite_credito: Optional[float] = 0.0
    estado: Optional[str] = "Activo"

class ClienteCreate(ClienteBase):
    pass

class ClienteUpdate(ClienteBase):
    documento: Optional[str] = None
    nombre: Optional[str] = None

class ClienteResponse(ClienteBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

class AbonoCreate(BaseModel):
    monto: float
    metodo: str
    observacion: Optional[str] = None
"""

files["server/schemas/categoria.py"] = """from pydantic import BaseModel
from typing import Optional

class CategoriaBase(BaseModel):
    nombre: str
    tipo: str
    estado: Optional[str] = "Activo"

class CategoriaCreate(CategoriaBase):
    pass

class CategoriaUpdate(CategoriaBase):
    nombre: Optional[str] = None
    tipo: Optional[str] = None
    estado: Optional[str] = None

class CategoriaResponse(CategoriaBase):
    id: int

    class Config:
        from_attributes = True
"""

files["server/schemas/nomina.py"] = """from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class ComisionResponse(BaseModel):
    id: int
    usuario_id: int
    venta_id: int
    servicio_id: int
    valor_servicio: float
    utilidad: float
    porcentaje: float
    monto_comision: float
    estado: str
    created_at: datetime

    class Config:
        from_attributes = True

class AsistenciaCreate(BaseModel):
    usuario_id: int
    fecha: str
    estado: str

class AsistenciaResponse(BaseModel):
    id: int
    usuario_id: int
    fecha: datetime
    estado: str
    registrado_por: int
    salario_generado: float

    class Config:
        from_attributes = True

class LiquidacionCreate(BaseModel):
    usuario_id: int
    periodo_inicio: datetime
    periodo_fin: datetime
    observaciones: Optional[str] = None

class LiquidacionResponse(BaseModel):
    id: int
    usuario_id: int
    periodo_inicio: datetime
    periodo_fin: datetime
    total_servicios_vendidos: float
    total_comisiones: float
    total_salario_fijo: float
    total_liquidado: float
    estado: str
    observaciones: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
"""

files["server/schemas/gasto.py"] = """from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class GastoBase(BaseModel):
    concepto: str
    categoria: str
    valor: float
    tipo: str
    referencia_id: Optional[int] = None
    observacion: Optional[str] = None

class GastoCreate(GastoBase):
    pass

class GastoUpdate(BaseModel):
    concepto: Optional[str] = None
    categoria: Optional[str] = None
    valor: Optional[float] = None
    observacion: Optional[str] = None

class GastoResponse(GastoBase):
    id: int
    usuario_id: int
    created_at: datetime

    class Config:
        from_attributes = True
"""

files["server/schemas/inventario.py"] = """from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class AjusteStock(BaseModel):
    cantidad: float
    tipo: str
    observacion: str

class MovimientoInventarioResponse(BaseModel):
    id: int
    producto_id: int
    tipo: str
    cantidad: float
    stock_anterior: float
    stock_nuevo: float
    referencia: Optional[str] = None
    usuario_id: int
    terminal_id: int
    observacion: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
"""

files["server/routers/productos.py"] = """from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from typing import Optional
from ..database import get_db
from ..models.producto import Producto
from ..models.inventario import MovimientoInventario
from ..schemas.producto import ProductoCreate, ProductoUpdate, ProductoResponse
from ..schemas.inventario import AjusteStock, MovimientoInventarioResponse
from ..schemas.common import PaginatedResponse
from ..middleware.auth import get_current_user, require_permission
from ..models.usuario import Usuario
from ..middleware.audit import log_audit

router = APIRouter(prefix="/productos", tags=["productos"])

@router.get("", response_model=PaginatedResponse[ProductoResponse])
async def list_productos(page: int = 1, size: int = 10, nombre: Optional[str] = None, categoria_id: Optional[int] = None, estado: Optional[str] = None, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    query = select(Producto)
    if nombre:
        query = query.where(Producto.nombre.ilike(f"%{nombre}%"))
    if categoria_id:
        query = query.where(Producto.categoria_id == categoria_id)
    if estado:
        query = query.where(Producto.estado == estado)
        
    result = await db.execute(query.offset((page - 1) * size).limit(size))
    items = result.scalars().all()
    # Simple count
    total = len(items)
    return PaginatedResponse(items=items, total=total, page=page, size=size, pages=1)

@router.get("/{id}", response_model=ProductoResponse)
async def get_producto(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Producto).where(Producto.id == id))
    producto = result.scalars().first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return producto

@router.post("", response_model=ProductoResponse, dependencies=[Depends(require_permission("productos.crear"))])
async def create_producto(producto: ProductoCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    # Auto-generate codigo: Max + 1
    # We use a transaction with table lock or similar, but for asyncpg simple scalar should be okay for demo
    async with db.begin_nested():
        result = await db.execute(select(func.max(Producto.codigo)))
        max_cod = result.scalar()
        if max_cod and max_cod.isdigit():
            next_cod = int(max_cod) + 1
        else:
            next_cod = 1
        codigo = f"{next_cod:05d}"
        
        db_producto = Producto(**producto.model_dump(exclude={'codigo'}), codigo=codigo)
        db.add(db_producto)
        
    await db.commit()
    await db.refresh(db_producto)
    
    await log_audit(db, current_user.id, current_user.nombre, None, None, "CREAR", "PRODUCTOS", "productos", str(db_producto.id), valor_nuevo=producto.model_dump())
    
    return db_producto

@router.put("/{id}", response_model=ProductoResponse, dependencies=[Depends(require_permission("productos.editar"))])
async def update_producto(id: int, producto_update: ProductoUpdate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Producto).where(Producto.id == id))
    producto = result.scalars().first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
        
    for key, value in producto_update.model_dump(exclude_unset=True).items():
        setattr(producto, key, value)
        
    await db.commit()
    await db.refresh(producto)
    
    await log_audit(db, current_user.id, current_user.nombre, None, None, "EDITAR", "PRODUCTOS", "productos", str(producto.id), valor_nuevo=producto_update.model_dump(exclude_unset=True))
    return producto

@router.patch("/{id}/estado", response_model=ProductoResponse, dependencies=[Depends(require_permission("productos.eliminar"))])
async def change_estado(id: int, estado: str, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Producto).where(Producto.id == id))
    producto = result.scalars().first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    producto.estado = estado
    await db.commit()
    await db.refresh(producto)
    await log_audit(db, current_user.id, current_user.nombre, None, None, "ESTADO", "PRODUCTOS", "productos", str(producto.id), valor_nuevo={"estado": estado})
    return producto

@router.post("/{id}/ajuste-stock", response_model=MovimientoInventarioResponse, dependencies=[Depends(require_permission("productos.editar"))])
async def ajuste_stock(id: int, ajuste: AjusteStock, terminal_id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Producto).with_for_update().where(Producto.id == id))
    producto = result.scalars().first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
        
    stock_anterior = producto.stock
    producto.stock += ajuste.cantidad
    
    mov = MovimientoInventario(
        producto_id=producto.id,
        tipo=ajuste.tipo,
        cantidad=ajuste.cantidad,
        stock_anterior=stock_anterior,
        stock_nuevo=producto.stock,
        referencia=f"Ajuste manual",
        usuario_id=current_user.id,
        terminal_id=terminal_id,
        observacion=ajuste.observacion
    )
    db.add(mov)
    await db.commit()
    await db.refresh(mov)
    await log_audit(db, current_user.id, current_user.nombre, terminal_id, None, "AJUSTE_STOCK", "INVENTARIO", "movimientos_inventario", str(mov.id), valor_nuevo={"cantidad": ajuste.cantidad})
    return mov
"""

files["server/routers/servicios.py"] = """from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from typing import Optional
from ..database import get_db
from ..models.servicio import Servicio
from ..schemas.servicio import ServicioCreate, ServicioUpdate, ServicioResponse
from ..schemas.common import PaginatedResponse
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario
from ..middleware.audit import log_audit

router = APIRouter(prefix="/servicios", tags=["servicios"])

@router.get("", response_model=PaginatedResponse[ServicioResponse])
async def list_servicios(page: int = 1, size: int = 10, nombre: Optional[str] = None, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    query = select(Servicio)
    if nombre:
        query = query.where(Servicio.nombre.ilike(f"%{nombre}%"))
        
    result = await db.execute(query.offset((page - 1) * size).limit(size))
    items = result.scalars().all()
    total = len(items)
    return PaginatedResponse(items=items, total=total, page=page, size=size, pages=1)

@router.get("/{id}", response_model=ServicioResponse)
async def get_servicio(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Servicio).where(Servicio.id == id))
    servicio = result.scalars().first()
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    return servicio

@router.post("", response_model=ServicioResponse)
async def create_servicio(servicio: ServicioCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    async with db.begin_nested():
        result = await db.execute(select(func.max(func.cast(func.substring(Servicio.codigo, 2), func.Integer))))
        max_cod = result.scalar()
        next_cod = (max_cod + 1) if max_cod else 1
        codigo = f"S{next_cod:05d}"
        
        db_servicio = Servicio(**servicio.model_dump(exclude={'codigo'}), codigo=codigo)
        db.add(db_servicio)
        
    await db.commit()
    await db.refresh(db_servicio)
    await log_audit(db, current_user.id, current_user.nombre, None, None, "CREAR", "SERVICIOS", "servicios", str(db_servicio.id))
    return db_servicio

@router.put("/{id}", response_model=ServicioResponse)
async def update_servicio(id: int, servicio_update: ServicioUpdate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Servicio).where(Servicio.id == id))
    servicio = result.scalars().first()
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
        
    for key, value in servicio_update.model_dump(exclude_unset=True).items():
        setattr(servicio, key, value)
        
    await db.commit()
    await db.refresh(servicio)
    await log_audit(db, current_user.id, current_user.nombre, None, None, "EDITAR", "SERVICIOS", "servicios", str(servicio.id))
    return servicio

@router.patch("/{id}/estado", response_model=ServicioResponse)
async def change_estado(id: int, estado: str, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Servicio).where(Servicio.id == id))
    servicio = result.scalars().first()
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    servicio.estado = estado
    await db.commit()
    await db.refresh(servicio)
    await log_audit(db, current_user.id, current_user.nombre, None, None, "ESTADO", "SERVICIOS", "servicios", str(servicio.id))
    return servicio
"""

files["server/routers/proveedores.py"] = """from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from ..database import get_db
from ..models.proveedor import Proveedor
from ..schemas.proveedor import ProveedorCreate, ProveedorUpdate, ProveedorResponse
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario

router = APIRouter(prefix="/proveedores", tags=["proveedores"])

@router.get("", response_model=List[ProveedorResponse])
async def list_proveedores(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Proveedor))
    return result.scalars().all()

@router.get("/{id}", response_model=ProveedorResponse)
async def get_proveedor(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Proveedor).where(Proveedor.id == id))
    proveedor = result.scalars().first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    return proveedor

@router.post("", response_model=ProveedorResponse)
async def create_proveedor(proveedor: ProveedorCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    db_prov = Proveedor(**proveedor.model_dump())
    db.add(db_prov)
    await db.commit()
    await db.refresh(db_prov)
    return db_prov

@router.put("/{id}", response_model=ProveedorResponse)
async def update_proveedor(id: int, prov_update: ProveedorUpdate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Proveedor).where(Proveedor.id == id))
    proveedor = result.scalars().first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    for key, value in prov_update.model_dump(exclude_unset=True).items():
        setattr(proveedor, key, value)
    await db.commit()
    await db.refresh(proveedor)
    return proveedor

@router.patch("/{id}/estado", response_model=ProveedorResponse)
async def change_estado(id: int, estado: str, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Proveedor).where(Proveedor.id == id))
    proveedor = result.scalars().first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    proveedor.estado = estado
    await db.commit()
    await db.refresh(proveedor)
    return proveedor
"""

files["server/routers/categorias.py"] = """from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from ..database import get_db
from ..models.categoria import Categoria
from ..schemas.categoria import CategoriaCreate, CategoriaUpdate, CategoriaResponse
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario

router = APIRouter(prefix="/categorias", tags=["categorias"])

@router.get("", response_model=List[CategoriaResponse])
async def list_categorias(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Categoria))
    return result.scalars().all()

@router.post("", response_model=CategoriaResponse)
async def create_categoria(cat: CategoriaCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    db_cat = Categoria(**cat.model_dump())
    db.add(db_cat)
    await db.commit()
    await db.refresh(db_cat)
    return db_cat

@router.put("/{id}", response_model=CategoriaResponse)
async def update_categoria(id: int, cat_update: CategoriaUpdate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Categoria).where(Categoria.id == id))
    cat = result.scalars().first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria no encontrada")
    for key, value in cat_update.model_dump(exclude_unset=True).items():
        setattr(cat, key, value)
    await db.commit()
    await db.refresh(cat)
    return cat
"""

files["server/routers/clientes.py"] = """from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from ..database import get_db
from ..models.cliente import Cliente
from ..models.finanzas import CuentaPorCobrar, Abono
from ..schemas.cliente import ClienteCreate, ClienteUpdate, ClienteResponse, AbonoCreate
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario
from ..middleware.audit import log_audit

router = APIRouter(prefix="/clientes", tags=["clientes"])

@router.get("", response_model=List[ClienteResponse])
async def list_clientes(nombre: Optional[str] = None, documento: Optional[str] = None, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    query = select(Cliente)
    if nombre:
        query = query.where(Cliente.nombre.ilike(f"%{nombre}%"))
    if documento:
        query = query.where(Cliente.documento == documento)
    result = await db.execute(query)
    return result.scalars().all()

@router.get("/{id}", response_model=ClienteResponse)
async def get_cliente(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Cliente).where(Cliente.id == id))
    cliente = result.scalars().first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return cliente

@router.post("", response_model=ClienteResponse)
async def create_cliente(cliente: ClienteCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    db_cli = Cliente(**cliente.model_dump())
    db.add(db_cli)
    await db.commit()
    await db.refresh(db_cli)
    return db_cli

@router.put("/{id}", response_model=ClienteResponse)
async def update_cliente(id: int, cli_update: ClienteUpdate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Cliente).where(Cliente.id == id))
    cliente = result.scalars().first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    for key, value in cli_update.model_dump(exclude_unset=True).items():
        setattr(cliente, key, value)
    await db.commit()
    await db.refresh(cliente)
    return cliente

@router.patch("/{id}/estado", response_model=ClienteResponse)
async def change_estado(id: int, estado: str, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Cliente).where(Cliente.id == id))
    cliente = result.scalars().first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    cliente.estado = estado
    await db.commit()
    await db.refresh(cliente)
    return cliente

@router.post("/{id}/abonos")
async def register_abono(id: int, cuenta_id: int, abono: AbonoCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(CuentaPorCobrar).with_for_update().where(CuentaPorCobrar.id == cuenta_id, CuentaPorCobrar.cliente_id == id))
    cuenta = result.scalars().first()
    if not cuenta:
        raise HTTPException(status_code=404, detail="Cuenta por cobrar no encontrada")
    
    if abono.monto > cuenta.saldo_pendiente:
        raise HTTPException(status_code=400, detail="Monto excede el saldo pendiente")
        
    cuenta.saldo_pendiente -= abono.monto
    if cuenta.saldo_pendiente == 0:
        cuenta.estado = "Pagada"
        
    db_abono = Abono(cuenta_id=cuenta.id, monto=abono.monto, metodo=abono.metodo, recibido_por=current_user.id, observacion=abono.observacion)
    db.add(db_abono)
    
    await db.commit()
    await log_audit(db, current_user.id, current_user.nombre, None, None, "ABONO", "FINANZAS", "abonos", str(db_abono.id), valor_nuevo={"monto": abono.monto})
    return {"message": "Abono registrado", "saldo_pendiente": cuenta.saldo_pendiente}
"""

files["server/services/venta_service.py"] = """from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from fastapi import HTTPException
from ..models.venta import Venta, DetalleVenta, Pago
from ..models.producto import Producto
from ..models.servicio import Servicio
from ..models.inventario import MovimientoInventario
from ..models.nomina import Comision
from ..models.finanzas import CuentaPorPagar, CuentaPorCobrar
from ..models.cliente import Cliente
from ..models.usuario import Usuario
from ..schemas.venta import VentaCreate
from ..middleware.audit import log_audit

class VentaService:
    @staticmethod
    async def procesar_venta(db: AsyncSession, venta_data: VentaCreate, usuario_id: int, terminal_id: int, usuario: Usuario) -> Venta:
        try:
            # 1. Generate venta numero
            result = await db.execute(select(func.max(func.cast(func.substring(Venta.numero, 3), func.Integer))))
            max_num = result.scalar()
            next_num = (max_num + 1) if max_num else 1
            numero = f"V-{next_num:06d}"

            venta = Venta(
                numero=numero,
                cliente_id=venta_data.cliente_id,
                usuario_id=usuario_id,
                terminal_id=terminal_id,
                subtotal=venta_data.subtotal,
                descuento=venta_data.descuento,
                total=venta_data.total,
                observaciones=venta_data.observaciones
            )
            db.add(venta)
            await db.flush() # get venta.id

            monto_fiado = 0

            # 2. Process items
            for item in venta_data.detalles:
                if item.tipo_item == 'Producto':
                    # Lock product
                    prod_result = await db.execute(select(Producto).with_for_update().where(Producto.id == item.item_id))
                    producto = prod_result.scalars().first()
                    if not producto:
                        raise HTTPException(status_code=404, detail=f"Producto {item.item_id} no encontrado")
                    if producto.stock < item.cantidad:
                        raise HTTPException(status_code=409, detail=f"Stock insuficiente para {producto.nombre}")
                    
                    stock_ant = producto.stock
                    producto.stock -= item.cantidad
                    
                    # Movimiento inventario
                    mov = MovimientoInventario(
                        producto_id=producto.id,
                        tipo="VENTA",
                        cantidad=-item.cantidad,
                        stock_anterior=stock_ant,
                        stock_nuevo=producto.stock,
                        referencia=numero,
                        usuario_id=usuario_id,
                        terminal_id=terminal_id
                    )
                    db.add(mov)
                    
                elif item.tipo_item == 'Servicio':
                    serv_result = await db.execute(select(Servicio).where(Servicio.id == item.item_id))
                    servicio = serv_result.scalars().first()
                    if not servicio or servicio.estado != 'Activo':
                        raise HTTPException(status_code=404, detail=f"Servicio {item.item_id} no activo")
                    
                    # Commission
                    if servicio.tipo_servicio == 'Interno' and servicio.genera_comision and usuario.tipo_remuneracion == 'Porcentual':
                        utilidad = item.precio_vendido - servicio.costo_proveedor
                        comision_monto = utilidad * usuario.porcentaje_comision / 100.0
                        comision = Comision(
                            usuario_id=usuario_id,
                            venta_id=venta.id,
                            detalle_venta_id=0, # temp, will update later
                            servicio_id=servicio.id,
                            valor_servicio=item.precio_vendido,
                            costo_servicio=servicio.costo_proveedor,
                            utilidad=utilidad,
                            porcentaje=usuario.porcentaje_comision,
                            monto_comision=comision_monto
                        )
                        db.add(comision)
                        
                    # Provider Accounts Payable
                    if servicio.proveedor_id:
                        cxp = CuentaPorPagar(
                            proveedor_id=servicio.proveedor_id,
                            venta_id=venta.id,
                            concepto=f"Servicio {servicio.nombre} - Venta {numero}",
                            monto=servicio.costo_proveedor
                        )
                        db.add(cxp)
                
                det = DetalleVenta(
                    venta_id=venta.id,
                    tipo_item=item.tipo_item,
                    item_id=item.item_id,
                    item_codigo=item.item_codigo,
                    item_nombre=item.item_nombre,
                    precio_original=item.precio_original,
                    precio_vendido=item.precio_vendido,
                    cantidad=item.cantidad,
                    descuento=item.descuento,
                    subtotal=item.subtotal,
                    costo_unitario=item.costo_unitario
                )
                db.add(det)
                
            # Process payments
            for p in venta_data.pagos:
                pago = Pago(
                    venta_id=venta.id,
                    metodo=p.metodo,
                    monto=p.monto,
                    referencia=p.referencia,
                    recibido=p.recibido,
                    cambio=p.cambio
                )
                db.add(pago)
                if p.metodo == 'Fiado':
                    monto_fiado += p.monto

            # Fiado logic
            if monto_fiado > 0:
                if not venta_data.cliente_id:
                    raise HTTPException(status_code=400, detail="Cliente requerido para Fiado")
                cli_result = await db.execute(select(Cliente).where(Cliente.id == venta_data.cliente_id))
                cliente = cli_result.scalars().first()
                if not cliente or not cliente.permite_fiado:
                    raise HTTPException(status_code=400, detail="Cliente no permite fiado")
                
                # Check limit
                cxc_result = await db.execute(select(func.sum(CuentaPorCobrar.saldo_pendiente)).where(CuentaPorCobrar.cliente_id == cliente.id))
                deuda_actual = cxc_result.scalar() or 0.0
                if deuda_actual + monto_fiado > cliente.limite_credito:
                    raise HTTPException(status_code=400, detail="Limite de credito excedido")
                
                cxc = CuentaPorCobrar(
                    cliente_id=cliente.id,
                    venta_id=venta.id,
                    monto_original=monto_fiado,
                    saldo_pendiente=monto_fiado
                )
                db.add(cxc)

            await db.commit()
            await db.refresh(venta)
            await log_audit(db, usuario_id, usuario.nombre, terminal_id, "Terminal", "CREAR", "VENTAS", "ventas", str(venta.id))
            return venta
            
        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(e))
"""

files["server/routers/ventas.py"] = """from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from ..database import get_db
from ..models.venta import Venta, DetalleVenta
from ..models.producto import Producto
from ..models.inventario import MovimientoInventario
from ..schemas.venta import VentaCreate, VentaResponse
from ..services.venta_service import VentaService
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario

router = APIRouter(prefix="/ventas", tags=["ventas"])

@router.post("", response_model=VentaResponse)
async def process_venta(venta_data: VentaCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    return await VentaService.procesar_venta(db, venta_data, current_user.id, venta_data.terminal_id, current_user)

@router.get("", response_model=List[VentaResponse])
async def list_ventas(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Venta))
    return result.scalars().all()

@router.get("/{id}", response_model=VentaResponse)
async def get_venta(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Venta).where(Venta.id == id))
    venta = result.scalars().first()
    if not venta:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    return venta

@router.post("/{id}/anular")
async def anular_venta(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    # To be fully implemented: restore stock, cancel comisiones, etc
    return {"message": "Anulacion parcial/temporal no implementada al completo en este script"}
"""

files["server/routers/nomina.py"] = """from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from datetime import datetime, date
from ..database import get_db
from ..models.nomina import Comision, Asistencia, Liquidacion
from ..models.finanzas import Gasto
from ..models.usuario import Usuario
from ..schemas.nomina import ComisionResponse, AsistenciaCreate, AsistenciaResponse, LiquidacionCreate, LiquidacionResponse
from ..middleware.auth import get_current_user

router = APIRouter(prefix="/nomina", tags=["nomina"])

@router.get("/empleados")
async def list_empleados(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Usuario).where(Usuario.rol != 'Administrador'))
    return result.scalars().all()

@router.get("/empleados/{id}/comisiones", response_model=List[ComisionResponse])
async def get_comisiones(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Comision).where(Comision.usuario_id == id, Comision.estado == 'Pendiente'))
    return result.scalars().all()

@router.post("/asistencia", response_model=AsistenciaResponse)
async def register_asistencia(asistencia: AsistenciaCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    user_result = await db.execute(select(Usuario).where(Usuario.id == asistencia.usuario_id))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
    salario_generado = user.salario_diario if user.tipo_remuneracion == 'Fija' and asistencia.estado == 'Presente' else 0.0
    
    fecha_dt = datetime.strptime(asistencia.fecha, "%Y-%m-%d")
    
    db_asist = Asistencia(
        usuario_id=user.id,
        fecha=fecha_dt,
        estado=asistencia.estado,
        registrado_por=current_user.id,
        salario_generado=salario_generado
    )
    db.add(db_asist)
    await db.commit()
    await db.refresh(db_asist)
    return db_asist

@router.get("/asistencia", response_model=List[AsistenciaResponse])
async def get_asistencias(fecha: str, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    fecha_dt = datetime.strptime(fecha, "%Y-%m-%d")
    # Cast to date to match day exactly
    from sqlalchemy import cast, Date
    result = await db.execute(select(Asistencia).where(cast(Asistencia.fecha, Date) == fecha_dt.date()))
    return result.scalars().all()

@router.post("/liquidaciones", response_model=LiquidacionResponse)
async def create_liquidacion(liq: LiquidacionCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    # Very simplified due to complexity, standard atomic procedure
    try:
        # 1. Comisiones
        com_result = await db.execute(select(Comision).with_for_update().where(Comision.usuario_id == liq.usuario_id, Comision.estado == 'Pendiente'))
        comisiones = com_result.scalars().all()
        total_com = sum(c.monto_comision for c in comisiones)
        
        # 2. Asistencias
        asi_result = await db.execute(select(Asistencia).where(Asistencia.usuario_id == liq.usuario_id, Asistencia.fecha >= liq.periodo_inicio, Asistencia.fecha <= liq.periodo_fin, Asistencia.salario_generado > 0))
        asistencias = asi_result.scalars().all()
        total_sal = sum(a.salario_generado for a in asistencias)
        
        # 3. Liquidacion
        liquidacion = Liquidacion(
            usuario_id=liq.usuario_id,
            periodo_inicio=liq.periodo_inicio,
            periodo_fin=liq.periodo_fin,
            total_servicios_vendidos=len(comisiones),
            total_comisiones=total_com,
            total_salario_fijo=total_sal,
            total_liquidado=total_com + total_sal,
            estado="Liquidado",
            liquidado_por=current_user.id,
            observaciones=liq.observaciones
        )
        db.add(liquidacion)
        await db.flush()
        
        # 4. Update comisiones
        for c in comisiones:
            c.estado = 'Liquidada'
            c.liquidacion_id = liquidacion.id
            
        # 5. Gasto
        gasto = Gasto(
            concepto=f"Liquidacion Nomina Usuario {liq.usuario_id}",
            categoria="Nomina",
            valor=liquidacion.total_liquidado,
            tipo="Liquidacion_Nomina",
            referencia_id=liquidacion.id,
            usuario_id=current_user.id
        )
        db.add(gasto)
        
        await db.commit()
        await db.refresh(liquidacion)
        return liquidacion
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/liquidaciones", response_model=List[LiquidacionResponse])
async def list_liquidaciones(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Liquidacion))
    return result.scalars().all()

@router.get("/liquidaciones/{id}", response_model=LiquidacionResponse)
async def get_liquidacion(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Liquidacion).where(Liquidacion.id == id))
    return result.scalars().first()
"""

files["server/routers/gastos.py"] = """from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from ..database import get_db
from ..models.finanzas import Gasto
from ..schemas.gasto import GastoCreate, GastoUpdate, GastoResponse
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario

router = APIRouter(prefix="/gastos", tags=["gastos"])

@router.get("", response_model=List[GastoResponse])
async def list_gastos(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Gasto))
    return result.scalars().all()

@router.post("", response_model=GastoResponse)
async def create_gasto(gasto: GastoCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    db_gasto = Gasto(**gasto.model_dump(), usuario_id=current_user.id)
    db.add(db_gasto)
    await db.commit()
    await db.refresh(db_gasto)
    return db_gasto

@router.put("/{id}", response_model=GastoResponse)
async def update_gasto(id: int, gasto_update: GastoUpdate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Gasto).where(Gasto.id == id))
    gasto = result.scalars().first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    if gasto.tipo != 'Manual':
        raise HTTPException(status_code=400, detail="Solo se pueden editar gastos manuales")
        
    for key, value in gasto_update.model_dump(exclude_unset=True).items():
        setattr(gasto, key, value)
    await db.commit()
    await db.refresh(gasto)
    return gasto

@router.delete("/{id}")
async def delete_gasto(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Gasto).where(Gasto.id == id))
    gasto = result.scalars().first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    if gasto.tipo != 'Manual':
        raise HTTPException(status_code=400, detail="Solo se pueden eliminar gastos manuales")
    
    # Actually just delete since there's no estado in Gasto model, or we just throw error
    await db.delete(gasto)
    await db.commit()
    return {"message": "Gasto eliminado"}
"""

# Modify main.py
files["server/main.py"] = """from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import auth, usuarios, terminales, productos, servicios, proveedores, categorias, clientes, ventas, nomina, gastos
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
app.include_router(productos.router)
app.include_router(servicios.router)
app.include_router(proveedores.router)
app.include_router(categorias.router)
app.include_router(clientes.router)
app.include_router(ventas.router)
app.include_router(nomina.router)
app.include_router(gastos.router)

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/")
async def root():
    return {"app": settings.APP_NAME, "version": settings.APP_VERSION}
"""


for path, content in files.items():
    full_path = os.path.join(base_dir, path)
    with open(full_path, "w") as f:
        f.write(content)
print("Phase 2-4 files generated successfully.")
