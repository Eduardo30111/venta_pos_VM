import os
import io
import json
import base64
import hashlib
import sqlite3
import tempfile
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db
from ..models.configuracion import ConfiguracionNegocio
from ..models.usuario import Usuario
from ..middleware.auth import require_admin
from ..middleware.audit import log_audit

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

MAX_LOGO_BYTES = 3 * 1024 * 1024  # 3 MB máximo para logo institucional

try:
    from interface.config import CONFIG_DIR, LOGOS_DIR, DB_VENTAS_PATH
except Exception:
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    CONFIG_DIR = os.path.join(_ROOT, "config")
    LOGOS_DIR = os.path.join(_ROOT, "assets", "logos")
    DB_VENTAS_PATH = os.path.join(_ROOT, "database", "ventas.db")

router = APIRouter(prefix="/configuracion", tags=["Configuración del Negocio"])

CAMPOS_TEXTO = [
    "nombre_negocio",
    "razon_social",
    "subtitulo_negocio",
    "tipo_documento_fiscal",
    "nit",
    "regimen_fiscal",
    "direccion",
    "ciudad",
    "telefono",
    "email",
    "eslogan",
    "encabezado_recibo",
    "tipo_comprobante",
    "prefijo_comprobante",
    "color_barra",
    "color_login",
]


class ConfiguracionNegocioPayload(BaseModel):
    nombre_negocio: Optional[str] = None
    razon_social: Optional[str] = None
    subtitulo_negocio: Optional[str] = None
    tipo_documento_fiscal: Optional[str] = None
    nit: Optional[str] = None
    regimen_fiscal: Optional[str] = None
    direccion: Optional[str] = None
    ciudad: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    eslogan: Optional[str] = None
    encabezado_recibo: Optional[str] = None
    tipo_comprobante: Optional[str] = None
    prefijo_comprobante: Optional[str] = None
    color_barra: Optional[str] = None
    color_login: Optional[str] = None
    logo_base64: Optional[str] = None
    logo_filename: Optional[str] = None
    eliminar_logo: Optional[bool] = False


class LogoPayload(BaseModel):
    logo_base64: str
    filename: Optional[str] = "logo_negocio.png"


def _validar_y_decodificar_logo(b64_str: str) -> bytes:
    """Decodifica base64, limita el tamaño máximo y valida que sea una imagen real con Pillow."""
    try:
        raw = base64.b64decode(b64_str, validate=True)
    except Exception:
        try:
            raw = base64.b64decode(b64_str)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Imagen de logo inválida: {exc}")
    if not raw:
        raise HTTPException(status_code=400, detail="La imagen de logo está vacía.")
    if len(raw) > MAX_LOGO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"El logo supera el tamaño máximo permitido ({MAX_LOGO_BYTES // (1024 * 1024)} MB).",
        )
    if _HAS_PIL:
        try:
            with Image.open(io.BytesIO(raw)) as img:
                img.verify()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"El archivo enviado no es una imagen válida: {exc}")
    return raw


