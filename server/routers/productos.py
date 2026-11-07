from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
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
async def list_productos(
    page: int = 1,
    size: int = 1000,
    nombre: Optional[str] = None,
    categoria_id: Optional[int] = None,
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    query = select(Producto)
    if nombre:
        query = query.where(Producto.nombre.ilike(f"%{nombre}%"))
    if categoria_id:
        query = query.where(Producto.categoria_id == categoria_id)
    if estado:
        query = query.where(Producto.estado == estado)

    count_q = select(func.count()).select_from(query.subquery())
    total_res = await db.execute(count_q)
    total = int(total_res.scalar() or 0)

    result = await db.execute(query.order_by(Producto.nombre.asc()).offset((page - 1) * size).limit(size))
    items = result.scalars().all()
    pages = max(1, (total + size - 1) // size)
    return PaginatedResponse(items=items, total=total, page=page, size=size, pages=pages)


@router.get("/{id}", response_model=ProductoResponse)
async def get_producto(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    result = await db.execute(select(Producto).where(Producto.id == id))
    producto = result.scalars().first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return producto


@router.post("", response_model=ProductoResponse, dependencies=[Depends(require_permission("productos.crear"))])
async def create_producto(
    producto: ProductoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    codigo_custom = (producto.codigo or "").strip()
    if codigo_custom:
        dup = await db.execute(select(Producto).where(Producto.codigo == codigo_custom))
        if dup.scalars().first():
            raise HTTPException(status_code=400, detail=f"El código {codigo_custom} ya existe")
        codigo = codigo_custom
    else:
        result = await db.execute(select(Producto.codigo))
        codigos = result.scalars().all()
        max_cod = 0
        for c in codigos:
            if c and str(c).isdigit():
                max_cod = max(max_cod, int(c))
        codigo = f"{max_cod + 1:05d}"

    payload = producto.model_dump(exclude={"codigo"})
    sb = float(payload.get("stock_bodega") or 0.0)
    sv = float(payload.get("stock_vitrina") or 0.0)
    st = float(payload.get("stock") or 0.0)
    if sb == 0.0 and sv == 0.0 and st > 0.0:
        sv = st
        payload["stock_vitrina"] = sv
    payload["stock"] = round(sb + sv, 4)

    db_producto = Producto(**payload, codigo=codigo)
    db.add(db_producto)
    await db.commit()
    await db.refresh(db_producto)

    await log_audit(
        db,
        current_user.id,
        current_user.nombre,
        None,
        None,
        "CREAR",
        "PRODUCTOS",
        "productos",
        str(db_producto.id),
        valor_nuevo=producto.model_dump(),
    )
    return db_producto


@router.put("/{id}", response_model=ProductoResponse, dependencies=[Depends(require_permission("productos.editar"))])
async def update_producto(
    id: int,
    producto_update: ProductoUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    result = await db.execute(select(Producto).where(Producto.id == id))
    producto = result.scalars().first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    cambios = producto_update.model_dump(exclude_unset=True)
    for key, value in cambios.items():
        setattr(producto, key, value)

    if "stock_bodega" in cambios or "stock_vitrina" in cambios:
        producto.stock = round(float(producto.stock_bodega or 0.0) + float(producto.stock_vitrina or 0.0), 4)
    elif "stock" in cambios:
        producto.stock_vitrina = float(producto.stock or 0.0)
        producto.stock_bodega = 0.0

    await db.commit()
    await db.refresh(producto)

    await log_audit(
        db,
        current_user.id,
        current_user.nombre,
        None,
        None,
        "EDITAR",
        "PRODUCTOS",
        "productos",
        str(producto.id),
        valor_nuevo=cambios,
    )
    return producto


@router.delete("/{id}", dependencies=[Depends(require_permission("productos.eliminar"))])
async def delete_producto(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
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
async def change_estado(
    id: int,
    estado: str,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    result = await db.execute(select(Producto).where(Producto.id == id))
    producto = result.scalars().first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    producto.estado = estado
    await db.commit()
    await db.refresh(producto)
    await log_audit(
        db,
        current_user.id,
        current_user.nombre,
        None,
        None,
        "ESTADO",
        "PRODUCTOS",
        "productos",
        str(producto.id),
        valor_nuevo={"estado": estado},
    )
    return producto


@router.post("/{id}/ajuste-stock", response_model=MovimientoInventarioResponse, dependencies=[Depends(require_permission("productos.editar"))])
async def ajuste_stock(
    id: int,
    ajuste: AjusteStock,
    terminal_id: int = 1,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    result = await db.execute(select(Producto).with_for_update().where(Producto.id == id))
    producto = result.scalars().first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    ahora = datetime.now()
    stock_anterior = float(producto.stock or 0.0)
    sv_ant = float(producto.stock_vitrina or 0.0)
    sb_ant = float(producto.stock_bodega or 0.0)
    sv_nuevo = round(max(0.0, sv_ant + float(ajuste.cantidad)), 4)
    producto.stock_vitrina = sv_nuevo
    producto.stock = round(sb_ant + sv_nuevo, 4)

    mov = MovimientoInventario(
        fecha=ahora.strftime("%Y-%m-%d"),
        hora=ahora.strftime("%H:%M:%S"),
        producto_id=producto.id,
        codigo_producto=producto.codigo,
        nombre_producto=producto.nombre,
        tipo=ajuste.tipo,
        cantidad=abs(float(ajuste.cantidad)),
        unidad_medida=producto.unidad_medida or "Unidad",
        ubicacion_origen="AJUSTE" if ajuste.cantidad > 0 else "VITRINA",
        ubicacion_destino="VITRINA" if ajuste.cantidad > 0 else "BAJA",
        stock_anterior=stock_anterior,
        stock_nuevo=producto.stock,
        stock_origen_ant=sv_ant,
        stock_origen_des=sv_nuevo,
        stock_destino_ant=sv_ant,
        stock_destino_des=sv_nuevo,
        costo_unitario=float(producto.precio_costo or 0.0),
        valor_total=round(abs(float(ajuste.cantidad)) * float(producto.precio_costo or 0.0), 2),
        referencia="Ajuste manual",
        usuario_id=current_user.id,
        usuario_nombre=current_user.nombre,
        terminal_id=terminal_id,
        observacion=ajuste.observacion,
        estado="Completado",
    )
    db.add(mov)
    await db.commit()
    await db.refresh(mov)
    await log_audit(
        db,
        current_user.id,
        current_user.nombre,
        terminal_id,
        None,
        "AJUSTE_STOCK",
        "INVENTARIO",
        "movimientos_inventario",
        str(mov.id),
        valor_nuevo={"cantidad": ajuste.cantidad},
    )
    return mov
