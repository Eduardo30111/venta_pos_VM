from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_, delete

from ..database import get_db
from ..models.producto import Producto
from ..models.servicio import Servicio
from ..models.categoria import Categoria
from ..models.proveedor import Proveedor
from ..models.inventario import (
    MovimientoInventario,
    TrasladoInventario,
    CompraInventario,
    DetalleCompra,
)
from ..models.usuario import Usuario
from ..schemas.inventario import (
    ArticuloCatalogoCreate,
    ArticuloCatalogoUpdate,
    TrasladoCreate,
    AjusteInventarioCreate,
    CompraCreate,
)
from ..middleware.auth import get_current_user
from ..middleware.audit import log_audit

router = APIRouter(prefix="/inventario", tags=["inventario"])

UNIDADES_DISCRETAS = {"Unidad", "Caja", "Paquete", "Docena", "Servicio"}


def _validar_cantidad_unidad(unidad: str, cantidad: float):
    if cantidad <= 0:
        raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a cero.")
    if (unidad or "Unidad") in UNIDADES_DISCRETAS and not float(cantidad).is_integer():
        raise HTTPException(
            status_code=400,
            detail=f"La unidad '{unidad}' es discreta y no admite fracciones decimales.",
        )


async def _asegurar_categoria(db: AsyncSession, nombre_cat: str, tipo_cat: str = "Ambos") -> Optional[int]:
    nom = (nombre_cat or "General").strip() or "General"
    res = await db.execute(select(Categoria).where(func.lower(Categoria.nombre) == nom.lower()))
    cat = res.scalars().first()
    if cat:
        return cat.id
    nueva = Categoria(nombre=nom, tipo=tipo_cat, estado="Activo")
    db.add(nueva)
    await db.flush()
    return nueva.id


def _fmt_dt(dt_val) -> str:
    if not dt_val:
        return ""
    if isinstance(dt_val, str):
        return dt_val
    return dt_val.strftime("%Y-%m-%d %H:%M:%S")


def _producto_a_catalogo(p: Producto, prov_map: Dict[int, str], cat_map: Dict[int, str]) -> Dict[str, Any]:
    sb = float(p.stock_bodega or 0.0)
    sv = float(p.stock_vitrina or 0.0)
    st = float(p.stock or 0.0)
    if sb == 0.0 and sv == 0.0 and st > 0.0:
        sv = st
    else:
        st = round(sb + sv, 4)
    cat_nom = p.categoria or (cat_map.get(p.categoria_id, "General") if p.categoria_id else "General")
    return {
        "id": p.id,
        "codigo": p.codigo or "",
        "nombre": p.nombre or "",
        "tipo_producto": "Fisico",
        "categoria": cat_nom or "General",
        "categoria_id": p.categoria_id,
        "marca": p.marca or "",
        "codigo_barras": p.codigo_barras or "",
        "unidad_medida": p.unidad_medida or "Unidad",
        "precio": float(p.precio_venta or 0.0),
        "precio_venta": float(p.precio_venta or 0.0),
        "costo": float(p.precio_costo or 0.0),
        "precio_costo": float(p.precio_costo or 0.0),
        "stock": st,
        "stock_total": st,
        "stock_bodega": sb,
        "stock_vitrina": sv,
        "stock_minimo_bodega": float(p.stock_minimo_bodega if p.stock_minimo_bodega is not None else 5.0),
        "stock_minimo_vitrina": float(p.stock_minimo_vitrina if p.stock_minimo_vitrina is not None else 3.0),
        "proveedor_id": p.proveedor_id,
        "proveedor_nombre": prov_map.get(p.proveedor_id) if p.proveedor_id else None,
        "precio_variable": 1 if p.precio_variable else 0,
        "porcentaje_comision": float(p.porcentaje_comision or 0.0),
        "descripcion": p.descripcion or "",
        "estado": p.estado or "Activo",
        "fecha_creacion": _fmt_dt(p.created_at),
        "fecha_modificacion": _fmt_dt(p.updated_at or p.created_at),
    }


def _servicio_a_catalogo(s: Servicio, prov_map: Dict[int, str], cat_map: Dict[int, str]) -> Dict[str, Any]:
    cat_nom = s.categoria or (cat_map.get(s.categoria_id, "Servicios") if s.categoria_id else "Servicios")
    return {
        "id": s.id,
        "codigo": s.codigo or "",
        "nombre": s.nombre or "",
        "tipo_producto": "Servicio",
        "categoria": cat_nom or "Servicios",
        "categoria_id": s.categoria_id,
        "marca": s.marca or "",
        "codigo_barras": s.codigo_barras or "",
        "unidad_medida": s.unidad_medida or "Servicio",
        "precio": float(s.precio_venta or 0.0),
        "precio_venta": float(s.precio_venta or 0.0),
        "costo": float(s.costo_proveedor or 0.0),
        "precio_costo": float(s.costo_proveedor or 0.0),
        "stock": 0.0,
        "stock_bodega": 0.0,
        "stock_vitrina": 0.0,
        "stock_minimo_bodega": 0.0,
        "stock_minimo_vitrina": 0.0,
        "proveedor_id": s.proveedor_id,
        "proveedor_nombre": prov_map.get(s.proveedor_id) if s.proveedor_id else None,
        "precio_variable": 1 if s.precio_variable else 0,
        "porcentaje_comision": float(s.porcentaje_comision or 0.0),
        "descripcion": s.descripcion or "",
        "estado": s.estado or "Activo",
        "solo_operarios": bool(s.solo_operarios),
        "creado_por_operario_id": s.creado_por_operario_id,
        "fecha_creacion": _fmt_dt(s.created_at),
        "fecha_modificacion": _fmt_dt(s.updated_at or s.created_at),
    }


