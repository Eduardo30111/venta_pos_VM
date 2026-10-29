from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, delete
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
        result = await db.execute(select(Producto.codigo))
        codigos = result.scalars().all()
        max_cod = 0
        for c in codigos:
            if c and str(c).isdigit():
                max_cod = max(max_cod, int(c))
        codigo = f"{max_cod + 1:05d}"
        
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

@router.delete("/{id}", dependencies=[Depends(require_permission("productos.eliminar"))])
async def delete_producto(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Producto).where(Producto.id == id))
    producto = result.scalars().first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
        
    await db.execute(delete(MovimientoInventario).where(MovimientoInventario.producto_id == id))
    await db.delete(producto)
    await db.commit()
    await log_audit(db, current_user.id, current_user.nombre, None, None, "ELIMINAR", "PRODUCTOS", "productos", str(id))
    return {"message": "Producto eliminado exitosamente"}

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
