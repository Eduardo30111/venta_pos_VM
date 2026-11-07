import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func, or_
from fastapi import HTTPException
from typing import Optional, List, Dict, Any
from datetime import datetime, date

from ..models.cliente import Cliente
from ..models.finanzas import CuentaPorCobrar, Abono, MovimientoCuentaCliente
from ..models.venta import Venta, Pago
from ..models.usuario import Usuario
from ..middleware.audit import log_audit
from .caja_service import CajaService

class _LazyAsyncLock:
    def __init__(self):
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def __aenter__(self):
        return await self._get_lock().__aenter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return await self._get_lock().__aexit__(exc_type, exc_val, exc_tb)


_ABONO_LOCK = _LazyAsyncLock()


def normalizar_metodo_abono(metodo: str) -> str:
    m = (metodo or "").strip().lower()
    if m in ("efectivo", "cash"):
        return "Efectivo"
    if m in ("transferencia", "nequi", "daviplata", "bancolombia", "banco", "qr"):
        return "Transferencia"
    raise HTTPException(
        status_code=400,
        detail=f"Método de pago inválido para abono: '{metodo}'. Use 'Efectivo' o 'Transferencia'.",
    )


class ClienteService:
    @staticmethod
    async def obtener_saldo_cliente(db: AsyncSession, cliente_id: int) -> float:
        res = await db.execute(
            select(func.sum(CuentaPorCobrar.saldo_pendiente))
            .where(CuentaPorCobrar.cliente_id == cliente_id, CuentaPorCobrar.estado == "Pendiente")
        )
        return round(float(res.scalar() or 0.0), 2)

    @staticmethod
    async def registrar_movimiento_fiado(
        db: AsyncSession,
        cliente_id: int,
        cuenta_id: int,
        venta_id: int,
        monto: float,
        usuario_id: int,
        terminal_id: Optional[int] = None,
        observacion: Optional[str] = None,
        fecha_str: Optional[str] = None,
        hora_str: Optional[str] = None,
    ) -> MovimientoCuentaCliente:
        """
        Registra el movimiento contable cuando nace una deuda por venta fiada.
        """
        ahora = datetime.now()
        f_str = fecha_str or ahora.strftime("%Y-%m-%d")
        h_str = hora_str or ahora.strftime("%H:%M:%S")

        res_prev = await db.execute(
            select(func.sum(CuentaPorCobrar.saldo_pendiente))
            .where(
                CuentaPorCobrar.cliente_id == cliente_id,
                CuentaPorCobrar.estado == "Pendiente",
                CuentaPorCobrar.id != cuenta_id,
            )
        )
        saldo_ant = round(float(res_prev.scalar() or 0.0), 2)
        saldo_nuevo = round(saldo_ant + float(monto), 2)

        mov = MovimientoCuentaCliente(
            cliente_id=cliente_id,
            cuenta_id=cuenta_id,
            venta_id=venta_id,
            abono_id=None,
            fecha=f_str,
            hora=h_str,
            tipo="FIADO",
            monto=round(float(monto), 2),
            saldo_anterior=saldo_ant,
            saldo_nuevo=saldo_nuevo,
            metodo_pago="Fiado",
            usuario_id=usuario_id,
            terminal_id=terminal_id,
            motivo="Venta a crédito",
            observacion=observacion,
        )
        db.add(mov)
        await db.flush()
        return mov

    @staticmethod
    async def registrar_abono_fifo(
        db: AsyncSession,
        cliente_id: int,
        monto: float,
        metodo: str,
        usuario_id: int,
        usuario_nombre: Optional[str] = None,
        terminal_id: Optional[int] = None,
        sesion_caja_id: Optional[int] = None,
        cuenta_id_especifica: Optional[int] = None,
        observacion: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Aplica un abono a la cartera del cliente usando estrategia FIFO (cuentas más antiguas primero).
        Garantiza idempotencia, actualización de Caja o Transferencia, e inmutabilidad en libro mayor.
        """
        monto_clean = round(float(monto or 0.0), 2)
        if monto_clean <= 0:
            raise HTTPException(status_code=400, detail="El valor del abono debe ser mayor a 0")

        metodo_norm = normalizar_metodo_abono(metodo)
        idem_clean = (idempotency_key or "").strip() or None

        async with _ABONO_LOCK:
            if idem_clean:
                dup_res = await db.execute(
                    select(Abono).where(
                        or_(
                            Abono.idempotency_key == idem_clean,
                            Abono.idempotency_key.like(f"{idem_clean}:%"),
                        )
                    )
                )
                existentes = dup_res.scalars().all()
                if existentes:
                    primer_ab = existentes[0]
                    mov_dup_res = await db.execute(
                        select(MovimientoCuentaCliente).where(MovimientoCuentaCliente.abono_id == primer_ab.id)
                    )
                    mov_dup = mov_dup_res.scalars().first()
                    saldo_actual = await ClienteService.obtener_saldo_cliente(db, cliente_id)
                    return {
                        "ok": True,
                        "ya_existia_idempotencia": True,
                        "cliente_id": cliente_id,
                        "monto_abonado": round(sum(float(a.monto or 0.0) for a in existentes), 2),
                        "metodo": primer_ab.metodo,
                        "saldo_anterior": float(mov_dup.saldo_anterior) if mov_dup else round(saldo_actual + monto_clean, 2),
                        "saldo_nuevo": float(mov_dup.saldo_nuevo) if mov_dup else saldo_actual,
                        "movimiento_id": mov_dup.id if mov_dup else primer_ab.id,
                        "abonos_count": len(existentes),
                    }

            # 1. Bloqueo de fila del cliente
            cli_res = await db.execute(
                select(Cliente).with_for_update().where(Cliente.id == cliente_id)
            )
            cliente = cli_res.scalars().first()
            if not cliente:
                raise HTTPException(status_code=404, detail="Cliente no encontrado")

            if not usuario_nombre:
                u_res = await db.execute(select(Usuario).where(Usuario.id == usuario_id))
                u_obj = u_res.scalars().first()
                usuario_nombre = (
                    (f"{u_obj.nombre or ''} {u_obj.apellidos or ''}".strip() or u_obj.usuario)
                    if u_obj
                    else f"Usuario #{usuario_id}"
                )

            # 2. Bloqueo de cuentas por cobrar pendientes (FIFO)
            query_cxc = (
                select(CuentaPorCobrar)
                .with_for_update()
                .where(CuentaPorCobrar.cliente_id == cliente_id, CuentaPorCobrar.estado == "Pendiente")
                .order_by(CuentaPorCobrar.created_at.asc(), CuentaPorCobrar.id.asc())
            )
            if cuenta_id_especifica:
                query_cxc = query_cxc.where(CuentaPorCobrar.id == cuenta_id_especifica)

            cxc_res = await db.execute(query_cxc)
            cuentas_pendientes = cxc_res.scalars().all()

            saldo_total = round(sum(float(c.saldo_pendiente or 0.0) for c in cuentas_pendientes), 2)
            if saldo_total <= 0:
                raise HTTPException(status_code=400, detail="El cliente no tiene saldo pendiente por pagar")

            if monto_clean > (saldo_total + 0.009):
                raise HTTPException(
                    status_code=400,
                    detail=f"El abono (${monto_clean:,.0f}) no puede ser superior al saldo pendiente (${saldo_total:,.0f})",
                )

            ahora = datetime.now()
            f_str = ahora.strftime("%Y-%m-%d")
            h_str = ahora.strftime("%H:%M:%S")

            saldo_anterior = saldo_total
            monto_restante = monto_clean
            abonos_creados = []
            primer_abono_id = None

            # 3. Distribuir el abono por FIFO
            for idx, cxc in enumerate(cuentas_pendientes):
                if monto_restante <= 0.0001:
                    break

                pago_en_esta = round(min(monto_restante, float(cxc.saldo_pendiente or 0.0)), 2)
                cxc.saldo_pendiente = round(float(cxc.saldo_pendiente or 0.0) - pago_en_esta, 2)
                if cxc.saldo_pendiente <= 0.009:
                    cxc.saldo_pendiente = 0.0
                    cxc.estado = "Pagada"

                # Sincronizar saldo_pendiente de la venta originadora si existe
                if cxc.venta_id:
                    v_res = await db.execute(select(Venta).where(Venta.id == cxc.venta_id))
                    v_obj = v_res.scalars().first()
                    if v_obj:
                        v_obj.saldo_pendiente = cxc.saldo_pendiente

                idem_abono = None
                if idem_clean:
                    idem_abono = idem_clean if idx == 0 else f"{idem_clean}:{idx}"

                abono_obj = Abono(
                    idempotency_key=idem_abono,
                    cuenta_id=cxc.id,
                    fecha=f_str,
                    hora=h_str,
                    monto=pago_en_esta,
                    metodo=metodo_norm,
                    recibido_por=usuario_id,
                    observacion=observacion,
                )
                db.add(abono_obj)
                await db.flush()
                if primer_abono_id is None:
                    primer_abono_id = abono_obj.id
                abonos_creados.append(abono_obj)

                monto_restante = round(monto_restante - pago_en_esta, 2)

            saldo_nuevo = round(max(0.0, saldo_anterior - monto_clean), 2)

            # 4. Registrar movimiento contable en libro mayor del cliente
            mov = MovimientoCuentaCliente(
                cliente_id=cliente_id,
                cuenta_id=cuentas_pendientes[0].id if cuentas_pendientes else None,
                venta_id=cuentas_pendientes[0].venta_id if cuentas_pendientes else None,
                abono_id=primer_abono_id,
                fecha=f_str,
                hora=h_str,
                tipo="ABONO",
                monto=monto_clean,
                saldo_anterior=saldo_anterior,
                saldo_nuevo=saldo_nuevo,
                metodo_pago=metodo_norm,
                usuario_id=usuario_id,
                terminal_id=terminal_id,
                motivo="Abono a cartera",
                observacion=observacion,
            )
            db.add(mov)
            await db.flush()

            # 5. Registrar ingreso real en Caja (si Efectivo) o Banco (si Transferencia). NUNCA como nueva venta.
            cuenta_dest = "CAJA_FISICA" if metodo_norm == "Efectivo" else "BANCO_TRANSFERENCIA"
            tipo_fin = "ABONO_EFECTIVO" if metodo_norm == "Efectivo" else "ABONO_TRANSFERENCIA"
            await CajaService.registrar_movimiento_financiero(
                db=db,
                tipo=tipo_fin,
                concepto=f"Abono a deuda cliente: {cliente.nombre} ({cliente.documento})",
                monto=monto_clean,
                metodo_pago=metodo_norm,
                cuenta_afectada=cuenta_dest,
                usuario=usuario_nombre,
                referencia_origen=f"ABONO-{primer_abono_id or mov.id}",
                sesion_id=sesion_caja_id,
                observaciones=observacion or f"Abono FIFO cliente ID {cliente_id}",
                sincronizar_caja=(metodo_norm == "Efectivo"),
                fecha_str=f_str,
                hora_str=h_str,
            )

            # 6. Auditoría con el usuario que recibe el dinero
            await log_audit(
                db=db,
                usuario_id=usuario_id,
                usuario_nombre=usuario_nombre,
                terminal_id=terminal_id,
                terminal_nombre=f"Terminal-{terminal_id or 1}",
                accion="REGISTRAR_ABONO",
                modulo="CLIENTES",
                tabla_afectada="movimientos_cliente",
                registro_id=str(mov.id),
                valor_anterior={"saldo_anterior": saldo_anterior, "cliente": cliente.nombre},
                valor_nuevo={
                    "abono": monto_clean,
                    "saldo_nuevo": saldo_nuevo,
                    "metodo": metodo_norm,
                    "recibido_por": usuario_nombre,
                },
            )

            return {
                "ok": True,
                "ya_existia_idempotencia": False,
                "cliente_id": cliente_id,
                "cliente_nombre": cliente.nombre,
                "cliente_documento": cliente.documento,
                "monto_abonado": monto_clean,
                "metodo": metodo_norm,
                "recibido_por": usuario_nombre,
                "fecha": f_str,
                "hora": h_str,
                "saldo_anterior": saldo_anterior,
                "saldo_nuevo": saldo_nuevo,
                "movimiento_id": mov.id,
                "abono_id": primer_abono_id,
                "abonos_count": len(abonos_creados),
            }

    @staticmethod
    async def registrar_ajuste_manual(
        db: AsyncSession,
        cliente_id: int,
        monto_ajuste: float,
        motivo: str,
        usuario_id: int,
        usuario_nombre: Optional[str] = None,
        terminal_id: Optional[int] = None,
        observacion: Optional[str] = None,
    ) -> MovimientoCuentaCliente:
        if not motivo or not motivo.strip():
            raise HTTPException(status_code=400, detail="El motivo del ajuste es estrictamente obligatorio")

        cli_res = await db.execute(
            select(Cliente).with_for_update().where(Cliente.id == cliente_id)
        )
        cliente = cli_res.scalars().first()
        if not cliente:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")

        if not usuario_nombre:
            u_res = await db.execute(select(Usuario).where(Usuario.id == usuario_id))
            u_obj = u_res.scalars().first()
            usuario_nombre = u_obj.nombre if u_obj else f"Usuario #{usuario_id}"

        ahora = datetime.now()
        f_str = ahora.strftime("%Y-%m-%d")
        h_str = ahora.strftime("%H:%M:%S")
        saldo_anterior = await ClienteService.obtener_saldo_cliente(db, cliente_id)

        if monto_ajuste < 0:
            monto_abs = round(abs(float(monto_ajuste)), 2)
            if monto_abs > (saldo_anterior + 0.009):
                raise HTTPException(
                    status_code=400,
                    detail=f"El ajuste negativo (${monto_abs:,.0f}) excede el saldo pendiente (${saldo_anterior:,.0f})",
                )

            monto_restante = monto_abs
            cxc_res = await db.execute(
                select(CuentaPorCobrar)
                .with_for_update()
                .where(CuentaPorCobrar.cliente_id == cliente_id, CuentaPorCobrar.estado == "Pendiente")
                .order_by(CuentaPorCobrar.created_at.asc(), CuentaPorCobrar.id.asc())
            )
            for cxc in cxc_res.scalars().all():
                if monto_restante <= 0.0001:
                    break
                p = round(min(monto_restante, float(cxc.saldo_pendiente or 0.0)), 2)
                cxc.saldo_pendiente = round(float(cxc.saldo_pendiente or 0.0) - p, 2)
                if cxc.saldo_pendiente <= 0.009:
                    cxc.saldo_pendiente = 0.0
                    cxc.estado = "Pagada"
                monto_restante = round(monto_restante - p, 2)

            saldo_nuevo = round(max(0.0, saldo_anterior - monto_abs), 2)
        else:
            monto_pos = round(float(monto_ajuste), 2)
            cxc_ajuste = CuentaPorCobrar(
                cliente_id=cliente_id,
                venta_id=None,
                fecha=f_str,
                hora=h_str,
                monto_original=monto_pos,
                saldo_pendiente=monto_pos,
                estado="Pendiente",
            )
            db.add(cxc_ajuste)
            await db.flush()
            saldo_nuevo = round(saldo_anterior + monto_pos, 2)

        mov = MovimientoCuentaCliente(
            cliente_id=cliente_id,
            fecha=f_str,
            hora=h_str,
            tipo="AJUSTE_MANUAL",
            monto=round(abs(float(monto_ajuste)), 2),
            saldo_anterior=saldo_anterior,
            saldo_nuevo=saldo_nuevo,
            usuario_id=usuario_id,
            terminal_id=terminal_id,
            motivo=motivo.strip(),
            observacion=observacion,
        )
        db.add(mov)
        await db.flush()

        await log_audit(
            db=db,
            usuario_id=usuario_id,
            usuario_nombre=usuario_nombre,
            terminal_id=terminal_id,
            terminal_nombre="Terminal",
            accion="AJUSTAR_DEUDA",
            modulo="CLIENTES",
            tabla_afectada="movimientos_cliente",
            registro_id=str(mov.id),
            valor_anterior={"saldo_anterior": saldo_anterior},
            valor_nuevo={"ajuste": monto_ajuste, "saldo_nuevo": saldo_nuevo, "motivo": motivo},
        )

        return mov

    @staticmethod
    async def revertir_fiado_por_anulacion(
        db: AsyncSession,
        venta_id: int,
        usuario_id: int,
        terminal_id: Optional[int] = None,
        motivo: str = "Anulación de venta",
    ):
        ahora = datetime.now()
        f_str = ahora.strftime("%Y-%m-%d")
        h_str = ahora.strftime("%H:%M:%S")
        cxc_res = await db.execute(
            select(CuentaPorCobrar).with_for_update().where(CuentaPorCobrar.venta_id == venta_id)
        )
        cxcs = cxc_res.scalars().all()
        for cxc in cxcs:
            if cxc.estado == "Anulada":
                continue
            saldo_ant = await ClienteService.obtener_saldo_cliente(db, cxc.cliente_id)
            monto_revertir = round(float(cxc.saldo_pendiente or 0.0), 2)

            cxc.estado = "Anulada"
            cxc.saldo_pendiente = 0.0

            saldo_post = round(max(0.0, saldo_ant - monto_revertir), 2)

            mov = MovimientoCuentaCliente(
                cliente_id=cxc.cliente_id,
                cuenta_id=cxc.id,
                venta_id=venta_id,
                fecha=f_str,
                hora=h_str,
                tipo="ANULACION",
                monto=monto_revertir,
                saldo_anterior=saldo_ant,
                saldo_nuevo=saldo_post,
                usuario_id=usuario_id,
                terminal_id=terminal_id,
                motivo=motivo,
                observacion=f"Reversión de cuenta por cobrar de venta anulada #{venta_id}",
            )
            db.add(mov)
            await db.flush()
