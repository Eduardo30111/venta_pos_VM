from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base


class MovimientoInventario(Base):
    __tablename__ = "movimientos_inventario"
    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(String, nullable=True, index=True)  # YYYY-MM-DD local
    hora = Column(String, nullable=True)  # HH:MM:SS local
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False, index=True)
    codigo_producto = Column(String, nullable=True)
    nombre_producto = Column(String, nullable=True)
    tipo = Column(String, nullable=False, index=True)  # ENTRADA_INICIAL/ENTRADA_COMPRA/REVERSION_COMPRA/VENTA/DEVOLUCION_VENTA/ANULACION/TRASLADO_BODEGA_A_VITRINA/TRASLADO_VITRINA_A_BODEGA/AJUSTE_POSITIVO/AJUSTE_NEGATIVO
    cantidad = Column(Float, nullable=False)
    unidad_medida = Column(String, default="Unidad", nullable=True)
    ubicacion_origen = Column(String, nullable=True)
    ubicacion_destino = Column(String, nullable=True)
    stock_anterior = Column(Float, nullable=False, default=0.0)
    stock_nuevo = Column(Float, nullable=False, default=0.0)
    stock_origen_ant = Column(Float, default=0.0)
    stock_origen_des = Column(Float, default=0.0)
    stock_destino_ant = Column(Float, default=0.0)
    stock_destino_des = Column(Float, default=0.0)
    costo_unitario = Column(Float, default=0.0)
    valor_total = Column(Float, default=0.0)
    referencia = Column(String, nullable=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    usuario_nombre = Column(String, nullable=True)
    terminal_id = Column(Integer, ForeignKey("terminales.id"), nullable=True)
    observacion = Column(String, nullable=True)
    estado = Column(String, default="Completado")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TrasladoInventario(Base):
    __tablename__ = "traslados_inventario"
    id = Column(Integer, primary_key=True, index=True)
    numero_traslado = Column(String, unique=True, index=True, nullable=False)
    fecha = Column(String, nullable=False)
    hora = Column(String, nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    codigo_producto = Column(String, nullable=False)
    nombre_producto = Column(String, nullable=False)
    ubicacion_origen = Column(String, nullable=False)
    ubicacion_destino = Column(String, nullable=False)
    cantidad = Column(Float, nullable=False)
    usuario = Column(String, nullable=False)
    estado = Column(String, default="Completado")
    observaciones = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CompraInventario(Base):
    __tablename__ = "compras_inventario"
    id = Column(Integer, primary_key=True, index=True)
    numero_compra = Column(String, unique=True, index=True, nullable=False)
    fecha = Column(String, nullable=False)
    hora = Column(String, nullable=False)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=True)
    proveedor_nombre = Column(String, nullable=True)
    documento_referencia = Column(String, nullable=True)
    ubicacion_destino = Column(String, default="BODEGA", nullable=False)
    total_compra = Column(Float, default=0.0)
    usuario = Column(String, nullable=False)
    observaciones = Column(String, nullable=True)
    estado = Column(String, default="Recibida")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DetalleCompra(Base):
    __tablename__ = "detalle_compras"
    id = Column(Integer, primary_key=True, index=True)
    compra_id = Column(Integer, ForeignKey("compras_inventario.id"), nullable=False, index=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    codigo_producto = Column(String, nullable=False)
    nombre_producto = Column(String, nullable=False)
    unidad_compra = Column(String, default="Unidad")
    factor_conversion = Column(Float, default=1.0)
    cantidad_comprada = Column(Float, default=1.0)
    cantidad_unidades = Column(Float, default=1.0)
    costo_unidad_compra = Column(Float, default=0.0)
    costo_unitario_convertido = Column(Float, default=0.0)
    subtotal = Column(Float, default=0.0)


class InventarioOperario(Base):
    __tablename__ = "inventario_operarios"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, nullable=True)
    usuario_nombre = Column(String, index=True, nullable=False)
    rol = Column(String, default="Operario", nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False, index=True)
    codigo_producto = Column(String, nullable=False)
    nombre_producto = Column(String, nullable=False)
    unidad_medida = Column(String, default="Unidad", nullable=False)
    stock_disponible = Column(Float, default=0.0, nullable=False)
    total_recibido = Column(Float, default=0.0, nullable=False)
    total_consumido = Column(Float, default=0.0, nullable=False)
    total_desperdiciado = Column(Float, default=0.0, nullable=False)
    total_devuelto = Column(Float, default=0.0, nullable=False)
    ultimo_movimiento = Column(String, nullable=True)
    fecha_actualizacion = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PresentacionProducto(Base):
    __tablename__ = "presentaciones_producto"
    id = Column(Integer, primary_key=True, index=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False, index=True)
    codigo_producto = Column(String, nullable=False)
    nombre_presentacion = Column(String, nullable=False)
    unidad_compra = Column(String, default="Paquete", nullable=False)
    cantidad_unidades_base = Column(Float, default=1.0, nullable=False)
    unidad_consumo = Column(String, default="Unidad", nullable=False)
    costo_defecto = Column(Float, default=0.0)
    codigo_barras = Column(String, default="")
    activo = Column(Integer, default=1, nullable=False)
    fecha_creacion = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ConsumoMaterialVenta(Base):
    __tablename__ = "consumos_materiales_venta"
    id = Column(Integer, primary_key=True, index=True)
    venta_id = Column(Integer, nullable=False, index=True)
    numero_factura = Column(String, default="")
    usuario_responsable = Column(String, index=True, nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False, index=True)
    codigo_producto = Column(String, nullable=False)
    nombre_producto = Column(String, nullable=False)
    cantidad_consumida = Column(Float, nullable=False)
    unidad_medida = Column(String, default="Unidad", nullable=False)
    saldo_anterior = Column(Float, default=0.0)
    saldo_restante = Column(Float, default=0.0)
    costo_unitario = Column(Float, default=0.0)
    costo_total = Column(Float, default=0.0)
    fecha = Column(String, nullable=False)
    hora = Column(String, nullable=False)
    estado = Column(String, default="Aplicado", nullable=False)
    observaciones = Column(String, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
