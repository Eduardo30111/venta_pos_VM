from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func, or_
from typing import List, Optional, Dict, Any
from datetime import date, timedelta

from ..database import get_db
from ..models.cliente import Cliente
from ..models.finanzas import CuentaPorCobrar, Abono, MovimientoCuentaCliente
from ..models.venta import Venta, Pago
from ..models.usuario import Usuario
from ..schemas.cliente import (
    ClienteCreate,
    ClienteUpdate,
    ClienteResponse,
    AbonoCreate,
    AjusteDeudaCreate,
)
from ..middleware.auth import get_current_user
from ..middleware.audit import log_audit
from ..services.cliente_service import ClienteService

router = APIRouter(prefix="/clientes", tags=["clientes"])


def parse_date_range(
    fecha_filtro: Optional[str] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
):
    """Resuelve el rango de fechas local del servidor evitando desfases UTC."""
    hoy = date.today()
    if not fecha_filtro:
        return None, None
    f = fecha_filtro.lower().strip()
    if f in ("hoy", "today"):
        return hoy, hoy
    elif f in ("ayer", "yesterday"):
        ayer = hoy - timedelta(days=1)
        return ayer, ayer
    elif f in ("esta_semana", "esta semana", "this_week"):
        inicio_sem = hoy - timedelta(days=hoy.weekday())
        return inicio_sem, hoy
    elif f in ("este_mes", "este mes", "this_month"):
        inicio_mes = date(hoy.year, hoy.month, 1)
        return inicio_mes, hoy
    elif f in ("personalizado", "rango", "custom"):
        return fecha_desde or hoy, fecha_hasta or hoy
    return None, None


