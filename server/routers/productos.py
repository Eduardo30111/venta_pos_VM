from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, delete
from typing import Optional

from ..database import get_db
from ..models.producto import Producto
from ..models.inventario import MovimientoInventario
from ..models.venta import DetalleVenta
from ..schemas.producto import ProductoCreate, ProductoUpdate, ProductoResponse
from ..schemas.inventario import AjusteStock, MovimientoInventarioResponse
from ..schemas.common import PaginatedResponse
from ..middleware.auth import get_current_user, require_permission
from ..models.usuario import Usuario
from ..middleware.audit import log_audit
from ..async_lock import SHARED_INVENTORY_LOCK

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
    if sb < 0 or sv < 0 or st < 0:
        raise HTTPException(status_code=400, detail="El stock no puede ser negativo.")
    if float(payload.get("precio_venta") or 0.0) < 0 or float(payload.get("precio_costo") or 0.0) < 0:
        raise HTTPException(status_code=400, detail="El precio de venta y el costo no pueden ser negativos.")
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
    async with SHARED_INVENTORY_LOCK:
        result = await db.execute(select(Producto).with_for_update().where(Producto.id == id))
        producto = result.scalars().first()
        if not producto:
            raise HTTPException(status_code=404, detail="Producto no encontrado")

        cambios = producto_update.model_dump(exclude_unset=True)
        for campo_no_neg in ("stock", "stock_bodega", "stock_vitrina", "precio_venta", "precio_costo"):
            if campo_no_neg in cambios and cambios[campo_no_neg] is not None and float(cambios[campo_no_neg]) < 0:
                raise HTTPException(status_code=400, detail=f"El campo '{campo_no_neg}' no puede ser negativo.")

        anterior = {k: getattr(producto, k, None) for k in cambios.keys()}
        for key, value in cambios.items():
            setattr(producto, key, value)

        if "stock_bodega" in cambios or "stock_vitrina" in cambios:
            producto.stock = round(float(producto.stock_bodega or 0.0) + float(producto.stock_vitrina or 0.0), 4)
        elif "stock" in cambios:
            producto.stock_vitrina = float(producto.stock or 0.0)
            producto.stock_bodega = 0.0

        await log_audit(
            db,
            current_user.id,
            current_user.nombre or current_user.usuario,
            None,
            None,
            "EDITAR",
            "PRODUCTOS",
            "productos",
            str(producto.id),
            valor_anterior=anterior,
            valor_nuevo=cambios,
            auto_commit=False,
        )
        await db.commit()
        await db.refresh(producto)
        return producto


@router.delete("/{id}", dependencies=[Depends(require_permission("productos.eliminar"))])
async def delete_producto(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    async with SHARED_INVENTORY_LOCK:
        result = await db.execute(select(Producto).with_for_update().where(Producto.id == id))
        producto = result.scalars().first()
        if not producto:
            raise HTTPException(status_code=404, detail="Producto no encontrado")

        cnt_kardex = int((await db.execute(select(func.count(MovimientoInventario.id)).where(MovimientoInventario.producto_id == id))).scalar() or 0)
        cnt_ventas = int((await db.execute(select(func.count(DetalleVenta.id)).where(DetalleVenta.tipo_item == "Producto", DetalleVenta.item_id == id))).scalar() or 0)

        if (cnt_kardex + cnt_ventas) > 0:
            estado_ant = producto.estado
            producto.estado = "Inactivo"
            await log_audit(
                db,
                current_user.id,
                current_user.nombre or current_user.usuario,
                None,
                None,
                "DESACTIVAR_CON_HISTORIAL",
                "PRODUCTOS",
                "productos",
                str(id),
                valor_anterior={"estado": estado_ant, "codigo": producto.codigo, "nombre": producto.nombre},
                valor_nuevo={"estado": "Inactivo", "movimientos_kardex": cnt_kardex, "ventas_historicas": cnt_ventas},
                auto_commit=False,
            )
            await db.commit()
            return {
                "message": "Producto desactivado lógicamente (Inactivo) para preservar el Kárdex e historial de ventas.",
                "accion": "DESACTIVADO_CON_HISTORIAL",
            }

        snap = {"codigo": producto.codigo, "nombre": producto.nombre}
        await db.delete(producto)
        await log_audit(
            db,
            current_user.id,
            current_user.nombre or current_user.usuario,
            None,
            None,
            "ELIMINAR",
            "PRODUCTOS",
            "productos",
            str(id),
            valor_anterior=snap,
            auto_commit=False,
        )
        await db.commit()
        return {"message": "Producto eliminado exitosamente", "accion": "ELIMINADO_DEFINITIVO"}


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
    async with SHARED_INVENTORY_LOCK:
        result = await db.execute(select(Producto).with_for_update().where(Producto.id == id))
        producto = result.scalars().first()
        if not producto:
            raise HTTPException(status_code=404, detail="Producto no encontrado")

        ahora = datetime.now()
        stock_anterior = float(producto.stock or 0.0)
        sv_ant = float(producto.stock_vitrina or 0.0)
        sb_ant = float(producto.stock_bodega or 0.0)
        if sv_ant + float(ajuste.cantidad) < -1e-6:
            raise HTTPException(
                status_code=400,
                detail=f"El ajuste dejaría stock negativo en Vitrina (disponible: {sv_ant:g}, ajuste: {ajuste.cantidad:g}).",
            )
        sv_nuevo = round(max(0.0, sv_ant + float(ajuste.cantidad)), 4)
        delta_real = round(abs(sv_nuevo - sv_ant), 4)
        producto.stock_vitrina = sv_nuevo
        producto.stock = round(sb_ant + sv_nuevo, 4)

        mov = MovimientoInventario(
            fecha=ahora.strftime("%Y-%m-%d"),
            hora=ahora.strftime("%H:%M:%S"),
            producto_id=producto.id,
            codigo_producto=producto.codigo,
            nombre_producto=producto.nombre,
            tipo=ajuste.tipo,
            cantidad=delta_real,
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
            valor_total=round(delta_real * float(producto.precio_costo or 0.0), 2),
            referencia="Ajuste manual",
            usuario_id=current_user.id,
            usuario_nombre=current_user.nombre or current_user.usuario,
            terminal_id=terminal_id,
            observacion=ajuste.observacion,
            estado="Completado",
        )
        db.add(mov)
        await db.flush()
        await log_audit(
            db,
            current_user.id,
            current_user.nombre or current_user.usuario,
            terminal_id,
            None,
            "AJUSTE_STOCK",
            "INVENTARIO",
            "movimientos_inventario",
            str(mov.id),
            valor_anterior={"stock_vitrina": sv_ant, "stock": stock_anterior},
            valor_nuevo={"cantidad": ajuste.cantidad, "stock_vitrina": sv_nuevo, "stock": producto.stock},
            auto_commit=False,
        )
        await db.commit()
        await db.refresh(mov)
        return mov
