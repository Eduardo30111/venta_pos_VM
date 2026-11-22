import asyncio
import json
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_, and_, delete
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException

from ..models.venta import Venta, DetalleVenta, Pago
from ..models.producto import Producto
from ..models.servicio import Servicio
from ..models.inventario import MovimientoInventario
from ..models.nomina import Comision
from ..models.finanzas import CuentaPorPagar, CuentaPorCobrar
from ..models.proveedor import Proveedor
from ..models.cliente import Cliente
from ..models.usuario import Usuario
from ..models.terminal import Terminal
from ..models.caja import MovimientoFinanciero, MovimientoCaja
from ..schemas.venta import VentaCreate, CobroOrdenCreate, EditarVentaRequest
from ..middleware.audit import log_audit
from ..middleware.auth import is_admin_role
from .caja_service import CajaService

from ..async_lock import SHARED_INVENTORY_LOCK as _VENTA_LOCK


def normalizar_metodo_pago(metodo: str) -> str:
    m = (metodo or "").strip().lower()
    if m in ("efectivo", "cash"):
        return "Efectivo"
    if m in ("transferencia", "nequi", "daviplata", "bancolombia", "banco", "qr"):
        return "Transferencia"
    if m in ("fiado", "credito", "crédito", "cartera"):
        return "Fiado"
    raise HTTPException(
        status_code=400,
        detail=f"Método de pago inválido: '{metodo}'. Use Efectivo, Transferencia o Fiado.",
    )


def normalizar_fecha(fecha_str: str) -> str:
    """Normaliza formatos de fecha DD/MM/YYYY o YYYY-MM-DD a YYYY-MM-DD."""
    if not fecha_str:
        return ""
    txt = str(fecha_str).strip()
    if "/" in txt:
        partes = txt.split("/")
        if len(partes) == 3 and len(partes[2]) == 4:
            return f"{partes[2]}-{partes[1].zfill(2)}-{partes[0].zfill(2)}"
    elif "-" in txt:
        partes = txt.split("-")
        if len(partes) == 3:
            if len(partes[0]) == 4:
                return f"{partes[0]}-{partes[1].zfill(2)}-{partes[2].zfill(2)}"
            elif len(partes[2]) == 4:
                return f"{partes[2]}-{partes[1].zfill(2)}-{partes[0].zfill(2)}"
    return txt


def normalizar_hora(hora_str: str) -> str:
    """
    Normaliza cualquier formato de hora (12h con am/pm, a. m./p. m., o 24h, con o sin segundos)
    a formato canónico 'HH:MM:SS' de 24 horas.
    Lanza ValueError si no es un formato de hora válido.
    """
    if not hora_str:
        return ""
    txt = str(hora_str).strip()
    if not txt:
        return ""

    t_clean = txt.lower().replace(".", "").strip()
    t_clean = re.sub(r"\s+", " ", t_clean)
    t_clean = t_clean.replace("a m", "am").replace("p m", "pm")

    formatos = [
        "%H:%M:%S", "%H:%M",
        "%I:%M:%S %p", "%I:%M %p",
        "%I:%M:%S%p", "%I:%M%p",
    ]
    for fmt in formatos:
        try:
            dt = datetime.strptime(t_clean, fmt)
            return dt.strftime("%H:%M:%S")
        except ValueError:
            pass

    for fmt in ["%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p", "%I:%M:%S%p", "%I:%M%p"]:
        try:
            dt = datetime.strptime(txt, fmt)
            return dt.strftime("%H:%M:%S")
        except ValueError:
            pass

    m = re.match(r"^(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?\s*(am|pm|a\.?\s*m\.?|p\.?\s*m\.?)?$", txt, re.IGNORECASE)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        ss = int(m.group(3)) if m.group(3) else 0
        ampm = m.group(4)
        if ampm:
            ampm_norm = ampm.lower().replace(".", "").replace(" ", "")
            if ampm_norm == "pm" and hh < 12:
                hh += 12
            elif ampm_norm == "am" and hh == 12:
                hh = 0
        if 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59:
            return f"{hh:02d}:{mm:02d}:{ss:02d}"

    raise ValueError(f"Formato de hora no reconocido: '{hora_str}'. Use HH:MM o HH:MM a. m. / p. m.")


