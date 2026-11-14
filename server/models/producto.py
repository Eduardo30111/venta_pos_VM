from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base


class Producto(Base):
    __tablename__ = "productos"
    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String, unique=True, index=True, nullable=True)  # 00001
    nombre = Column(String, nullable=True)
    descripcion = Column(String, nullable=True)
    categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=True)
    categoria = Column(String, default="General", nullable=True)
    marca = Column(String, default="", nullable=True)
    unidad_medida = Column(String, default="Unidad", nullable=True)
    precio_costo = Column(Float, default=0.0, nullable=True)
    costo = Column(Float, default=0.0, nullable=True)
    precio_venta = Column(Float, default=0.0, nullable=True)
    precio = Column(Float, default=0.0, nullable=True)
    tipo_producto = Column(String, default="Producto", nullable=True)
    stock = Column(Float, default=0.0)
    stock_minimo = Column(Float, default=0.0)
    stock_bodega = Column(Float, default=0.0)
    stock_vitrina = Column(Float, default=0.0)
    stock_minimo_bodega = Column(Float, default=5.0)
    stock_minimo_vitrina = Column(Float, default=3.0)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=True)
    codigo_barras = Column(String, nullable=True)
    imagen_url = Column(String, nullable=True)
    precio_variable = Column(Boolean, default=False)
    porcentaje_comision = Column(Float, default=0.0)
    es_material = Column(Boolean, default=False)
    presentacion_defecto = Column(String, default="Paquete")
    factor_conversion_defecto = Column(Float, default=1.0)
    unidad_consumo_defecto = Column(String, default="Unidad")
    estado = Column(String, default="Activo")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __init__(self, **kwargs):
        # Sincronización automática de alias heredados de columnas
        pc = kwargs.get("precio_costo") if "precio_costo" in kwargs else kwargs.get("costo")
        if pc is not None:
            kwargs["precio_costo"] = float(pc or 0.0)
            kwargs["costo"] = float(pc or 0.0)
        pv = kwargs.get("precio_venta") if "precio_venta" in kwargs else kwargs.get("precio")
        if pv is not None:
            kwargs["precio_venta"] = float(pv or 0.0)
            kwargs["precio"] = float(pv or 0.0)
        super().__init__(**kwargs)

    def __setattr__(self, key, value):
        super().__setattr__(key, value)
        if key == "precio_costo" and getattr(self, "costo", None) != value:
            super().__setattr__("costo", value)
        elif key == "costo" and getattr(self, "precio_costo", None) != value:
            super().__setattr__("precio_costo", value)
        elif key == "precio_venta" and getattr(self, "precio", None) != value:
            super().__setattr__("precio", value)
        elif key == "precio" and getattr(self, "precio_venta", None) != value:
            super().__setattr__("precio_venta", value)

