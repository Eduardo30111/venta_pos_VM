from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from fastapi import HTTPException

from ..models.caja import SesionCaja, MovimientoCaja, MovimientoFinanciero
from ..models.venta import Venta, Pago
from ..models.finanzas import CuentaPorCobrar


class CajaService:
    @staticmethod
    async def obtener_sesion_activa(db: AsyncSession) -> Optional[SesionCaja]:
        try:
            res = await db.execute(
                select(SesionCaja)
                .where(SesionCaja.estado == "Abierta")
                .order_by(SesionCaja.id.desc())
                .limit(1)
            )
            return res.scalars().first()
        except Exception as e:
            err_msg = str(e).lower()
            if "no such column" in err_msg or "operationalerror" in err_msg:
                try:
                    from sqlalchemy import text
                    cols_caja = [
                        ("arqueo_apertura_json", "TEXT"),
                        ("monto_transferencias_esperado", "FLOAT DEFAULT 0.0"),
                        ("monto_transferencias_verificado", "FLOAT DEFAULT 0.0"),
                        ("diferencia_banco", "FLOAT DEFAULT 0.0"),
                        ("estado_banco", "VARCHAR DEFAULT 'Pendiente'"),
                        ("terminal_id", "INTEGER"),
                        ("terminal_nombre", "VARCHAR"),
                        ("observaciones", "VARCHAR"),
                        ("fecha_cierre", "VARCHAR"),
                        ("hora_cierre", "VARCHAR"),
                        ("usuario_cierre", "VARCHAR"),
                        ("monto_esperado_efectivo", "FLOAT DEFAULT 0.0"),
                        ("monto_real_contado", "FLOAT DEFAULT 0.0"),
                        ("diferencia", "FLOAT DEFAULT 0.0"),
                        ("created_at", "TIMESTAMP"),
                    ]
                    for c_nom, c_def in cols_caja:
                        try:
                            await db.execute(text(f"ALTER TABLE sesiones_caja ADD COLUMN {c_nom} {c_def}"))
                        except Exception:
                            pass
                    await db.commit()
                    res = await db.execute(
                        select(SesionCaja)
                        .where(SesionCaja.estado == "Abierta")
                        .order_by(SesionCaja.id.desc())
                        .limit(1)
                    )
                    return res.scalars().first()
                except Exception as e_repair:
                    print(f"Aviso auto-reparando esquema sesiones_caja: {e_repair}")
                    return None
            return None

    @staticmethod
    async def abrir_sesion(
        db: AsyncSession,
        usuario: str = "Administrador",
        monto_inicial: float = 0.0,
        terminal_id: Optional[int] = 1,
        terminal_nombre: Optional[str] = "CAJA-01",
        arqueo_apertura: Optional[Any] = None,
    ) -> SesionCaja:
        activa = await CajaService.obtener_sesion_activa(db)
        if activa:
            return activa

        import json
        ahora = datetime.now()
        f_str = ahora.strftime("%Y-%m-%d")
        h_str = ahora.strftime("%H:%M:%S")
        monto_ini = max(0.0, float(monto_inicial or 0.0))
        arq_json = json.dumps(arqueo_apertura, ensure_ascii=False) if isinstance(arqueo_apertura, (dict, list)) else (arqueo_apertura if isinstance(arqueo_apertura, str) else None)

        sesion = SesionCaja(
            fecha_apertura=f_str,
            hora_apertura=h_str,
            usuario_apertura=usuario or "Administrador",
            terminal_id=terminal_id,
            terminal_nombre=terminal_nombre or "CAJA-01",
            monto_inicial=monto_ini,
            arqueo_apertura_json=arq_json,
            estado="Abierta",
        )
        db.add(sesion)
        await db.flush()

        mov_caja = MovimientoCaja(
            sesion_caja_id=sesion.id,
            fecha=f_str,
            hora=h_str,
            tipo="APERTURA",
            monto=monto_ini,
            usuario=usuario or "Administrador",
            terminal=terminal_nombre or "CAJA-01",
            referencia_id=f"SESION-{sesion.id}",
            descripcion="Apertura de turno con base inicial",
        )
        db.add(mov_caja)

        mov_fin = MovimientoFinanciero(
            fecha=f_str,
            hora=h_str,
            tipo="APERTURA_CAJA",
            concepto="Apertura de turno con base inicial",
            monto=monto_ini,
            metodo_pago="Efectivo",
            cuenta_afectada="CAJA_FISICA",
            usuario=usuario or "Administrador",
            referencia_origen=f"SESION-{sesion.id}",
            sesion_caja_id=sesion.id,
            estado="Activo",
            observaciones="Base inicial de gaveta",
        )
        db.add(mov_fin)
        await db.flush()
        return sesion

    @staticmethod
    async def registrar_movimiento_caja(
        db: AsyncSession,
        tipo: str,
        monto: float,
        usuario: str = "Administrador",
        terminal: str = "CAJA-01",
        referencia_id: Optional[str] = None,
        descripcion: str = "",
        sesion_id: Optional[int] = None,
        sincronizar_financiero: bool = True,
        fecha_str: Optional[str] = None,
        hora_str: Optional[str] = None,
    ) -> MovimientoCaja:
        ahora = datetime.now()
        f_str = fecha_str or ahora.strftime("%Y-%m-%d")
        h_str = hora_str or ahora.strftime("%H:%M:%S")

        if not sesion_id:
            activa = await CajaService.obtener_sesion_activa(db)
            if activa:
                sesion_id = activa.id
            else:
                nueva = await CajaService.abrir_sesion(
                    db=db,
                    usuario=usuario,
                    monto_inicial=0.0,
                    terminal_nombre=terminal,
                )
                sesion_id = nueva.id

        mov = MovimientoCaja(
            sesion_caja_id=sesion_id,
            fecha=f_str,
            hora=h_str,
            tipo=tipo,
            monto=float(monto),
            usuario=usuario or "Administrador",
            terminal=terminal or "CAJA-01",
            referencia_id=str(referencia_id or ""),
            descripcion=descripcion or f"Movimiento {tipo}",
        )
        db.add(mov)
        await db.flush()

        if sincronizar_financiero and tipo != "CIERRE":
            tipo_fin_map = {
                "APERTURA": "APERTURA_CAJA",
                "VENTA_EFECTIVO": "VENTA_EFECTIVO",
                "ABONO_EFECTIVO": "ABONO_EFECTIVO",
                "EGRESO": "GASTO_PAGADO",
                "RETIRO": "RETIRO_CAJA",
                "AJUSTE": "AJUSTE_AUTORIZADO",
                "DEVOLUCION_VENTA": "DEVOLUCION_VENTA",
            }
            tipo_f = tipo_fin_map.get(tipo, "AJUSTE_AUTORIZADO")
            mf = MovimientoFinanciero(
                fecha=f_str,
                hora=h_str,
                tipo=tipo_f,
                concepto=descripcion or f"Movimiento {tipo}",
                monto=float(monto),
                metodo_pago="Efectivo",
                cuenta_afectada="CAJA_FISICA",
                usuario=usuario or "Administrador",
                referencia_origen=str(referencia_id or mov.id),
                sesion_caja_id=sesion_id,
                estado="Activo",
                observaciones=f"Sincronizado desde caja física #{mov.id}",
            )
            db.add(mf)
            await db.flush()

        return mov

    @staticmethod
    async def registrar_movimiento_financiero(
        db: AsyncSession,
        tipo: str,
        concepto: str,
        monto: float,
        metodo_pago: str = "Efectivo",
        cuenta_afectada: str = "CAJA_FISICA",
        usuario: str = "Administrador",
        referencia_origen: str = "",
        sesion_id: Optional[int] = None,
        observaciones: str = "",
        estado: str = "Activo",
        sincronizar_caja: bool = True,
        terminal: str = "CAJA-01",
        fecha_str: Optional[str] = None,
        hora_str: Optional[str] = None,
    ) -> MovimientoFinanciero:
        ahora = datetime.now()
        f_str = fecha_str or ahora.strftime("%Y-%m-%d")
        h_str = hora_str or ahora.strftime("%H:%M:%S")

        if not sesion_id and cuenta_afectada == "CAJA_FISICA":
            activa = await CajaService.obtener_sesion_activa(db)
            if activa:
                sesion_id = activa.id
            elif sincronizar_caja:
                nueva = await CajaService.abrir_sesion(
                    db=db,
                    usuario=usuario,
                    monto_inicial=0.0,
                    terminal_nombre=terminal,
                )
                sesion_id = nueva.id

        mf = MovimientoFinanciero(
            fecha=f_str,
            hora=h_str,
            tipo=str(tipo),
            concepto=str(concepto),
            monto=float(monto),
            metodo_pago=str(metodo_pago),
            cuenta_afectada=str(cuenta_afectada),
            usuario=str(usuario or "Administrador"),
            referencia_origen=str(referencia_origen or ""),
            sesion_caja_id=sesion_id,
            estado=str(estado or "Activo"),
            observaciones=str(observaciones or ""),
        )
        db.add(mf)
        await db.flush()

        if cuenta_afectada == "CAJA_FISICA" and sincronizar_caja:
            tipo_caja_map = {
                "APERTURA_CAJA": "APERTURA",
                "VENTA_EFECTIVO": "VENTA_EFECTIVO",
                "ABONO_EFECTIVO": "ABONO_EFECTIVO",
                "GASTO_PAGADO": "EGRESO",
                "PAGO_PROVEEDOR": "EGRESO",
                "RETIRO_CAJA": "RETIRO",
                "INGRESO_EXTRAORDINARIO": "AJUSTE",
                "DEVOLUCION_VENTA": "DEVOLUCION_VENTA",
                "AJUSTE_AUTORIZADO": "AJUSTE",
            }
            t_caja = tipo_caja_map.get(tipo, "AJUSTE" if "INGRESO" in tipo else "EGRESO")
            await CajaService.registrar_movimiento_caja(
                db=db,
                tipo=t_caja,
                monto=float(monto),
                usuario=usuario,
                terminal=terminal,
                referencia_id=str(referencia_origen or mf.id),
                descripcion=concepto,
                sesion_id=sesion_id,
                sincronizar_financiero=False,
                fecha_str=f_str,
                hora_str=h_str,
            )

        return mf

    @staticmethod
    def _sesion_to_dict(s: SesionCaja) -> Dict[str, Any]:
        return {
            "id": s.id,
            "fecha_apertura": s.fecha_apertura,
            "hora_apertura": s.hora_apertura,
            "usuario_apertura": s.usuario_apertura,
            "terminal_id": s.terminal_id,
            "terminal_nombre": s.terminal_nombre,
            "monto_inicial": float(s.monto_inicial or 0.0),
            "monto_base": float(s.monto_inicial or 0.0),
            "fecha_cierre": s.fecha_cierre,
            "hora_cierre": s.hora_cierre,
            "usuario_cierre": s.usuario_cierre,
            "monto_esperado_efectivo": float(s.monto_esperado_efectivo or 0.0),
            "monto_esperado": float(s.monto_esperado_efectivo or 0.0),
            "monto_real_contado": float(s.monto_real_contado or 0.0),
            "diferencia": float(s.diferencia or 0.0),
            "monto_transferencias_esperado": float(s.monto_transferencias_esperado or 0.0),
            "monto_transferencias_verificado": float(s.monto_transferencias_verificado or 0.0),
            "diferencia_banco": float(s.diferencia_banco or 0.0),
            "estado_banco": s.estado_banco or "Pendiente",
            "observaciones": s.observaciones or "",
            "arqueo_apertura_json": getattr(s, "arqueo_apertura_json", "") or "",
            "estado": s.estado or "Abierta",
        }

    @staticmethod
    async def calcular_arqueo_sesion(db: AsyncSession, sesion_id: int) -> Dict[str, Any]:
        res_s = await db.execute(select(SesionCaja).where(SesionCaja.id == sesion_id))
        sesion = res_s.scalars().first()
        if not sesion:
            return {}

        sesion_dict = CajaService._sesion_to_dict(sesion)
        monto_inicial = float(sesion.monto_inicial or 0.0)

        res_m = await db.execute(
            select(MovimientoCaja.tipo, func.sum(MovimientoCaja.monto))
            .where(MovimientoCaja.sesion_caja_id == sesion_id)
            .group_by(MovimientoCaja.tipo)
        )
        movs = {tipo: float(total or 0.0) for tipo, total in res_m.all()}

        ventas_efectivo = movs.get("VENTA_EFECTIVO", 0.0)
        abonos_efectivo = movs.get("ABONO_EFECTIVO", 0.0)
        egresos = movs.get("EGRESO", 0.0)
        retiros = movs.get("RETIRO", 0.0)
        devoluciones = movs.get("DEVOLUCION_VENTA", 0.0)
        ajustes = movs.get("AJUSTE", 0.0)

        efectivo_esperado = (
            monto_inicial + ventas_efectivo + abonos_efectivo - egresos - retiros - devoluciones + ajustes
        )

        # Ventas completadas en esta sesión o fecha de apertura
        res_v = await db.execute(
            select(Pago.metodo, func.sum(Pago.monto))
            .join(Venta, Pago.venta_id == Venta.id)
            .where(
                Venta.estado == "Completada",
                (Venta.sesion_caja_id == sesion_id) | (Venta.fecha == sesion.fecha_apertura),
            )
            .group_by(Pago.metodo)
        )
        v_map: Dict[str, float] = {}
        for m_raw, val in res_v.all():
            m_norm = (m_raw or "Efectivo").strip().capitalize()
            v_map[m_norm] = v_map.get(m_norm, 0.0) + float(val or 0.0)

        transf_total = v_map.get("Transferencia", 0.0)
        fiado_total = v_map.get("Fiado", 0.0)
        ef_ventas_total = v_map.get("Efectivo", ventas_efectivo)

        res_b = await db.execute(
            select(MovimientoFinanciero.tipo, func.sum(MovimientoFinanciero.monto))
            .where(
                (MovimientoFinanciero.sesion_caja_id == sesion_id)
                | (MovimientoFinanciero.fecha == sesion.fecha_apertura),
                MovimientoFinanciero.cuenta_afectada == "BANCO_TRANSFERENCIA",
                MovimientoFinanciero.estado != "Anulado",
            )
            .group_by(MovimientoFinanciero.tipo)
        )
        b_movs = {t: float(val or 0.0) for t, val in res_b.all()}
        abonos_transferencia = b_movs.get("ABONO_TRANSFERENCIA", 0.0)
        gastos_transferencia = b_movs.get("GASTO_PAGADO", 0.0) + b_movs.get("PAGO_PROVEEDOR", 0.0)
        devol_transferencia = b_movs.get("DEVOLUCION_VENTA", 0.0)

        res_cxc = await db.execute(
            select(func.sum(CuentaPorCobrar.saldo_pendiente)).where(CuentaPorCobrar.estado == "Pendiente")
        )
        saldo_cartera_total = float(res_cxc.scalar() or 0.0)

        total_ventas_facturadas = ef_ventas_total + transf_total + fiado_total
        entradas_efectivo = ventas_efectivo + abonos_efectivo + (ajustes if ajustes > 0 else 0.0)
        salidas_efectivo = egresos + retiros + devoluciones + (abs(ajustes) if ajustes < 0 else 0.0)
        transferencias_esperadas = transf_total + abonos_transferencia - gastos_transferencia - devol_transferencia

        return {
            "sesion": sesion_dict,
            "monto_inicial": monto_inicial,
            "monto_base": monto_inicial,
            "entradas_efectivo": entradas_efectivo,
            "salidas_efectivo": salidas_efectivo,
            "ventas_efectivo": ventas_efectivo,
            "abonos_efectivo": abonos_efectivo,
            "ingresos_autorizados": (ajustes if ajustes > 0 else 0.0),
            "egresos": egresos,
            "retiros": retiros,
            "devoluciones": devoluciones,
            "ajustes": ajustes,
            "efectivo_esperado": efectivo_esperado,
            "monto_esperado_efectivo": efectivo_esperado,
            "monto_esperado": efectivo_esperado,
            "ventas_transferencia": transf_total,
            "abonos_transferencia": abonos_transferencia,
            "gastos_transferencia": gastos_transferencia,
            "transferencias_esperadas": transferencias_esperadas,
            "total_transferencia": transf_total,
            "ventas_fiado": fiado_total,
            "total_ventas_facturadas": total_ventas_facturadas,
            "saldo_cartera_total": saldo_cartera_total,
        }

    @staticmethod
    async def cerrar_sesion(
        db: AsyncSession,
        sesion_id: int,
        usuario: str = "Administrador",
        monto_real_contado: Optional[float] = None,
        observaciones: str = "",
        terminal: str = "CAJA-01",
        monto_transferencias_verificado: Optional[float] = None,
    ) -> Dict[str, Any]:
        res_s = await db.execute(select(SesionCaja).with_for_update().where(SesionCaja.id == sesion_id))
        sesion = res_s.scalars().first()
        if not sesion:
            raise HTTPException(status_code=404, detail=f"No se encontró la sesión de caja #{sesion_id}")
        if sesion.estado == "Cerrada":
            raise HTTPException(status_code=400, detail=f"La sesión #{sesion_id} ya fue cerrada")

        arqueo = await CajaService.calcular_arqueo_sesion(db, sesion_id)
        efectivo_esperado = float(arqueo["efectivo_esperado"])
        contado = float(monto_real_contado if monto_real_contado is not None else 0.0)
        diferencia = contado - efectivo_esperado

        transf_esperadas = float(arqueo.get("transferencias_esperadas", 0.0))
        transf_verif = (
            float(monto_transferencias_verificado)
            if monto_transferencias_verificado is not None
            else transf_esperadas
        )
        dif_banco = transf_verif - transf_esperadas
        estado_banco = "Verificada" if abs(dif_banco) < 0.01 else "Con diferencia"

        ahora = datetime.now()
        f_str = ahora.strftime("%Y-%m-%d")
        h_str = ahora.strftime("%H:%M:%S")

        sesion.estado = "Cerrada"
        sesion.fecha_cierre = f_str
        sesion.hora_cierre = h_str
        sesion.usuario_cierre = usuario or "Administrador"
        sesion.monto_esperado_efectivo = efectivo_esperado
        sesion.monto_real_contado = contado
        sesion.diferencia = diferencia
        sesion.observaciones = observaciones or ""
        sesion.monto_transferencias_esperado = transf_esperadas
        sesion.monto_transferencias_verificado = transf_verif
        sesion.diferencia_banco = dif_banco
        sesion.estado_banco = estado_banco

        mov_cierre = MovimientoCaja(
            sesion_caja_id=sesion_id,
            fecha=f_str,
            hora=h_str,
            tipo="CIERRE",
            monto=contado,
            usuario=usuario or "Administrador",
            terminal=terminal or "CAJA-01",
            referencia_id=f"CIERRE-{sesion_id}",
            descripcion=f"Cierre de caja. Diferencia: {diferencia:+,.0f} COP",
        )
        db.add(mov_cierre)
        await db.flush()

        tipo_dif = "Cuadrada" if abs(diferencia) < 0.01 else ("Faltante" if diferencia < 0 else "Sobrante")
        estado_cierre = "CUADRADA" if abs(diferencia) < 0.01 else ("CON_FALTANTE" if diferencia < 0 else "CON_SOBRANTE")
        return {
            "sesion_id": sesion_id,
            "efectivo_esperado": efectivo_esperado,
            "monto_esperado": efectivo_esperado,
            "monto_real_contado": contado,
            "monto_real_efectivo": contado,
            "diferencia": diferencia,
            "diferencia_efectivo": diferencia,
            "transferencias_esperadas": transf_esperadas,
            "transferencias_verificadas": transf_verif,
            "diferencia_banco": dif_banco,
            "estado_banco": estado_banco,
            "estado": "Cerrada",
            "tipo_diferencia": tipo_dif,
            "estado_cierre": estado_cierre,
        }