class VentaService:
    @staticmethod
    async def hidratar_venta(db: AsyncSession, venta: Venta, ya_existia: bool = False) -> Venta:
        det_res = await db.execute(select(DetalleVenta).where(DetalleVenta.venta_id == venta.id))
        dets = det_res.scalars().all()
        pag_res = await db.execute(select(Pago).where(Pago.venta_id == venta.id))
        pags = pag_res.scalars().all()

        cli_doc = venta.cliente_documento or ""
        cli_nom = ""
        if venta.cliente_id:
            c_res = await db.execute(select(Cliente).where(Cliente.id == venta.cliente_id))
            c_obj = c_res.scalars().first()
            if c_obj:
                cli_doc = c_obj.documento
                cli_nom = c_obj.nombre

        op_nom = venta.operario_nombre
        if not op_nom and venta.usuario_id:
            u_res = await db.execute(select(Usuario).where(Usuario.id == venta.usuario_id))
            u_obj = u_res.scalars().first()
            if u_obj:
                op_nom = (f"{u_obj.nombre or ''} {u_obj.apellidos or ''}".strip() or u_obj.usuario)

        cxc_id = None
        cxc_res = await db.execute(select(CuentaPorCobrar).where(CuentaPorCobrar.venta_id == venta.id))
        cxc_obj = cxc_res.scalars().first()
        if cxc_obj:
            cxc_id = cxc_obj.id

        venta.detalles = dets
        venta.pagos = pags
        venta.cliente_documento = cli_doc
        venta.cliente_nombre = cli_nom
        venta.operario_nombre = op_nom or f"Usuario {venta.usuario_id}"
        if not venta.fecha and venta.created_at:
            venta.fecha = venta.created_at.strftime("%Y-%m-%d")
        if not venta.hora and venta.created_at:
            venta.hora = venta.created_at.strftime("%H:%M:%S")
        venta.total_items = sum(float(d.cantidad or 0.0) for d in dets)
        venta.cuenta_por_cobrar_id = cxc_id
        venta.ya_existia_idempotencia = ya_existia
        venta.repetido = ya_existia
        return venta

    @staticmethod
    async def buscar_por_idempotencia(db: AsyncSession, idempotency_key: str) -> Optional[Venta]:
        idem_clean = (idempotency_key or "").strip()
        if not idem_clean:
            return None
        res = await db.execute(select(Venta).where(Venta.idempotency_key == idem_clean))
        venta = res.scalars().first()
        if not venta:
            return None
        return await VentaService.hidratar_venta(db, venta, ya_existia=True)

    @staticmethod
    async def _recalcular_acumulados_proveedor(db: AsyncSession, proveedor_id: int):
        res_prov = await db.execute(select(Proveedor).where(Proveedor.id == proveedor_id))
        prov = res_prov.scalars().first()
        if not prov:
            return
        res_sum = await db.execute(
            select(
                func.sum(CuentaPorPagar.precio_venta),
                func.sum(CuentaPorPagar.monto_comision),
                func.sum(CuentaPorPagar.monto_pagado),
                func.sum(CuentaPorPagar.saldo_pendiente),
            ).where(
                CuentaPorPagar.proveedor_id == proveedor_id,
                CuentaPorPagar.estado.notin_(["Anulada", "Pendiente_Caja"]),
            )
        )
        row = res_sum.first()
        prov.total_ventas = float((row[0] if row else 0.0) or 0.0)
        prov.total_comisiones = float((row[1] if row else 0.0) or 0.0)
        prov.total_pagado = float((row[2] if row else 0.0) or 0.0)
        prov.saldo_acumulado = float((row[3] if row else 0.0) or 0.0)

    @staticmethod
    async def procesar_venta(
        db: AsyncSession,
        venta_data: VentaCreate,
        usuario_id: int,
        terminal_id: int,
        usuario: Usuario,
    ) -> Venta:
        if not venta_data.detalles:
            raise HTTPException(status_code=400, detail="La venta debe incluir al menos un artículo o servicio.")

        idem_clean = (getattr(venta_data, "idempotency_key", None) or "").strip() or None

        async with _VENTA_LOCK:
            # 0. Control persistente de idempotencia ANTES de tocar inventario o contabilidad
            if idem_clean:
                existente = await VentaService.buscar_por_idempotencia(db, idem_clean)
                if existente:
                    return existente

            try:
                ahora = datetime.now()
                f_str = ahora.strftime("%Y-%m-%d")
                h_str = ahora.strftime("%H:%M:%S")

                # Distinguir Fecha de Operación vs Fecha de Registro (ventas atrasadas)
                fecha_operacion = f_str
                hora_operacion = h_str
                es_atrasada = bool(getattr(venta_data, "es_venta_atrasada", False))
                custom_fecha = getattr(venta_data, "fecha", None)
                if custom_fecha and str(custom_fecha).strip():
                    f_c_norm = normalizar_fecha(str(custom_fecha).strip())
                    try:
                        datetime.strptime(f_c_norm[:10], "%Y-%m-%d")
                        fecha_operacion = f_c_norm[:10]
                        if fecha_operacion != f_str:
                            es_atrasada = True
                    except ValueError:
                        pass
                custom_hora = getattr(venta_data, "hora", None)
                if custom_hora and str(custom_hora).strip():
                    try:
                        hora_operacion = normalizar_hora(str(custom_hora).strip())
                    except ValueError:
                        hora_operacion = str(custom_hora).strip()[:8]

                op_nombre = (f"{usuario.nombre or ''} {usuario.apellidos or ''}".strip() or usuario.usuario)

                # 1. Validar terminal
                term_result = await db.execute(select(Terminal).where(Terminal.id == (terminal_id or 1)))
                term = term_result.scalars().first()
                if not term:
                    term_any = await db.execute(select(Terminal).order_by(Terminal.id.asc()))
                    term = term_any.scalars().first()
                    if term:
                        terminal_id = term.id
                    else:
                        term = Terminal(nombre="CAJA-01", descripcion="Caja Principal")
                        db.add(term)
                        await db.flush()
                        terminal_id = term.id
                terminal_nombre = term.nombre or f"Terminal-{terminal_id}"

                # 2. Normalizar pagos antes de crear registros
                estado_venta = venta_data.estado or "Completada"
                total_esperado = round(float(venta_data.total or 0.0), 2)
                if total_esperado < 0:
                    raise HTTPException(status_code=400, detail="El total de la venta no puede ser negativo.")
                pagos_limpios: List[Dict[str, Any]] = []
                monto_fiado = 0.0
                if estado_venta != "Pendiente_Caja":
                    if not venta_data.pagos:
                        pagos_limpios.append(
                            {
                                "metodo": "Efectivo",
                                "monto": total_esperado,
                                "referencia": None,
                                "recibido": total_esperado,
                                "cambio": 0.0,
                            }
                        )
                    else:
                        for p in venta_data.pagos:
                            m_norm = normalizar_metodo_pago(p.metodo)
                            m_val = round(float(p.monto or 0.0), 2)
                            if m_val <= 0:
                                raise HTTPException(status_code=400, detail="El monto del pago debe ser mayor a cero.")
                            pagos_limpios.append(
                                {
                                    "metodo": m_norm,
                                    "monto": m_val,
                                    "referencia": p.referencia,
                                    "recibido": float(p.recibido or 0.0),
                                    "cambio": float(p.cambio or 0.0),
                                }
                            )
                            if m_norm == "Fiado":
                                monto_fiado = round(monto_fiado + m_val, 2)
                        suma_pagos = round(sum(p["monto"] for p in pagos_limpios), 2)
                        if abs(suma_pagos - total_esperado) > 0.05:
                            raise HTTPException(
                                status_code=400,
                                detail=(
                                    f"La suma de los pagos (${suma_pagos:,.2f}) no coincide con "
                                    f"el total de la venta (${total_esperado:,.2f})."
                                ),
                            )

                # 3. Resolver Cliente por ID estable primero; recuperar documento automáticamente
                cliente_obj: Optional[Cliente] = None
                raw_doc = (getattr(venta_data, "cliente_documento", None) or "").strip()
                es_consumidor_final = raw_doc.lower() in ("", "consumidor final", "cf", "none", "null")

                if venta_data.cliente_id and int(venta_data.cliente_id) > 0:
                    cli_res = await db.execute(
                        select(Cliente).with_for_update().where(Cliente.id == int(venta_data.cliente_id))
                    )
                    cliente_obj = cli_res.scalars().first()

                if not cliente_obj and not es_consumidor_final:
                    cli_doc_res = await db.execute(
                        select(Cliente).with_for_update().where(Cliente.documento == raw_doc)
                    )
                    cliente_obj = cli_doc_res.scalars().first()

                # Si es venta FIADA, el cliente real es estrictamente obligatorio (nunca inventar cliente fantasma)
                if monto_fiado > 0:
                    if not cliente_obj:
                        raise HTTPException(
                            status_code=400,
                            detail="Para registrar una venta FIADA debe seleccionar un cliente registrado válido.",
                        )
                    if str(cliente_obj.estado or "Activo").strip().lower() == "inactivo":
                        raise HTTPException(
                            status_code=400,
                            detail=f"El cliente '{cliente_obj.nombre}' se encuentra inactivo y no puede recibir crédito.",
                        )
                    es_admin_u = is_admin_role(usuario)
                    if not cliente_obj.permite_fiado:
                        if not es_admin_u:
                            raise HTTPException(
                                status_code=403,
                                detail=f"El cliente '{cliente_obj.nombre}' no tiene crédito habilitado. Requiere autorización de un administrador.",
                            )
                        cliente_obj.permite_fiado = True
                        db.add(cliente_obj)
                        await db.flush()

                    # Verificar límite de crédito (solo un administrador puede autorizar exceso)
                    cxc_sum_res = await db.execute(
                        select(func.sum(CuentaPorCobrar.saldo_pendiente)).where(
                            CuentaPorCobrar.cliente_id == cliente_obj.id,
                            CuentaPorCobrar.estado == "Pendiente",
                        )
                    )
                    deuda_actual = round(float(cxc_sum_res.scalar() or 0.0), 2)
                    limite_cli = round(float(cliente_obj.limite_credito or 0.0), 2)
                    if getattr(venta_data, "autorizado_exceso_credito", False) and not es_admin_u:
                        raise HTTPException(
                            status_code=403,
                            detail="Solo un Administrador puede autorizar ventas que excedan el límite de crédito.",
                        )
                    autorizado_exceso = bool(getattr(venta_data, "autorizado_exceso_credito", False)) and es_admin_u
                    if limite_cli > 0 and (deuda_actual + monto_fiado > limite_cli + 0.009) and not autorizado_exceso:
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                f"Límite de crédito excedido para {cliente_obj.nombre}: "
                                f"Deuda actual ${deuda_actual:,.0f} + Venta ${monto_fiado:,.0f} "
                                f"supera el tope de ${limite_cli:,.0f}."
                            ),
                        )

                resolved_cliente_id = cliente_obj.id if cliente_obj else None
                doc_final = (
                    cliente_obj.documento
                    if cliente_obj
                    else (raw_doc if not es_consumidor_final else "Consumidor Final")
                )

                # 4. Resolver sesión activa de caja si aplica (sin bloquear la venta ante inconsistencias)
                sesion_id = getattr(venta_data, "sesion_caja_id", None)
                if not sesion_id and estado_venta != "Pendiente_Caja":
                    try:
                        activa = await CajaService.obtener_sesion_activa(db)
                        if activa:
                            sesion_id = activa.id
                    except Exception as e_act_caja:
                        print(f"Aviso resolviendo sesion de caja en venta: {e_act_caja}")

                # 5. Generar consecutivo único V-XXXXXX
                result = await db.execute(select(Venta.numero))
                numeros = result.scalars().all()
                max_num = 0
                for num_str in numeros:
                    if num_str and str(num_str).startswith("V-"):
                        part = str(num_str)[2:]
                        if part.isdigit():
                            max_num = max(max_num, int(part))
                next_num = max_num + 1
                numero = f"V-{next_num:06d}"

                metodo_principal = pagos_limpios[0]["metodo"] if pagos_limpios else "Pendiente"
                if len({p["metodo"] for p in pagos_limpios}) > 1:
                    metodo_principal = "Mixto"
                total_recibido = sum(p["recibido"] for p in pagos_limpios)
                total_cambio = sum(p["cambio"] for p in pagos_limpios)
                snap_str = (
                    json.dumps(venta_data.snapshot_negocio, ensure_ascii=False)
                    if getattr(venta_data, "snapshot_negocio", None)
                    else None
                )

                venta = Venta(
                    numero=numero,
                    idempotency_key=idem_clean,
                    fecha=fecha_operacion,
                    hora=hora_operacion,
                    es_venta_atrasada=es_atrasada,
                    sesion_caja_id=sesion_id if not es_atrasada else None,
                    cliente_id=resolved_cliente_id,
                    cliente_documento=doc_final,
                    usuario_id=usuario_id,
                    operario_nombre=op_nombre,
                    terminal_id=terminal_id,
                    subtotal=round(float(venta_data.subtotal), 2),
                    descuento=round(float(venta_data.descuento or 0.0), 2),
                    total=round(float(venta_data.total), 2),
                    metodo_pago_principal=metodo_principal,
                    recibido=round(total_recibido, 2),
                    cambio=round(total_cambio, 2),
                    saldo_pendiente=round(monto_fiado, 2) if estado_venta != "Pendiente_Caja" else 0.0,
                    estado=estado_venta,
                    observaciones=venta_data.observaciones,
                    snapshot_negocio=snap_str,
                )
                db.add(venta)
                await db.flush()

                # 6. Procesar detalles e inventario de forma atómica
                for item in venta_data.detalles:
                    tipo_raw = (item.tipo_item or "Producto").strip()
                    es_servicio = tipo_raw.lower() == "servicio"
                    tipo_norm = "Servicio" if es_servicio else "Producto"
                    cantidad_item = float(item.cantidad)
                    if cantidad_item <= 0:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Cantidad inválida para '{item.item_nombre}'. Debe ser mayor a cero.",
                        )

                    if not es_servicio:
                        producto = None
                        if item.item_id and int(item.item_id) > 0:
                            prod_res = await db.execute(
                                select(Producto).with_for_update().where(Producto.id == int(item.item_id))
                            )
                            producto = prod_res.scalars().first()
                        if not producto and item.item_codigo:
                            cod_q = str(item.item_codigo).strip()
                            prod_res = await db.execute(
                                select(Producto)
                                .with_for_update()
                                .where(or_(Producto.codigo == cod_q, Producto.codigo == cod_q.zfill(5)))
                            )
                            producto = prod_res.scalars().first()
                        if not producto:
                            raise HTTPException(
                                status_code=404,
                                detail=f"Producto '{item.item_nombre}' ({item.item_codigo}) no existe en el inventario central.",
                            )
                        if str(producto.estado or "Activo").strip().lower() == "inactivo":
                            raise HTTPException(
                                status_code=400,
                                detail=f"El producto '{producto.nombre}' está inactivo.",
                            )

                        sv_ant = float(producto.stock_vitrina or 0.0)
                        sb_ant = float(producto.stock_bodega or 0.0)
                        st_ant = float(producto.stock or 0.0)
                        # Auto-alinear si fue creado solo con stock general
                        if sv_ant == 0.0 and sb_ant == 0.0 and st_ant > 0.0:
                            sv_ant = st_ant

                        if sv_ant + 1e-6 < cantidad_item:
                            if sb_ant > 0 and (sv_ant + sb_ant) + 1e-6 >= cantidad_item:
                                raise HTTPException(
                                    status_code=409,
                                    detail=(
                                        f"Stock insuficiente en Vitrina para '{producto.nombre}': "
                                        f"hay {sv_ant:g} en Vitrina y {sb_ant:g} en Bodega (solicitado: {cantidad_item:g}). "
                                        f"Realice un traslado de Bodega a Vitrina en Inventario."
                                    ),
                                )
                            raise HTTPException(
                                status_code=409,
                                detail=(
                                    f"Stock insuficiente para '{producto.nombre}': "
                                    f"disponible {sv_ant:g}, solicitado {cantidad_item:g}."
                                ),
                            )

                        sv_des = round(max(0.0, sv_ant - cantidad_item), 4)
                        st_nuevo = round(sb_ant + sv_des, 4)
                        producto.stock_vitrina = sv_des
                        producto.stock_bodega = sb_ant
                        producto.stock = st_nuevo

                        costo_hist = float(producto.precio_costo or item.costo_unitario or 0.0)
                        unidad_med = producto.unidad_medida or "Unidad"

                        det = DetalleVenta(
                            venta_id=venta.id,
                            tipo_item="Producto",
                            item_id=producto.id,
                            item_codigo=producto.codigo or item.item_codigo,
                            item_nombre=producto.nombre or item.item_nombre,
                            precio_original=float(item.precio_original),
                            precio_vendido=float(item.precio_vendido),
                            cantidad=cantidad_item,
                            descuento=float(item.descuento or 0.0),
                            subtotal=round(float(item.subtotal), 2),
                            costo_unitario=costo_hist,
                        )
                        db.add(det)
                        await db.flush()

                        mov = MovimientoInventario(
                            fecha=f_str,
                            hora=h_str,
                            producto_id=producto.id,
                            codigo_producto=producto.codigo,
                            nombre_producto=producto.nombre,
                            tipo="VENTA",
                            cantidad=cantidad_item,
                            unidad_medida=unidad_med,
                            ubicacion_origen="VITRINA",
                            ubicacion_destino="CLIENTE",
                            stock_anterior=st_ant if st_ant > 0 else (sb_ant + sv_ant),
                            stock_nuevo=st_nuevo,
                            stock_origen_ant=sv_ant,
                            stock_origen_des=sv_des,
                            stock_destino_ant=0.0,
                            stock_destino_des=0.0,
                            costo_unitario=costo_hist,
                            valor_total=round(costo_hist * cantidad_item, 2),
                            referencia=numero,
                            usuario_id=usuario_id,
                            usuario_nombre=op_nombre,
                            terminal_id=terminal_id,
                            observacion=f"Salida por venta {numero} ({cantidad_item:g} {unidad_med})",
                            estado="Completado",
                        )
                        db.add(mov)

                        # Comisión para Producto (si el operario tiene remuneración porcentual y NO fija)
                        porcentaje = float(usuario.porcentaje_comision or 0.0) if usuario.tipo_remuneracion != "Fija" else 0.0
                        es_porcentual = (usuario.tipo_remuneracion == "Porcentual" or (usuario.tipo_remuneracion != "Fija" and porcentaje > 0))
                        if es_porcentual and porcentaje > 0 and usuario.tipo_remuneracion != "Fija":
                            precio_prod = float(item.precio_vendido)
                            utilidad_prod = max(0.0, precio_prod - costo_hist)
                            base_com = utilidad_prod if utilidad_prod > 0 else precio_prod
                            comision_monto = round((base_com * cantidad_item) * (porcentaje / 100.0), 2)
                            estado_comision = "Pendiente_Caja" if estado_venta == "Pendiente_Caja" else "Pendiente"
                            db.add(
                                Comision(
                                    usuario_id=usuario_id,
                                    venta_id=venta.id,
                                    detalle_venta_id=det.id,
                                    producto_id=producto.id,
                                    servicio_id=None,
                                    valor_servicio=round(precio_prod * cantidad_item, 2),
                                    costo_servicio=round(costo_hist * cantidad_item, 2),
                                    utilidad=round(utilidad_prod * cantidad_item, 2),
                                    porcentaje=porcentaje,
                                    monto_comision=comision_monto,
                                    estado=estado_comision,
                                )
                            )

                        # Cuenta por Pagar a proveedor para Producto físico con proveedor asignado
                        prov_id_prod = producto.proveedor_id or getattr(item, "proveedor_id", None)
                        if prov_id_prod:
                            costo_prod = float(producto.precio_costo or item.costo_unitario or 0.0)
                            pct_prov = float(getattr(producto, "porcentaje_comision", 0.0) or getattr(item, "porcentaje_comision", 0.0) or 0.0)
                            precio_total_prod = round(float(item.precio_vendido) * cantidad_item, 2)
                            if pct_prov > 0:
                                comision_prov = round((precio_total_prod * pct_prov) / 100.0, 2)
                                monto_cxp_prod = round(max(0.0, precio_total_prod - comision_prov), 2)
                            elif costo_prod > 0:
                                monto_cxp_prod = round(costo_prod * cantidad_item, 2)
                                comision_prov = round(max(0.0, precio_total_prod - monto_cxp_prod), 2)
                            else:
                                monto_cxp_prod = precio_total_prod
                                comision_prov = 0.0

                            if monto_cxp_prod > 0:
                                estado_cxp = "Pendiente_Caja" if estado_venta == "Pendiente_Caja" else "Pendiente"
                                cxp_prod = CuentaPorPagar(
                                    proveedor_id=prov_id_prod,
                                    venta_id=venta.id,
                                    numero_venta=numero,
                                    codigo_servicio=producto.codigo or item.item_codigo,
                                    nombre_servicio=producto.nombre or item.item_nombre,
                                    precio_venta=precio_total_prod,
                                    porcentaje_comision=pct_prov,
                                    monto_comision=comision_prov,
                                    concepto=f"Producto {producto.nombre or item.item_nombre} - Venta {numero}",
                                    monto=monto_cxp_prod,
                                    monto_pagado=0.0,
                                    saldo_pendiente=monto_cxp_prod,
                                    estado=estado_cxp,
                                    fecha=f_str,
                                    hora=h_str,
                                    usuario=op_nombre,
                                )
                                db.add(cxp_prod)
                                await db.flush()
                                await VentaService._recalcular_acumulados_proveedor(db, prov_id_prod)
                    else:
                        # Servicio
                        servicio = None
                        if item.item_id and int(item.item_id) > 0:
                            serv_res = await db.execute(select(Servicio).where(Servicio.id == int(item.item_id)))
                            servicio = serv_res.scalars().first()
                        if not servicio and item.item_codigo:
                            cod_s = str(item.item_codigo).strip()
                            serv_res = await db.execute(select(Servicio).where(Servicio.codigo == cod_s))
                            servicio = serv_res.scalars().first()

                        if not servicio or str(servicio.estado or "Activo").strip().lower() != "activo":
                            raise HTTPException(
                                status_code=404,
                                detail=f"Servicio '{item.item_nombre}' ({item.item_codigo}) no encontrado o inactivo.",
                            )

                        prov_id_serv = servicio.proveedor_id or getattr(item, "proveedor_id", None)
                        costo_prov = float(servicio.costo_proveedor or item.costo_unitario or 0.0)
                        pct_prov = float(getattr(servicio, "porcentaje_comision", 0.0) or getattr(item, "porcentaje_comision", 0.0) or 0.0)
                        precio_total_item = round(float(item.precio_vendido) * cantidad_item, 2)

                        if prov_id_serv:
                            if pct_prov > 0:
                                comision_prov = round((precio_total_item * pct_prov) / 100.0, 2)
                                monto_cxp = round(max(0.0, precio_total_item - comision_prov), 2)
                            elif costo_prov > 0:
                                monto_cxp = round(costo_prov * cantidad_item, 2)
                                comision_prov = round(max(0.0, precio_total_item - monto_cxp), 2)
                            else:
                                monto_cxp = precio_total_item
                                comision_prov = 0.0
                            monto_costo_unitario = round(monto_cxp / cantidad_item, 2) if cantidad_item > 0 else 0.0
                        else:
                            monto_cxp = 0.0
                            comision_prov = 0.0
                            monto_costo_unitario = 0.0

                        det = DetalleVenta(
                            venta_id=venta.id,
                            tipo_item="Servicio",
                            item_id=servicio.id,
                            item_codigo=servicio.codigo or item.item_codigo,
                            item_nombre=servicio.nombre or item.item_nombre,
                            precio_original=float(item.precio_original),
                            precio_vendido=float(item.precio_vendido),
                            cantidad=cantidad_item,
                            descuento=float(item.descuento or 0.0),
                            subtotal=precio_total_item,
                            costo_unitario=monto_costo_unitario,
                        )
                        db.add(det)
                        await db.flush()

                        porcentaje = float(usuario.porcentaje_comision or 0.0) if usuario.tipo_remuneracion != "Fija" else 0.0
                        es_porcentual = (usuario.tipo_remuneracion == "Porcentual" or (usuario.tipo_remuneracion != "Fija" and porcentaje > 0))
                        genera_com = (
                            servicio.genera_comision
                            if servicio.genera_comision is not None
                            else (servicio.proveedor_id is None)
                        )
                        if genera_com and es_porcentual and porcentaje > 0 and usuario.tipo_remuneracion != "Fija":
                            utilidad_unitaria = float(item.precio_vendido) - monto_costo_unitario
                            base_com = utilidad_unitaria if utilidad_unitaria > 0 else float(item.precio_vendido)
                            utilidad_total = round(max(0.0, utilidad_unitaria) * cantidad_item, 2)
                            comision_monto = round((base_com * cantidad_item) * (porcentaje / 100.0), 2)
                            estado_comision = "Pendiente_Caja" if estado_venta == "Pendiente_Caja" else "Pendiente"
                            db.add(
                                Comision(
                                    usuario_id=usuario_id,
                                    venta_id=venta.id,
                                    detalle_venta_id=det.id,
                                    servicio_id=servicio.id,
                                    producto_id=None,
                                    valor_servicio=precio_total_item,
                                    costo_servicio=round(monto_costo_unitario * cantidad_item, 2),
                                    utilidad=utilidad_total,
                                    porcentaje=porcentaje,
                                    monto_comision=comision_monto,
                                    estado=estado_comision,
                                )
                            )

                        # Cuenta por Pagar a proveedor (para Servicios con proveedor asignado)
                        if prov_id_serv and monto_cxp > 0:
                            estado_cxp = "Pendiente_Caja" if estado_venta == "Pendiente_Caja" else "Pendiente"
                            cxp = CuentaPorPagar(
                                proveedor_id=prov_id_serv,
                                venta_id=venta.id,
                                numero_venta=numero,
                                codigo_servicio=servicio.codigo or item.item_codigo,
                                nombre_servicio=servicio.nombre or item.item_nombre,
                                precio_venta=precio_total_item,
                                porcentaje_comision=pct_prov,
                                monto_comision=comision_prov,
                                concepto=f"Servicio {servicio.nombre or item.item_nombre} - Venta {numero}",
                                monto=monto_cxp,
                                monto_pagado=0.0,
                                saldo_pendiente=monto_cxp,
                                estado=estado_cxp,
                                fecha=f_str,
                                hora=h_str,
                                usuario=op_nombre,
                            )
                            db.add(cxp)
                            await db.flush()
                            await VentaService._recalcular_acumulados_proveedor(db, prov_id_serv)

                # 7. Registrar pagos, cuentas por cobrar y movimientos contables/caja (TODO en la misma transacción)
                if estado_venta != "Pendiente_Caja":
                    for p_dict in pagos_limpios:
                        m_pago = p_dict["metodo"]
                        m_monto = p_dict["monto"]
                        pago_row = Pago(
                            venta_id=venta.id,
                            metodo=m_pago,
                            monto=m_monto,
                            referencia=p_dict["referencia"],
                            recibido=p_dict["recibido"],
                            cambio=p_dict["cambio"],
                        )
                        db.add(pago_row)

                        if m_pago == "Efectivo":
                            mf_ef = await CajaService.registrar_movimiento_financiero(
                                db=db,
                                tipo="VENTA_EXTEMPORANEA" if es_atrasada else "VENTA_EFECTIVO",
                                concepto=f"Venta {numero} en efectivo {'(Extemporánea)' if es_atrasada else ''}",
                                monto=m_monto,
                                metodo_pago="Efectivo",
                                cuenta_afectada="CAJA_FISICA",
                                usuario=op_nombre,
                                referencia_origen=f"VENTA-{venta.id}",
                                sesion_id=sesion_id if not es_atrasada else None,
                                observaciones=f"Cobro efectivo venta {numero}{' [VENTA ATRASADA]' if es_atrasada else ''}",
                                sincronizar_caja=not es_atrasada,
                                terminal=terminal_nombre,
                                fecha_str=fecha_operacion,
                                hora_str=hora_operacion,
                            )
                            if not es_atrasada and not venta.sesion_caja_id and mf_ef.sesion_caja_id:
                                venta.sesion_caja_id = mf_ef.sesion_caja_id

                        elif m_pago == "Transferencia":
                            await CajaService.registrar_movimiento_financiero(
                                db=db,
                                tipo="VENTA_TRANSFERENCIA",
                                concepto=f"Venta {numero} por transferencia {'(Extemporánea)' if es_atrasada else ''}",
                                monto=m_monto,
                                metodo_pago="Transferencia",
                                cuenta_afectada="BANCO_TRANSFERENCIA",
                                usuario=op_nombre,
                                referencia_origen=f"VENTA-{venta.id}",
                                sesion_id=sesion_id if not es_atrasada else None,
                                observaciones=f"Recaudo transferencia venta {numero}",
                                sincronizar_caja=False,
                                terminal=terminal_nombre,
                                fecha_str=fecha_operacion,
                                hora_str=hora_operacion,
                            )

                    if monto_fiado > 0:
                        if not cliente_obj:
                            raise HTTPException(status_code=400, detail="Cliente requerido para Fiado")

                        cxc = CuentaPorCobrar(
                            cliente_id=cliente_obj.id,
                            venta_id=venta.id,
                            fecha=f_str,
                            hora=h_str,
                            monto_original=monto_fiado,
                            saldo_pendiente=monto_fiado,
                            estado="Pendiente",
                        )
                        db.add(cxc)
                        await db.flush()

                        from .cliente_service import ClienteService

                        await ClienteService.registrar_movimiento_fiado(
                            db=db,
                            cliente_id=cliente_obj.id,
                            cuenta_id=cxc.id,
                            venta_id=venta.id,
                            monto=monto_fiado,
                            usuario_id=usuario_id,
                            terminal_id=terminal_id,
                            observacion=f"Fiado por venta {numero}",
                            fecha_str=f_str,
                            hora_str=h_str,
                        )

                        # Regla contable estricta: Venta fiada registra cuenta por cobrar en CARTERA_CLIENTES, NO dinero recibido
                        await CajaService.registrar_movimiento_financiero(
                            db=db,
                            tipo="VENTA_CREDITO",
                            concepto=f"Venta a crédito {numero} - Cliente: {cliente_obj.nombre}",
                            monto=monto_fiado,
                            metodo_pago="Fiado",
                            cuenta_afectada="CARTERA_CLIENTES",
                            usuario=op_nombre,
                            referencia_origen=f"VENTA-{venta.id}",
                            sesion_id=sesion_id,
                            observaciones=f"Cuenta por cobrar #{cxc.id} asociada al cliente ID {cliente_obj.id}",
                            sincronizar_caja=False,
                            terminal=terminal_nombre,
                            fecha_str=f_str,
                            hora_str=h_str,
                        )

                # 8. Turno de atención (en savepoint aislado para nunca romper ni hacer commit prematuro de la transacción)
                if estado_venta != "Pendiente_Caja":
                    try:
                        async with db.begin_nested():
                            from .turno_service import TurnoService

                            es_esp = getattr(venta_data, "es_turno_especial", False) or False
                            motivo_esp = getattr(venta_data, "motivo_especial", None)
                            await TurnoService.registrar_atencion_venta(
                                db=db,
                                venta=venta,
                                usuario_id=usuario_id,
                                terminal_id=terminal_id,
                                es_turno_especial=es_esp,
                                motivo_especial=motivo_esp,
                            )
                    except Exception as ex_turno:
                        print(f"Nota: aviso registrando atención en módulo de turnos: {ex_turno}")

                await db.commit()
                await db.refresh(venta)

                accion_audit = "MANDAR_A_CAJA" if estado_venta == "Pendiente_Caja" else "CREAR"
                await log_audit(
                    db,
                    usuario_id,
                    op_nombre,
                    terminal_id,
                    terminal_nombre,
                    accion_audit,
                    "VENTAS",
                    "ventas",
                    str(venta.id),
                )
                return await VentaService.hidratar_venta(db, venta, ya_existia=False)

            except IntegrityError:
                await db.rollback()
                if idem_clean:
                    existente = await VentaService.buscar_por_idempotencia(db, idem_clean)
                    if existente:
                        return existente
                raise HTTPException(status_code=409, detail="Conflicto de integridad al registrar la venta.")
            except HTTPException:
                await db.rollback()
                raise
            except Exception as e:
                await db.rollback()
                raise HTTPException(status_code=400, detail=str(e))

    @staticmethod
    async def autorizar_pago_orden(
        db: AsyncSession,
        venta_id: int,
        cobro_data: CobroOrdenCreate,
        admin_id: int,
        terminal_id: int,
        admin_user: Usuario,
    ) -> Venta:
        async with _VENTA_LOCK:
            try:
                res = await db.execute(select(Venta).with_for_update().where(Venta.id == venta_id))
                venta = res.scalars().first()
                if not venta:
                    raise HTTPException(status_code=404, detail="Venta no encontrada")
                if venta.estado == "Completada":
                    return await VentaService.hidratar_venta(db, venta, ya_existia=True)
                if venta.estado != "Pendiente_Caja":
                    raise HTTPException(
                        status_code=400,
                        detail=f"La orden no está pendiente de caja (Estado actual: {venta.estado})",
                    )

                ahora = datetime.now()
                f_str = ahora.strftime("%Y-%m-%d")
                h_str = ahora.strftime("%H:%M:%S")
                admin_nombre = (f"{admin_user.nombre or ''} {admin_user.apellidos or ''}".strip() or admin_user.usuario)

                pagos_limpios = []
                monto_fiado = 0.0
                if not cobro_data.pagos:
                    raise HTTPException(status_code=400, detail="Debe especificar al menos un pago para autorizar la orden.")
                for p in cobro_data.pagos:
                    m_norm = normalizar_metodo_pago(p.metodo)
                    m_val = round(float(p.monto or 0.0), 2)
                    if m_val <= 0:
                        raise HTTPException(status_code=400, detail="El monto del pago debe ser mayor a cero.")
                    pagos_limpios.append(
                        {
                            "metodo": m_norm,
                            "monto": m_val,
                            "referencia": p.referencia,
                            "recibido": float(p.recibido or 0.0),
                            "cambio": float(p.cambio or 0.0),
                        }
                    )
                    if m_norm == "Fiado":
                        monto_fiado = round(monto_fiado + m_val, 2)
                suma_cobro = round(sum(p["monto"] for p in pagos_limpios), 2)
                total_orden = round(float(venta.total or 0.0), 2)
                if abs(suma_cobro - total_orden) > 0.05:
                    raise HTTPException(
                        status_code=400,
                        detail=f"La suma de los pagos (${suma_cobro:,.2f}) no coincide con el total de la orden (${total_orden:,.2f}).",
                    )

                cliente_obj = None
                raw_doc = (getattr(cobro_data, "cliente_documento", None) or "").strip()
                es_cf = raw_doc.lower() in ("", "consumidor final", "cf", "none", "null")
                target_cli_id = cobro_data.cliente_id or venta.cliente_id

                if target_cli_id and int(target_cli_id) > 0:
                    cli_r = await db.execute(select(Cliente).with_for_update().where(Cliente.id == int(target_cli_id)))
                    cliente_obj = cli_r.scalars().first()
                if not cliente_obj and not es_cf:
                    cli_d = await db.execute(select(Cliente).with_for_update().where(Cliente.documento == raw_doc))
                    cliente_obj = cli_d.scalars().first()

                if cliente_obj:
                    venta.cliente_id = cliente_obj.id
                    venta.cliente_documento = cliente_obj.documento
                elif not es_cf:
                    venta.cliente_documento = raw_doc

                if cobro_data.observaciones:
                    obs_prev = f"{venta.observaciones} | " if venta.observaciones else ""
                    venta.observaciones = f"{obs_prev}{cobro_data.observaciones}"

                sesion_id = cobro_data.sesion_caja_id or venta.sesion_caja_id
                if not sesion_id:
                    try:
                        activa = await CajaService.obtener_sesion_activa(db)
                        if activa:
                            sesion_id = activa.id
                    except Exception as e_c_act:
                        print(f"Aviso resolviendo sesion de caja en autorizar_pago: {e_c_act}")
                venta.sesion_caja_id = sesion_id

                for p_dict in pagos_limpios:
                    m_pago = p_dict["metodo"]
                    m_monto = p_dict["monto"]
                    db.add(
                        Pago(
                            venta_id=venta.id,
                            metodo=m_pago,
                            monto=m_monto,
                            referencia=p_dict["referencia"],
                            recibido=p_dict["recibido"],
                            cambio=p_dict["cambio"],
                        )
                    )
                    if m_pago == "Efectivo":
                        mf_ef = await CajaService.registrar_movimiento_financiero(
                            db=db,
                            tipo="VENTA_EFECTIVO",
                            concepto=f"Cobro orden {venta.numero} en efectivo",
                            monto=m_monto,
                            metodo_pago="Efectivo",
                            cuenta_afectada="CAJA_FISICA",
                            usuario=admin_nombre,
                            referencia_origen=f"VENTA-{venta.id}",
                            sesion_id=sesion_id,
                            observaciones=f"Autorización en caja orden {venta.numero}",
                            sincronizar_caja=True,
                            fecha_str=f_str,
                            hora_str=h_str,
                        )
                        if not venta.sesion_caja_id and mf_ef.sesion_caja_id:
                            venta.sesion_caja_id = mf_ef.sesion_caja_id
                    elif m_pago == "Transferencia":
                        await CajaService.registrar_movimiento_financiero(
                            db=db,
                            tipo="VENTA_TRANSFERENCIA",
                            concepto=f"Cobro orden {venta.numero} por transferencia",
                            monto=m_monto,
                            metodo_pago="Transferencia",
                            cuenta_afectada="BANCO_TRANSFERENCIA",
                            usuario=admin_nombre,
                            referencia_origen=f"VENTA-{venta.id}",
                            sesion_id=sesion_id,
                            observaciones=f"Autorización transferencia orden {venta.numero}",
                            sincronizar_caja=False,
                            fecha_str=f_str,
                            hora_str=h_str,
                        )

                if monto_fiado > 0:
                    if not cliente_obj:
                        raise HTTPException(
                            status_code=400,
                            detail="Para autorizar como FIADO debe seleccionar un cliente registrado válido.",
                        )
                    if str(cliente_obj.estado or "Activo").strip().lower() == "inactivo":
                        raise HTTPException(
                            status_code=400,
                            detail=f"El cliente '{cliente_obj.nombre}' se encuentra inactivo y no puede recibir crédito.",
                        )
                    es_admin_cobro = is_admin_role(admin_user)
                    if not cliente_obj.permite_fiado:
                        if not es_admin_cobro:
                            raise HTTPException(
                                status_code=403,
                                detail=f"El cliente '{cliente_obj.nombre}' no tiene crédito habilitado. Requiere autorización de un administrador.",
                            )
                        cliente_obj.permite_fiado = True
                        db.add(cliente_obj)
                        await db.flush()

                    cxc_result = await db.execute(
                        select(func.sum(CuentaPorCobrar.saldo_pendiente)).where(
                            CuentaPorCobrar.cliente_id == cliente_obj.id,
                            CuentaPorCobrar.estado == "Pendiente",
                        )
                    )
                    deuda_actual = round(float(cxc_result.scalar() or 0.0), 2)
                    limite_cli = round(float(cliente_obj.limite_credito or 0.0), 2)
                    autorizado_exceso_cobro = bool(getattr(cobro_data, "autorizado_exceso_credito", False)) and es_admin_cobro
                    if (
                        limite_cli > 0
                        and (deuda_actual + monto_fiado > limite_cli + 0.009)
                        and not autorizado_exceso_cobro
                    ):
                        raise HTTPException(status_code=400, detail="Límite de crédito excedido")

                    cxc = CuentaPorCobrar(
                        cliente_id=cliente_obj.id,
                        venta_id=venta.id,
                        fecha=f_str,
                        hora=h_str,
                        monto_original=monto_fiado,
                        saldo_pendiente=monto_fiado,
                        estado="Pendiente",
                    )
                    db.add(cxc)
                    await db.flush()

                    from .cliente_service import ClienteService

                    await ClienteService.registrar_movimiento_fiado(
                        db=db,
                        cliente_id=cliente_obj.id,
                        cuenta_id=cxc.id,
                        venta_id=venta.id,
                        monto=monto_fiado,
                        usuario_id=admin_id,
                        terminal_id=terminal_id,
                        observacion=f"Fiado por orden {venta.numero}",
                        fecha_str=f_str,
                        hora_str=h_str,
                    )

                    await CajaService.registrar_movimiento_financiero(
                        db=db,
                        tipo="VENTA_CREDITO",
                        concepto=f"Orden a crédito {venta.numero} - Cliente: {cliente_obj.nombre}",
                        monto=monto_fiado,
                        metodo_pago="Fiado",
                        cuenta_afectada="CARTERA_CLIENTES",
                        usuario=admin_nombre,
                        referencia_origen=f"VENTA-{venta.id}",
                        sesion_id=sesion_id,
                        observaciones=f"Cuenta por cobrar #{cxc.id}",
                        sincronizar_caja=False,
                        fecha_str=f_str,
                        hora_str=h_str,
                    )

                com_res = await db.execute(select(Comision).with_for_update().where(Comision.venta_id == venta.id))
                for c in com_res.scalars().all():
                    if c.estado == "Pendiente_Caja":
                        c.estado = "Pendiente"

                cxp_res = await db.execute(select(CuentaPorPagar).with_for_update().where(CuentaPorPagar.venta_id == venta.id))
                provs_activar = set()
                for cxp_o in cxp_res.scalars().all():
                    if cxp_o.estado == "Pendiente_Caja":
                        cxp_o.estado = "Pendiente"
                        provs_activar.add(cxp_o.proveedor_id)
                for pid_act in provs_activar:
                    await VentaService._recalcular_acumulados_proveedor(db, pid_act)

                venta.metodo_pago_principal = (
                    "Mixto"
                    if len({p["metodo"] for p in pagos_limpios}) > 1
                    else (pagos_limpios[0]["metodo"] if pagos_limpios else "Efectivo")
                )
                venta.recibido = round(sum(p["recibido"] for p in pagos_limpios), 2)
                venta.cambio = round(sum(p["cambio"] for p in pagos_limpios), 2)
                venta.saldo_pendiente = round(monto_fiado, 2)
                venta.estado = "Completada"

                try:
                    async with db.begin_nested():
                        from .turno_service import TurnoService

                        await TurnoService.registrar_atencion_venta(
                            db=db,
                            venta=venta,
                            usuario_id=venta.usuario_id,
                            terminal_id=terminal_id,
                        )
                except Exception as ex_turno:
                    print(f"Nota: aviso registrando atención de turno al cobrar: {ex_turno}")

                await db.commit()
                await db.refresh(venta)
                await log_audit(
                    db,
                    admin_id,
                    admin_nombre,
                    terminal_id,
                    "Terminal",
                    "AUTORIZAR_PAGO",
                    "VENTAS",
                    "ventas",
                    str(venta.id),
                )
                return await VentaService.hidratar_venta(db, venta, ya_existia=False)
            except HTTPException:
                await db.rollback()
                raise
            except Exception as e:
                await db.rollback()
                raise HTTPException(status_code=400, detail=str(e))

    @staticmethod
    async def anular_venta(
        db: AsyncSession,
        venta_id: int,
        usuario_id: int,
        terminal_id: int,
        usuario: Usuario,
        motivo: str = "Anulación administrativa",
    ) -> Venta:
        async with _VENTA_LOCK:
            try:
                result = await db.execute(select(Venta).with_for_update().where(Venta.id == venta_id))
                venta = result.scalars().first()
                if not venta:
                    raise HTTPException(status_code=404, detail="Venta no encontrada")
                if venta.estado == "Anulada":
                    raise HTTPException(status_code=400, detail="La venta ya se encuentra anulada")

                ahora = datetime.now()
                f_str = ahora.strftime("%Y-%m-%d")
                h_str = ahora.strftime("%H:%M:%S")
                admin_nom = (f"{usuario.nombre or ''} {usuario.apellidos or ''}".strip() or usuario.usuario)

                # Validar comisiones y abonos antes de mutar
                com_result = await db.execute(select(Comision).with_for_update().where(Comision.venta_id == venta.id))
                comisiones = com_result.scalars().all()
                for com in comisiones:
                    if com.estado == "Liquidada":
                        raise HTTPException(status_code=400, detail="No se puede anular: existen comisiones ya liquidadas")

                cxc_result = await db.execute(
                    select(CuentaPorCobrar).with_for_update().where(CuentaPorCobrar.venta_id == venta.id)
                )
                cxc_list = cxc_result.scalars().all()
                for cxc in cxc_list:
                    if float(cxc.monto_original or 0.0) - float(cxc.saldo_pendiente or 0.0) > 0.01:
                        raise HTTPException(
                            status_code=400,
                            detail="No se puede anular: el cliente ya ha realizado abonos a esta deuda",
                        )

                cxp_result = await db.execute(
                    select(CuentaPorPagar).with_for_update().where(CuentaPorPagar.venta_id == venta.id)
                )
                cxp_list = cxp_result.scalars().all()
                for cxp in cxp_list:
                    if cxp.estado == "Pagada" or float(cxp.monto_pagado or 0.0) > 0.01:
                        raise HTTPException(status_code=400, detail="No se puede anular: ya se liquidó al proveedor")

                # 1. Revertir inventario a Vitrina
                det_result = await db.execute(select(DetalleVenta).where(DetalleVenta.venta_id == venta.id))
                detalles = det_result.scalars().all()
                for item in detalles:
                    if item.tipo_item == "Producto":
                        prod_result = await db.execute(
                            select(Producto).with_for_update().where(Producto.id == item.item_id)
                        )
                        producto = prod_result.scalars().first()
                        if producto:
                            sv_ant = float(producto.stock_vitrina or 0.0)
                            sb_ant = float(producto.stock_bodega or 0.0)
                            st_ant = float(producto.stock or 0.0)
                            sv_des = round(sv_ant + float(item.cantidad), 4)
                            st_des = round(sb_ant + sv_des, 4)
                            producto.stock_vitrina = sv_des
                            producto.stock = st_des

                            db.add(
                                MovimientoInventario(
                                    fecha=f_str,
                                    hora=h_str,
                                    producto_id=producto.id,
                                    codigo_producto=producto.codigo,
                                    nombre_producto=producto.nombre,
                                    tipo="DEVOLUCION_VENTA",
                                    cantidad=float(item.cantidad),
                                    unidad_medida=producto.unidad_medida or "Unidad",
                                    ubicacion_origen="CLIENTE",
                                    ubicacion_destino="VITRINA",
                                    stock_anterior=st_ant,
                                    stock_nuevo=st_des,
                                    stock_origen_ant=0.0,
                                    stock_origen_des=0.0,
                                    stock_destino_ant=sv_ant,
                                    stock_destino_des=sv_des,
                                    costo_unitario=float(item.costo_unitario or producto.precio_costo or 0.0),
                                    valor_total=round(float(item.costo_unitario or 0.0) * float(item.cantidad), 2),
                                    referencia=f"ANULACION-{venta.numero}",
                                    usuario_id=usuario_id,
                                    usuario_nombre=admin_nom,
                                    terminal_id=terminal_id,
                                    observacion=f"Anulación de venta {venta.numero}: {motivo}",
                                    estado="Completado",
                                )
                            )

                # 2. Anular comisiones
                for com in comisiones:
                    if com.estado in ("Pendiente", "Pendiente_Caja"):
                        com.estado = "Anulada"

                # 3. Revertir Cuentas por Cobrar
                from .cliente_service import ClienteService

                await ClienteService.revertir_fiado_por_anulacion(
                    db=db,
                    venta_id=venta.id,
                    usuario_id=usuario_id,
                    terminal_id=terminal_id,
                    motivo=f"Anulación de venta {venta.numero}: {motivo}",
                )

                # 4. Revertir Cuentas por Pagar
                provs_afectados = set()
                for cxp in cxp_list:
                    cxp.estado = "Anulada"
                    cxp.saldo_pendiente = 0.0
                    provs_afectados.add(cxp.proveedor_id)
                for pid in provs_afectados:
                    await VentaService._recalcular_acumulados_proveedor(db, pid)

                # 5. Revertir impacto en Caja / Banco / Movimientos Financieros
                pag_res = await db.execute(select(Pago).where(Pago.venta_id == venta.id))
                pagos_orig = pag_res.scalars().all()
                try:
                    activa = await CajaService.obtener_sesion_activa(db)
                except Exception:
                    activa = None
                sesion_id = activa.id if activa else venta.sesion_caja_id

                for p in pagos_orig:
                    m_norm = (p.metodo or "").strip().capitalize()
                    if m_norm == "Efectivo" and float(p.monto or 0.0) > 0:
                        await CajaService.registrar_movimiento_financiero(
                            db=db,
                            tipo="DEVOLUCION_VENTA",
                            concepto=f"Devolución efectivo por anulación {venta.numero}: {motivo}",
                            monto=float(p.monto),
                            metodo_pago="Efectivo",
                            cuenta_afectada="CAJA_FISICA",
                            usuario=admin_nom,
                            referencia_origen=f"ANULACION-VENTA-{venta.id}",
                            sesion_id=sesion_id,
                            observaciones=motivo,
                            sincronizar_caja=True,
                            fecha_str=f_str,
                            hora_str=h_str,
                        )
                    elif m_norm == "Transferencia" and float(p.monto or 0.0) > 0:
                        await CajaService.registrar_movimiento_financiero(
                            db=db,
                            tipo="DEVOLUCION_VENTA",
                            concepto=f"Reversión transferencia por anulación {venta.numero}: {motivo}",
                            monto=float(p.monto),
                            metodo_pago="Transferencia",
                            cuenta_afectada="BANCO_TRANSFERENCIA",
                            usuario=admin_nom,
                            referencia_origen=f"ANULACION-VENTA-{venta.id}",
                            sesion_id=sesion_id,
                            observaciones=motivo,
                            sincronizar_caja=False,
                            fecha_str=f_str,
                            hora_str=h_str,
                        )

                mf_res = await db.execute(
                    select(MovimientoFinanciero).where(MovimientoFinanciero.referencia_origen == f"VENTA-{venta.id}")
                )
                for mf in mf_res.scalars().all():
                    mf.estado = "Anulado"
                    mf.observaciones = f"{mf.observaciones or ''} | Venta anulada: {motivo}".strip(" |")

                venta.estado = "Anulada"
                venta.saldo_pendiente = 0.0
                venta.motivo_anulacion = motivo
                venta.anulada_por = admin_nom
                venta.anulada_at = f"{f_str} {h_str}"

                await db.commit()
                await db.refresh(venta)
                await log_audit(
                    db,
                    usuario_id,
                    admin_nom,
                    terminal_id,
                    "Terminal",
                    "ANULAR",
                    "VENTAS",
                    "ventas",
                    str(venta.id),
                    valor_anterior={"total": venta.total, "metodo": venta.metodo_pago_principal},
                    valor_nuevo={"estado": "Anulada", "motivo": motivo},
                )
                return await VentaService.hidratar_venta(db, venta, ya_existia=False)
            except HTTPException:
                await db.rollback()
                raise
            except Exception as e:
                await db.rollback()
                raise HTTPException(status_code=400, detail=str(e))

    @staticmethod
    async def editar_venta(
        db: AsyncSession,
        venta_id: int,
        req: EditarVentaRequest,
        usuario_id: int,
        usuario: Usuario,
    ) -> Dict[str, Any]:
        if not req.motivo or len(req.motivo.strip()) < 3:
            raise HTTPException(status_code=400, detail="El motivo de edición es obligatorio (mínimo 3 caracteres).")
        if not req.nuevos_items:
            raise HTTPException(status_code=400, detail="La venta debe conservar al menos un ítem.")

        nuevo_metodo = normalizar_metodo_pago(req.nuevo_metodo)

        async with _VENTA_LOCK:
            try:
                res_v = await db.execute(select(Venta).with_for_update().where(Venta.id == venta_id))
                venta = res_v.scalars().first()
                if not venta:
                    raise HTTPException(status_code=404, detail=f"No existe la venta #{venta_id}")
                if venta.estado == "Anulada":
                    raise HTTPException(status_code=400, detail="No se puede editar una venta anulada.")
                if venta.estado == "Pendiente_Caja":
                    raise HTTPException(
                        status_code=400,
                        detail="No se puede editar una orden en estado Pendiente_Caja. Cobre o anule la orden primero.",
                    )

                ahora = datetime.now()
                f_str = ahora.strftime("%Y-%m-%d")
                h_str = ahora.strftime("%H:%M:%S")
                admin_nom = (f"{usuario.nombre or ''} {usuario.apellidos or ''}".strip() or usuario.usuario)

                # Validar comisiones ya liquidadas y CXP ya pagadas antes de mutar
                com_res_ant = await db.execute(select(Comision).with_for_update().where(Comision.venta_id == venta.id))
                coms_ant = com_res_ant.scalars().all()
                for com in coms_ant:
                    if com.estado == "Liquidada":
                        raise HTTPException(status_code=400, detail="No se puede editar: existen comisiones ya liquidadas.")

                cxp_res_ant = await db.execute(select(CuentaPorPagar).with_for_update().where(CuentaPorPagar.venta_id == venta.id))
                cxps_ant = cxp_res_ant.scalars().all()
                provs_afectados = set()
                for cxp in cxps_ant:
                    if cxp.estado == "Pagada" or float(cxp.monto_pagado or 0.0) > 0.01:
                        raise HTTPException(status_code=400, detail="No se puede editar: ya existen pagos al proveedor asociados.")
                    provs_afectados.add(cxp.proveedor_id)

                total_anterior = float(venta.total or 0.0)
                pag_res = await db.execute(select(Pago).where(Pago.venta_id == venta.id))
                pagos_ant = pag_res.scalars().all()
                metodo_anterior = venta.metodo_pago_principal or (pagos_ant[0].metodo if pagos_ant else "Efectivo")

                ef_ant = round(sum(float(p.monto or 0.0) for p in pagos_ant if (p.metodo or "").strip().lower() == "efectivo"), 2)
                tr_ant = round(sum(float(p.monto or 0.0) for p in pagos_ant if (p.metodo or "").strip().lower() == "transferencia"), 2)
                fi_ant = round(sum(float(p.monto or 0.0) for p in pagos_ant if (p.metodo or "").strip().lower() == "fiado"), 2)
                if not pagos_ant:
                    if metodo_anterior == "Efectivo":
                        ef_ant = total_anterior
                    elif metodo_anterior == "Transferencia":
                        tr_ant = total_anterior
                    elif metodo_anterior == "Fiado":
                        fi_ant = total_anterior

                # Validar abonos previos si tenía CXC
                cxc_res = await db.execute(
                    select(CuentaPorCobrar).with_for_update().where(CuentaPorCobrar.venta_id == venta.id)
                )
                cxc_ant = cxc_res.scalars().first()
                if cxc_ant and (float(cxc_ant.monto_original or 0.0) - float(cxc_ant.saldo_pendiente or 0.0)) > 0.01:
                    raise HTTPException(
                        status_code=400,
                        detail="No se puede editar una venta fiada que ya tiene abonos registrados.",
                    )

                cliente_obj = None
                if venta.cliente_id:
                    cli_r = await db.execute(select(Cliente).with_for_update().where(Cliente.id == venta.cliente_id))
                    cliente_obj = cli_r.scalars().first()

                if nuevo_metodo == "Fiado":
                    if not cliente_obj:
                        raise HTTPException(
                            status_code=400,
                            detail="No se puede cambiar a Fiado porque la venta no tiene un cliente registrado asociado.",
                        )
                    if str(cliente_obj.estado or "Activo").strip().lower() == "inactivo":
                        raise HTTPException(
                            status_code=400,
                            detail=f"El cliente '{cliente_obj.nombre}' está inactivo y no puede recibir crédito.",
                        )

                # Obtener usuario original de la venta para recalcular comisiones
                v_user_res = await db.execute(select(Usuario).where(Usuario.id == venta.usuario_id))
                venta_usuario = v_user_res.scalars().first() or usuario

                # 1. Eliminar comisiones y CXP anteriores ANTES de borrar DetalleVenta (evita violación FK en PostgreSQL)
                await db.execute(delete(Comision).where(Comision.venta_id == venta.id))
                await db.execute(delete(CuentaPorPagar).where(CuentaPorPagar.venta_id == venta.id))

                # 2. Revertir stock anterior con registro en Kárdex
                det_res = await db.execute(select(DetalleVenta).where(DetalleVenta.venta_id == venta.id))
                dets_ant = det_res.scalars().all()
                for d_old in dets_ant:
                    if str(d_old.tipo_item or "").strip().lower() in ("producto", "productos"):
                        p_res = await db.execute(select(Producto).with_for_update().where(Producto.id == d_old.item_id))
                        prod = p_res.scalars().first()
                        if prod:
                            sv_ant = float(prod.stock_vitrina or 0.0)
                            sb_ant = float(prod.stock_bodega or 0.0)
                            st_ant = float(prod.stock or 0.0)
                            sv_des = round(sv_ant + float(d_old.cantidad), 4)
                            st_des = round(sb_ant + sv_des, 4)
                            prod.stock_vitrina = sv_des
                            prod.stock = st_des
                            db.add(
                                MovimientoInventario(
                                    fecha=f_str,
                                    hora=h_str,
                                    producto_id=prod.id,
                                    codigo_producto=prod.codigo,
                                    nombre_producto=prod.nombre,
                                    tipo="DEVOLUCION_VENTA",
                                    cantidad=float(d_old.cantidad),
                                    unidad_medida=prod.unidad_medida or "Unidad",
                                    ubicacion_origen="CLIENTE",
                                    ubicacion_destino="VITRINA",
                                    stock_anterior=st_ant,
                                    stock_nuevo=st_des,
                                    stock_origen_ant=0.0,
                                    stock_origen_des=0.0,
                                    stock_destino_ant=sv_ant,
                                    stock_destino_des=sv_des,
                                    costo_unitario=float(d_old.costo_unitario or prod.precio_costo or 0.0),
                                    valor_total=round(float(d_old.costo_unitario or prod.precio_costo or 0.0) * float(d_old.cantidad), 2),
                                    referencia=f"EDIT-REV-{venta.numero}",
                                    usuario_id=usuario_id,
                                    usuario_nombre=admin_nom,
                                    terminal_id=req.terminal_id or venta.terminal_id or 1,
                                    observacion=f"Reverso por edición de venta {venta.numero}: {req.motivo}",
                                    estado="Completado",
                                )
                            )

                await db.execute(delete(DetalleVenta).where(DetalleVenta.venta_id == venta.id))

                # 3. Insertar nuevos ítems, descontar stock con Kárdex y recalcular comisiones + CXP
                nuevo_total = 0.0
                pct_op = float(venta_usuario.porcentaje_comision or 0.0) if venta_usuario.tipo_remuneracion != "Fija" else 0.0
                es_porcentual_op = (venta_usuario.tipo_remuneracion == "Porcentual" or (venta_usuario.tipo_remuneracion != "Fija" and pct_op > 0)) and venta_usuario.tipo_remuneracion != "Fija"

                for it in req.nuevos_items:
                    cod = str(it.codigo_producto).strip()
                    cant = float(it.cantidad)
                    pu = float(it.precio_unitario)
                    if cant <= 0:
                        raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a cero.")
                    if pu < 0:
                        raise HTTPException(status_code=400, detail="El precio unitario no puede ser negativo.")
                    sub = round(pu * cant, 2)
                    nuevo_total = round(nuevo_total + sub, 2)

                    prod_res = await db.execute(
                        select(Producto).with_for_update().where(or_(Producto.codigo == cod, Producto.codigo == cod.zfill(5)))
                    )
                    prod = prod_res.scalars().first()
                    if prod:
                        sv_ant = float(prod.stock_vitrina or 0.0)
                        sb_ant = float(prod.stock_bodega or 0.0)
                        st_ant = float(prod.stock or 0.0)
                        if sv_ant + 1e-6 < cant:
                            raise HTTPException(
                                status_code=409,
                                detail=f"Stock insuficiente en Vitrina para '{prod.nombre}' al editar.",
                            )
                        sv_des = round(max(0.0, sv_ant - cant), 4)
                        st_des = round(sb_ant + sv_des, 4)
                        prod.stock_vitrina = sv_des
                        prod.stock = st_des
                        costo_u = float(prod.precio_costo or 0.0)
                        det_new = DetalleVenta(
                            venta_id=venta.id,
                            tipo_item="Producto",
                            item_id=prod.id,
                            item_codigo=prod.codigo,
                            item_nombre=prod.nombre,
                            precio_original=float(prod.precio_venta or pu),
                            precio_vendido=pu,
                            cantidad=cant,
                            descuento=0.0,
                            subtotal=sub,
                            costo_unitario=costo_u,
                        )
                        db.add(det_new)
                        await db.flush()

                        db.add(
                            MovimientoInventario(
                                fecha=f_str,
                                hora=h_str,
                                producto_id=prod.id,
                                codigo_producto=prod.codigo,
                                nombre_producto=prod.nombre,
                                tipo="VENTA",
                                cantidad=cant,
                                unidad_medida=prod.unidad_medida or "Unidad",
                                ubicacion_origen="VITRINA",
                                ubicacion_destino="CLIENTE",
                                stock_anterior=st_ant,
                                stock_nuevo=st_des,
                                stock_origen_ant=sv_ant,
                                stock_origen_des=sv_des,
                                stock_destino_ant=0.0,
                                stock_destino_des=0.0,
                                costo_unitario=costo_u,
                                valor_total=round(costo_u * cant, 2),
                                referencia=f"EDIT-{venta.numero}",
                                usuario_id=usuario_id,
                                usuario_nombre=admin_nom,
                                terminal_id=req.terminal_id or venta.terminal_id or 1,
                                observacion=f"Salida por edición de venta {venta.numero}: {req.motivo}",
                                estado="Completado",
                            )
                        )

                        if es_porcentual_op and pct_op > 0:
                            util_u = max(0.0, pu - costo_u)
                            base_c = util_u if util_u > 0 else pu
                            db.add(
                                Comision(
                                    usuario_id=venta.usuario_id,
                                    venta_id=venta.id,
                                    detalle_venta_id=det_new.id,
                                    producto_id=prod.id,
                                    servicio_id=None,
                                    valor_servicio=sub,
                                    costo_servicio=round(costo_u * cant, 2),
                                    utilidad=round(util_u * cant, 2),
                                    porcentaje=pct_op,
                                    monto_comision=round((base_c * cant) * (pct_op / 100.0), 2),
                                    estado="Pendiente",
                                )
                            )

                        if prod.proveedor_id:
                            pct_p = float(getattr(prod, "porcentaje_comision", 0.0) or 0.0)
                            if pct_p > 0:
                                com_p = round((sub * pct_p) / 100.0, 2)
                                m_cxp = round(max(0.0, sub - com_p), 2)
                            elif costo_u > 0:
                                m_cxp = round(costo_u * cant, 2)
                                com_p = round(max(0.0, sub - m_cxp), 2)
                            else:
                                m_cxp = sub
                                com_p = 0.0
                            if m_cxp > 0:
                                db.add(
                                    CuentaPorPagar(
                                        proveedor_id=prod.proveedor_id,
                                        venta_id=venta.id,
                                        numero_venta=venta.numero,
                                        codigo_servicio=prod.codigo,
                                        nombre_servicio=prod.nombre,
                                        precio_venta=sub,
                                        porcentaje_comision=pct_p,
                                        monto_comision=com_p,
                                        concepto=f"Producto {prod.nombre} - Venta {venta.numero} (Editada)",
                                        monto=m_cxp,
                                        monto_pagado=0.0,
                                        saldo_pendiente=m_cxp,
                                        estado="Pendiente",
                                        fecha=f_str,
                                        hora=h_str,
                                        usuario=admin_nom,
                                    )
                                )
                                provs_afectados.add(prod.proveedor_id)
                    else:
                        serv_res = await db.execute(select(Servicio).where(Servicio.codigo == cod))
                        serv = serv_res.scalars().first()
                        prov_id_s = serv.proveedor_id if serv else None
                        costo_p_s = float(getattr(serv, "costo_proveedor", 0.0) or 0.0) if serv else 0.0
                        pct_p_s = float(getattr(serv, "porcentaje_comision", 0.0) or 0.0) if serv else 0.0
                        if prov_id_s:
                            if pct_p_s > 0:
                                com_ps = round((sub * pct_p_s) / 100.0, 2)
                                m_cxp_s = round(max(0.0, sub - com_ps), 2)
                            elif costo_p_s > 0:
                                m_cxp_s = round(costo_p_s * cant, 2)
                                com_ps = round(max(0.0, sub - m_cxp_s), 2)
                            else:
                                m_cxp_s = sub
                                com_ps = 0.0
                            costo_u_s = round(m_cxp_s / cant, 2) if cant > 0 else 0.0
                        else:
                            m_cxp_s = 0.0
                            com_ps = 0.0
                            costo_u_s = 0.0

                        det_new = DetalleVenta(
                            venta_id=venta.id,
                            tipo_item="Servicio",
                            item_id=serv.id if serv else 0,
                            item_codigo=cod,
                            item_nombre=serv.nombre if serv else it.nombre_producto,
                            precio_original=float(serv.precio_venta if serv else pu),
                            precio_vendido=pu,
                            cantidad=cant,
                            descuento=0.0,
                            subtotal=sub,
                            costo_unitario=costo_u_s,
                        )
                        db.add(det_new)
                        await db.flush()

                        gen_c = (
                            (serv.genera_comision if serv.genera_comision is not None else (serv.proveedor_id is None))
                            if serv
                            else True
                        )
                        if gen_c and es_porcentual_op and pct_op > 0:
                            util_us = pu - costo_u_s
                            base_cs = util_us if util_us > 0 else pu
                            db.add(
                                Comision(
                                    usuario_id=venta.usuario_id,
                                    venta_id=venta.id,
                                    detalle_venta_id=det_new.id,
                                    servicio_id=serv.id if serv else None,
                                    producto_id=None,
                                    valor_servicio=sub,
                                    costo_servicio=round(costo_u_s * cant, 2),
                                    utilidad=round(max(0.0, util_us) * cant, 2),
                                    porcentaje=pct_op,
                                    monto_comision=round((base_cs * cant) * (pct_op / 100.0), 2),
                                    estado="Pendiente",
                                )
                            )

                        if prov_id_s and m_cxp_s > 0:
                            db.add(
                                CuentaPorPagar(
                                    proveedor_id=prov_id_s,
                                    venta_id=venta.id,
                                    numero_venta=venta.numero,
                                    codigo_servicio=cod,
                                    nombre_servicio=serv.nombre if serv else it.nombre_producto,
                                    precio_venta=sub,
                                    porcentaje_comision=pct_p_s,
                                    monto_comision=com_ps,
                                    concepto=f"Servicio {serv.nombre if serv else it.nombre_producto} - Venta {venta.numero} (Editada)",
                                    monto=m_cxp_s,
                                    monto_pagado=0.0,
                                    saldo_pendiente=m_cxp_s,
                                    estado="Pendiente",
                                    fecha=f_str,
                                    hora=h_str,
                                    usuario=admin_nom,
                                )
                            )
                            provs_afectados.add(prov_id_s)

                await db.flush()
                for pid_af in provs_afectados:
                    await VentaService._recalcular_acumulados_proveedor(db, pid_af)

                # 4. Reemplazar pagos y ajustar Caja Física / Banco Transferencias / Cartera CXC
                await db.execute(delete(Pago).where(Pago.venta_id == venta.id))
                db.add(
                    Pago(
                        venta_id=venta.id,
                        metodo=nuevo_metodo,
                        monto=nuevo_total,
                        referencia="Edición administrativa",
                        recibido=0.0 if nuevo_metodo == "Fiado" else nuevo_total,
                        cambio=0.0,
                    )
                )

                try:
                    activa = await CajaService.obtener_sesion_activa(db)
                except Exception:
                    activa = None
                sesion_id = activa.id if activa else venta.sesion_caja_id

                ef_nuevo = nuevo_total if nuevo_metodo == "Efectivo" else 0.0
                delta_ef = round(ef_nuevo - ef_ant, 2)
                if abs(delta_ef) > 0.01:
                    await CajaService.registrar_movimiento_caja(
                        db=db,
                        tipo="AJUSTE",
                        monto=delta_ef,
                        usuario=admin_nom,
                        referencia_id=f"EDIT-VENTA-{venta.id}",
                        descripcion=f"Ajuste efectivo por edición Venta {venta.numero}: {req.motivo}",
                        sesion_id=sesion_id,
                        fecha_str=f_str,
                        hora_str=h_str,
                    )

                tr_nuevo = nuevo_total if nuevo_metodo == "Transferencia" else 0.0
                delta_tr = round(tr_nuevo - tr_ant, 2)
                if abs(delta_tr) > 0.01:
                    await CajaService.registrar_movimiento_financiero(
                        db=db,
                        tipo="AJUSTE_AUTORIZADO",
                        concepto=f"Ajuste banco por edición Venta {venta.numero}: {req.motivo}",
                        monto=delta_tr,
                        metodo_pago="Transferencia",
                        cuenta_afectada="BANCO_TRANSFERENCIA",
                        usuario=admin_nom,
                        referencia_origen=f"EDIT-VENTA-{venta.id}",
                        sesion_id=sesion_id,
                        observaciones=req.motivo,
                        sincronizar_caja=False,
                        fecha_str=f_str,
                        hora_str=h_str,
                    )

                from .cliente_service import ClienteService

                if cxc_ant and nuevo_metodo != "Fiado":
                    await ClienteService.revertir_fiado_por_anulacion(
                        db=db,
                        venta_id=venta.id,
                        usuario_id=usuario_id,
                        terminal_id=req.terminal_id or venta.terminal_id or 1,
                        motivo=f"Edición de venta {venta.numero} (cambio de Fiado a {nuevo_metodo}): {req.motivo}",
                    )
                elif nuevo_metodo == "Fiado":
                    fi_nuevo = nuevo_total
                    delta_fi = round(fi_nuevo - fi_ant, 2)
                    if cxc_ant:
                        saldo_ant_cli = await ClienteService.obtener_saldo_cliente(db, venta.cliente_id)
                        cxc_ant.monto_original = nuevo_total
                        cxc_ant.saldo_pendiente = nuevo_total
                        cxc_ant.estado = "Pendiente"
                        await db.flush()
                        if abs(delta_fi) > 0.01:
                            from ..models.finanzas import MovimientoCuentaCliente
                            db.add(
                                MovimientoCuentaCliente(
                                    cliente_id=venta.cliente_id,
                                    cuenta_id=cxc_ant.id,
                                    venta_id=venta.id,
                                    fecha=f_str,
                                    hora=h_str,
                                    tipo="AJUSTE_EDICION",
                                    monto=abs(delta_fi),
                                    saldo_anterior=saldo_ant_cli,
                                    saldo_nuevo=round(max(0.0, saldo_ant_cli + delta_fi), 2),
                                    metodo_pago="Fiado",
                                    usuario_id=usuario_id,
                                    terminal_id=req.terminal_id or venta.terminal_id or 1,
                                    motivo=f"Edición de venta {venta.numero}: {req.motivo}",
                                    observacion=f"Delta fiado {delta_fi:+,.2f}",
                                )
                            )
                    else:
                        cxc_new = CuentaPorCobrar(
                            cliente_id=venta.cliente_id,
                            venta_id=venta.id,
                            fecha=f_str,
                            hora=h_str,
                            monto_original=nuevo_total,
                            saldo_pendiente=nuevo_total,
                            estado="Pendiente",
                        )
                        db.add(cxc_new)
                        await db.flush()
                        await ClienteService.registrar_movimiento_fiado(
                            db=db,
                            cliente_id=venta.cliente_id,
                            cuenta_id=cxc_new.id,
                            venta_id=venta.id,
                            monto=nuevo_total,
                            usuario_id=usuario_id,
                            terminal_id=req.terminal_id or venta.terminal_id or 1,
                            observacion=f"Cambio a Fiado por edición Venta {venta.numero}: {req.motivo}",
                            fecha_str=f_str,
                            hora_str=h_str,
                        )

                fecha_anterior = str(venta.fecha or "")
                hora_anterior = str(venta.hora or "")
                nueva_f = getattr(req, "nueva_fecha", None)
                nueva_h = getattr(req, "nueva_hora", None)
                cambio_fecha = False
                cambio_hora = False

                if nueva_f and str(nueva_f).strip():
                    f_norm = normalizar_fecha(str(nueva_f).strip())
                    try:
                        datetime.strptime(f_norm[:10], "%Y-%m-%d")
                        if f_norm[:10] != fecha_anterior:
                            venta.fecha = f_norm[:10]
                            venta.es_venta_atrasada = True
                            venta.motivo_modificacion_fecha = req.motivo
                            cambio_fecha = True
                        else:
                            venta.fecha = f_norm[:10]
                    except ValueError:
                        raise HTTPException(status_code=400, detail="El formato de la nueva fecha debe ser YYYY-MM-DD o DD/MM/YYYY.")

                if nueva_h and str(nueva_h).strip():
                    try:
                        h_norm = normalizar_hora(str(nueva_h).strip())
                        if h_norm != hora_anterior:
                            venta.hora = h_norm
                            cambio_hora = True
                        else:
                            venta.hora = h_norm
                    except ValueError as ve:
                        raise HTTPException(status_code=400, detail=f"Formato de hora inválido: {ve}")

                venta.subtotal = nuevo_total
                venta.total = nuevo_total
                venta.metodo_pago_principal = nuevo_metodo
                venta.recibido = 0.0 if nuevo_metodo == "Fiado" else nuevo_total
                venta.cambio = 0.0
                venta.saldo_pendiente = nuevo_total if nuevo_metodo == "Fiado" else 0.0
                venta.modificado_por = admin_nom
                venta.fecha_modificacion = f"{f_str} {h_str}"

                await db.commit()
                await log_audit(
                    db,
                    usuario_id,
                    admin_nom,
                    req.terminal_id or 1,
                    "Terminal",
                    "EDICION",
                    "VENTAS",
                    "ventas",
                    str(venta.id),
                    valor_anterior={"total": total_anterior, "metodo": metodo_anterior, "fecha": fecha_anterior, "hora": hora_anterior},
                    valor_nuevo={
                        "total": nuevo_total,
                        "metodo": nuevo_metodo,
                        "fecha": venta.fecha,
                        "hora": venta.hora,
                        "motivo": req.motivo,
                        "cambio_fecha": cambio_fecha,
                        "cambio_hora": cambio_hora,
                    },
                )
                return {
                    "ok": True,
                    "success": True,
                    "id_venta": venta.id,
                    "total_anterior": total_anterior,
                    "nuevo_total": nuevo_total,
                    "delta_monto": round(nuevo_total - total_anterior, 2),
                    "motivo": req.motivo,
                    "fecha": venta.fecha,
                    "hora": venta.hora,
                    "cambio_fecha": cambio_fecha,
                    "cambio_hora": cambio_hora,
                }
            except HTTPException:
                await db.rollback()
                raise
            except Exception as e:
                await db.rollback()
                raise HTTPException(status_code=400, detail=str(e))