def _leer_semilla_local_servidor() -> Dict[str, Any]:
    """Lee la configuración existente del equipo servidor (SQLite local + JSON) para inicializar la tabla central."""
    datos: Dict[str, Any] = {
        "nombre_negocio": "VmPOS",
        "razon_social": "",
        "subtitulo_negocio": "Sistema de Punto de Venta Profesional",
        "tipo_documento_fiscal": "NIT",
        "nit": "",
        "regimen_fiscal": "",
        "direccion": "",
        "ciudad": "",
        "telefono": "",
        "email": "",
        "eslogan": "¡Gracias por su compra!",
        "encabezado_recibo": "",
        "tipo_comprobante": "FACTURA DE VENTA POS",
        "prefijo_comprobante": "",
        "color_barra": "#0284C7",
        "color_login": "#1E40AF",
        "logo_path": "",
    }
    json_path = os.path.join(CONFIG_DIR, "business_config.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                cargado = json.load(f)
            if isinstance(cargado, dict):
                datos.update({k: v for k, v in cargado.items() if v is not None})
        except Exception:
            pass

    if os.path.exists(DB_VENTAS_PATH):
        try:
            conn = sqlite3.connect(DB_VENTAS_PATH, timeout=5)
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(configuracion_negocio)")
            cols = {row[1] for row in cur.fetchall()}
            row = None
            if "clave" in cols and "valor_json" in cols:
                cur.execute("SELECT valor_json FROM configuracion_negocio WHERE clave = 'business_config'")
                row = cur.fetchone()
            elif "datos_json" in cols:
                cur.execute("SELECT datos_json FROM configuracion_negocio WHERE id = 1")
                row = cur.fetchone()
            conn.close()
            if row and row[0]:
                cargado_db = json.loads(row[0])
                if isinstance(cargado_db, dict):
                    datos.update({k: v for k, v in cargado_db.items() if v is not None})
        except Exception:
            pass

    # Cargar bytes del logo si existe en el servidor
    logo_path = str(datos.get("logo_path", "") or "").strip()
    if logo_path and not os.path.isabs(logo_path):
        cand = os.path.join(os.path.dirname(CONFIG_DIR), logo_path)
        if os.path.exists(cand):
            logo_path = cand
    if logo_path and os.path.exists(logo_path) and os.path.isfile(logo_path):
        try:
            with open(logo_path, "rb") as lf:
                raw = lf.read()
            if raw:
                datos["logo_base64"] = base64.b64encode(raw).decode("ascii")
                datos["logo_filename"] = os.path.basename(logo_path)
                datos["logo_hash"] = hashlib.sha256(raw).hexdigest()[:16]
        except Exception:
            pass
    return datos


def _sincronizar_hacia_archivos_servidor(cfg: ConfiguracionNegocio):
    """Mantiene sincronizados los archivos locales del propio servidor (business_config.json y ventas.db)."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        os.makedirs(LOGOS_DIR, exist_ok=True)
        logo_local_path = ""
        logo_thermal_path = ""

        # Conservar logo_thermal_path existente si corresponde
        json_path = os.path.join(CONFIG_DIR, "business_config.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f_old:
                    prev_cfg = json.load(f_old)
                if isinstance(prev_cfg, dict):
                    logo_thermal_path = str(prev_cfg.get("logo_thermal_path") or "")
            except Exception:
                pass

        if cfg.logo_base64:
            try:
                raw_logo = base64.b64decode(cfg.logo_base64)
                fname = os.path.basename(cfg.logo_filename or "logo_negocio.png")
                ext = os.path.splitext(fname)[1].lower()
                if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"):
                    ext = ".png"
                logo_local_path = os.path.join(LOGOS_DIR, f"logo_negocio{ext}")
                with open(logo_local_path, "wb") as lf:
                    lf.write(raw_logo)
                # Regenerar bitmap térmico 1-bit si Pillow está disponible
                if _HAS_PIL:
                    try:
                        thermal_dest = os.path.join(LOGOS_DIR, "logo_thermal_auto.png")
                        with Image.open(io.BytesIO(raw_logo)) as img_t:
                            img_gray = img_t.convert("L")
                            img_gray.thumbnail((384, 160))
                            img_bw = img_gray.point(lambda x: 0 if x < 165 else 255, "1")
                            img_bw.save(thermal_dest, format="PNG")
                        logo_thermal_path = thermal_dest
                    except Exception:
                        pass
            except Exception:
                logo_local_path = ""
        else:
            logo_thermal_path = ""

        payload_local = {k: getattr(cfg, k, "") or "" for k in CAMPOS_TEXTO}
        payload_local["logo_path"] = logo_local_path
        payload_local["logo_thermal_path"] = logo_thermal_path
        payload_local["logo_hash"] = cfg.logo_hash or ""

        # Escritura atómica del archivo JSON
        fd, tmp_path = tempfile.mkstemp(prefix=".business_cfg_", suffix=".tmp", dir=CONFIG_DIR)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload_local, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, json_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

        if os.path.exists(DB_VENTAS_PATH):
            conn = sqlite3.connect(DB_VENTAS_PATH, timeout=5)
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(configuracion_negocio)")
            cols = {row[1] for row in cur.fetchall()}
            if not cols:
                # Esquema canónico compatible con interface/business_manager.py
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS configuracion_negocio (
                        clave TEXT PRIMARY KEY,
                        valor_json TEXT NOT NULL,
                        actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cols = {"clave", "valor_json", "actualizado_en"}
            payload_str = json.dumps(payload_local, ensure_ascii=False)
            if "clave" in cols and "valor_json" in cols:
                cur.execute(
                    "INSERT INTO configuracion_negocio (clave, valor_json, actualizado_en) "
                    "VALUES ('business_config', ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(clave) DO UPDATE SET valor_json = excluded.valor_json, actualizado_en = CURRENT_TIMESTAMP",
                    (payload_str,),
                )
            elif "datos_json" in cols:
                cur.execute(
                    "INSERT INTO configuracion_negocio (id, datos_json, actualizado_en) VALUES (1, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(id) DO UPDATE SET datos_json = excluded.datos_json, actualizado_en = CURRENT_TIMESTAMP",
                    (payload_str,),
                )
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"Aviso sincronizando configuración en disco del servidor: {e}")


async def obtener_o_crear_config_negocio(db: AsyncSession) -> ConfiguracionNegocio:
    res = await db.execute(select(ConfiguracionNegocio).where(ConfiguracionNegocio.id == 1))
    cfg = res.scalars().first()
    if not cfg:
        semilla = _leer_semilla_local_servidor()
        cfg = ConfiguracionNegocio(
            id=1,
            nombre_negocio=str(semilla.get("nombre_negocio") or "VmPOS"),
            razon_social=str(semilla.get("razon_social") or ""),
            subtitulo_negocio=str(semilla.get("subtitulo_negocio") or ""),
            tipo_documento_fiscal=str(semilla.get("tipo_documento_fiscal") or "NIT"),
            nit=str(semilla.get("nit") or ""),
            regimen_fiscal=str(semilla.get("regimen_fiscal") or ""),
            direccion=str(semilla.get("direccion") or ""),
            ciudad=str(semilla.get("ciudad") or ""),
            telefono=str(semilla.get("telefono") or ""),
            email=str(semilla.get("email") or ""),
            eslogan=str(semilla.get("eslogan") or ""),
            encabezado_recibo=str(semilla.get("encabezado_recibo") or ""),
            tipo_comprobante=str(semilla.get("tipo_comprobante") or "FACTURA DE VENTA POS"),
            prefijo_comprobante=str(semilla.get("prefijo_comprobante") or ""),
            color_barra=str(semilla.get("color_barra") or "#0284C7"),
            color_login=str(semilla.get("color_login") or "#1E40AF"),
            logo_filename=str(semilla.get("logo_filename") or ""),
            logo_base64=str(semilla.get("logo_base64") or ""),
            logo_hash=str(semilla.get("logo_hash") or ""),
        )
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
    return cfg


def _serializar_config(cfg: ConfiguracionNegocio, incluir_logo_base64: bool = True) -> Dict[str, Any]:
    tiene_logo = bool(cfg.logo_base64 and len(cfg.logo_base64.strip()) > 0)
    data = {k: getattr(cfg, k, "") or "" for k in CAMPOS_TEXTO}
    data.update({
        "tiene_logo": tiene_logo,
        "logo_hash": cfg.logo_hash or "",
        "logo_filename": cfg.logo_filename or "",
        "logo_url": "/api/configuracion/logo" if tiene_logo else "",
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else datetime.now(timezone.utc).isoformat(),
    })
    if incluir_logo_base64 and tiene_logo:
        data["logo_base64"] = cfg.logo_base64
    return data


@router.get("/negocio")
async def get_configuracion_negocio(db: AsyncSession = Depends(get_db)):
    cfg = await obtener_o_crear_config_negocio(db)
    return _serializar_config(cfg, incluir_logo_base64=True)


@router.put("/negocio")
async def update_configuracion_negocio(
    payload: ConfiguracionNegocioPayload,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    cfg = await obtener_o_crear_config_negocio(db)
    estado_anterior = {k: getattr(cfg, k, "") or "" for k in CAMPOS_TEXTO}
    estado_anterior["logo_hash"] = cfg.logo_hash or ""

    datos_dict = payload.dict(exclude_unset=True)

    for campo in CAMPOS_TEXTO:
        if campo in datos_dict and datos_dict[campo] is not None:
            setattr(cfg, campo, str(datos_dict[campo]).strip())

    if datos_dict.get("eliminar_logo"):
        cfg.logo_base64 = ""
        cfg.logo_filename = ""
        cfg.logo_hash = ""
    elif "logo_base64" in datos_dict and datos_dict["logo_base64"] is not None:
        b64_str = str(datos_dict["logo_base64"]).strip()
        if b64_str:
            raw = _validar_y_decodificar_logo(b64_str)
            cfg.logo_base64 = base64.b64encode(raw).decode("ascii")
            cfg.logo_filename = os.path.basename(str(datos_dict.get("logo_filename") or "logo_negocio.png"))
            cfg.logo_hash = hashlib.sha256(raw).hexdigest()[:16]
        else:
            cfg.logo_base64 = ""
            cfg.logo_filename = ""
            cfg.logo_hash = ""

    cfg.updated_at = datetime.now(timezone.utc)
    estado_nuevo = {k: getattr(cfg, k, "") or "" for k in CAMPOS_TEXTO}
    estado_nuevo["logo_hash"] = cfg.logo_hash or ""
    await log_audit(
        db=db,
        modulo="CONFIGURACION",
        accion="ACTUALIZAR_NEGOCIO",
        entidad_id=1,
        usuario_id=current_user.id,
        usuario_nombre=current_user.nombre or current_user.usuario,
        valor_anterior=estado_anterior,
        valor_nuevo=estado_nuevo,
        detalles=f"Identidad del negocio actualizada: {cfg.nombre_negocio}",
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(cfg)
    _sincronizar_hacia_archivos_servidor(cfg)
    return _serializar_config(cfg, incluir_logo_base64=True)


@router.get("/logo")
async def get_logo_negocio(db: AsyncSession = Depends(get_db)):
    cfg = await obtener_o_crear_config_negocio(db)
    if not cfg.logo_base64:
        raise HTTPException(status_code=404, detail="El negocio no tiene un logo configurado en el servidor central.")
    try:
        raw_bytes = base64.b64decode(cfg.logo_base64)
    except Exception:
        raise HTTPException(status_code=500, detail="Error decodificando el logo almacenado en el servidor.")

    ext = os.path.splitext(cfg.logo_filename or "")[1].lower()
    media_type = "image/png"
    if ext in (".jpg", ".jpeg"):
        media_type = "image/jpeg"
    elif ext == ".webp":
        media_type = "image/webp"
    elif ext == ".gif":
        media_type = "image/gif"

    return Response(
        content=raw_bytes,
        media_type=media_type,
        headers={"X-Logo-Hash": cfg.logo_hash or ""},
    )


@router.post("/logo")
async def upload_logo_negocio(
    payload: LogoPayload,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    cfg = await obtener_o_crear_config_negocio(db)
    hash_anterior = cfg.logo_hash or ""
    b64_str = (payload.logo_base64 or "").strip()
    if not b64_str:
        cfg.logo_base64 = ""
        cfg.logo_filename = ""
        cfg.logo_hash = ""
    else:
        raw = _validar_y_decodificar_logo(b64_str)
        cfg.logo_base64 = base64.b64encode(raw).decode("ascii")
        cfg.logo_filename = os.path.basename(payload.filename or "logo_negocio.png")
        cfg.logo_hash = hashlib.sha256(raw).hexdigest()[:16]

    cfg.updated_at = datetime.now(timezone.utc)
    await log_audit(
        db=db,
        modulo="CONFIGURACION",
        accion="ACTUALIZAR_LOGO",
        entidad_id=1,
        usuario_id=current_user.id,
        usuario_nombre=current_user.nombre or current_user.usuario,
        valor_anterior={"logo_hash": hash_anterior},
        valor_nuevo={"logo_hash": cfg.logo_hash or "", "logo_filename": cfg.logo_filename or ""},
        detalles="Logo del negocio actualizado" if cfg.logo_base64 else "Logo del negocio eliminado",
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(cfg)
    _sincronizar_hacia_archivos_servidor(cfg)
    return {
        "ok": True,
        "tiene_logo": bool(cfg.logo_base64),
        "logo_hash": cfg.logo_hash,
        "logo_url": "/api/configuracion/logo" if cfg.logo_base64 else "",
    }
