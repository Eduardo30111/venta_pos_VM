from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func
from fastapi import HTTPException
from typing import Optional, List, Dict, Any
from datetime import datetime, date

from ..models.cliente import Cliente
from ..models.finanzas import CuentaPorCobrar, Abono, MovimientoCuentaCliente
from ..models.venta import Venta, Pago
from ..models.usuario import Usuario
from ..middleware.audit import log_audit

class ClienteService:
    @staticmethod
    async def obtener_saldo_cliente(db: AsyncSession, cliente_id: int) -> float:
        res = await db.execute(
            select(func.sum(CuentaPorCobrar.saldo_pendiente))
            .where(CuentaPorCobrar.cliente_id == cliente_id, CuentaPorCobrar.estado == "Pendiente")
        )
        return float(res.scalar() or 0.0)

    @staticmethod
    async def registrar_movimiento_fiado(
        db: AsyncSession,
        cliente_id: int,
        cuenta_id: int,
        venta_id: int,
        monto: float,
        usuario_id: int,
        terminal_id: Optional[int] = None,
        observacion: Optional[str] = None
    ) -> MovimientoCuentaCliente:
        """
        Registra el movimiento contable cuando nace una deuda por venta fiada.
        Calcula saldo anterior y nuevo con bloqueo pesimista previo.
        """
        # Calcular saldo anterior (excluyendo la cuenta recién agregada que ya tiene saldo_pendiente)
        res_prev = await db.execute(
            select(func.sum(CuentaPorCobrar.saldo_pendiente))
            .where(
                CuentaPorCobrar.cliente_id == cliente_id,
                CuentaPorCobrar.estado == "Pendiente",
                CuentaPorCobrar.id != cuenta_id
            )
        )
        saldo_ant = float(res_prev.scalar() or 0.0)
        saldo_nuevo = saldo_ant + monto

        mov = MovimientoCuentaCliente(
            cliente_id=cliente_id,
            cuenta_id=cuenta_id,
            venta_id=venta_id,
            abono_id=None,
            tipo="FIADO",
            monto=monto,
            saldo_anterior=saldo_ant,
            saldo_nuevo=saldo_nuevo,
            metodo_pago="Fiado",
            usuario_id=usuario_id,
            terminal_id=terminal_id,
            motivo="Venta a crédito",
            observacion=observacion
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
        terminal_id: Optional[int] = None,
        cuenta_id_especifica: Optional[int] = None,
        observacion: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Aplica un abono a la cartera del cliente usando estrategia FIFO (cuentas más antiguas primero).
        Garantiza consistencia contable y bloqueo a nivel de fila.
        """
        if monto <= 0:
            raise HTTPException(status_code=400, detail="El valor del abono debe ser mayor a 0")

        # 1. Bloqueo de fila del cliente
        cli_res = await db.execute(
            select(Cliente).with_for_update().where(Cliente.id == cliente_id)
        )
        cliente = cli_res.scalars().first()
        if not cliente:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")

        # 2. Bloqueo de las cuentas por cobrar pendientes
        query_cxc = (
            select(CuentaPorCobrar)
            .with_for_update()
            .where(CuentaPorCobrar.cliente_id == cliente_id, CuentaPorCobrar.estado == "Pendiente")
            .order_by(CuentaPorCobrar.created_at.asc())
        )
        if cuenta_id_especifica:
            query_cxc = query_cxc.where(CuentaPorCobrar.id == cuenta_id_especifica)

        cxc_res = await db.execute(query_cxc)
        cuentas_pendientes = cxc_res.scalars().all()

        saldo_total = sum(c.saldo_pendiente for c in cuentas_pendientes)
        if saldo_total <= 0:
            raise HTTPException(status_code=400, detail="El cliente no tiene saldo pendiente por pagar")

        if monto > saldo_total:
            raise HTTPException(
                status_code=400,
                detail=f"El abono (${monto:,.0f}) no puede ser superior al saldo pendiente (${saldo_total:,.0f})"
            )

        saldo_anterior = saldo_total
        monto_restante = monto
        abonos_creados = []
        primer_abono_id = None

        # 3. Distribuir el abono por FIFO
        for cxc in cuentas_pendientes:
            if monto_restante <= 0:
                break
            
            pago_en_esta = min(monto_restante, cxc.saldo_pendiente)
            cxc.saldo_pendiente -= pago_en_esta
            if cxc.saldo_pendiente <= 0.0001:
                cxc.saldo_pendiente = 0.0
                cxc.estado = "Pagada"

            abono_obj = Abono(
                cuenta_id=cxc.id,
                monto=pago_en_esta,
                metodo=metodo,
                recibido_por=usuario_id,
                observacion=observacion
            )
            db.add(abono_obj)
            await db.flush()
            if primer_abono_id is None:
                primer_abono_id = abono_obj.id
            abonos_creados.append(abono_obj)

            monto_restante -= pago_en_esta

        saldo_nuevo = saldo_anterior - monto

        # 4. Registrar movimiento contable inmutable
        mov = MovimientoCuentaCliente(
            cliente_id=cliente_id,
            cuenta_id=cuentas_pendientes[0].id if cuentas_pendientes else None,
            venta_id=cuentas_pendientes[0].venta_id if cuentas_pendientes else None,
            abono_id=primer_abono_id,
            tipo="ABONO",
            monto=monto,
            saldo_anterior=saldo_anterior,
            saldo_nuevo=saldo_nuevo,
            metodo_pago=metodo,
            usuario_id=usuario_id,
            terminal_id=terminal_id,
            motivo="Abono a cartera",
            observacion=observacion
        )
        db.add(mov)
        await db.flush()

        # 5. Auditoría
        await log_audit(
            db=db,
            usuario_id=usuario_id,
            usuario_nombre=cliente.nombre,
            terminal_id=terminal_id,
            terminal_nombre="Terminal",
            accion="REGISTRAR_ABONO",
            modulo="CLIENTES",
            tabla_afectada="movimientos_cliente",
            registro_id=str(mov.id),
            valor_anterior={"saldo_anterior": saldo_anterior},
            valor_nuevo={"abono": monto, "saldo_nuevo": saldo_nuevo, "metodo": metodo}
        )

        return {
            "cliente_id": cliente_id,
            "monto_abonado": monto,
            "metodo": metodo,
            "saldo_anterior": saldo_anterior,
            "saldo_nuevo": saldo_nuevo,
            "movimiento_id": mov.id,
            "abonos_count": len(abonos_creados)
        }

    @staticmethod
    async def registrar_ajuste_manual(
        db: AsyncSession,
        cliente_id: int,
        monto_ajuste: float,
        motivo: str,
        usuario_id: int,
        terminal_id: Optional[int] = None,
        observacion: Optional[str] = None
    ) -> MovimientoCuentaCliente:
        """
        Permite a un administrador ajustar manualmente una deuda con motivo obligatorio.
        Si monto_ajuste > 0, incrementa la deuda creando una cuenta de ajuste.
        Si monto_ajuste < 0, reduce la deuda mediante FIFO.
        """
        if not motivo or not motivo.strip():
            raise HTTPException(status_code=400, detail="El motivo del ajuste es estrictamente obligatorio")

        cli_res = await db.execute(
            select(Cliente).with_for_update().where(Cliente.id == cliente_id)
        )
        cliente = cli_res.scalars().first()
        if not cliente:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")

        saldo_anterior = await ClienteService.obtener_saldo_cliente(db, cliente_id)

        if monto_ajuste < 0:
            monto_abs = abs(monto_ajuste)
            if monto_abs > saldo_anterior:
                raise HTTPException(
                    status_code=400,
                    detail=f"El ajuste negativo (${monto_abs:,.0f}) excede el saldo pendiente (${saldo_anterior:,.0f})"
                )
            
            # Reducción por FIFO
            monto_restante = monto_abs
            cxc_res = await db.execute(
                select(CuentaPorCobrar)
                .with_for_update()
                .where(CuentaPorCobrar.cliente_id == cliente_id, CuentaPorCobrar.estado == "Pendiente")
                .order_by(CuentaPorCobrar.created_at.asc())
            )
            for cxc in cxc_res.scalars().all():
                if monto_restante <= 0:
                    break
                p = min(monto_restante, cxc.saldo_pendiente)
                cxc.saldo_pendiente -= p
                if cxc.saldo_pendiente <= 0.0001:
                    cxc.saldo_pendiente = 0.0
                    cxc.estado = "Pagada"
                monto_restante -= p

            saldo_nuevo = saldo_anterior - monto_abs
        else:
            # Incremento de deuda manual
            cxc_ajuste = CuentaPorCobrar(
                cliente_id=cliente_id,
                venta_id=None,
                monto_original=monto_ajuste,
                saldo_pendiente=monto_ajuste,
                estado="Pendiente"
            )
            db.add(cxc_ajuste)
            await db.flush()
            saldo_nuevo = saldo_anterior + monto_ajuste

        mov = MovimientoCuentaCliente(
            cliente_id=cliente_id,
            tipo="AJUSTE_MANUAL",
            monto=abs(monto_ajuste),
            saldo_anterior=saldo_anterior,
            saldo_nuevo=saldo_nuevo,
            usuario_id=usuario_id,
            terminal_id=terminal_id,
            motivo=motivo.strip(),
            observacion=observacion
        )
        db.add(mov)
        await db.flush()

        await log_audit(
            db=db,
            usuario_id=usuario_id,
            usuario_nombre=cliente.nombre,
            terminal_id=terminal_id,
            terminal_nombre="Terminal",
            accion="AJUSTAR_DEUDA",
            modulo="CLIENTES",
            tabla_afectada="movimientos_cliente",
            registro_id=str(mov.id),
            valor_anterior={"saldo_anterior": saldo_anterior},
            valor_nuevo={"ajuste": monto_ajuste, "saldo_nuevo": saldo_nuevo, "motivo": motivo}
        )

        return mov

    @staticmethod
    async def revertir_fiado_por_anulacion(
        db: AsyncSession,
        venta_id: int,
        usuario_id: int,
        terminal_id: Optional[int] = None,
        motivo: str = "Anulación de venta"
    ):
        """
        Reversa el crédito generado por una venta que fue anulada.
        """
        cxc_res = await db.execute(
            select(CuentaPorCobrar).with_for_update().where(CuentaPorCobrar.venta_id == venta_id)
        )
        cxcs = cxc_res.scalars().all()
        for cxc in cxcs:
            if cxc.estado == "Anulada":
                continue
            saldo_ant = await ClienteService.obtener_saldo_cliente(db, cxc.cliente_id)
            monto_revertir = cxc.saldo_pendiente
            
            cxc.estado = "Anulada"
            cxc.saldo_pendiente = 0.0

            saldo_post = max(0.0, saldo_ant - monto_revertir)

            mov = MovimientoCuentaCliente(
                cliente_id=cxc.cliente_id,
                cuenta_id=cxc.id,
                venta_id=venta_id,
                tipo="ANULACION",
                monto=monto_revertir,
                saldo_anterior=saldo_ant,
                saldo_nuevo=saldo_post,
                usuario_id=usuario_id,
                terminal_id=terminal_id,
                motivo=motivo,
                observacion=f"Reversión de cuenta por cobrar de venta anulada #{venta_id}"
            )
            db.add(mov)
            await db.flush()