@router.get("/catalogo")
async def obtener_catalogo_endpoint(
    filtro: Optional[str] = None,
    categoria: Optional[str] = None,
    tipo: Optional[str] = None,
    solo_activos: bool = False,
    proveedor_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    prov_res = await db.execute(select(Proveedor))
    prov_map = {p.id: p.nombre for p in prov_res.scalars().all()}
    cat_res = await db.execute(select(Categoria))
    cat_map = {c.id: c.nombre for c in cat_res.scalars().all()}

    rol_norm = (current_user.rol or "").strip().lower()
    items: List[Dict[str, Any]] = []

    if not tipo or tipo in ("Todos", "Fisico", "Producto"):
        q_prod = select(Producto)
        if solo_activos:
            q_prod = q_prod.where(Producto.estado == "Activo")
        res_p = await db.execute(q_prod)
        for p in res_p.scalars().all():
            items.append(_producto_a_catalogo(p, prov_map, cat_map))

    if not tipo or tipo in ("Todos", "Servicio"):
        q_serv = select(Servicio)
        if solo_activos:
            q_serv = q_serv.where(Servicio.estado == "Activo")
        if rol_norm == "operario":
            q_serv = q_serv.where(
                or_(
                    Servicio.creado_por_operario_id.is_(None),
                    Servicio.creado_por_operario_id == current_user.id,
                )
            )
        res_s = await db.execute(q_serv)
        for s in res_s.scalars().all():
            items.append(_servicio_a_catalogo(s, prov_map, cat_map))

    if categoria and categoria != "Todas":
        cat_q = categoria.strip().lower()
        items = [it for it in items if (it.get("categoria") or "").strip().lower() == cat_q]

    if proveedor_id is not None:
        items = [it for it in items if it.get("proveedor_id") == int(proveedor_id)]

    if filtro and filtro.strip():
        t_q = filtro.strip().lower()
        items = [
            it
            for it in items
            if t_q in (it.get("codigo") or "").lower()
            or t_q in (it.get("nombre") or "").lower()
            or t_q in (it.get("codigo_barras") or "").lower()
        ]

    items.sort(key=lambda x: (x.get("nombre") or "").lower())
    return items


@router.get("/sugerir-codigo")
async def sugerir_codigo_endpoint(
    tipo: str = "Fisico",
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    res_p = await db.execute(select(Producto.codigo))
    res_s = await db.execute(select(Servicio.codigo))
    codigos = [c for c in list(res_p.scalars().all()) + list(res_s.scalars().all()) if c]
    prefix = "S" if (tipo or "").strip() == "Servicio" else ""
    max_num = 0
    for c in codigos:
        c_str = str(c).strip()
        if prefix and c_str.upper().startswith(prefix):
            num_part = c_str[len(prefix) :]
            if num_part.isdigit():
                max_num = max(max_num, int(num_part))
        elif not prefix and c_str.isdigit():
            max_num = max(max_num, int(c_str))
    sugerido = f"{prefix}{max_num + 1:05d}" if prefix else f"{max_num + 1:05d}"
    return {"codigo": sugerido}


@router.get("/articulo/{codigo}")
async def obtener_articulo_por_codigo_endpoint(
    codigo: str,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    cod_clean = str(codigo or "").strip()
    prov_res = await db.execute(select(Proveedor))
    prov_map = {p.id: p.nombre for p in prov_res.scalars().all()}
    cat_res = await db.execute(select(Categoria))
    cat_map = {c.id: c.nombre for c in cat_res.scalars().all()}

    res_p = await db.execute(
        select(Producto).where(
            or_(
                Producto.codigo == cod_clean,
                Producto.codigo == cod_clean.zfill(5),
                Producto.codigo_barras == cod_clean,
            )
        )
    )
    prod = res_p.scalars().first()
    if prod:
        return _producto_a_catalogo(prod, prov_map, cat_map)

    res_s = await db.execute(
        select(Servicio).where(
            or_(
                Servicio.codigo == cod_clean,
                Servicio.codigo_barras == cod_clean,
            )
        )
    )
    serv = res_s.scalars().first()
    if serv:
        return _servicio_a_catalogo(serv, prov_map, cat_map)

    raise HTTPException(status_code=404, detail=f"Artículo '{cod_clean}' no encontrado")


@router.get("/existe-codigo-barras")
async def existe_codigo_barras_endpoint(
    codigo_barras: str,
    excluir_id: Optional[int] = None,
    excluir_codigo: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    cb = (codigo_barras or "").strip()
    if not cb:
        return {"existe": False}
    q_p = select(Producto).where(Producto.codigo_barras == cb)
    if excluir_id is not None:
        q_p = q_p.where(Producto.id != excluir_id)
    if excluir_codigo:
        q_p = q_p.where(Producto.codigo != excluir_codigo)
    r_p = await db.execute(q_p)
    if r_p.scalars().first():
        return {"existe": True}
    q_s = select(Servicio).where(Servicio.codigo_barras == cb)
    if excluir_codigo:
        q_s = q_s.where(Servicio.codigo != excluir_codigo)
    r_s = await db.execute(q_s)
    return {"existe": r_s.scalars().first() is not None}


@router.post("/articulo")
async def crear_articulo_endpoint(
    datos: ArticuloCatalogoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    codigo = str(datos.codigo or "").strip()
    nombre = str(datos.nombre or "").strip()
    tipo = str(datos.tipo_producto or "Fisico").strip()
    if not codigo:
        raise HTTPException(status_code=400, detail="El código SKU es obligatorio.")
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre del artículo es obligatorio.")
    if tipo != "Servicio" and float(datos.precio or 0.0) < 0:
        raise HTTPException(status_code=400, detail="El precio de venta no puede ser negativo.")

    # Unicidad global de SKU entre Productos y Servicios
    dup_p = await db.execute(select(Producto.id).where(Producto.codigo == codigo))
    dup_s = await db.execute(select(Servicio.id).where(Servicio.codigo == codigo))
    if dup_p.scalars().first() or dup_s.scalars().first():
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe un artículo con el código '{codigo}'. Los códigos deben ser únicos.",
        )

    cb_clean = (datos.codigo_barras or "").strip() or None
    if cb_clean:
        dup_cb_p = await db.execute(select(Producto.id).where(Producto.codigo_barras == cb_clean))
        dup_cb_s = await db.execute(select(Servicio.id).where(Servicio.codigo_barras == cb_clean))
        if dup_cb_p.scalars().first() or dup_cb_s.scalars().first():
            raise HTTPException(
                status_code=409,
                detail=f"El código de barras '{cb_clean}' ya está asignado a otro artículo.",
            )

    cat_nom = (datos.categoria or ("Servicios" if tipo == "Servicio" else "General")).strip()
    cat_id = await _asegurar_categoria(db, cat_nom, "Servicio" if tipo == "Servicio" else "Producto")
    pct_com = max(0.0, min(100.0, float(datos.porcentaje_comision or 0.0)))
    usuario_nom = (f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario)
    ahora = datetime.now()
    f_str = ahora.strftime("%Y-%m-%d")
    h_str = ahora.strftime("%H:%M:%S")

    if tipo == "Servicio":
        rol_norm = (current_user.rol or "").strip().lower()
        nuevo_serv = Servicio(
            codigo=codigo,
            nombre=nombre,
            descripcion=datos.descripcion or "",
            categoria_id=cat_id,
            categoria=cat_nom,
            marca=datos.marca or "",
            codigo_barras=cb_clean,
            unidad_medida=datos.unidad_medida or "Servicio",
            precio_venta=float(datos.precio or 0.0),
            tipo_servicio="Proveedor" if datos.proveedor_id else "Interno",
            proveedor_id=datos.proveedor_id,
            costo_proveedor=float(datos.costo or 0.0),
            porcentaje_comision=pct_com,
            genera_comision=(datos.proveedor_id is None),
            precio_variable=bool(datos.precio_variable),
            solo_operarios=(rol_norm == "operario"),
            creado_por_operario_id=(current_user.id if rol_norm == "operario" else None),
            estado=datos.estado or "Activo",
        )
        db.add(nuevo_serv)
        await db.commit()
        await db.refresh(nuevo_serv)
        await log_audit(
            db,
            current_user.id,
            usuario_nom,
            None,
            None,
            "CREAR",
            "SERVICIOS",
            "servicios",
            str(nuevo_serv.id),
            valor_nuevo=datos.model_dump(),
        )
        return {"id": nuevo_serv.id, "codigo": nuevo_serv.codigo, "nombre": nuevo_serv.nombre, "tipo_producto": "Servicio"}

    sb = max(0.0, float(datos.stock_bodega or 0.0))
    sv = max(0.0, float(datos.stock_vitrina or 0.0))
    st_tot = round(sb + sv, 4)
    costo_val = max(0.0, float(datos.costo or 0.0))
    unidad_med = (datos.unidad_medida or "Unidad").strip() or "Unidad"

    nuevo_prod = Producto(
        codigo=codigo,
        nombre=nombre,
        descripcion=datos.descripcion or "",
        categoria_id=cat_id,
        categoria=cat_nom,
        marca=datos.marca or "",
        unidad_medida=unidad_med,
        precio_costo=costo_val,
        precio_venta=float(datos.precio or 0.0),
        stock=st_tot,
        stock_minimo=float(datos.stock_minimo_vitrina or 3.0),
        stock_bodega=sb,
        stock_vitrina=sv,
        stock_minimo_bodega=float(datos.stock_minimo_bodega if datos.stock_minimo_bodega is not None else 5.0),
        stock_minimo_vitrina=float(datos.stock_minimo_vitrina if datos.stock_minimo_vitrina is not None else 3.0),
        proveedor_id=datos.proveedor_id,
        codigo_barras=cb_clean,
        precio_variable=bool(datos.precio_variable),
        porcentaje_comision=pct_com,
        estado=datos.estado or "Activo",
    )
    db.add(nuevo_prod)
    await db.flush()

    if sb > 0:
        db.add(
            MovimientoInventario(
                fecha=f_str,
                hora=h_str,
                producto_id=nuevo_prod.id,
                codigo_producto=codigo,
                nombre_producto=nombre,
                tipo="ENTRADA_INICIAL",
                cantidad=sb,
                unidad_medida=unidad_med,
                ubicacion_origen="PROVEEDOR",
                ubicacion_destino="BODEGA",
                stock_anterior=0.0,
                stock_nuevo=sb,
                stock_origen_ant=0.0,
                stock_origen_des=0.0,
                stock_destino_ant=0.0,
                stock_destino_des=sb,
                costo_unitario=costo_val,
                valor_total=round(sb * costo_val, 2),
                referencia="ALTA-CATALOGO",
                usuario_id=current_user.id,
                usuario_nombre=usuario_nom,
                observacion="Stock inicial de apertura en Bodega",
                estado="Completado",
            )
        )
    if sv > 0:
        db.add(
            MovimientoInventario(
                fecha=f_str,
                hora=h_str,
                producto_id=nuevo_prod.id,
                codigo_producto=codigo,
                nombre_producto=nombre,
                tipo="ENTRADA_INICIAL",
                cantidad=sv,
                unidad_medida=unidad_med,
                ubicacion_origen="PROVEEDOR",
                ubicacion_destino="VITRINA",
                stock_anterior=sb,
                stock_nuevo=st_tot,
                stock_origen_ant=0.0,
                stock_origen_des=0.0,
                stock_destino_ant=0.0,
                stock_destino_des=sv,
                costo_unitario=costo_val,
                valor_total=round(sv * costo_val, 2),
                referencia="ALTA-CATALOGO",
                usuario_id=current_user.id,
                usuario_nombre=usuario_nom,
                observacion="Stock inicial de apertura en Vitrina",
                estado="Completado",
            )
        )

    await db.commit()
    await db.refresh(nuevo_prod)
    await log_audit(
        db,
        current_user.id,
        usuario_nom,
        None,
        None,
        "CREAR",
        "PRODUCTOS",
        "productos",
        str(nuevo_prod.id),
        valor_nuevo=datos.model_dump(),
    )
    return {"id": nuevo_prod.id, "codigo": nuevo_prod.codigo, "nombre": nuevo_prod.nombre, "tipo_producto": "Fisico"}


async def _resolver_articulo_existente(db: AsyncSession, id_o_codigo: str, tipo_hint: Optional[str] = None):
    key = str(id_o_codigo or "").strip()
    # Primero por código exacto (inequívoco entre productos y servicios)
    r_p_cod = await db.execute(select(Producto).where(Producto.codigo == key))
    p_cod = r_p_cod.scalars().first()
    if p_cod:
        return "Fisico", p_cod

    r_s_cod = await db.execute(select(Servicio).where(Servicio.codigo == key))
    s_cod = r_s_cod.scalars().first()
    if s_cod:
        return "Servicio", s_cod

    # Si es numérico y no coincidió con SKU exacto, buscar por ID según tipo_hint
    if key.isdigit():
        num_id = int(key)
        if tipo_hint == "Servicio":
            r_s = await db.execute(select(Servicio).where(Servicio.id == num_id))
            s_obj = r_s.scalars().first()
            if s_obj:
                return "Servicio", s_obj
        r_p = await db.execute(select(Producto).where(Producto.id == num_id))
        p_obj = r_p.scalars().first()
        if p_obj:
            return "Fisico", p_obj
        r_s2 = await db.execute(select(Servicio).where(Servicio.id == num_id))
        s_obj2 = r_s2.scalars().first()
        if s_obj2:
            return "Servicio", s_obj2

    return None, None


@router.put("/articulo/{id_o_codigo}")
async def actualizar_articulo_endpoint(
    id_o_codigo: str,
    datos: ArticuloCatalogoUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    cambios = datos.model_dump(exclude_unset=True)
    tipo_actual, obj = await _resolver_articulo_existente(db, id_o_codigo, cambios.get("tipo_producto"))
    if not obj:
        raise HTTPException(status_code=404, detail=f"Artículo '{id_o_codigo}' no encontrado.")

    usuario_nom = (f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario)

    if "codigo_barras" in cambios and cambios["codigo_barras"]:
        cb_new = str(cambios["codigo_barras"]).strip()
        q_p = select(Producto.id).where(Producto.codigo_barras == cb_new)
        q_s = select(Servicio.id).where(Servicio.codigo_barras == cb_new)
        if tipo_actual == "Fisico":
            q_p = q_p.where(Producto.id != obj.id)
        else:
            q_s = q_s.where(Servicio.id != obj.id)
        if (await db.execute(q_p)).scalars().first() or (await db.execute(q_s)).scalars().first():
            raise HTTPException(status_code=409, detail=f"El código de barras '{cb_new}' ya está en uso.")

    if tipo_actual == "Fisico":
        if "nombre" in cambios and cambios["nombre"] is not None:
            obj.nombre = cambios["nombre"].strip()
        if "precio" in cambios and cambios["precio"] is not None:
            obj.precio_venta = float(cambios["precio"])
        if "costo" in cambios and cambios["costo"] is not None:
            obj.precio_costo = float(cambios["costo"])
        if "categoria" in cambios and cambios["categoria"] is not None:
            cat_nom = cambios["categoria"].strip() or "General"
            obj.categoria = cat_nom
            obj.categoria_id = await _asegurar_categoria(db, cat_nom, "Producto")
        if "marca" in cambios and cambios["marca"] is not None:
            obj.marca = cambios["marca"].strip()
        if "codigo_barras" in cambios:
            obj.codigo_barras = (cambios["codigo_barras"] or "").strip() or None
        if "unidad_medida" in cambios and cambios["unidad_medida"] is not None:
            obj.unidad_medida = cambios["unidad_medida"].strip() or "Unidad"
        if "descripcion" in cambios and cambios["descripcion"] is not None:
            obj.descripcion = cambios["descripcion"].strip()
        if "proveedor_id" in cambios:
            obj.proveedor_id = cambios["proveedor_id"]
        if "estado" in cambios and cambios["estado"] is not None:
            obj.estado = cambios["estado"].strip()
        if "stock_minimo_bodega" in cambios and cambios["stock_minimo_bodega"] is not None:
            obj.stock_minimo_bodega = float(cambios["stock_minimo_bodega"])
        if "stock_minimo_vitrina" in cambios and cambios["stock_minimo_vitrina"] is not None:
            obj.stock_minimo_vitrina = float(cambios["stock_minimo_vitrina"])
            obj.stock_minimo = float(cambios["stock_minimo_vitrina"])
        if "precio_variable" in cambios and cambios["precio_variable"] is not None:
            obj.precio_variable = bool(cambios["precio_variable"])
        if "porcentaje_comision" in cambios and cambios["porcentaje_comision"] is not None:
            obj.porcentaje_comision = max(0.0, min(100.0, float(cambios["porcentaje_comision"])))

        await db.commit()
        await db.refresh(obj)
        await log_audit(
            db, current_user.id, usuario_nom, None, None, "EDITAR", "PRODUCTOS", "productos", str(obj.id), valor_nuevo=cambios
        )
        return {"ok": True, "id": obj.id, "codigo": obj.codigo, "nombre": obj.nombre}

    else:
        if "nombre" in cambios and cambios["nombre"] is not None:
            obj.nombre = cambios["nombre"].strip()
        if "precio" in cambios and cambios["precio"] is not None:
            obj.precio_venta = float(cambios["precio"])
        if "costo" in cambios and cambios["costo"] is not None:
            obj.costo_proveedor = float(cambios["costo"])
        if "categoria" in cambios and cambios["categoria"] is not None:
            cat_nom = cambios["categoria"].strip() or "Servicios"
            obj.categoria = cat_nom
            obj.categoria_id = await _asegurar_categoria(db, cat_nom, "Servicio")
        if "marca" in cambios and cambios["marca"] is not None:
            obj.marca = cambios["marca"].strip()
        if "codigo_barras" in cambios:
            obj.codigo_barras = (cambios["codigo_barras"] or "").strip() or None
        if "unidad_medida" in cambios and cambios["unidad_medida"] is not None:
            obj.unidad_medida = cambios["unidad_medida"].strip() or "Servicio"
        if "descripcion" in cambios and cambios["descripcion"] is not None:
            obj.descripcion = cambios["descripcion"].strip()
        if "proveedor_id" in cambios:
            obj.proveedor_id = cambios["proveedor_id"]
            obj.tipo_servicio = "Proveedor" if cambios["proveedor_id"] else "Interno"
        if "estado" in cambios and cambios["estado"] is not None:
            obj.estado = cambios["estado"].strip()
        if "precio_variable" in cambios and cambios["precio_variable"] is not None:
            obj.precio_variable = bool(cambios["precio_variable"])
        if "porcentaje_comision" in cambios and cambios["porcentaje_comision"] is not None:
            obj.porcentaje_comision = max(0.0, min(100.0, float(cambios["porcentaje_comision"])))

        await db.commit()
        await db.refresh(obj)
        await log_audit(
            db, current_user.id, usuario_nom, None, None, "EDITAR", "SERVICIOS", "servicios", str(obj.id), valor_nuevo=cambios
        )
        return {"ok": True, "id": obj.id, "codigo": obj.codigo, "nombre": obj.nombre}


@router.patch("/articulo/{id_o_codigo}/estado")
async def cambiar_estado_articulo_endpoint(
    id_o_codigo: str,
    estado: str = Query(...),
    tipo_producto: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    tipo_actual, obj = await _resolver_articulo_existente(db, id_o_codigo, tipo_producto)
    if not obj:
        raise HTTPException(status_code=404, detail=f"Artículo '{id_o_codigo}' no encontrado.")
    obj.estado = estado
    await db.commit()
    return {"ok": True, "codigo": obj.codigo, "estado": obj.estado}


@router.get("/bodega")
async def obtener_bodega_endpoint(
    filtro: Optional[str] = None,
    categoria: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    catalogo = await obtener_catalogo_endpoint(
        filtro=filtro, categoria=categoria, tipo="Fisico", solo_activos=False, db=db, current_user=current_user
    )
    resultados = []
    for d in catalogo:
        sb = float(d["stock_bodega"])
        sm = float(d["stock_minimo_bodega"])
        costo = float(d["costo"])
        item = {
            "id": d["id"],
            "codigo": d["codigo"],
            "nombre": d["nombre"],
            "categoria": d["categoria"],
            "unidad_medida": d["unidad_medida"],
            "stock_bodega": sb,
            "stock_minimo_bodega": sm,
            "costo": costo,
            "valor_total_bodega": round(sb * costo, 2),
            "proveedor_nombre": d["proveedor_nombre"],
            "estado": d["estado"],
        }
        if sb <= 0:
            item["alerta_bodega"] = "Agotado en Bodega"
            item["badge_color"] = "#EF4444"
        elif sb <= sm:
            item["alerta_bodega"] = "Stock Bajo Bodega"
            item["badge_color"] = "#F59E0B"
        else:
            item["alerta_bodega"] = "Normal"
            item["badge_color"] = "#10B981"
        resultados.append(item)
    return resultados


@router.get("/vitrina")
async def obtener_vitrina_endpoint(
    filtro: Optional[str] = None,
    categoria: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    catalogo = await obtener_catalogo_endpoint(
        filtro=filtro, categoria=categoria, tipo="Fisico", solo_activos=False, db=db, current_user=current_user
    )
    resultados = []
    for d in catalogo:
        sv = float(d["stock_vitrina"])
        sm = float(d["stock_minimo_vitrina"])
        sb = float(d["stock_bodega"])
        precio = float(d["precio"])
        costo = float(d["costo"])
        item = {
            "id": d["id"],
            "codigo": d["codigo"],
            "nombre": d["nombre"],
            "categoria": d["categoria"],
            "unidad_medida": d["unidad_medida"],
            "stock_vitrina": sv,
            "stock_minimo_vitrina": sm,
            "stock_bodega": sb,
            "precio": precio,
            "costo": costo,
            "valor_venta_vitrina": round(sv * precio, 2),
            "estado": d["estado"],
        }
        if sv <= 0:
            if sb > 0:
                item["alerta_vitrina"] = "Agotado (Hay en Bodega)"
                item["badge_color"] = "#3B82F6"
            else:
                item["alerta_vitrina"] = "Agotado Global"
                item["badge_color"] = "#EF4444"
        elif sv <= sm:
            item["alerta_vitrina"] = "Reponer Vitrina"
            item["badge_color"] = "#F59E0B"
        else:
            item["alerta_vitrina"] = "Disponible"
            item["badge_color"] = "#10B981"
        resultados.append(item)
    return resultados


@router.post("/traslados")
async def ejecutar_traslado_endpoint(
    req: TrasladoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    origen = str(req.origen or "").strip().upper()
    destino = str(req.destino or "").strip().upper()
    if origen not in ("BODEGA", "VITRINA") or destino not in ("BODEGA", "VITRINA"):
        raise HTTPException(status_code=400, detail="Las ubicaciones deben ser BODEGA o VITRINA.")
    if origen == destino:
        raise HTTPException(status_code=400, detail="La ubicación de origen y destino deben ser diferentes.")

    cant_float = float(req.cantidad or 0.0)
    if cant_float <= 0:
        raise HTTPException(status_code=400, detail="La cantidad a trasladar debe ser mayor que cero.")

    key = str(req.codigo_o_id or "").strip()
    q_prod = select(Producto).with_for_update().where(
        or_(
            Producto.codigo == key,
            Producto.codigo == key.zfill(5),
            Producto.codigo_barras == key,
        )
    )
    prod = (await db.execute(q_prod)).scalars().first()
    if not prod and key.isdigit():
        prod = (await db.execute(select(Producto).with_for_update().where(Producto.id == int(key)))).scalars().first()
    if not prod:
        raise HTTPException(status_code=404, detail=f"No se encontró el producto físico '{key}'.")

    unidad = prod.unidad_medida or "Unidad"
    _validar_cantidad_unidad(unidad, cant_float)

    sb_ant = float(prod.stock_bodega or 0.0)
    sv_ant = float(prod.stock_vitrina or 0.0)
    st_ant = float(prod.stock or 0.0)
    if sb_ant == 0.0 and sv_ant == 0.0 and st_ant > 0.0:
        sv_ant = st_ant

    if origen == "BODEGA":
        if sb_ant + 1e-6 < cant_float:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Existencias insuficientes en Bodega para '{prod.nombre}'. "
                    f"Disponible: {sb_ant:g} {unidad}, Solicitado: {cant_float:g} {unidad}."
                ),
            )
        sb_des = round(sb_ant - cant_float, 4)
        sv_des = round(sv_ant + cant_float, 4)
        st_orig_ant, st_orig_des = sb_ant, sb_des
        st_dest_ant, st_dest_des = sv_ant, sv_des
        tipo_mov = "TRASLADO_BODEGA_A_VITRINA"
    else:
        if sv_ant + 1e-6 < cant_float:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Existencias insuficientes en Vitrina para '{prod.nombre}'. "
                    f"Disponible: {sv_ant:g} {unidad}, Solicitado: {cant_float:g} {unidad}."
                ),
            )
        sv_des = round(sv_ant - cant_float, 4)
        sb_des = round(sb_ant + cant_float, 4)
        st_orig_ant, st_orig_des = sv_ant, sv_des
        st_dest_ant, st_dest_des = sb_ant, sb_des
        tipo_mov = "TRASLADO_VITRINA_A_BODEGA"

    cnt_res = await db.execute(select(func.count(TrasladoInventario.id)))
    total_tr = int(cnt_res.scalar() or 0)
    num_traslado = f"TR-{total_tr + 1:05d}"

    ahora = datetime.now()
    f_str = ahora.strftime("%Y-%m-%d")
    h_str = ahora.strftime("%H:%M:%S")
    usuario_nom = req.usuario or (f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario)
    st_nuevo = round(sb_des + sv_des, 4)
    costo_u = float(prod.precio_costo or 0.0)

    prod.stock_bodega = sb_des
    prod.stock_vitrina = sv_des
    prod.stock = st_nuevo

    db.add(
        TrasladoInventario(
            numero_traslado=num_traslado,
            fecha=f_str,
            hora=h_str,
            producto_id=prod.id,
            codigo_producto=prod.codigo or "",
            nombre_producto=prod.nombre or "",
            ubicacion_origen=origen,
            ubicacion_destino=destino,
            cantidad=cant_float,
            usuario=usuario_nom,
            estado="Completado",
            observaciones=req.observaciones or "",
        )
    )
    db.add(
        MovimientoInventario(
            fecha=f_str,
            hora=h_str,
            producto_id=prod.id,
            codigo_producto=prod.codigo,
            nombre_producto=prod.nombre,
            tipo=tipo_mov,
            cantidad=cant_float,
            unidad_medida=unidad,
            ubicacion_origen=origen,
            ubicacion_destino=destino,
            stock_anterior=st_nuevo,
            stock_nuevo=st_nuevo,
            stock_origen_ant=st_orig_ant,
            stock_origen_des=st_orig_des,
            stock_destino_ant=st_dest_ant,
            stock_destino_des=st_dest_des,
            costo_unitario=costo_u,
            valor_total=round(cant_float * costo_u, 2),
            referencia=num_traslado,
            usuario_id=current_user.id,
            usuario_nombre=usuario_nom,
            observacion=req.observaciones or f"Traslado de {cant_float:g} {unidad} de {origen} a {destino}",
            estado="Completado",
        )
    )
    await db.commit()
    return {
        "numero_traslado": num_traslado,
        "producto": prod.nombre,
        "codigo": prod.codigo,
        "origen": origen,
        "destino": destino,
        "cantidad": cant_float,
        "stock_bodega": sb_des,
        "stock_vitrina": sv_des,
        "stock_total": st_nuevo,
    }


@router.get("/traslados")
async def listar_traslados_endpoint(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    res = await db.execute(
        select(TrasladoInventario, Producto.unidad_medida, Producto.precio_costo)
        .outerjoin(Producto, TrasladoInventario.producto_id == Producto.id)
        .order_by(TrasladoInventario.id.desc())
        .limit(limit)
    )
    out = []
    for t, u_med, costo in res.all():
        out.append(
            {
                "id": t.id,
                "numero_traslado": t.numero_traslado,
                "fecha": t.fecha,
                "hora": t.hora,
                "producto_id": t.producto_id,
                "codigo_producto": t.codigo_producto,
                "nombre_producto": t.nombre_producto,
                "ubicacion_origen": t.ubicacion_origen,
                "ubicacion_destino": t.ubicacion_destino,
                "cantidad": float(t.cantidad or 0.0),
                "usuario": t.usuario,
                "estado": t.estado,
                "observaciones": t.observaciones or "",
                "unidad_medida": u_med or "Unidad",
                "costo": float(costo or 0.0),
            }
        )
    return out


@router.post("/ajustes")
async def registrar_ajuste_endpoint(
    req: AjusteInventarioCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    ubicacion = str(req.ubicacion or "").strip().upper()
    if ubicacion not in ("BODEGA", "VITRINA"):
        raise HTTPException(status_code=400, detail="La ubicación a ajustar debe ser BODEGA o VITRINA.")
    conteo_flt = float(req.conteo_fisico)
    if conteo_flt < 0:
        raise HTTPException(status_code=400, detail="El conteo físico no puede ser negativo.")

    key = str(req.codigo_o_id or "").strip()
    prod = (
        await db.execute(
            select(Producto).with_for_update().where(
                or_(
                    Producto.codigo == key,
                    Producto.codigo == key.zfill(5),
                    Producto.codigo_barras == key,
                )
            )
        )
    ).scalars().first()
    if not prod and key.isdigit():
        prod = (await db.execute(select(Producto).with_for_update().where(Producto.id == int(key)))).scalars().first()
    if not prod:
        raise HTTPException(status_code=404, detail=f"No se encontró el artículo físico '{key}'.")

    sb_ant = float(prod.stock_bodega or 0.0)
    sv_ant = float(prod.stock_vitrina or 0.0)
    st_ant = float(prod.stock or 0.0)
    if sb_ant == 0.0 and sv_ant == 0.0 and st_ant > 0.0:
        sv_ant = st_ant

    stock_actual_ub = sb_ant if ubicacion == "BODEGA" else sv_ant
    delta = round(conteo_flt - stock_actual_ub, 4)
    if abs(delta) < 0.0001:
        return {"mensaje": "El conteo físico coincide exactamente con el sistema. No se requirió ajuste."}

    tipo_mov = "AJUSTE_POSITIVO" if delta > 0 else "AJUSTE_NEGATIVO"
    cant_ajuste = abs(delta)
    if ubicacion == "BODEGA":
        sb_des = conteo_flt
        sv_des = sv_ant
    else:
        sb_des = sb_ant
        sv_des = conteo_flt

    st_nuevo = round(sb_des + sv_des, 4)
    prod.stock_bodega = sb_des
    prod.stock_vitrina = sv_des
    prod.stock = st_nuevo

    ahora = datetime.now()
    f_str = ahora.strftime("%Y-%m-%d")
    h_str = ahora.strftime("%H:%M:%S")
    usuario_nom = req.usuario or (f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario)
    unidad = prod.unidad_medida or "Unidad"
    costo_u = float(prod.precio_costo or 0.0)

    db.add(
        MovimientoInventario(
            fecha=f_str,
            hora=h_str,
            producto_id=prod.id,
            codigo_producto=prod.codigo,
            nombre_producto=prod.nombre,
            tipo=tipo_mov,
            cantidad=cant_ajuste,
            unidad_medida=unidad,
            ubicacion_origen=ubicacion if delta < 0 else "NINGUNA",
            ubicacion_destino=ubicacion if delta > 0 else "NINGUNA",
            stock_anterior=sb_ant + sv_ant,
            stock_nuevo=st_nuevo,
            stock_origen_ant=stock_actual_ub,
            stock_origen_des=conteo_flt,
            stock_destino_ant=stock_actual_ub,
            stock_destino_des=conteo_flt,
            costo_unitario=costo_u,
            valor_total=round(cant_ajuste * costo_u, 2),
            referencia="AJUSTE-FISICO",
            usuario_id=current_user.id,
            usuario_nombre=usuario_nom,
            observacion=req.motivo or f"Ajuste en {ubicacion}: {stock_actual_ub:g} -> {conteo_flt:g} {unidad}",
            estado="Completado",
        )
    )
    await db.commit()
    return {
        "producto": prod.nombre,
        "ubicacion": ubicacion,
        "stock_anterior": stock_actual_ub,
        "stock_nuevo": conteo_flt,
        "diferencia": delta,
        "tipo_ajuste": tipo_mov,
    }


async def _generar_numero_compra_central(db: AsyncSession) -> str:
    res = await db.execute(select(CompraInventario.numero_compra))
    max_n = 0
    for nc in res.scalars().all():
        if nc and str(nc).startswith("CMP-"):
            part = str(nc).split("-")[1]
            if part.isdigit():
                max_n = max(max_n, int(part))
    res_m = await db.execute(select(MovimientoInventario.referencia).where(MovimientoInventario.referencia.like("CMP-%")))
    for ref in res_m.scalars().all():
        if ref and "-" in str(ref):
            part = str(ref).split("-")[1]
            if part.isdigit():
                max_n = max(max_n, int(part))
    return f"CMP-{max_n + 1:05d}"


async def _aplicar_items_compra_central(
    db: AsyncSession,
    compra_id: int,
    num_compra: str,
    items: list,
    ubicacion_destino: str,
    usuario_id: int,
    usuario_nom: str,
    f_str: str,
    h_str: str,
    etiqueta: str = "Entrada por compra",
) -> float:
    total_compra = 0.0
    for it in items:
        cod = str(it.codigo or "").strip()
        prod = None
        if cod:
            prod = (
                await db.execute(
                    select(Producto).with_for_update().where(or_(Producto.codigo == cod, Producto.codigo == cod.zfill(5)))
                )
            ).scalars().first()
        if not prod and it.producto_id:
            prod = (await db.execute(select(Producto).with_for_update().where(Producto.id == int(it.producto_id)))).scalars().first()
        if not prod:
            raise HTTPException(status_code=404, detail=f"Artículo físico '{cod}' no encontrado en el catálogo central.")

        unidad_base = prod.unidad_medida or "Unidad"
        costo_ant = float(prod.precio_costo or 0.0)
        sb_ant = float(prod.stock_bodega or 0.0)
        sv_ant = float(prod.stock_vitrina or 0.0)
        st_ant = sb_ant + sv_ant

        unidad_compra = (it.unidad_compra or unidad_base).strip()
        factor = float(it.factor_conversion or 1.0)
        if factor <= 0:
            factor = 1.0
        cant_comprada = float(it.cantidad_comprada or 0.0)
        costo_pres = float(it.costo_unidad_compra or 0.0)
        if cant_comprada <= 0 or costo_pres <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"La cantidad y el costo de '{prod.nombre}' deben ser mayores a cero.",
            )

        unidades_reales = round(cant_comprada * factor, 4)
        costo_unit_conv = round(costo_pres / factor, 4)
        subtotal_item = round(cant_comprada * costo_pres, 2)
        total_compra = round(total_compra + subtotal_item, 2)

        db.add(
            DetalleCompra(
                compra_id=compra_id,
                producto_id=prod.id,
                codigo_producto=prod.codigo or cod,
                nombre_producto=prod.nombre or "",
                unidad_compra=unidad_compra,
                factor_conversion=factor,
                cantidad_comprada=cant_comprada,
                cantidad_unidades=unidades_reales,
                costo_unidad_compra=costo_pres,
                costo_unitario_convertido=costo_unit_conv,
                subtotal=subtotal_item,
            )
        )

        if ubicacion_destino == "BODEGA":
            sb_des = round(sb_ant + unidades_reales, 4)
            sv_des = sv_ant
            st_dest_ant, st_dest_des = sb_ant, sb_des
        else:
            sb_des = sb_ant
            sv_des = round(sv_ant + unidades_reales, 4)
            st_dest_ant, st_dest_des = sv_ant, sv_des

        nuevo_total = round(sb_des + sv_des, 4)
        if nuevo_total > 0 and costo_unit_conv > 0:
            costo_pond = round(((st_ant * costo_ant) + (unidades_reales * costo_unit_conv)) / nuevo_total, 4)
        else:
            costo_pond = costo_unit_conv or costo_ant

        prod.stock_bodega = sb_des
        prod.stock_vitrina = sv_des
        prod.stock = nuevo_total
        prod.precio_costo = costo_pond

        db.add(
            MovimientoInventario(
                fecha=f_str,
                hora=h_str,
                producto_id=prod.id,
                codigo_producto=prod.codigo,
                nombre_producto=prod.nombre,
                tipo="ENTRADA_COMPRA",
                cantidad=unidades_reales,
                unidad_medida=unidad_base,
                ubicacion_origen="PROVEEDOR",
                ubicacion_destino=ubicacion_destino,
                stock_anterior=st_ant,
                stock_nuevo=nuevo_total,
                stock_origen_ant=0.0,
                stock_origen_des=0.0,
                stock_destino_ant=st_dest_ant,
                stock_destino_des=st_dest_des,
                costo_unitario=costo_unit_conv,
                valor_total=subtotal_item,
                referencia=num_compra,
                usuario_id=usuario_id,
                usuario_nombre=usuario_nom,
                observacion=f"{etiqueta} {num_compra} ({cant_comprada:g} {unidad_compra} x {factor:g} = {unidades_reales:g} {unidad_base})",
                estado="Completado",
            )
        )
    return total_compra


async def _revertir_items_compra_central(
    db: AsyncSession,
    compra_id: int,
    num_compra: str,
    ubicacion_destino: str,
    usuario_id: int,
    usuario_nom: str,
    f_str: str,
    h_str: str,
    motivo: str = "Reversión de compra",
):
    det_res = await db.execute(select(DetalleCompra).where(DetalleCompra.compra_id == compra_id))
    for det in det_res.scalars().all():
        prod = (
            await db.execute(select(Producto).with_for_update().where(Producto.id == det.producto_id))
        ).scalars().first()
        if not prod:
            continue
        unidades = float(det.cantidad_unidades or 0.0)
        costo_u_compra = float(det.costo_unitario_convertido or 0.0)
        subtotal = float(det.subtotal or 0.0)
        unidad_base = prod.unidad_medida or "Unidad"
        costo_act = float(prod.precio_costo or 0.0)
        sb_ant = float(prod.stock_bodega or 0.0)
        sv_ant = float(prod.stock_vitrina or 0.0)
        st_ant = sb_ant + sv_ant

        disponible = sb_ant if ubicacion_destino == "BODEGA" else sv_ant
        if disponible + 1e-6 < unidades:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"No se puede modificar/eliminar la compra {num_compra}: el artículo '{det.nombre_producto}' "
                    f"solo tiene {disponible:g} {unidad_base} en {ubicacion_destino} y la compra ingresó {unidades:g}."
                ),
            )

        if ubicacion_destino == "BODEGA":
            sb_des, sv_des = round(sb_ant - unidades, 4), sv_ant
            st_ub_ant, st_ub_des = sb_ant, sb_des
        else:
            sb_des, sv_des = sb_ant, round(sv_ant - unidades, 4)
            st_ub_ant, st_ub_des = sv_ant, sv_des

        nuevo_total = round(sb_des + sv_des, 4)
        if nuevo_total > 1e-9:
            costo_rev = round(((st_ant * costo_act) - (unidades * costo_u_compra)) / nuevo_total, 4)
            if costo_rev <= 0:
                costo_rev = costo_act
        else:
            costo_rev = costo_act

        prod.stock_bodega = sb_des
        prod.stock_vitrina = sv_des
        prod.stock = nuevo_total
        prod.precio_costo = costo_rev

        db.add(
            MovimientoInventario(
                fecha=f_str,
                hora=h_str,
                producto_id=prod.id,
                codigo_producto=prod.codigo,
                nombre_producto=prod.nombre,
                tipo="REVERSION_COMPRA",
                cantidad=unidades,
                unidad_medida=unidad_base,
                ubicacion_origen=ubicacion_destino,
                ubicacion_destino="PROVEEDOR",
                stock_anterior=st_ant,
                stock_nuevo=nuevo_total,
                stock_origen_ant=st_ub_ant,
                stock_origen_des=st_ub_des,
                stock_destino_ant=0.0,
                stock_destino_des=0.0,
                costo_unitario=costo_u_compra,
                valor_total=subtotal,
                referencia=num_compra,
                usuario_id=usuario_id,
                usuario_nombre=usuario_nom,
                observacion=f"{motivo} {num_compra} (-{unidades:g} {unidad_base} de {ubicacion_destino})",
                estado="Completado",
            )
        )


@router.post("/compras")
async def registrar_compra_endpoint(
    req: CompraCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    if not req.items:
        raise HTTPException(status_code=400, detail="Debe incluir al menos un artículo en la entrada de mercancía.")
    ubic = (req.ubicacion_destino or "BODEGA").strip().upper()
    if ubic not in ("BODEGA", "VITRINA"):
        ubic = "BODEGA"

    ahora = datetime.now()
    f_str = ahora.strftime("%Y-%m-%d")
    h_str = ahora.strftime("%H:%M:%S")
    usuario_nom = req.usuario or (f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario)
    num_compra = await _generar_numero_compra_central(db)

    compra = CompraInventario(
        numero_compra=num_compra,
        fecha=f_str,
        hora=h_str,
        proveedor_id=req.proveedor_id,
        proveedor_nombre=req.proveedor_nombre or "Sin Proveedor",
        documento_referencia=req.doc_referencia or "",
        ubicacion_destino=ubic,
        total_compra=0.0,
        usuario=usuario_nom,
        observaciones=req.observaciones or "",
        estado="Recibida",
    )
    db.add(compra)
    await db.flush()

    total_compra = await _aplicar_items_compra_central(
        db, compra.id, num_compra, req.items, ubic, current_user.id, usuario_nom, f_str, h_str
    )
    compra.total_compra = total_compra
    await db.commit()
    return {"numero_compra": num_compra, "compra_id": compra.id, "total": total_compra}


@router.get("/compras")
async def listar_compras_endpoint(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    res = await db.execute(select(CompraInventario).order_by(CompraInventario.id.desc()).limit(limit))
    compras = res.scalars().all()
    out = []
    for c in compras:
        cnt_res = await db.execute(select(func.count(DetalleCompra.id)).where(DetalleCompra.compra_id == c.id))
        cant_items = int(cnt_res.scalar() or 0)
        out.append(
            {
                "id": c.id,
                "numero_compra": c.numero_compra,
                "fecha": c.fecha,
                "hora": c.hora,
                "proveedor_id": c.proveedor_id,
                "proveedor_nombre": c.proveedor_nombre or "Sin Proveedor",
                "documento_referencia": c.documento_referencia or "",
                "ubicacion_destino": c.ubicacion_destino,
                "total_compra": float(c.total_compra or 0.0),
                "cantidad_items": cant_items,
                "usuario": c.usuario,
                "observaciones": c.observaciones or "",
                "estado": c.estado,
            }
        )
    return out


@router.get("/compras/{compra_id}")
async def detalle_compra_endpoint(
    compra_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    c = (await db.execute(select(CompraInventario).where(CompraInventario.id == compra_id))).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Compra no encontrada")
    det_res = await db.execute(
        select(DetalleCompra).where(DetalleCompra.compra_id == compra_id).order_by(DetalleCompra.id.asc())
    )
    items = [
        {
            "id": d.id,
            "compra_id": d.compra_id,
            "producto_id": d.producto_id,
            "codigo_producto": d.codigo_producto,
            "nombre_producto": d.nombre_producto,
            "unidad_compra": d.unidad_compra,
            "factor_conversion": float(d.factor_conversion or 1.0),
            "cantidad_comprada": float(d.cantidad_comprada or 0.0),
            "cantidad_unidades": float(d.cantidad_unidades or 0.0),
            "costo_unidad_compra": float(d.costo_unidad_compra or 0.0),
            "costo_unitario_convertido": float(d.costo_unitario_convertido or 0.0),
            "subtotal": float(d.subtotal or 0.0),
        }
        for d in det_res.scalars().all()
    ]
    return {
        "id": c.id,
        "numero_compra": c.numero_compra,
        "fecha": c.fecha,
        "hora": c.hora,
        "proveedor_id": c.proveedor_id,
        "proveedor_nombre": c.proveedor_nombre or "",
        "documento_referencia": c.documento_referencia or "",
        "ubicacion_destino": c.ubicacion_destino,
        "total_compra": float(c.total_compra or 0.0),
        "usuario": c.usuario,
        "observaciones": c.observaciones or "",
        "estado": c.estado,
        "items": items,
    }


@router.put("/compras/{compra_id}")
async def editar_compra_endpoint(
    compra_id: int,
    req: CompraCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    if not req.items:
        raise HTTPException(status_code=400, detail="La compra debe tener al menos un artículo.")
    c = (await db.execute(select(CompraInventario).with_for_update().where(CompraInventario.id == compra_id))).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="La compra seleccionada ya no existe.")

    ahora = datetime.now()
    f_str = ahora.strftime("%Y-%m-%d")
    h_str = ahora.strftime("%H:%M:%S")
    usuario_nom = req.usuario or (f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario)
    ubic_nueva = (req.ubicacion_destino or "BODEGA").strip().upper()
    if ubic_nueva not in ("BODEGA", "VITRINA"):
        ubic_nueva = "BODEGA"

    await _revertir_items_compra_central(
        db, compra_id, c.numero_compra, (c.ubicacion_destino or "BODEGA").upper(),
        current_user.id, usuario_nom, f_str, h_str, motivo="Edición: reversión de"
    )
    await db.execute(delete(DetalleCompra).where(DetalleCompra.compra_id == compra_id))

    nuevo_total = await _aplicar_items_compra_central(
        db, compra_id, c.numero_compra, req.items, ubic_nueva,
        current_user.id, usuario_nom, f_str, h_str, etiqueta="Edición: nueva entrada de"
    )
    c.proveedor_id = req.proveedor_id
    c.proveedor_nombre = req.proveedor_nombre or "Sin Proveedor"
    c.documento_referencia = req.doc_referencia or ""
    c.ubicacion_destino = ubic_nueva
    c.total_compra = nuevo_total
    if req.observaciones is not None:
        c.observaciones = req.observaciones
    await db.commit()
    return {"numero_compra": c.numero_compra, "compra_id": c.id, "total": nuevo_total}


@router.delete("/compras/{compra_id}")
async def eliminar_compra_endpoint(
    compra_id: int,
    usuario: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    c = (await db.execute(select(CompraInventario).with_for_update().where(CompraInventario.id == compra_id))).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="La compra seleccionada ya no existe.")

    ahora = datetime.now()
    f_str = ahora.strftime("%Y-%m-%d")
    h_str = ahora.strftime("%H:%M:%S")
    usuario_nom = usuario or (f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario)
    num_compra = c.numero_compra

    await _revertir_items_compra_central(
        db, compra_id, num_compra, (c.ubicacion_destino or "BODEGA").upper(),
        current_user.id, usuario_nom, f_str, h_str, motivo="Eliminación de compra"
    )
    await db.execute(delete(DetalleCompra).where(DetalleCompra.compra_id == compra_id))
    await db.delete(c)
    await db.commit()
    return {"numero_compra": num_compra}


@router.get("/kardex")
async def obtener_kardex_endpoint(
    filtro_codigo: Optional[str] = None,
    tipo_movimiento: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    q = (
        select(
            MovimientoInventario,
            Producto.codigo,
            Producto.codigo_barras,
            Producto.nombre,
            Producto.categoria,
            Producto.unidad_medida,
        )
        .outerjoin(Producto, MovimientoInventario.producto_id == Producto.id)
        .order_by(MovimientoInventario.id.desc())
    )
    if tipo_movimiento and tipo_movimiento != "Todos":
        q = q.where(MovimientoInventario.tipo == tipo_movimiento)
    if fecha_inicio:
        q = q.where(MovimientoInventario.fecha >= fecha_inicio)
    if fecha_fin:
        q = q.where(MovimientoInventario.fecha <= fecha_fin)
    q = q.limit(limit * 2 if filtro_codigo else limit)

    res = await db.execute(q)
    out = []
    term = (filtro_codigo or "").strip().lower()
    for m, p_cod, p_bar, p_nom, p_cat, p_unid in res.all():
        cod_val = m.codigo_producto or p_cod or ""
        bar_val = p_bar or ""
        nom_val = m.nombre_producto or p_nom or ""
        ref_val = m.referencia or ""
        if term and (
            term not in cod_val.lower()
            and term not in bar_val.lower()
            and term not in nom_val.lower()
            and term not in ref_val.lower()
        ):
            continue
        f_val = m.fecha or (m.created_at.strftime("%Y-%m-%d") if m.created_at else "")
        h_val = m.hora or (m.created_at.strftime("%H:%M:%S") if m.created_at else "")
        out.append(
            {
                "id": m.id,
                "fecha": f_val,
                "hora": h_val,
                "producto_id": m.producto_id,
                "codigo_producto": cod_val,
                "nombre_producto": nom_val,
                "categoria": p_cat or "General",
                "tipo_movimiento": m.tipo,
                "cantidad": abs(float(m.cantidad or 0.0)),
                "unidad_medida": m.unidad_medida or p_unid or "Unidad",
                "ubicacion_origen": m.ubicacion_origen or ("VITRINA" if m.tipo == "VENTA" else "PROVEEDOR"),
                "ubicacion_destino": m.ubicacion_destino or ("CLIENTE" if m.tipo == "VENTA" else "VITRINA"),
                "stock_origen_ant": float(m.stock_origen_ant or m.stock_anterior or 0.0),
                "stock_origen_des": float(m.stock_origen_des or m.stock_nuevo or 0.0),
                "stock_destino_ant": float(m.stock_destino_ant or 0.0),
                "stock_destino_des": float(m.stock_destino_des or 0.0),
                "costo_unitario": float(m.costo_unitario or 0.0),
                "valor_total": float(m.valor_total or 0.0),
                "referencia": ref_val,
                "usuario": m.usuario_nombre or f"Usuario #{m.usuario_id or 1}",
                "observaciones": m.observacion or "",
                "estado": m.estado or "Completado",
            }
        )
        if len(out) >= limit:
            break
    return out


@router.get("/alertas")
async def obtener_alertas_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    catalogo = await obtener_catalogo_endpoint(tipo="Fisico", solo_activos=True, db=db, current_user=current_user)
    bajo_vitrina = []
    bajo_bodega = []
    agotados_globales = []
    for it in catalogo:
        sv = float(it["stock_vitrina"])
        sm_v = float(it["stock_minimo_vitrina"])
        sb = float(it["stock_bodega"])
        sm_b = float(it["stock_minimo_bodega"])
        st = float(it["stock"])
        row = {
            "codigo": it["codigo"],
            "nombre": it["nombre"],
            "categoria": it["categoria"],
            "stock_vitrina": sv,
            "stock_minimo_vitrina": sm_v,
            "stock_bodega": sb,
            "stock_minimo_bodega": sm_b,
            "stock": st,
            "unidad_medida": it["unidad_medida"],
        }
        if st <= 0:
            agotados_globales.append(row)
        else:
            if sv <= sm_v:
                bajo_vitrina.append(row)
            if sb <= sm_b:
                bajo_bodega.append(row)
    return {
        "bajo_vitrina": bajo_vitrina,
        "bajo_bodega": bajo_bodega,
        "agotados_globales": agotados_globales,
        "total_alertas": len(bajo_vitrina) + len(bajo_bodega) + len(agotados_globales),
    }


@router.get("/resumen-indicadores")
async def obtener_resumen_indicadores_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    catalogo = await obtener_catalogo_endpoint(solo_activos=True, db=db, current_user=current_user)
    fisicos = [it for it in catalogo if it["tipo_producto"] == "Fisico"]
    servicios = [it for it in catalogo if it["tipo_producto"] == "Servicio"]

    unid_bod = sum(float(it["stock_bodega"]) for it in fisicos)
    unid_vit = sum(float(it["stock_vitrina"]) for it in fisicos)
    unid_tot = sum(float(it["stock"]) for it in fisicos)
    val_bod_costo = sum(float(it["stock_bodega"]) * float(it["costo"]) for it in fisicos)
    val_vit_costo = sum(float(it["stock_vitrina"]) * float(it["costo"]) for it in fisicos)
    val_vit_venta = sum(float(it["stock_vitrina"]) * float(it["precio"]) for it in fisicos)
    val_inv_total = sum(float(it["stock"]) * float(it["costo"]) for it in fisicos)

    alertas = await obtener_alertas_endpoint(db=db, current_user=current_user)
    return {
        "total_articulos": len(catalogo),
        "total_fisicos": len(fisicos),
        "total_servicios": len(servicios),
        "unidades_bodega": round(unid_bod, 4),
        "unidades_vitrina": round(unid_vit, 4),
        "unidades_totales": round(unid_tot, 4),
        "valor_bodega_costo": round(val_bod_costo, 2),
        "valor_vitrina_costo": round(val_vit_costo, 2),
        "valor_vitrina_venta": round(val_vit_venta, 2),
        "valor_inventario_total": round(val_inv_total, 2),
        "alertas_bajo_vitrina": len(alertas["bajo_vitrina"]),
        "alertas_bajo_bodega": len(alertas["bajo_bodega"]),
        "alertas_agotados": len(alertas["agotados_globales"]),
        "total_alertas": alertas["total_alertas"],
    }
