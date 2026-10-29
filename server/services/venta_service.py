from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_, and_
from fastapi import HTTPException
from ..models.venta import Venta, DetalleVenta, Pago
from ..models.producto import Producto
from ..models.servicio import Servicio
from ..models.inventario import MovimientoInventario
from ..models.nomina import Comision
from ..models.finanzas import CuentaPorPagar, CuentaPorCobrar
from ..models.cliente import Cliente
from ..models.usuario import Usuario
from ..models.terminal import Terminal
from ..schemas.venta import VentaCreate, CobroOrdenCreate
from ..middleware.audit import log_audit

class VentaService:
    @staticmethod
    async def procesar_venta(db: AsyncSession, venta_data: VentaCreate, usuario_id: int, terminal_id: int, usuario: Usuario) -> Venta:
        try:
            # 0. Validate terminal
            term_result = await db.execute(select(Terminal).where(Terminal.id == terminal_id))
            term = term_result.scalars().first()
            if not term:
                term_any = await db.execute(select(Terminal).order_by(Terminal.id.asc()))
                term = term_any.scalars().first()
                if term:
                    terminal_id = term.id

            # 1. Generate venta numero
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

            # 0.5 Resolver cliente de forma segura (sin violar Foreign Key)
            resolved_cliente_id = None
            doc_cliente = (getattr(venta_data, 'cliente_documento', None) or "").strip()
            if not doc_cliente and venta_data.cliente_id:
                doc_cliente = str(venta_data.cliente_id).strip()

            if venta_data.cliente_id:
                cli_res = await db.execute(select(Cliente).where(Cliente.id == venta_data.cliente_id))
                cli = cli_res.scalars().first()
                if cli:
                    resolved_cliente_id = cli.id

            if not resolved_cliente_id and doc_cliente:
                cli_doc_res = await db.execute(select(Cliente).where(Cliente.documento == doc_cliente))
                cli_doc = cli_doc_res.scalars().first()
                if cli_doc:
                    resolved_cliente_id = cli_doc.id
                else:
                    try:
                        nuevo_cli = Cliente(
                            documento=doc_cliente,
                            nombre=f"Cliente {doc_cliente}",
                            permite_fiado=False,
                            limite_credito=0.0,
                            estado="Activo"
                        )
                        db.add(nuevo_cli)
                        await db.flush()
                        resolved_cliente_id = nuevo_cli.id
                    except Exception:
                        resolved_cliente_id = None

            estado_venta = venta_data.estado or "Completada"
            venta = Venta(
                numero=numero,
                cliente_id=resolved_cliente_id,
                usuario_id=usuario_id,
                terminal_id=terminal_id,
                subtotal=venta_data.subtotal,
                descuento=venta_data.descuento,
                total=venta_data.total,
                estado=estado_venta,
                observaciones=venta_data.observaciones
            )
            db.add(venta)
            await db.flush() # get venta.id

            monto_fiado = 0

            # 2. Process items
            for item in venta_data.detalles:
                det = DetalleVenta(
                    venta_id=venta.id,
                    tipo_item=item.tipo_item,
                    item_id=item.item_id,
                    item_codigo=item.item_codigo,
                    item_nombre=item.item_nombre,
                    precio_original=item.precio_original,
                    precio_vendido=item.precio_vendido,
                    cantidad=item.cantidad,
                    descuento=item.descuento or 0.0,
                    subtotal=item.subtotal,
                    costo_unitario=item.costo_unitario
                )
                db.add(det)
                await db.flush() # get det.id

                if item.tipo_item == 'Producto':
                    # Lock product
                    prod_result = await db.execute(select(Producto).with_for_update().where(Producto.id == item.item_id))
                    producto = prod_result.scalars().first()
                    if not producto:
                        raise HTTPException(status_code=404, detail=f"Producto {item.item_id} no encontrado")
                    if producto.stock < item.cantidad:
                        raise HTTPException(status_code=409, detail=f"Stock insuficiente para {producto.nombre}")
                    
                    stock_ant = producto.stock
                    producto.stock -= item.cantidad
                    
                    # Movimiento inventario
                    mov = MovimientoInventario(
                        producto_id=producto.id,
                        tipo="VENTA",
                        cantidad=-item.cantidad,
                        stock_anterior=stock_ant,
                        stock_nuevo=producto.stock,
                        referencia=numero,
                        usuario_id=usuario_id,
                        terminal_id=terminal_id
                    )
                    db.add(mov)

                    # Cuentas por pagar a proveedor por producto
                    costo_prod = float(producto.precio_costo or 0.0)
                    cantidad_item = float(item.cantidad)
                    if producto.proveedor_id and costo_prod > 0:
                        cxp = CuentaPorPagar(
                            proveedor_id=producto.proveedor_id,
                            venta_id=venta.id,
                            concepto=f"Producto {producto.nombre} - Venta {numero}",
                            monto=costo_prod * cantidad_item
                        )
                        db.add(cxp)

                    # Cálculo de comisión para Producto
                    porcentaje = float(usuario.porcentaje_comision or 0.0)
                    es_porcentual = (usuario.tipo_remuneracion == 'Porcentual' or porcentaje > 0)
                    if es_porcentual and porcentaje > 0:
                        precio_prod = float(item.precio_vendido)
                        utilidad_prod = max(0.0, precio_prod - costo_prod)
                        base_com = utilidad_prod if utilidad_prod > 0 else precio_prod
                        comision_monto = (base_com * cantidad_item) * (porcentaje / 100.0)
                        estado_comision = "Pendiente_Caja" if estado_venta == "Pendiente_Caja" else "Pendiente"
                        comision = Comision(
                            usuario_id=usuario_id,
                            venta_id=venta.id,
                            detalle_venta_id=det.id,
                            producto_id=producto.id,
                            servicio_id=None,
                            valor_servicio=precio_prod * cantidad_item,
                            costo_servicio=costo_prod * cantidad_item,
                            utilidad=utilidad_prod * cantidad_item,
                            porcentaje=porcentaje,
                            monto_comision=comision_monto,
                            estado=estado_comision
                        )
                        db.add(comision)
                    
                elif item.tipo_item == 'Servicio':
                    rol_usuario = (usuario.rol or "").strip().lower()
                    if rol_usuario == "operario":
                        visibilidad_servicio = or_(
                            and_(Servicio.solo_operarios == True, Servicio.creado_por_operario_id.is_(None)),
                            Servicio.creado_por_operario_id == usuario_id
                        )
                    else:
                        visibilidad_servicio = and_(
                            Servicio.solo_operarios == False,
                            Servicio.creado_por_operario_id.is_(None)
                        )
                    serv_result = await db.execute(select(Servicio).where(Servicio.id == item.item_id, visibilidad_servicio))
                    servicio = serv_result.scalars().first()
                    if not servicio or servicio.estado != 'Activo':
                        raise HTTPException(status_code=404, detail=f"Servicio {item.item_id} no activo")
                    
                    costo_prov = float(servicio.costo_proveedor or 0.0)
                    cantidad_item = float(item.cantidad)

                    # Si el servicio tiene proveedor asignado y costo_proveedor es 0 o no está definido (como en recargas con precio variable),
                    # el costo adeudado al proveedor es el valor de la recarga / monto vendido.
                    monto_costo_unitario = costo_prov if costo_prov > 0 else (float(item.precio_vendido) if servicio.proveedor_id else 0.0)

                    # Actualizar costo_unitario en el detalle si era 0
                    if servicio.proveedor_id and (det.costo_unitario is None or det.costo_unitario <= 0):
                        det.costo_unitario = monto_costo_unitario

                    # Commission calculation
                    porcentaje = float(usuario.porcentaje_comision or 0.0)
                    es_porcentual = (usuario.tipo_remuneracion == 'Porcentual' or porcentaje > 0)
                    genera_com = servicio.genera_comision if servicio.genera_comision is not None else (servicio.proveedor_id is None)

                    if genera_com and es_porcentual and porcentaje > 0:
                        utilidad_unitaria = float(item.precio_vendido) - monto_costo_unitario
                        base_com = utilidad_unitaria if utilidad_unitaria > 0 else float(item.precio_vendido)
                        utilidad_total = max(0.0, utilidad_unitaria) * cantidad_item
                        comision_monto = (base_com * cantidad_item) * (porcentaje / 100.0)
                        estado_comision = "Pendiente_Caja" if estado_venta == "Pendiente_Caja" else "Pendiente"
                        comision = Comision(
                            usuario_id=usuario_id,
                            venta_id=venta.id,
                            detalle_venta_id=det.id,
                            servicio_id=servicio.id,
                            producto_id=None,
                            valor_servicio=float(item.precio_vendido) * cantidad_item,
                            costo_servicio=monto_costo_unitario * cantidad_item,
                            utilidad=utilidad_total,
                            porcentaje=porcentaje,
                            monto_comision=comision_monto,
                            estado=estado_comision
                        )
                        db.add(comision)
                        
                    # Provider Accounts Payable
                    if servicio.proveedor_id:
                        pct_prov = float(getattr(servicio, "porcentaje_comision", 0.0) or 0.0)
                        precio_total_item = float(item.precio_vendido) * cantidad_item
                        if pct_prov > 0:
                            comision_prov = (precio_total_item * pct_prov) / 100.0
                            monto_cxp = max(0.0, precio_total_item - comision_prov)
                        elif costo_prov > 0:
                            monto_cxp = costo_prov * cantidad_item
                        else:
                            monto_cxp = precio_total_item

                        if monto_cxp > 0:
                            cxp = CuentaPorPagar(
                                proveedor_id=servicio.proveedor_id,
                                venta_id=venta.id,
                                concepto=f"Servicio {servicio.nombre} - Venta {numero}",
                                monto=monto_cxp
                            )
                            db.add(cxp)

            # Process payments (only if not Pendiente_Caja and payments provided)
            if estado_venta != "Pendiente_Caja" and venta_data.pagos:
                for p in venta_data.pagos:
                    pago = Pago(
                        venta_id=venta.id,
                        metodo=p.metodo,
                        monto=p.monto,
                        referencia=p.referencia,
                        recibido=p.recibido,
                        cambio=p.cambio
                    )
                    db.add(pago)
                    if p.metodo == 'Fiado':
                        monto_fiado += p.monto

                # Fiado logic
                if monto_fiado > 0:
                    if not venta_data.cliente_id:
                        raise HTTPException(status_code=400, detail="Cliente requerido para Fiado")
                    cli_result = await db.execute(select(Cliente).where(Cliente.id == venta_data.cliente_id))
                    cliente = cli_result.scalars().first()
                    if not cliente or not cliente.permite_fiado:
                        raise HTTPException(status_code=400, detail="Cliente no permite fiado")
                    
                    # Check limit
                    cxc_result = await db.execute(select(func.sum(CuentaPorCobrar.saldo_pendiente)).where(CuentaPorCobrar.cliente_id == cliente.id, CuentaPorCobrar.estado == "Pendiente"))
                    deuda_actual = cxc_result.scalar() or 0.0
                    if cliente.limite_credito > 0 and (deuda_actual + monto_fiado > cliente.limite_credito):
                        raise HTTPException(status_code=400, detail="Limite de credito excedido")
                    
                    cxc = CuentaPorCobrar(
                        cliente_id=cliente.id,
                        venta_id=venta.id,
                        monto_original=monto_fiado,
                        saldo_pendiente=monto_fiado,
                        estado="Pendiente"
                    )
                    db.add(cxc)
                    await db.flush()

                    from .cliente_service import ClienteService
                    await ClienteService.registrar_movimiento_fiado(
                        db=db,
                        cliente_id=cliente.id,
                        cuenta_id=cxc.id,
                        venta_id=venta.id,
                        monto=monto_fiado,
                        usuario_id=usuario_id,
                        terminal_id=terminal_id,
                        observacion=f"Fiado por venta {numero}"
                    )


            # Una orden pendiente de caja todavía no fue atendida: su turno
            # se registra al confirmar el pago en autorizar_pago_orden().
            if estado_venta != "Pendiente_Caja":
                try:
                    from .turno_service import TurnoService
                    es_esp = getattr(venta_data, 'es_turno_especial', False) or False
                    motivo_esp = getattr(venta_data, 'motivo_especial', None)
                    await TurnoService.registrar_atencion_venta(
                        db=db,
                        venta=venta,
                        usuario_id=usuario_id,
                        terminal_id=terminal_id,
                        es_turno_especial=es_esp,
                        motivo_especial=motivo_esp
                    )
                except Exception as ex_turno:
                    print(f"Nota: error al registrar atención en módulo de turnos: {ex_turno}")

            await db.commit()
            await db.refresh(venta)
            accion_audit = "MANDAR_A_CAJA" if estado_venta == "Pendiente_Caja" else "CREAR"
            await log_audit(db, usuario_id, usuario.nombre, terminal_id, "Terminal", accion_audit, "VENTAS", "ventas", str(venta.id))
            return venta
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(e))

    @staticmethod
    async def autorizar_pago_orden(db: AsyncSession, venta_id: int, cobro_data: CobroOrdenCreate, admin_id: int, terminal_id: int, admin_user: Usuario) -> Venta:
        try:
            res = await db.execute(select(Venta).with_for_update().where(Venta.id == venta_id))
            venta = res.scalars().first()
            if not venta:
                raise HTTPException(status_code=404, detail="Venta no encontrada")
            if venta.estado != "Pendiente_Caja":
                raise HTTPException(status_code=400, detail=f"La orden no está pendiente de caja (Estado actual: {venta.estado})")
            
            # Resolver cliente si vino en cobro_data de forma segura
            if cobro_data.cliente_id or getattr(cobro_data, 'cliente_documento', None):
                doc_cli = (getattr(cobro_data, 'cliente_documento', None) or "").strip()
                if not doc_cli and cobro_data.cliente_id:
                    doc_cli = str(cobro_data.cliente_id).strip()

                res_cli_id = None
                if cobro_data.cliente_id:
                    cli_r = await db.execute(select(Cliente).where(Cliente.id == cobro_data.cliente_id))
                    cli_obj = cli_r.scalars().first()
                    if cli_obj:
                        res_cli_id = cli_obj.id

                if not res_cli_id and doc_cli:
                    cli_d = await db.execute(select(Cliente).where(Cliente.documento == doc_cli))
                    cli_doc_obj = cli_d.scalars().first()
                    if cli_doc_obj:
                        res_cli_id = cli_doc_obj.id
                    else:
                        try:
                            nuevo_c = Cliente(documento=doc_cli, nombre=f"Cliente {doc_cli}", permite_fiado=False, limite_credito=0.0, estado="Activo")
                            db.add(nuevo_c)
                            await db.flush()
                            res_cli_id = nuevo_c.id
                        except Exception:
                            res_cli_id = None

                if res_cli_id:
                    venta.cliente_id = res_cli_id

            if cobro_data.observaciones:
                obs_prev = f"{venta.observaciones} | " if venta.observaciones else ""
                venta.observaciones = f"{obs_prev}{cobro_data.observaciones}"
            
            monto_fiado = 0.0
            for p in cobro_data.pagos:
                pago = Pago(
                    venta_id=venta.id,
                    metodo=p.metodo,
                    monto=p.monto,
                    referencia=p.referencia,
                    recibido=p.recibido,
                    cambio=p.cambio
                )
                db.add(pago)
                if p.metodo == 'Fiado':
                    monto_fiado += p.monto
            
            if monto_fiado > 0:
                if not venta.cliente_id:
                    raise HTTPException(status_code=400, detail="Cliente requerido para Fiado")
                cli_result = await db.execute(select(Cliente).where(Cliente.id == venta.cliente_id))
                cliente = cli_result.scalars().first()
                if not cliente or not cliente.permite_fiado:
                    raise HTTPException(status_code=400, detail="Cliente no permite fiado")
                
                cxc_result = await db.execute(select(func.sum(CuentaPorCobrar.saldo_pendiente)).where(CuentaPorCobrar.cliente_id == cliente.id, CuentaPorCobrar.estado == "Pendiente"))
                deuda_actual = cxc_result.scalar() or 0.0
                if cliente.limite_credito > 0 and (deuda_actual + monto_fiado > cliente.limite_credito):
                    raise HTTPException(status_code=400, detail="Limite de credito excedido")
                
                cxc = CuentaPorCobrar(
                    cliente_id=cliente.id,
                    venta_id=venta.id,
                    monto_original=monto_fiado,
                    saldo_pendiente=monto_fiado,
                    estado="Pendiente"
                )
                db.add(cxc)
                await db.flush()

                from .cliente_service import ClienteService
                await ClienteService.registrar_movimiento_fiado(
                    db=db,
                    cliente_id=cliente.id,
                    cuenta_id=cxc.id,
                    venta_id=venta.id,
                    monto=monto_fiado,
                    usuario_id=admin_id,
                    terminal_id=terminal_id,
                    observacion=f"Fiado por venta {venta.numero}"
                )

                
            # Activar comisiones que estaban esperando autorización en caja
            com_res = await db.execute(
                select(Comision).with_for_update().where(Comision.venta_id == venta.id)
            )
            comisiones_orden = com_res.scalars().all()
            for c in comisiones_orden:
                if c.estado == "Pendiente_Caja":
                    c.estado = "Pendiente"

            venta.estado = "Completada"

            # La atención real termina cuando el administrador confirma el
            # pago, no cuando la orden se envía a la caja.
            try:
                from .turno_service import TurnoService
                await TurnoService.registrar_atencion_venta(
                    db=db,
                    venta=venta,
                    usuario_id=venta.usuario_id,
                    terminal_id=terminal_id
                )
            except Exception as ex_turno:
                print(f"Nota: error al registrar atención de turno al cobrar: {ex_turno}")

            await db.commit()
            await db.refresh(venta)
            await log_audit(db, admin_id, admin_user.nombre, terminal_id, "Terminal", "AUTORIZAR_PAGO", "VENTAS", "ventas", str(venta.id))
            return venta
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(e))

    @staticmethod
    async def anular_venta(db: AsyncSession, venta_id: int, usuario_id: int, terminal_id: int, usuario: Usuario) -> Venta:
        try:
            # 1. Obtener la venta bloqueando la fila
            result = await db.execute(select(Venta).with_for_update().where(Venta.id == venta_id))
            venta = result.scalars().first()
            if not venta:
                raise HTTPException(status_code=404, detail="Venta no encontrada")
            if venta.estado == 'Anulada':
                raise HTTPException(status_code=400, detail="La venta ya se encuentra anulada")
            
            venta.estado = 'Anulada'

            # 2. Revertir inventario
            det_result = await db.execute(select(DetalleVenta).where(DetalleVenta.venta_id == venta.id))
            detalles = det_result.scalars().all()
            
            for item in detalles:
                if item.tipo_item == 'Producto':
                    prod_result = await db.execute(select(Producto).with_for_update().where(Producto.id == item.item_id))
                    producto = prod_result.scalars().first()
                    if producto:
                        stock_ant = producto.stock
                        producto.stock += item.cantidad
                        
                        mov = MovimientoInventario(
                            producto_id=producto.id,
                            tipo="ANULACION",
                            cantidad=item.cantidad,
                            stock_anterior=stock_ant,
                            stock_nuevo=producto.stock,
                            referencia=f"Anulacion Venta {venta.numero}",
                            usuario_id=usuario_id,
                            terminal_id=terminal_id
                        )
                        db.add(mov)

            # 3. Anular comisiones pendientes
            com_result = await db.execute(select(Comision).with_for_update().where(Comision.venta_id == venta.id))
            comisiones = com_result.scalars().all()
            for com in comisiones:
                if com.estado in ('Pendiente', 'Pendiente_Caja'):
                    com.estado = 'Anulada'
                elif com.estado == 'Liquidada':
                    raise HTTPException(status_code=400, detail="No se puede anular: existen comisiones ya liquidadas")

            # 4. Anular Cuentas por Cobrar (Fiados) y registrar reversión contable
            cxc_result = await db.execute(select(CuentaPorCobrar).with_for_update().where(CuentaPorCobrar.venta_id == venta.id))
            cxc_list = cxc_result.scalars().all()
            for cxc in cxc_list:
                if cxc.monto_original > cxc.saldo_pendiente:
                    raise HTTPException(status_code=400, detail="No se puede anular: el cliente ya ha realizado abonos a esta deuda")
            
            from .cliente_service import ClienteService
            await ClienteService.revertir_fiado_por_anulacion(
                db=db,
                venta_id=venta.id,
                usuario_id=usuario_id,
                terminal_id=terminal_id,
                motivo=f"Anulación de venta {venta.numero}"
            )


            # 5. Anular Cuentas por Pagar (Proveedores)
            cxp_result = await db.execute(select(CuentaPorPagar).with_for_update().where(CuentaPorPagar.venta_id == venta.id))
            cxp_list = cxp_result.scalars().all()
            for cxp in cxp_list:
                if cxp.estado == 'Pagada':
                    raise HTTPException(status_code=400, detail="No se puede anular: ya se le pagó al proveedor")
                cxp.estado = 'Anulada'

            await db.commit()
            await log_audit(db, usuario_id, usuario.nombre, terminal_id, "Terminal", "ANULAR", "VENTAS", "ventas", str(venta.id))
            return venta

        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(e))
