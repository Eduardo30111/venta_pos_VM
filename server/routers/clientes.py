from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func, or_, and_
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta

from ..database import get_db
from ..models.cliente import Cliente
from ..models.finanzas import CuentaPorCobrar, Abono, MovimientoCuentaCliente
from ..models.venta import Venta, Pago
from ..models.usuario import Usuario
from ..schemas.cliente import (
    ClienteCreate, ClienteUpdate, ClienteResponse, 
    AbonoCreate, AjusteDeudaCreate, ClienteListItemResponse,
    FiadoResumenItem, ClienteDeudaDetalleResponse
)
from ..middleware.auth import get_current_user
from ..middleware.audit import log_audit
from ..services.cliente_service import ClienteService

router = APIRouter(prefix="/clientes", tags=["clientes"])

def parse_date_range(
    fecha_filtro: Optional[str] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None
):
    """
    Resuelve el rango de fechas en el servidor para evitar discrepancias de clientes.
    """
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
    current_user: Usuario = Depends(get_current_user)
):
    # 1. Base query for clients
    query = select(Cliente)
    
    # Búsqueda flexible por texto
    if busqueda and busqueda.strip():
        term = f"%{busqueda.strip()}%"
        query = query.where(
            or_(
                Cliente.documento.ilike(term),
                Cliente.nombre.ilike(term),
                Cliente.telefono.ilike(term)
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

    # 2. Calcular agregados de ventas, fiados, abonos y deudas
    items = []
    for c in clientes:
        # Ventas completadas del cliente
        q_ventas = select(func.sum(Venta.total)).where(
            Venta.cliente_id == c.id,
            Venta.estado == 'Completada'
        )
        if f_inicio and f_fin:
            q_ventas = q_ventas.where(func.date(Venta.created_at) >= f_inicio, func.date(Venta.created_at) <= f_fin)
        res_v = await db.execute(q_ventas)
        total_compras = float(res_v.scalar() or 0.0)

        # Total fiado histórico/periodo
        q_fiado = select(func.sum(CuentaPorCobrar.monto_original)).where(
            CuentaPorCobrar.cliente_id == c.id,
            CuentaPorCobrar.estado != 'Anulada'
        )
        if f_inicio and f_fin:
            q_fiado = q_fiado.where(func.date(CuentaPorCobrar.created_at) >= f_inicio, func.date(CuentaPorCobrar.created_at) <= f_fin)
        res_f = await db.execute(q_fiado)
        total_fiado = float(res_f.scalar() or 0.0)

        # Deuda actual (saldo pendiente)
        res_d = await db.execute(
            select(func.sum(CuentaPorCobrar.saldo_pendiente)).where(
                CuentaPorCobrar.cliente_id == c.id,
                CuentaPorCobrar.estado == 'Pendiente'
            )
        )
        deuda_total = float(res_d.scalar() or 0.0)

        # Total abonado
        res_ab = await db.execute(
            select(func.sum(Abono.monto)).join(CuentaPorCobrar, Abono.cuenta_id == CuentaPorCobrar.id).where(
                CuentaPorCobrar.cliente_id == c.id
            )
        )
        total_abonado = float(res_ab.scalar() or 0.0)

        # Operario / Vendedor que realizó la venta o atención
        q_op = (
            select(Usuario.nombre, Usuario.rol)
            .select_from(Venta)
            .join(Usuario, Venta.usuario_id == Usuario.id)
            .where(Venta.cliente_id == c.id)
            .order_by(Venta.created_at.desc())
            .limit(1)
        )
        if f_inicio and f_fin:
            q_op = q_op.where(func.date(Venta.created_at) >= f_inicio, func.date(Venta.created_at) <= f_fin)
        res_op = await db.execute(q_op)
        row_op = res_op.first()
        if row_op:
            u_nom, u_rol = row_op
            operario_venta = f"{u_nom} ({u_rol})" if u_rol else u_nom
        else:
            operario_venta = "—"

        # Filtro de tipo
        if filtro_tipo == "compras" and total_compras <= 0:
            continue
        if filtro_tipo == "fiados" and (deuda_total <= 0 and total_fiado <= 0 and not c.permite_fiado):
            continue

        items.append({
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
            "created_at": c.created_at
        })


    return items

@router.get("/fiados/resumen")
async def resumen_fiados(
    busqueda: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Devuelve la cartera de fiados para el modal de Gestión de Fiados.
    """
    query = select(Cliente)
    if busqueda and busqueda.strip():
        term = f"%{busqueda.strip()}%"
        query = query.where(
            or_(
                Cliente.documento.ilike(term),
                Cliente.nombre.ilike(term),
                Cliente.telefono.ilike(term)
            )
        )
    res = await db.execute(query)
    clientes = res.scalars().all()

    lista_fiados = []
    for c in clientes:
        # Total fiado
        res_f = await db.execute(
            select(func.sum(CuentaPorCobrar.monto_original)).where(
                CuentaPorCobrar.cliente_id == c.id,
                CuentaPorCobrar.estado != 'Anulada'
            )
        )
        total_fiado = float(res_f.scalar() or 0.0)

        # Deuda actual
        res_d = await db.execute(
            select(func.sum(CuentaPorCobrar.saldo_pendiente)).where(
                CuentaPorCobrar.cliente_id == c.id,
                CuentaPorCobrar.estado == 'Pendiente'
            )
        )
        deuda_actual = float(res_d.scalar() or 0.0)

        # Total abonado
        res_ab = await db.execute(
            select(func.sum(Abono.monto)).join(CuentaPorCobrar, Abono.cuenta_id == CuentaPorCobrar.id).where(
                CuentaPorCobrar.cliente_id == c.id
            )
        )
        total_abonado = float(res_ab.scalar() or 0.0)

        # Último abono
        res_ult = await db.execute(
            select(Abono.created_at).join(CuentaPorCobrar, Abono.cuenta_id == CuentaPorCobrar.id)
            .where(CuentaPorCobrar.cliente_id == c.id)
            .order_by(Abono.created_at.desc())
            .limit(1)
        )
        ultimo_abono = res_ult.scalar()

        # Operario / Vendedor que originó el fiado o última atención
        q_op_f = (
            select(Usuario.nombre, Usuario.rol)
            .select_from(CuentaPorCobrar)
            .join(Venta, CuentaPorCobrar.venta_id == Venta.id)
            .join(Usuario, Venta.usuario_id == Usuario.id)
            .where(CuentaPorCobrar.cliente_id == c.id, CuentaPorCobrar.estado != 'Anulada')
            .order_by(CuentaPorCobrar.created_at.desc())
            .limit(1)
        )
        res_opf = await db.execute(q_op_f)
        row_opf = res_opf.first()
        if row_opf:
            unom, urol = row_opf
            operario_fiado = f"{unom} ({urol})" if urol else unom
        else:
            operario_fiado = "—"

        # Incluir clientes que tienen crédito, deuda o historial de fiado
        if total_fiado > 0 or deuda_actual > 0 or c.permite_fiado:
            estado_desc = "PENDIENTE" if deuda_actual > 0 else ("PAGADO" if total_abonado > 0 else "AL DÍA")
            lista_fiados.append({
                "cliente_id": c.id,
                "documento": c.documento,
                "nombre": c.nombre,
                "telefono": c.telefono or "",
                "operario_venta": operario_fiado,
                "vendedor": operario_fiado,
                "total_fiado": total_fiado,
                "total_abonado": total_abonado,
                "deuda_actual": deuda_actual,
                "ultimo_abono": ultimo_abono,
                "estado": estado_desc
            })


    return lista_fiados

@router.get("/buscar-precheck")
async def precheck_cliente(
    q: str,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Verifica si un cliente ya existe antes de crear uno nuevo para evitar duplicados.
    """
    term = q.strip()
    if not term:
        return {"existe": False, "cliente": None}

    # Búsqueda exacta por documento o teléfono primero, luego parcial por nombre
    res = await db.execute(
        select(Cliente).where(
            or_(
                Cliente.documento == term,
                Cliente.telefono == term,
                Cliente.nombre.ilike(f"%{term}%")
            )
        ).limit(1)
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
                "estado": cli.estado
            }
        }
    return {"existe": False, "cliente": None}

@router.get("/{id}")
async def get_cliente(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    result = await db.execute(select(Cliente).where(Cliente.id == id))
    cliente = result.scalars().first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    saldo = await ClienteService.obtener_saldo_cliente(db, cliente.id)
    cli_dict = {
        "id": cliente.id,
        "documento": cliente.documento,
        "nombre": cliente.nombre,
        "email": cliente.email,
        "telefono": cliente.telefono,
        "direccion": cliente.direccion,
        "permite_fiado": cliente.permite_fiado,
        "limite_credito": cliente.limite_credito,
        "estado": cliente.estado,
        "saldo_pendiente": saldo,
        "created_at": cliente.created_at
    }
    return cli_dict

@router.get("/{id}/deuda-detalle")
async def get_deuda_detalle(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Retorna la ficha contable completa: resumen de compras, fiados, abonos, cuentas pendientes
    y el libro cronológico de movimientos contables inmutables.
    """
    cli_res = await db.execute(select(Cliente).where(Cliente.id == id))
    cliente = cli_res.scalars().first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    # 1. Total compras
    res_v = await db.execute(
        select(func.sum(Venta.total)).where(Venta.cliente_id == id, Venta.estado == 'Completada')
    )
    total_compras = float(res_v.scalar() or 0.0)

    # 2. Total fiado
    res_f = await db.execute(
        select(func.sum(CuentaPorCobrar.monto_original)).where(CuentaPorCobrar.cliente_id == id, CuentaPorCobrar.estado != 'Anulada')
    )
    total_fiado = float(res_f.scalar() or 0.0)

    # 3. Total abonado
    res_ab = await db.execute(
        select(func.sum(Abono.monto)).join(CuentaPorCobrar, Abono.cuenta_id == CuentaPorCobrar.id).where(CuentaPorCobrar.cliente_id == id)
    )
    total_abonado = float(res_ab.scalar() or 0.0)

    # 4. Deuda actual
    deuda_actual = await ClienteService.obtener_saldo_cliente(db, id)

    # 5. Cuentas por cobrar pendientes
    cxc_res = await db.execute(
        select(CuentaPorCobrar, Venta.numero)
        .outerjoin(Venta, CuentaPorCobrar.venta_id == Venta.id)
        .where(CuentaPorCobrar.cliente_id == id, CuentaPorCobrar.estado == 'Pendiente')
        .order_by(CuentaPorCobrar.created_at.asc())
    )
    cuentas_pendientes = []
    for cxc, v_num in cxc_res.all():
        cuentas_pendientes.append({
            "id": cxc.id,
            "venta_id": cxc.venta_id,
            "numero_venta": v_num or f"Ajuste #{cxc.id}",
            "monto_original": cxc.monto_original,
            "saldo_pendiente": cxc.saldo_pendiente,
            "estado": cxc.estado,
            "created_at": cxc.created_at
        })

    # 6. Libro mayor de movimientos contables
    mov_res = await db.execute(
        select(MovimientoCuentaCliente, Usuario.nombre, Venta.numero)
        .outerjoin(Usuario, MovimientoCuentaCliente.usuario_id == Usuario.id)
        .outerjoin(Venta, MovimientoCuentaCliente.venta_id == Venta.id)
        .where(MovimientoCuentaCliente.cliente_id == id)
        .order_by(MovimientoCuentaCliente.created_at.asc())
    )
    movimientos = []
    for mov, u_nom, v_num in mov_res.all():
        movimientos.append({
            "id": mov.id,
            "cliente_id": mov.cliente_id,
            "cuenta_id": mov.cuenta_id,
            "venta_id": mov.venta_id,
            "numero_venta": v_num,
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
            "created_at": mov.created_at
        })

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
            "created_at": cliente.created_at
        },
        "total_compras": total_compras,
        "total_fiado": total_fiado,
        "total_abonado": total_abonado,
        "deuda_actual": deuda_actual,
        "cuentas_pendientes": cuentas_pendientes,
        "movimientos": movimientos
    }

@router.get("/{id}/compras")
async def get_compras_cliente(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Retorna el historial de compras directas realizadas por el cliente.
    """
    res = await db.execute(
        select(Venta, Usuario.nombre)
        .outerjoin(Usuario, Venta.usuario_id == Usuario.id)
        .where(Venta.cliente_id == id)
        .order_by(Venta.created_at.desc())
    )
    compras = []
    for venta, u_nom in res.all():
        # Obtener métodos de pago
        p_res = await db.execute(select(Pago).where(Pago.venta_id == venta.id))
        pagos = p_res.scalars().all()
        metodos = ", ".join([p.metodo for p in pagos]) if pagos else "N/A"

        compras.append({
            "id": venta.id,
            "numero": venta.numero,
            "fecha": venta.created_at.strftime("%Y-%m-%d") if venta.created_at else "",
            "hora": venta.created_at.strftime("%H:%M:%S") if venta.created_at else "",
            "total": venta.total,
            "metodo_pago": metodos,
            "vendedor": u_nom or f"Usuario #{venta.usuario_id}",
            "estado": venta.estado
        })
    return compras

@router.post("", response_model=ClienteResponse)
async def create_cliente(
    cliente: ClienteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    # Validación estricta de documento duplicado
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
        valor_nuevo={"documento": db_cli.documento, "nombre": db_cli.nombre}
    )
    return db_cli

@router.put("/{id}", response_model=ClienteResponse)
async def update_cliente(
    id: int,
    cli_update: ClienteUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    result = await db.execute(select(Cliente).where(Cliente.id == id))
    cliente = result.scalars().first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    update_data = cli_update.model_dump(exclude_unset=True, exclude={"cedula"})
    if "documento" in update_data and update_data["documento"]:
        doc = update_data["documento"].strip()
        # Verificar que no pertenezca a otro cliente
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
        valor_nuevo=update_data
    )
    return cliente

@router.delete("/{id}")
async def delete_cliente(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    result = await db.execute(select(Cliente).where(Cliente.id == id))
    cliente = result.scalars().first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    # Validar que no tenga deudas pendientes
    saldo = await ClienteService.obtener_saldo_cliente(db, id)
    if saldo > 0:
        raise HTTPException(
            status_code=400,
            detail=f"No se puede eliminar: el cliente tiene un saldo pendiente de ${saldo:,.0f} COP"
        )

    cliente.estado = "Inactivo"
    await db.commit()
    return {"message": "Cliente marcado como inactivo"}

@router.post("/{id}/abonos")
async def register_abono(
    id: int,
    abono: AbonoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Registra un abono a la cuenta del cliente aplicando lógica FIFO y actualizando libro mayor.
    """
    res = await ClienteService.registrar_abono_fifo(
        db=db,
        cliente_id=id,
        monto=abono.monto,
        metodo=abono.metodo,
        usuario_id=current_user.id,
        terminal_id=None,
        cuenta_id_especifica=abono.cuenta_id,
        observacion=abono.observacion
    )
    await db.commit()
    return res

@router.post("/{id}/ajustes")
async def register_ajuste(
    id: int,
    ajuste: AjusteDeudaCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Ajuste manual de deuda autorizado (solo Administrador).
    """
    if current_user.rol != "Administrador":
        raise HTTPException(status_code=403, detail="Solo los administradores pueden realizar ajustes manuales de deuda")

    mov = await ClienteService.registrar_ajuste_manual(
        db=db,
        cliente_id=id,
        monto_ajuste=ajuste.monto,
        motivo=ajuste.motivo,
        usuario_id=current_user.id,
        terminal_id=None,
        observacion=ajuste.observacion
    )
    await db.commit()
    return {
        "message": "Ajuste manual registrado exitosamente",
        "movimiento_id": mov.id,
        "saldo_anterior": mov.saldo_anterior,
        "saldo_nuevo": mov.saldo_nuevo
    }