@router.get("")
async def list_clientes(
    busqueda: Optional[str] = None,
    nombre: Optional[str] = None,
    documento: Optional[str] = None,
    filtro_tipo: Optional[str] = Query(None, description="todos | compras | fiados"),
    fecha_filtro: Optional[str] = Query(None, description="hoy | ayer | esta_semana | este_mes | personalizado"),
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    query = select(Cliente)

    if busqueda and busqueda.strip():
        term = f"%{busqueda.strip()}%"
        query = query.where(
            or_(
                Cliente.documento.ilike(term),
                Cliente.nombre.ilike(term),
                Cliente.telefono.ilike(term),
            )
        )
    if nombre:
        query = query.where(Cliente.nombre.ilike(f"%{nombre}%"))
    if documento:
        query = query.where(Cliente.documento == documento)

    query = query.order_by(Cliente.nombre.asc())
    result = await db.execute(query)
    clientes = result.scalars().all()

    f_inicio, f_fin = parse_date_range(fecha_filtro, fecha_desde, fecha_hasta)
    f_ini_s = f_inicio.isoformat() if f_inicio else None
    f_fin_s = f_fin.isoformat() if f_fin else None

    venta_fecha_col = func.coalesce(Venta.fecha, func.date(Venta.created_at))
    cxc_fecha_col = func.coalesce(CuentaPorCobrar.fecha, func.date(CuentaPorCobrar.created_at))

    items = []
    for c in clientes:
        q_ventas = select(func.sum(Venta.total)).where(
            Venta.cliente_id == c.id,
            Venta.estado != "Anulada",
        )
        if f_ini_s and f_fin_s:
            q_ventas = q_ventas.where(venta_fecha_col >= f_ini_s, venta_fecha_col <= f_fin_s)
        res_v = await db.execute(q_ventas)
        total_compras = float(res_v.scalar() or 0.0)

        q_fiado = select(func.sum(CuentaPorCobrar.monto_original)).where(
            CuentaPorCobrar.cliente_id == c.id,
            CuentaPorCobrar.estado != "Anulada",
        )
        if f_ini_s and f_fin_s:
            q_fiado = q_fiado.where(cxc_fecha_col >= f_ini_s, cxc_fecha_col <= f_fin_s)
        res_f = await db.execute(q_fiado)
        total_fiado = float(res_f.scalar() or 0.0)

        res_d = await db.execute(
            select(func.sum(CuentaPorCobrar.saldo_pendiente)).where(
                CuentaPorCobrar.cliente_id == c.id,
                CuentaPorCobrar.estado == "Pendiente",
            )
        )
        deuda_total = round(float(res_d.scalar() or 0.0), 2)

        res_ab = await db.execute(
            select(func.sum(Abono.monto))
            .join(CuentaPorCobrar, Abono.cuenta_id == CuentaPorCobrar.id)
            .where(CuentaPorCobrar.cliente_id == c.id)
        )
        total_abonado = round(float(res_ab.scalar() or 0.0), 2)

        q_op = (
            select(Usuario.nombre, Usuario.rol)
            .select_from(Venta)
            .join(Usuario, Venta.usuario_id == Usuario.id)
            .where(Venta.cliente_id == c.id, Venta.estado != "Anulada")
            .order_by(Venta.id.desc())
            .limit(1)
        )
        if f_ini_s and f_fin_s:
            q_op = q_op.where(venta_fecha_col >= f_ini_s, venta_fecha_col <= f_fin_s)
        res_op = await db.execute(q_op)
        row_op = res_op.first()
        if row_op:
            u_nom, u_rol = row_op
            operario_venta = f"{u_nom} ({u_rol})" if u_rol else u_nom
        else:
            operario_venta = "—"

        if filtro_tipo == "compras" and total_compras <= 0:
            continue
        if filtro_tipo == "fiados" and (deuda_total <= 0 and total_fiado <= 0 and not c.permite_fiado):
            continue

        items.append(
            {
                "id": c.id,
                "documento": c.documento,
                "cedula": c.documento,
                "nombre": c.nombre,
                "email": c.email,
                "telefono": c.telefono or "",
                "direccion": c.direccion or "",
                "operario_venta": operario_venta,
                "vendedor": operario_venta,
                "permite_fiado": bool(c.permite_fiado),
                "limite_credito": float(c.limite_credito or 0.0),
                "total_compras": total_compras,
                "total_fiado": total_fiado,
                "total_abonado": total_abonado,
                "deuda_total": deuda_total,
                "saldo_pendiente": deuda_total,
                "estado": c.estado,
                "created_at": c.created_at,
            }
        )

    return items


@router.get("/fiados/resumen")
async def resumen_fiados(
    busqueda: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Devuelve la cartera de fiados desde las tablas centrales CuentaPorCobrar y Abono."""
    query = select(Cliente)
    if busqueda and busqueda.strip():
        term = f"%{busqueda.strip()}%"
        query = query.where(
            or_(
                Cliente.documento.ilike(term),
                Cliente.nombre.ilike(term),
                Cliente.telefono.ilike(term),
            )
        )
    query = query.order_by(Cliente.nombre.asc())
    res = await db.execute(query)
    clientes = res.scalars().all()

    lista_fiados = []
    for c in clientes:
        res_f = await db.execute(
            select(func.sum(CuentaPorCobrar.monto_original)).where(
                CuentaPorCobrar.cliente_id == c.id,
                CuentaPorCobrar.estado != "Anulada",
            )
        )
        total_fiado = round(float(res_f.scalar() or 0.0), 2)

        res_d = await db.execute(
            select(func.sum(CuentaPorCobrar.saldo_pendiente)).where(
                CuentaPorCobrar.cliente_id == c.id,
                CuentaPorCobrar.estado == "Pendiente",
            )
        )
        deuda_actual = round(float(res_d.scalar() or 0.0), 2)

        res_ab = await db.execute(
            select(func.sum(Abono.monto))
            .join(CuentaPorCobrar, Abono.cuenta_id == CuentaPorCobrar.id)
            .where(CuentaPorCobrar.cliente_id == c.id)
        )
        total_abonado = round(float(res_ab.scalar() or 0.0), 2)

        res_ult = await db.execute(
            select(Abono.created_at)
            .join(CuentaPorCobrar, Abono.cuenta_id == CuentaPorCobrar.id)
            .where(CuentaPorCobrar.cliente_id == c.id)
            .order_by(Abono.id.desc())
            .limit(1)
        )
        ultimo_abono = res_ult.scalar()

        q_op_f = (
            select(Usuario.nombre, Usuario.rol)
            .select_from(CuentaPorCobrar)
            .join(Venta, CuentaPorCobrar.venta_id == Venta.id)
            .join(Usuario, Venta.usuario_id == Usuario.id)
            .where(CuentaPorCobrar.cliente_id == c.id, CuentaPorCobrar.estado != "Anulada")
            .order_by(CuentaPorCobrar.id.desc())
            .limit(1)
        )
        res_opf = await db.execute(q_op_f)
        row_opf = res_opf.first()
        if row_opf:
            unom, urol = row_opf
            operario_fiado = f"{unom} ({urol})" if urol else unom
        else:
            operario_fiado = "—"

        if total_fiado > 0 or deuda_actual > 0 or c.permite_fiado:
            estado_desc = "PENDIENTE" if deuda_actual > 0 else ("PAGADO" if total_abonado > 0 else "AL DÍA")
            lista_fiados.append(
                {
                    "id": c.id,
                    "cliente_id": c.id,
                    "documento": c.documento,
                    "cedula": c.documento,
                    "nombre": c.nombre,
                    "telefono": c.telefono or "",
                    "operario_venta": operario_fiado,
                    "vendedor": operario_fiado,
                    "total_fiado": total_fiado,
                    "total_abonado": total_abonado,
                    "deuda_actual": deuda_actual,
                    "total_deuda": deuda_actual,
                    "saldo_pendiente": deuda_actual,
                    "ultimo_abono": ultimo_abono,
                    "estado": estado_desc,
                }
            )

    return lista_fiados


@router.get("/buscar-precheck")
async def precheck_cliente(
    q: str,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    term = q.strip()
    if not term:
        return {"existe": False, "cliente": None}

    res = await db.execute(
        select(Cliente)
        .where(
            or_(
                Cliente.documento == term,
                Cliente.telefono == term,
                Cliente.nombre.ilike(f"%{term}%"),
            )
        )
        .limit(1)
    )
    cli = res.scalars().first()
    if cli:
        saldo = await ClienteService.obtener_saldo_cliente(db, cli.id)
        return {
            "existe": True,
            "cliente": {
                "id": cli.id,
                "documento": cli.documento,
                "nombre": cli.nombre,
                "telefono": cli.telefono or "",
                "email": cli.email or "",
                "direccion": cli.direccion or "",
                "permite_fiado": cli.permite_fiado,
                "limite_credito": cli.limite_credito,
                "saldo_pendiente": saldo,
                "deuda_total": saldo,
                "estado": cli.estado,
            },
        }
    return {"existe": False, "cliente": None}


@router.get("/{id}")
async def get_cliente(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    result = await db.execute(select(Cliente).where(Cliente.id == id))
    cliente = result.scalars().first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    saldo = await ClienteService.obtener_saldo_cliente(db, cliente.id)
    return {
        "id": cliente.id,
        "documento": cliente.documento,
        "cedula": cliente.documento,
        "nombre": cliente.nombre,
        "email": cliente.email,
        "telefono": cliente.telefono,
        "direccion": cliente.direccion,
        "permite_fiado": cliente.permite_fiado,
        "limite_credito": cliente.limite_credito,
        "estado": cliente.estado,
        "saldo_pendiente": saldo,
        "deuda_total": saldo,
        "created_at": cliente.created_at,
    }


@router.get("/{id}/deuda-detalle")
async def get_deuda_detalle(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    cli_res = await db.execute(select(Cliente).where(Cliente.id == id))
    cliente = cli_res.scalars().first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    res_v = await db.execute(
        select(func.sum(Venta.total)).where(Venta.cliente_id == id, Venta.estado != "Anulada")
    )
    total_compras = round(float(res_v.scalar() or 0.0), 2)

    res_f = await db.execute(
        select(func.sum(CuentaPorCobrar.monto_original)).where(
            CuentaPorCobrar.cliente_id == id, CuentaPorCobrar.estado != "Anulada"
        )
    )
    total_fiado = round(float(res_f.scalar() or 0.0), 2)

    res_ab = await db.execute(
        select(func.sum(Abono.monto))
        .join(CuentaPorCobrar, Abono.cuenta_id == CuentaPorCobrar.id)
        .where(CuentaPorCobrar.cliente_id == id)
    )
    total_abonado = round(float(res_ab.scalar() or 0.0), 2)

    deuda_actual = await ClienteService.obtener_saldo_cliente(db, id)

    cxc_res = await db.execute(
        select(CuentaPorCobrar, Venta.numero)
        .outerjoin(Venta, CuentaPorCobrar.venta_id == Venta.id)
        .where(CuentaPorCobrar.cliente_id == id, CuentaPorCobrar.estado == "Pendiente")
        .order_by(CuentaPorCobrar.id.asc())
    )
    cuentas_pendientes = []
    for cxc, v_num in cxc_res.all():
        cuentas_pendientes.append(
            {
                "id": cxc.id,
                "venta_id": cxc.venta_id,
                "numero_venta": v_num or f"Ajuste #{cxc.id}",
                "fecha": cxc.fecha or (cxc.created_at.strftime("%Y-%m-%d") if cxc.created_at else ""),
                "hora": cxc.hora or (cxc.created_at.strftime("%H:%M:%S") if cxc.created_at else ""),
                "monto_original": cxc.monto_original,
                "saldo_pendiente": cxc.saldo_pendiente,
                "estado": cxc.estado,
                "created_at": cxc.created_at,
            }
        )

    mov_res = await db.execute(
        select(MovimientoCuentaCliente, Usuario.nombre, Venta.numero)
        .outerjoin(Usuario, MovimientoCuentaCliente.usuario_id == Usuario.id)
        .outerjoin(Venta, MovimientoCuentaCliente.venta_id == Venta.id)
        .where(MovimientoCuentaCliente.cliente_id == id)
        .order_by(MovimientoCuentaCliente.id.asc())
    )
    movimientos = []
    for mov, u_nom, v_num in mov_res.all():
        movimientos.append(
            {
                "id": mov.id,
                "cliente_id": mov.cliente_id,
                "cuenta_id": mov.cuenta_id,
                "venta_id": mov.venta_id,
                "numero_venta": v_num,
                "fecha": mov.fecha or (mov.created_at.strftime("%Y-%m-%d") if mov.created_at else ""),
                "hora": mov.hora or (mov.created_at.strftime("%H:%M:%S") if mov.created_at else ""),
                "tipo": mov.tipo,
                "monto": mov.monto,
                "saldo_anterior": mov.saldo_anterior,
                "saldo_nuevo": mov.saldo_nuevo,
                "metodo_pago": mov.metodo_pago,
                "usuario_id": mov.usuario_id,
                "usuario_nombre": u_nom or f"Usuario #{mov.usuario_id}",
                "terminal_id": mov.terminal_id,
                "motivo": mov.motivo,
                "observacion": mov.observacion,
                "created_at": mov.created_at,
            }
        )

    return {
        "cliente": {
            "id": cliente.id,
            "documento": cliente.documento,
            "nombre": cliente.nombre,
            "email": cliente.email,
            "telefono": cliente.telefono,
            "direccion": cliente.direccion,
            "permite_fiado": cliente.permite_fiado,
            "limite_credito": cliente.limite_credito,
            "estado": cliente.estado,
            "saldo_pendiente": deuda_actual,
            "created_at": cliente.created_at,
        },
        "total_compras": total_compras,
        "total_fiado": total_fiado,
        "total_abonado": total_abonado,
        "deuda_actual": deuda_actual,
        "cuentas_pendientes": cuentas_pendientes,
        "movimientos": movimientos,
    }


@router.get("/{id}/abonos")
async def get_abonos_cliente(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    res = await db.execute(
        select(Abono, CuentaPorCobrar.venta_id, Usuario.nombre)
        .join(CuentaPorCobrar, Abono.cuenta_id == CuentaPorCobrar.id)
        .outerjoin(Usuario, Abono.recibido_por == Usuario.id)
        .where(CuentaPorCobrar.cliente_id == id)
        .order_by(Abono.id.desc())
    )
    salida = []
    for ab, venta_id, u_nom in res.all():
        salida.append(
            {
                "id": ab.id,
                "cuenta_id": ab.cuenta_id,
                "venta_id": venta_id,
                "fecha": ab.fecha or (ab.created_at.strftime("%Y-%m-%d") if ab.created_at else ""),
                "hora": ab.hora or (ab.created_at.strftime("%H:%M:%S") if ab.created_at else ""),
                "monto": float(ab.monto or 0.0),
                "metodo": ab.metodo,
                "recibido_por": ab.recibido_por,
                "usuario_nombre": u_nom or f"Usuario #{ab.recibido_por}",
                "observacion": ab.observacion or "",
                "created_at": ab.created_at,
            }
        )
    return salida


@router.get("/{id}/compras")
async def get_compras_cliente(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    res = await db.execute(
        select(Venta, Usuario.nombre)
        .outerjoin(Usuario, Venta.usuario_id == Usuario.id)
        .where(Venta.cliente_id == id)
        .order_by(Venta.id.desc())
    )
    compras = []
    for venta, u_nom in res.all():
        p_res = await db.execute(select(Pago).where(Pago.venta_id == venta.id))
        pagos = p_res.scalars().all()
        metodos = ", ".join([p.metodo for p in pagos]) if pagos else (venta.metodo_pago_principal or "N/A")

        compras.append(
            {
                "id": venta.id,
                "numero": venta.numero,
                "fecha": venta.fecha or (venta.created_at.strftime("%Y-%m-%d") if venta.created_at else ""),
                "hora": venta.hora or (venta.created_at.strftime("%H:%M:%S") if venta.created_at else ""),
                "total": venta.total,
                "saldo_pendiente": float(venta.saldo_pendiente or 0.0),
                "metodo_pago": metodos,
                "vendedor": u_nom or venta.operario_nombre or f"Usuario #{venta.usuario_id}",
                "estado": venta.estado,
            }
        )
    return compras


@router.post("", response_model=ClienteResponse)
async def create_cliente(
    cliente: ClienteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    doc = cliente.documento.strip()
    if not doc:
        raise HTTPException(status_code=400, detail="El documento o cédula es obligatorio")

    exist_res = await db.execute(select(Cliente).where(Cliente.documento == doc))
    if exist_res.scalars().first():
        raise HTTPException(status_code=400, detail=f"Ya existe un cliente registrado con el documento {doc}")

    cli_data = cliente.model_dump(exclude={"cedula"})
    cli_data["documento"] = doc
    db_cli = Cliente(**cli_data)
    db.add(db_cli)
    await db.commit()
    await db.refresh(db_cli)

    await log_audit(
        db=db,
        usuario_id=current_user.id,
        usuario_nombre=current_user.nombre,
        terminal_id=None,
        terminal_nombre="Terminal",
        accion="CREAR_CLIENTE",
        modulo="CLIENTES",
        tabla_afectada="clientes",
        registro_id=str(db_cli.id),
        valor_nuevo={"documento": db_cli.documento, "nombre": db_cli.nombre},
    )
    return db_cli


@router.put("/{id}", response_model=ClienteResponse)
async def update_cliente(
    id: int,
    cli_update: ClienteUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    result = await db.execute(select(Cliente).where(Cliente.id == id))
    cliente = result.scalars().first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    update_data = cli_update.model_dump(exclude_unset=True, exclude={"cedula"})
    if "documento" in update_data and update_data["documento"]:
        doc = update_data["documento"].strip()
        dup = await db.execute(select(Cliente).where(Cliente.documento == doc, Cliente.id != id))
        if dup.scalars().first():
            raise HTTPException(status_code=400, detail=f"El documento {doc} ya está asignado a otro cliente")
        update_data["documento"] = doc

    for key, value in update_data.items():
        setattr(cliente, key, value)

    await db.commit()
    await db.refresh(cliente)

    await log_audit(
        db=db,
        usuario_id=current_user.id,
        usuario_nombre=current_user.nombre,
        terminal_id=None,
        terminal_nombre="Terminal",
        accion="EDITAR_CLIENTE",
        modulo="CLIENTES",
        tabla_afectada="clientes",
        registro_id=str(cliente.id),
        valor_nuevo=update_data,
    )
    return cliente


@router.delete("/{id}")
async def delete_cliente(
    id: int,
    permanente: bool = True,
    forzar: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    if (current_user.rol or "").strip().lower() not in ("administrador", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Operación restringida: Solo los administradores pueden eliminar clientes",
        )

    result = await db.execute(select(Cliente).where(Cliente.id == id))
    cliente = result.scalars().first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    saldo = await ClienteService.obtener_saldo_cliente(db, id)
    if saldo > 0.01 and not forzar:
        raise HTTPException(
            status_code=400,
            detail=f"No se puede eliminar al cliente '{cliente.nombre}' porque mantiene una deuda pendiente de ${saldo:,.0f}",
        )

    doc_respaldo = cliente.documento
    nom_respaldo = cliente.nombre

    cxc_subquery = select(CuentaPorCobrar.id).where(CuentaPorCobrar.cliente_id == id)
    await db.execute(
        delete(MovimientoCuentaCliente).where(
            or_(
                MovimientoCuentaCliente.cliente_id == id,
                MovimientoCuentaCliente.cuenta_id.in_(cxc_subquery),
            )
        )
    )
    await db.execute(delete(Abono).where(Abono.cuenta_id.in_(cxc_subquery)))
    await db.execute(delete(CuentaPorCobrar).where(CuentaPorCobrar.cliente_id == id))
    await db.execute(update(Venta).where(Venta.cliente_id == id).values(cliente_id=None))
    await db.delete(cliente)
    await db.commit()

    await log_audit(
        db=db,
        usuario_id=current_user.id,
        usuario_nombre=current_user.nombre,
        terminal_id=None,
        terminal_nombre="Terminal",
        accion="ELIMINAR_CLIENTE_DEFINITIVO",
        modulo="CLIENTES",
        tabla_afectada="clientes",
        registro_id=str(id),
        valor_nuevo={
            "documento": doc_respaldo,
            "nombre": nom_respaldo,
            "motivo": "Eliminación solicitada por Administrador",
        },
    )
    return {
        "message": f"Cliente '{nom_respaldo}' eliminado definitivamente de la base de datos.",
        "accion": "ELIMINADO_DEFINITIVO",
    }


@router.post("/{id}/abonos")
async def register_abono(
    id: int,
    abono: AbonoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Registra un abono atómico a la cuenta del cliente aplicando lógica FIFO,
    idempotencia y actualizando Caja o Transferencias (nunca como nueva venta).
    """
    u_nombre = f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario
    try:
        res = await ClienteService.registrar_abono_fifo(
            db=db,
            cliente_id=id,
            monto=abono.monto,
            metodo=abono.metodo,
            usuario_id=current_user.id,
            usuario_nombre=u_nombre,
            terminal_id=abono.terminal_id,
            sesion_caja_id=abono.sesion_caja_id,
            cuenta_id_especifica=abono.cuenta_id,
            observacion=abono.observacion,
            idempotency_key=abono.idempotency_key,
        )
        await db.commit()
        return res
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{id}/ajustes")
async def register_ajuste(
    id: int,
    ajuste: AjusteDeudaCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    if (current_user.rol or "").strip().lower() not in ("administrador", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Solo los administradores pueden realizar ajustes manuales de deuda",
        )

    try:
        mov = await ClienteService.registrar_ajuste_manual(
            db=db,
            cliente_id=id,
            monto_ajuste=ajuste.monto,
            motivo=ajuste.motivo,
            usuario_id=current_user.id,
            terminal_id=None,
            observacion=ajuste.observacion,
        )
        await db.commit()
        return {
            "message": "Ajuste manual registrado exitosamente",
            "movimiento_id": mov.id,
            "saldo_anterior": mov.saldo_anterior,
            "saldo_nuevo": mov.saldo_nuevo,
        }
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
