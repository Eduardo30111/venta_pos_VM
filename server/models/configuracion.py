from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from ..database import Base


class ConfiguracionNegocio(Base):
    __tablename__ = "configuracion_negocio"

    id = Column(Integer, primary_key=True, index=True)
    nombre_negocio = Column(String, nullable=False, default="VmPOS")
    razon_social = Column(String, nullable=True, default="")
    subtitulo_negocio = Column(String, nullable=True, default="")
    tipo_documento_fiscal = Column(String, nullable=True, default="NIT")
    nit = Column(String, nullable=True, default="")
    regimen_fiscal = Column(String, nullable=True, default="")
    direccion = Column(String, nullable=True, default="")
    ciudad = Column(String, nullable=True, default="")
    telefono = Column(String, nullable=True, default="")
    email = Column(String, nullable=True, default="")
    eslogan = Column(String, nullable=True, default="")
    encabezado_recibo = Column(String, nullable=True, default="")
    tipo_comprobante = Column(String, nullable=True, default="FACTURA DE VENTA POS")
    prefijo_comprobante = Column(String, nullable=True, default="")
    color_barra = Column(String, nullable=True, default="#0284C7")
    color_login = Column(String, nullable=True, default="#1E40AF")
    logo_filename = Column(String, nullable=True, default="")
    logo_base64 = Column(Text, nullable=True, default="")
    logo_hash = Column(String, nullable=True, default="")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
