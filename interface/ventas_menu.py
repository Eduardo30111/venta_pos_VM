# ====================================================================================
#   SISTEMA DE VENTAS - VARIEDADES MARCE - VERSIÓN MEJORADA Y CORREGIDA
# ====================================================================================

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import os
import sys
import uuid
import time
import sqlite3
import subprocess
import threading
import httpx
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from client.api_client import api

try:
    from database_manager import conectar_db
except ImportError:
    from interface.database_manager import conectar_db

try:
    from theme_manager import theme_mgr, aplicar_tema, calcular_geometria_segura, calcular_color_texto_optimo, crear_boton, ScrollableContainer
except ImportError:
    from interface.theme_manager import theme_mgr, aplicar_tema, calcular_geometria_segura, calcular_color_texto_optimo, crear_boton, ScrollableContainer

try:
    from interface.business_manager import business_mgr
except ImportError:
    from business_manager import business_mgr

try:
    from escpos.printer import Usb, Win32Raw
    import usb.core
    import usb.util
    IMPRESION_DISPONIBLE = True
except Exception:
    Usb = None
    Win32Raw = None
    IMPRESION_DISPONIBLE = False

try:
    from components.currency_entry import CurrencyEntry, formatear_cop
except ImportError:
    from interface.components.currency_entry import CurrencyEntry, formatear_cop

try:
    from caja_manager import (
        obtener_sesion_activa, abrir_sesion_caja, registrar_movimiento_caja, registrar_movimiento_financiero
    )
except ImportError:
    from interface.caja_manager import (
        obtener_sesion_activa, abrir_sesion_caja, registrar_movimiento_caja, registrar_movimiento_financiero
    )

def guardar_venta_sqlite(
    doc_cliente,
    total,
    metodo_pago,
    detalles,
    operario_nombre="Administrador",
    cliente_id=None,
    recibido=0.0,
    cambio=0.0,
    numero_factura="",
    snapshot_negocio=None,
    pagos=None
):
    """Guarda la venta de forma local en SQLite (database/ventas.db) para persistencia y respaldo."""
    try:
        try:
            from database_manager import conectar_db
        except ImportError:
            from interface.database_manager import conectar_db

        try:
            from receipt_manager import asegurar_columnas_factura_ventas, guardar_snapshot_venta_sqlite
        except ImportError:
            from interface.receipt_manager import asegurar_columnas_factura_ventas, guardar_snapshot_venta_sqlite

        conn = conectar_db()
        if not conn:
            return None
        cur = conn.cursor()
        hoy_str = datetime.now().strftime("%Y-%m-%d")
        hora_str = datetime.now().strftime("%H:%M:%S")
        doc = str(doc_cliente or "Consumidor Final").strip() or "Consumidor Final"

        # Obtener o vincular sesión de caja activa (OBLIGATORIO)
        activa = obtener_sesion_activa(conn=conn)
        if not activa:
            try:
                sesion_id = abrir_sesion_caja(
                    usuario=operario_nombre or "Administrador",
                    monto_inicial=0.0,
                    observaciones="Apertura automática de seguridad por venta",
                    conn=conn
                )
            except Exception:
                sesion_id = 1
        else:
            sesion_id = activa["id"]

        # Asegurar columnas de cartera y de snapshot de factura en ventas
        asegurar_columnas_factura_ventas(conn=conn)
        cur.execute("PRAGMA table_info(ventas)")
        v_cols = [c[1] for c in cur.fetchall()]
        if "cliente_id" not in v_cols:
            try:
                cur.execute("ALTER TABLE ventas ADD COLUMN cliente_id INTEGER DEFAULT NULL")
            except Exception:
                pass
        if "saldo_pendiente" not in v_cols:
            try:
                cur.execute("ALTER TABLE ventas ADD COLUMN saldo_pendiente REAL DEFAULT 0.0")
            except Exception:
                pass

        # Si es Fiado y vino cliente_id o doc, sincronizar documento_cliente real
        cli_id_int = None
        if cliente_id is not None and str(cliente_id).strip().isdigit():
            cli_id_int = int(str(cliente_id).strip())
            try:
                cur.execute("SELECT cedula, nombre FROM clientes WHERE id = ?", (cli_id_int,))
                cr = cur.fetchone()
                if cr and cr[0]:
                    doc = str(cr[0]).strip()
                elif not cr and doc and doc != "Consumidor Final":
                    cur.execute("""
                        INSERT INTO clientes (id, cedula, nombre, permite_fiado, saldo_pendiente, fecha_registro)
                        VALUES (?, ?, ?, 1, 0.0, ?)
                    """, (cli_id_int, doc, f"Cliente #{cli_id_int}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            except Exception:
                pass
        elif doc and doc != "Consumidor Final":
            try:
                cur.execute("SELECT id, cedula FROM clientes WHERE cedula = ? OR LOWER(nombre) = LOWER(?)", (doc, doc))
                cr = cur.fetchone()
                if cr:
                    cli_id_int = int(cr[0])
                    if cr[1]:
                        doc = str(cr[1]).strip()
            except Exception:
                pass

        monto_fiado_calc = 0.0
        if str(metodo_pago) == "Fiado":
            monto_fiado_calc = float(total)
        elif str(metodo_pago) == "Mixto" and pagos:
            monto_fiado_calc = sum(float(p.get("monto", 0.0) or 0.0) for p in pagos if p.get("metodo") == "Fiado")

        saldo_pend_venta = monto_fiado_calc

        cur.execute("""
            INSERT INTO ventas (
                fecha_venta, hora_venta, documento_cliente, cliente_id,
                total_venta, saldo_pendiente, metodo_pago, operario, estado, sesion_caja_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Completada', ?)
        """, (hoy_str, hora_str, doc, cli_id_int, float(total), saldo_pend_venta, str(metodo_pago), str(operario_nombre), sesion_id))
        id_venta = cur.lastrowid

        # Guardar snapshot histórico inmutable del negocio y datos de cobro en la venta
        guardar_snapshot_venta_sqlite(
            id_venta=id_venta,
            numero_factura=numero_factura,
            recibido=recibido if recibido > 0 else (0.0 if str(metodo_pago) == "Fiado" else float(total)),
            cambio=cambio,
            snapshot_negocio=snapshot_negocio,
            conn=conn
        )

        detalles_enriquecidos = []
        for idx, d in enumerate(detalles, start=1):
            cod = str(d.get("item_codigo", d.get("codigo", "00000")))
            nom = str(d.get("item_nombre", d.get("nombre", "Producto")))
            pre = float(d.get("precio_vendido", d.get("precio", 0.0)))
            c_raw = float(d.get("cantidad", 1))
            cant = int(c_raw) if c_raw.is_integer() else round(c_raw, 3)
            sub = float(d.get("subtotal", pre * cant))

            # Obtener costo unitario histórico del producto en este instante exacto
            costo_unit = 0.0
            tipo_prod = str(d.get("tipo_item", "Fisico") or "Fisico")
            try:
                cur.execute("SELECT costo, tipo_producto FROM productos WHERE codigo = ?", (cod,))
                p_row = cur.fetchone()
                if p_row:
                    if p_row[0] is not None:
                        costo_unit = float(p_row[0])
                    if p_row[1]:
                        tipo_prod = str(p_row[1])
            except Exception:
                pass

            # Si es servicio, el costo de mercancía de inventario es 0
            if tipo_prod == "Servicio":
                costo_unit = 0.0

            cur.execute("""
                INSERT INTO detalle_ventas (id_venta, codigo_producto, nombre_producto, precio_unitario, cantidad, subtotal, costo_unitario)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (id_venta, cod, nom, pre, cant, sub, costo_unit))
            id_det = cur.lastrowid

            d_copy = dict(d)
            d_copy["id_detalle"] = id_det
            d_copy["tipo_item"] = "Servicio" if tipo_prod == "Servicio" else "Producto"
            d_copy["item_nombre"] = nom
            d_copy["subtotal"] = sub
            d_copy["costo_unitario"] = d.get("costo_unitario") or costo_unit
            d_copy["proveedor_id"] = d.get("proveedor_id")
            d_copy["porcentaje_comision"] = d.get("porcentaje_comision")
            detalles_enriquecidos.append(d_copy)

            # Registrar la Cuenta por Pagar al proveedor si el ítem (producto físico o servicio) tiene proveedor asignado
            try:
                try:
                    from interface.proveedores_manager import registrar_cxp_servicio_venta
                except ImportError:
                    from proveedores_manager import registrar_cxp_servicio_venta
                registrar_cxp_servicio_venta(
                    id_venta=id_venta,
                    detalle_item=d_copy,
                    operario_nombre=operario_nombre,
                    numero_venta=numero_factura or f"V-{id_venta:05d}",
                    fecha_str=hoy_str,
                    hora_str=hora_str,
                    conn=conn
                )
            except Exception as e_cxp:
                print(f"Aviso registrando cuenta por pagar a proveedor: {e_cxp}")

            if tipo_prod != "Servicio":
                try:
                    # Descontar de vitrina prioritariamente y mantener stock = stock_bodega + stock_vitrina
                    cur.execute("SELECT id, stock_vitrina, stock_bodega, unidad_medida FROM productos WHERE codigo = ?", (cod,))
                    p_info = cur.fetchone()
                    if p_info:
                        p_id = p_info[0]
                        sv_ant = float(p_info[1] or 0.0)
                        sb_ant = float(p_info[2] or 0.0)
                        u_med = str(p_info[3] or "Unidad")
                        sv_des = max(0.0, sv_ant - cant)
                        stock_tot = sb_ant + sv_des
                        cur.execute("""
                            UPDATE productos 
                            SET stock_vitrina = ?, stock = ? 
                            WHERE codigo = ?
                        """, (sv_des, stock_tot, cod))

                        # Registrar movimiento de Venta en el Kárdex de Inventario
                        cur.execute("""
                            INSERT INTO movimientos_inventario (
                                fecha, hora, producto_id, codigo_producto, nombre_producto,
                                tipo_movimiento, cantidad, unidad_medida, ubicacion_origen,
                                ubicacion_destino, stock_origen_ant, stock_origen_des,
                                stock_destino_ant, stock_destino_des, costo_unitario, valor_total,
                                referencia, usuario, observaciones, estado
                            ) VALUES (?, ?, ?, ?, ?, 'VENTA', ?, ?, 'VITRINA', 'CLIENTE', ?, ?, 0, 0, ?, ?, ?, ?, 'Salida por venta en mostrador', 'Completado')
                        """, (
                            hoy_str, hora_str, p_id, cod, nom,
                            cant, u_med, sv_ant, sv_des, costo_unit, costo_unit * cant,
                            f"VENTA-{id_venta}", operario_nombre
                        ))
                except Exception as e:
                    print(f"Aviso actualizando stock en venta: {e}")

        # Registrar medio de pago en libro mayor de pagos
        try:
            if pagos and str(metodo_pago) == "Mixto":
                for p_it in pagos:
                    cur.execute("""
                        INSERT INTO pagos_venta (id_venta, metodo_pago, monto, referencia, fecha, hora)
                        VALUES (?, ?, ?, '', ?, ?)
                    """, (id_venta, str(p_it.get("metodo", "Efectivo")), float(p_it.get("monto", 0.0)), hoy_str, hora_str))
            else:
                cur.execute("""
                    INSERT INTO pagos_venta (id_venta, metodo_pago, monto, referencia, fecha, hora)
                    VALUES (?, ?, ?, '', ?, ?)
                """, (id_venta, str(metodo_pago), float(total), hoy_str, hora_str))
        except Exception:
            pass

        # Asegurar commit previo para evitar bloqueo de SQLite durante sincronización de caja
        conn.commit()

        # Impacto contable en libro central según método de pago
        try:
            if str(metodo_pago) == "Mixto" and pagos:
                for p_it in pagos:
                    m_n = p_it.get("metodo")
                    m_v = float(p_it.get("monto", 0.0) or 0.0)
                    if m_v <= 0:
                        continue
                    if m_n == "Efectivo":
                        registrar_movimiento_financiero(
                            tipo="VENTA_EFECTIVO",
                            concepto=f"Venta mixta en efectivo #{id_venta}",
                            monto=m_v,
                            metodo_pago="Efectivo",
                            cuenta_afectada="CAJA_FISICA",
                            usuario=operario_nombre,
                            referencia_origen=f"VENTA-{id_venta}",
                            sesion_id=sesion_id,
                            conn=conn,
                            sincronizar_caja=True
                        )
                    elif m_n == "Transferencia":
                        registrar_movimiento_financiero(
                            tipo="VENTA_TRANSFERENCIA",
                            concepto=f"Venta mixta por transferencia #{id_venta}",
                            monto=m_v,
                            metodo_pago="Transferencia",
                            cuenta_afectada="BANCO_TRANSFERENCIA",
                            usuario=operario_nombre,
                            referencia_origen=f"VENTA-{id_venta}",
                            sesion_id=sesion_id,
                            conn=conn,
                            sincronizar_caja=False
                        )
                    elif m_n == "Fiado":
                        registrar_movimiento_financiero(
                            tipo="VENTA_CREDITO",
                            concepto=f"Venta mixta a crédito/fiado #{id_venta} - {doc}",
                            monto=m_v,
                            metodo_pago="Fiado",
                            cuenta_afectada="CARTERA_CLIENTES",
                            usuario=operario_nombre,
                            referencia_origen=f"VENTA-{id_venta}",
                            sesion_id=sesion_id,
                            conn=conn,
                            sincronizar_caja=False
                        )
                        try:
                            if cli_id_int is not None:
                                cur.execute("UPDATE clientes SET saldo_pendiente = COALESCE(saldo_pendiente, 0.0) + ? WHERE id = ?", (m_v, cli_id_int))
                            elif doc and doc != "Consumidor Final":
                                cur.execute("UPDATE clientes SET saldo_pendiente = COALESCE(saldo_pendiente, 0.0) + ? WHERE cedula = ? OR LOWER(nombre) = LOWER(?)", (m_v, doc, doc))
                        except Exception as e_fiado:
                            print(f"Aviso actualizando deuda de cliente en venta mixta: {e_fiado}")
            elif str(metodo_pago) == "Efectivo":
                registrar_movimiento_financiero(
                    tipo="VENTA_EFECTIVO",
                    concepto=f"Venta en efectivo #{id_venta}",
                    monto=float(total),
                    metodo_pago="Efectivo",
                    cuenta_afectada="CAJA_FISICA",
                    usuario=operario_nombre,
                    referencia_origen=f"VENTA-{id_venta}",
                    sesion_id=sesion_id,
                    conn=conn,
                    sincronizar_caja=True
                )
            elif str(metodo_pago) == "Transferencia":
                registrar_movimiento_financiero(
                    tipo="VENTA_TRANSFERENCIA",
                    concepto=f"Venta por transferencia #{id_venta}",
                    monto=float(total),
                    metodo_pago="Transferencia",
                    cuenta_afectada="BANCO_TRANSFERENCIA",
                    usuario=operario_nombre,
                    referencia_origen=f"VENTA-{id_venta}",
                    sesion_id=sesion_id,
                    conn=conn,
                    sincronizar_caja=False
                )
            elif str(metodo_pago) == "Fiado":
                registrar_movimiento_financiero(
                    tipo="VENTA_CREDITO",
                    concepto=f"Venta fiada/crédito #{id_venta} - {doc}",
                    monto=float(total),
                    metodo_pago="Fiado",
                    cuenta_afectada="CARTERA_CLIENTES",
                    usuario=operario_nombre,
                    referencia_origen=f"VENTA-{id_venta}",
                    sesion_id=sesion_id,
                    conn=conn,
                    sincronizar_caja=False
                )
                try:
                    if cli_id_int is not None:
                        cur.execute("UPDATE clientes SET saldo_pendiente = COALESCE(saldo_pendiente, 0.0) + ? WHERE id = ?", (float(total), cli_id_int))
                    elif doc and doc != "Consumidor Final":
                        cur.execute("UPDATE clientes SET saldo_pendiente = COALESCE(saldo_pendiente, 0.0) + ? WHERE cedula = ? OR LOWER(nombre) = LOWER(?)", (float(total), doc, doc))
                except Exception as e_fiado:
                    print(f"Aviso actualizando deuda de cliente: {e_fiado}")
        except Exception as e_fin:
            print(f"Aviso registrando movimiento financiero: {e_fin}")

        conn.commit()
        conn.close()

        # Procesar devengo de jornada (1ª venta del día) y comisiones de forma idempotente
        try:
            try:
                from nomina_manager import procesar_venta_nomina_y_comisiones
            except ImportError:
                from interface.nomina_manager import procesar_venta_nomina_y_comisiones
            procesar_venta_nomina_y_comisiones(
                id_venta=id_venta,
                operario_nombre=str(operario_nombre),
                total_venta=float(total),
                metodo_pago=str(metodo_pago),
                detalles_payload=detalles_enriquecidos,
                fecha=hoy_str
            )
        except Exception as e_nom_v:
            print(f"Aviso procesando nómina/comisiones de venta #{id_venta}: {e_nom_v}")

        print(f"✅ Venta local #{id_venta} registrada en SQLite por {operario_nombre} (${total:,.0f} COP)")
        return id_venta
    except Exception as e:
        print(f"Aviso guardando venta local en SQLite: {e}")
        return None

class PrinterManager:
    """Manejador de impresoras con configuración automática"""
    
    def __init__(self):
        self.printer = None
        self.printer_type = None
        self.config_exitosa = None
        self.ultima_factura = None  # Guardar última factura para reimpresión
    
    def conectar_impresora(self):
        """Conecta automáticamente usando el método que funcione"""
        # Configuraciones comunes de impresoras térmicas
        configs = [
            # DIG ISH58 / XP-58 - TU IMPRESORA ESPECÍFICA
            {"vid": 0x0fe6, "pid": 0x811e, "in_ep": 0x82, "out_ep": 0x01, "model": "DIG_ISH58"},
            {"vid": 0x0fe6, "pid": 0x811f, "in_ep": 0x82, "out_ep": 0x01, "model": "DIG_ISH58"}, 
            {"vid": 0x0fe6, "pid": 0x811d, "in_ep": 0x82, "out_ep": 0x01, "model": "DIG_ISH58"},
            # XP-58 genérico
            {"vid": 0x1fc9, "pid": 0x2016, "in_ep": 0x82, "out_ep": 0x01, "model": "XP58"},
            {"vid": 0x04b8, "pid": 0x0e28, "in_ep": 0x82, "out_ep": 0x01, "model": "XP58"},
            # DigitalPOS otros modelos
            {"vid": 0x0fe6, "pid": 0x811e, "in_ep": 0x82, "out_ep": 0x01},
            {"vid": 0x0fe6, "pid": 0x811f, "in_ep": 0x82, "out_ep": 0x01},
            {"vid": 0x0fe6, "pid": 0x811d, "in_ep": 0x82, "out_ep": 0x01},
            # Gprinter GP-58
            {"vid": 0x0416, "pid": 0x5011, "in_ep": 0x82, "out_ep": 0x01},
            {"vid": 0x0416, "pid": 0x5011, "in_ep": 0x81, "out_ep": 0x02},
            # Epson
            {"vid": 0x04b8, "pid": 0x0202, "in_ep": 0x82, "out_ep": 0x01},
            {"vid": 0x04b8, "pid": 0x0e15, "in_ep": 0x82, "out_ep": 0x01},
        ]
        
        print("🔍 Detectando impresora...")
        
        # Intentar conexión USB directa
        devices = usb.core.find(find_all=True)
        for device in devices:
            if device.bDeviceClass == 7:  # Clase de impresora
                vid, pid = device.idVendor, device.idProduct
                print(f"📱 Probando impresora: VID={hex(vid)}, PID={hex(pid)}")
                
                # Probar configuraciones conocidas
                for config in configs:
                    if config["vid"] == vid and config["pid"] == pid:
                        if self._probar_config_usb(config):
                            return True
                
                # Probar configuración genérica
                config_generica = {"vid": vid, "pid": pid, "in_ep": 0x82, "out_ep": 0x01}
                if self._probar_config_usb(config_generica):
                    return True
        
        # Intentar conexión Windows
        return self._conectar_windows()
    
    def _probar_config_usb(self, config):
        """Prueba una configuración USB específica"""
        try:
            printer = Usb(
                idVendor=config["vid"],
                idProduct=config["pid"],
                timeout=5000,
                in_ep=config["in_ep"],
                out_ep=config["out_ep"]
            )
            
            # Test básico
            printer.text("")
            
            self.printer = printer
            self.printer_type = "USB"
            self.config_exitosa = config
            
            # Detectar si es DIG ISH58/XP-58 para manejo especial
            if config.get("model") in ["DIG_ISH58", "XP58"] or config["vid"] == 0x0fe6:
                print(f"✅ Conexión USB exitosa - DIG ISH58/XP-58: {hex(config['vid'])}:{hex(config['pid'])}")
                self.is_dig_ish58 = True
            else:
                print(f"✅ Conexión USB exitosa: {hex(config['vid'])}:{hex(config['pid'])}")
                self.is_dig_ish58 = False
            
            return True
            
        except Exception as e:
            print(f"❌ Config fallida: {str(e)[:30]}...")
            return False
    
    def _conectar_windows(self):
        """Intenta conexión usando driver Windows"""
        try:
            import win32print
            printers = [p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL)]
            
            if printers:
                printer = Win32Raw(printers[0])
                self.printer = printer
                self.printer_type = "Windows"
                print(f"✅ Conexión Windows: {printers[0]}")
                return True
                
        except Exception as e:
            print(f"❌ Error Windows: {e}")
            
        return False
    
    def imprimir_factura(self, factura_data, callback=None, config_override=None):
        """Imprime factura usando el motor unificado (58mm, 80mm, A4, logo y caracteres español)."""
        try:
            from receipt_manager import (
                imprimir_factura_unificada,
                normalizar_datos_factura,
                generar_texto_factura,
                _imagen_a_escpos_raster,
                _codificar_texto_escpos
            )
        except ImportError:
            from interface.receipt_manager import (
                imprimir_factura_unificada,
                normalizar_datos_factura,
                generar_texto_factura,
                _imagen_a_escpos_raster,
                _codificar_texto_escpos
            )

        self.ultima_factura = dict(factura_data) if isinstance(factura_data, dict) else factura_data
        ok, msg = imprimir_factura_unificada(factura_data, config_override=config_override)
        if ok:
            if callback:
                callback(True, msg)
            return True

        # Fallback al objeto self.printer si ya estaba conectado en sesión
        if self.printer:
            try:
                norm = normalizar_datos_factura(factura_data)
                cfg = business_mgr.obtener_config_impresora()
                if isinstance(config_override, dict):
                    cfg.update(config_override)
                fmt = cfg.get("formato_papel", "58mm")
                if fmt not in ("58mm", "80mm"):
                    fmt = "58mm"
                neg = norm["negocio"]
                logo_b = b""
                if cfg.get("mostrar_logo", True) and neg.get("logo_path"):
                    logo_b = _imagen_a_escpos_raster(neg["logo_path"], max_width_dots=240 if fmt == "58mm" else 360)
                txt_b = _codificar_texto_escpos(generar_texto_factura(norm, formato=fmt, config_impresora=cfg) + "\n\n\n")
                corte_b = b"\x1D\x56\x41\x03" if cfg.get("corte_automatico", True) else b""
                self.printer._raw(b"\x1B\x40" + logo_b + txt_b + corte_b)
                if callback:
                    callback(True, "Factura impresa por conexión directa")
                return True
            except Exception as e_fb:
                msg = f"{msg} ({e_fb})"

        if callback:
            callback(False, msg)
        return False
    
    def reimprimir_ultima_factura(self):
        """Reimprime la última factura guardada"""
        if not self.ultima_factura:
            raise Exception("No hay factura previa para reimprimir")
        
        print("🔄 Reimprimiendo última factura...")
        self.imprimir_factura(self.ultima_factura)
    
    def abrir_caja_registradora(self):
        """Abre la caja registradora enviando comando ESC/POS - OPTIMIZADO PARA DIG ISH58"""
        try:
            if self.printer:
                print("DEBUG: Enviando comando de apertura de caja para DIG ISH58...")
                
                # MÉTODO ESPECÍFICO PARA DIG ISH58/XP-58: Múltiples comandos
                comandos_caja = [
                    b'\x1B\x70\x00\x32\x32',  # ESC p 0 50 50 - Comando principal
                    b'\x1B\x70\x01\x32\x32',  # ESC p 1 50 50 - Puerto alternativo
                    b'\x1C\x70\x00\x7F\xFF', # Comando alternativo DIG
                    b'\x10\x14\x01\x00\x05', # Comando específico XP-58
                ]
                
                for i, comando in enumerate(comandos_caja):
                    try:
                        print(f"DEBUG: Enviando comando caja #{i+1}...")
                        self.printer._raw(comando)
                        
                        # Pequeña pausa entre comandos
                        import time
                        time.sleep(0.1)
                        
                    except Exception as e:
                        print(f"DEBUG: Comando #{i+1} falló: {e}")
                        continue
                
                # FLUSH FORZADO igual que en impresión
                try:
                    if hasattr(self.printer, '_device'):
                        self.printer._device.write(self.printer._out_ep, b'\x00', timeout=1000)
                except:
                    pass
                
                print("💰 Comandos de caja enviados - DIG ISH58")
                return True
            else:
                raise Exception("Impresora no conectada")
        except Exception as e:
            print(f"⚠️ Error al abrir caja: {e}")
            raise e

class App:
    def __init__(self, ventana, user_id="", rol="", parent_pid="", usuario_nombre=""):
        self.ventana = ventana
        self.parent_pid = parent_pid or os.environ.get("VMPOS_PARENT_PID")
        try:
            from session_manager import session_mgr
        except ImportError:
            from interface.session_manager import session_mgr
        session_mgr.iniciar_vigilante_padre(self.ventana, parent_pid=self.parent_pid)
        try:
            from theme_manager import iniciar_observador_tema
        except ImportError:
            from interface.theme_manager import iniciar_observador_tema
        iniciar_observador_tema(self.ventana)

        business_mgr.recargar()
        self.user_id = user_id
        self.rol = rol
        self.user_nombre = usuario_nombre or ""
        
        # Obtener información del usuario desde la API si no vino completa
        if not self.user_nombre or not self.rol:
            try:
                me = api.get("/auth/me")
                if me.status_code == 200:
                    me_data = me.json()
                    self.user_id = self.user_id or str(me_data.get("id", ""))
                    self.rol = self.rol or me_data.get("rol", "")
                    self.user_nombre = self.user_nombre or f"{me_data.get('nombre', '')} {me_data.get('apellidos', '')}".strip() or me_data.get("usuario", "")
            except Exception as e:
                print("DEBUG: Error obteniendo perfil:", e)

        # Fallback local a usuarios.db si estamos offline o falta información
        if not self.user_nombre or not self.rol:
            try:
                try:
                    from interface.usuarios_db import conectar_usuarios_db
                except ImportError:
                    from usuarios_db import conectar_usuarios_db
                conn_u = conectar_usuarios_db()
                if conn_u:
                    cur_u = conn_u.cursor()
                    if self.user_id:
                        cur_u.execute("SELECT id, usuario, rol, nombre, apellidos FROM usuarios WHERE id = ? OR usuario = ?", (self.user_id, str(self.user_id)))
                    elif self.rol:
                        cur_u.execute("SELECT id, usuario, rol, nombre, apellidos FROM usuarios WHERE LOWER(rol) = LOWER(?) LIMIT 1", (str(self.rol),))
                    else:
                        cur_u.execute("SELECT id, usuario, rol, nombre, apellidos FROM usuarios LIMIT 1")
                    row_u = cur_u.fetchone()
                    if row_u:
                        nom_comp = f"{row_u[3] or ''} {row_u[4] or ''}".strip()
                        self.user_nombre = self.user_nombre or nom_comp or row_u[1]
                        self.rol = self.rol or row_u[2]
                        self.user_id = self.user_id or str(row_u[0])
                    conn_u.close()
            except Exception as e_loc:
                print("DEBUG: Error obteniendo perfil local:", e_loc)

        if not self.user_nombre:
            self.user_nombre = str(self.rol or "Usuario").capitalize()
            
        rol_clean = str(self.rol or "").strip().lower()
        self.es_admin = rol_clean in ("administrador", "admin", "gerente")
        self.es_operario = rol_clean in ("operario", "operador")
        self.es_vendedor = not self.es_admin and not self.es_operario
        # Solo los operarios están restringidos a MANDAR A CAJA. Administradores y Vendedores pueden procesar pago directamente.
        self.puede_procesar_venta = not self.es_operario
        self.orden_id_activa = None
        self.orden_numero_activa = None
        self.ventas_pendientes_cache = {}

        # Registrar apertura de jornada (Fase 3: Para vendedor registra 'Asistencia Marcada (Sin Venta)' sin salario diario)
        if not self.es_admin:
            try:
                try:
                    from interface.nomina_manager import registrar_asistencia_jornada
                except ImportError:
                    from nomina_manager import registrar_asistencia_jornada
                registrar_asistencia_jornada(
                    usuario_id=int(self.user_id) if str(self.user_id).isdigit() else None,
                    usuario_nombre=self.user_nombre,
                    rol=self.rol,
                    origen="APERTURA_POS",
                    responsable=self.user_nombre
                )
            except Exception as e_asist:
                print("DEBUG: Error registrando jornada inicial en POS:", e_asist)

        self.setup_ventana()
        self.setup_variables()
        self.setup_datos()
        self.crear_interfaz()
        self.configurar_eventos()
        
        # Inicializar impresora
        self.printer_manager = PrinterManager() if IMPRESION_DISPONIBLE else None
        self.impresora_conectada = False
        
        # Conectar impresora al inicio
        if self.printer_manager:
            self.conectar_impresora_async()

    def setup_ventana(self):
        """Configuración inicial de la ventana adaptada dinámicamente al monitor y rol con temas"""
        if self.es_admin:
            rol_titulo = "Administrador - Caja"
        elif self.es_vendedor:
            rol_titulo = f"Vendedor ({self.user_nombre or self.rol})"
        else:
            rol_titulo = f"Operario ({self.user_nombre or self.rol})"

        self.ventana.title(f"{business_mgr.nombre} - POS [{rol_titulo}]")
        self.ventana.resizable(True, True)
        
        self.t = aplicar_tema(self.ventana)
        default_w = 1220 if self.es_admin else 1060
        calcular_geometria_segura(self.ventana, default_w, 720, 860, 520)
        self.ventana.configure(bg=self.t["bg_app"])
        
        # Configurar estilos
        self.setup_estilos()

    def setup_estilos(self):
        """Configuración de estilos TTK acordes al tema activo"""
        pass

    def setup_variables(self):
        """Inicialización de variables de control"""
        self.documento = tk.StringVar()
        self.codigo_entrada = tk.StringVar()
        self.total_general = tk.DoubleVar(value=0.0)
        self.factura_num = datetime.now().strftime("%Y%m%d%H%M%S")
        self.tipo_filtro = tk.StringVar(value="Todos")
        self.busqueda_catalogo = tk.StringVar()
        self.cliente_id_seleccionado = None
        self._exceso_credito_autorizado = False
        self._registrando_venta = False
        self._venta_idempotency_key = None
        self._venta_fingerprint = None
        self._ultimo_refresh_catalogo = 0.0

        # Variables de control para Lector de Código de Barras (Hardware USB Keyboard Wedge)
        self._scanner_burst_chars = []
        self._scanner_modal_burst = []
        self._scanner_last_time = 0.0
        self._scanner_focused_widget = None
        self._scanner_widget_initial_val = ""
        self._scanner_no_enter_timer = None
        self._ultimo_escaneo_codigo = ""
        self._ultimo_escaneo_tiempo = 0.0
        self._dialogo_pago_activo = False

    def setup_datos(self):
        """Carga de datos desde la base de datos"""
        self.productos_inventario = self.obtener_productos()

    def conectar_impresora_async(self):
        """Conecta la impresora en segundo plano"""
        def conectar():
            try:
                if self.printer_manager.conectar_impresora():
                    self.impresora_conectada = True
                    print("✅ Impresora lista para usar")
                else:
                    print("⚠️ No se pudo conectar la impresora")
            except Exception as e:
                print(f"⚠️ Error conectando impresora: {e}")
        
        thread = threading.Thread(target=conectar, daemon=True)
        thread.start()

    def crear_interfaz(self):
        """Construye la interfaz de usuario con arquitectura de 3 capas responsive y paneles según rol"""
        bg_h = self.t["bg_header"]
        fg_h = self.t["text_header"]
        bg_app = self.t["bg_app"]
        bg_panel = self.t["bg_surface"]
        bg_panel_head = self.t["bg_surface_alt"]
        fg_main = self.t["text_main"]
        fg_muted = self.t["text_muted"]

        # 1. HEADER (Fijo arriba)
        header = tk.Frame(self.ventana, bg=bg_h)
        header.pack(side="top", fill="x")
        tk.Label(header, text=f"{business_mgr.nombre} • POS", font=("Segoe UI", 15, "bold"), 
                bg=bg_h, fg=fg_h).pack(side="left", padx=15, pady=6)

        if self.es_admin:
            rol_badge = "🔑 ADMINISTRADOR - CAJA"
            badge_bg = self.t["bg_header_sub"]
        elif self.es_vendedor:
            rol_badge = f"🛍️ VENDEDOR: {self.user_nombre or self.rol}"
            badge_bg = self.t.get("success", "#10B981")
        else:
            rol_badge = f"💼 OPERARIO: {self.user_nombre or self.rol}"
            badge_bg = self.t["btn_info_bg"]

        tk.Label(header, text=rol_badge, font=("Segoe UI", 9, "bold"), 
                bg=badge_bg, fg="white", padx=10, pady=3).pack(side="right", padx=15, pady=6)

        # 2. FOOTER ACCIONES (Sticky abajo - NUNCA SE CORTA)
        footer_container = tk.Frame(self.ventana, bg=bg_h)
        footer_container.pack(side="bottom", fill="x")

        # Fila del total
        total_frame = tk.Frame(footer_container, bg=bg_h)
        total_frame.pack(fill="x", padx=15, pady=(6, 2))
        tk.Label(total_frame, text="💸 TOTAL A PAGAR:", font=("Segoe UI", 14, "bold"),
                bg=bg_h, fg=fg_h).pack(side="left", padx=10)
        self.total_label = tk.Label(total_frame, text=self.formato_peso(0), font=("Segoe UI", 18, "bold"),
                                   bg=bg_h, fg="#FEF08A")
        self.total_label.pack(side="right", padx=15)

        # Botones de pago y nueva venta
        payment_frame = tk.Frame(footer_container, bg=bg_h)
        payment_frame.pack(fill="x", padx=15, pady=(2, 8))
        
        self.var_turno_especial = tk.BooleanVar(value=False)
        self.var_motivo_especial = tk.StringVar(value="Cliente solicita específicamente al operario")
        chk_esp = tk.Checkbutton(payment_frame, text="⭐ Turno Especial", variable=self.var_turno_especial,
                                 font=("Segoe UI", 9, "bold"), bg=bg_h, fg=fg_h, selectcolor=self.t["bg_header_sub"],
                                 activebackground=bg_h, activeforeground=fg_h)
        chk_esp.pack(side="left", padx=5)

        if self.puede_procesar_venta:
            btn_accion = crear_boton(payment_frame, "PROCESAR PAGO (F12)", command=self.pagar, tipo="success", icono="💳", tam_fuente=11)
        else:
            btn_accion = crear_boton(payment_frame, "MANDAR A CAJA (F12)", command=self.mandar_a_caja, tipo="info", icono="📤", tam_fuente=11)
        self.btn_accion_principal = btn_accion
        btn_accion.pack(side="right", padx=5)

        btn_nueva = crear_boton(payment_frame, "Nueva Venta (F5)", command=self.limpiar_formulario, tipo="warning", icono="🆕", tam_fuente=10)
        btn_nueva.pack(side="right", padx=5)

        btn_cajon = crear_boton(payment_frame, "Abrir Cajón (F7)", command=self.abrir_cajon_manual, tipo="secondary", icono="🔓", tam_fuente=10)
        btn_cajon.pack(side="right", padx=5)

        # 3. CUERPO CENTRAL (Flexible y expandible)
        central_frame = tk.Frame(self.ventana, bg=bg_app)
        central_frame.pack(side="top", fill="both", expand=True, padx=8, pady=3)

        # Barra de info de factura y reloj
        info_frame = tk.Frame(central_frame, bg=bg_panel_head, bd=1, relief="solid")
        info_frame.pack(fill="x", pady=(1, 2))
        
        self.lbl_factura = tk.Label(info_frame, text=f"🧾 Factura: {self.factura_num}",
                                   font=("Segoe UI", 9, "bold"), bg=bg_panel_head, fg=fg_main)
        self.lbl_factura.pack(side="left", padx=(8, 12), pady=3)
        
        self.lbl_fecha = tk.Label(info_frame, text="", font=("Segoe UI", 9), bg=bg_panel_head, fg=fg_muted)
        self.lbl_fecha.pack(side="left", padx=8, pady=3)
        
        self.lbl_hora = tk.Label(info_frame, text="", font=("Segoe UI", 9), bg=bg_panel_head, fg=fg_muted)
        self.lbl_hora.pack(side="left", padx=8, pady=3)

        self.btn_estado_caja = tk.Button(
            info_frame, text="🔴 Caja Cerrada [Abrir]",
            font=("Segoe UI", 8, "bold"), bg="#DC2626", fg="white",
            relief="flat", cursor="hand2", padx=8, pady=1,
            command=self.gestionar_caja_pos
        )
        self.btn_estado_caja.pack(side="right", padx=8, pady=2)

        # Barra de Indicadores de Ventas, Recaudo y Nómina (Fase 6)
        self.indicadores_frame = tk.Frame(central_frame, bg=bg_panel, bd=1, relief="solid")
        self.indicadores_frame.pack(fill="x", pady=(0, 3))

        self.lbl_ind_por_cobrar = tk.Label(
            self.indicadores_frame, text="📝 Por cobrar: $0 COP",
            font=("Segoe UI", 9, "bold"), bg=bg_panel, fg="#D97706"
        )
        self.lbl_ind_por_cobrar.pack(side="left", padx=(10, 12), pady=3)

        self.lbl_ind_total_pagado = tk.Label(
            self.indicadores_frame, text="✅ Total pagado: $0 COP",
            font=("Segoe UI", 9, "bold"), bg=bg_panel, fg="#059669"
        )
        self.lbl_ind_total_pagado.pack(side="left", padx=12, pady=3)

        self.lbl_ind_recaudado_hoy = tk.Label(
            self.indicadores_frame, text="💰 Recaudado hoy: $0 COP",
            font=("Segoe UI", 9, "bold"), bg=bg_panel, fg="#2563EB"
        )
        self.lbl_ind_recaudado_hoy.pack(side="left", padx=12, pady=3)

        if not self.es_admin:
            self.lbl_ind_nomina_pend = tk.Label(
                self.indicadores_frame, text="🧾 Mi Nómina pendiente: $0 COP",
                font=("Segoe UI", 8, "bold"), bg=bg_panel, fg="#7C3AED"
            )
            self.lbl_ind_nomina_pend.pack(side="left", padx=12, pady=3)

            self.lbl_ind_asistencia = tk.Label(
                self.indicadores_frame, text="📅 Asistencia: Pendiente",
                font=("Segoe UI", 8, "bold"), bg=bg_panel, fg=fg_muted
            )
            self.lbl_ind_asistencia.pack(side="right", padx=10, pady=3)

        btn_ref_ind = tk.Button(
            self.indicadores_frame, text="🔄",
            command=self.actualizar_indicadores_empleado_pos,
            font=("Segoe UI", 8, "bold"), bg=bg_panel_head, fg=fg_main,
            relief="flat", cursor="hand2", padx=5, pady=1
        )
        btn_ref_ind.pack(side="right", padx=6, pady=2)

        # Banner informativo cuando se atiende orden de operario (oculto por defecto)
        self.banner_frame = tk.Frame(central_frame, bg="#FEF08A", bd=1, relief="solid")
        self.lbl_banner_orden = tk.Label(self.banner_frame, text="", font=("Segoe UI", 9, "bold"), bg="#FEF08A", fg="#854D0E")
        self.lbl_banner_orden.pack(side="left", padx=10, pady=3)
        btn_cancel_orden = tk.Button(self.banner_frame, text="✖ Salir del Pedido", command=self.cancelar_orden_activa, 
                                    bg="#EF4444", fg="white", font=("Segoe UI", 8, "bold"), relief="flat", cursor="hand2")
        btn_cancel_orden.pack(side="right", padx=8, pady=2)

        # Banner de advertencia cuando la caja está cerrada
        self.banner_caja_cerrada = tk.Frame(central_frame, bg="#FEE2E2", bd=1, relief="solid")
        lbl_aviso_caja = tk.Label(
            self.banner_caja_cerrada,
            text="⚠️ ATENCIÓN: La caja se encuentra CERRADA. Debe abrir el turno de caja antes de registrar o cobrar ventas.",
            font=("Segoe UI", 9, "bold"), bg="#FEE2E2", fg="#991B1B"
        )
        lbl_aviso_caja.pack(side="left", padx=10, pady=3)
        btn_abrir_banner = tk.Button(
            self.banner_caja_cerrada,
            text="🟢 Abrir Turno de Caja Ahora",
            command=self.modal_abrir_caja,
            bg="#059669", fg="white",
            font=("Segoe UI", 8, "bold"),
            relief="flat", cursor="hand2",
            padx=8, pady=2
        )
        btn_abrir_banner.pack(side="right", padx=8, pady=2)

        # Contenedor dividido en columnas
        self.split_frame = tk.Frame(central_frame, bg=bg_app)
        self.split_frame.pack(fill="both", expand=True, pady=2)
        self.split_frame.grid_rowconfigure(0, weight=1)

        if self.es_admin:
            self.split_frame.grid_columnconfigure(0, weight=4) # Catálogo
            self.split_frame.grid_columnconfigure(1, weight=5) # Carrito Venta
            self.split_frame.grid_columnconfigure(2, weight=4) # Ventas Operarios
        else:
            self.split_frame.grid_columnconfigure(0, weight=5) # Catálogo
            self.split_frame.grid_columnconfigure(1, weight=6) # Carrito Venta

        # =========================================================================
        # COLUMNA 0: PANEL CATÁLOGO DE PRODUCTOS / SERVICIOS (CON SELECTOR EN TIEMPO REAL)
        # =========================================================================
        catalogo_panel = tk.Frame(self.split_frame, bg=bg_panel, bd=1, relief="solid")
        catalogo_panel.grid(row=0, column=0, sticky="nsew", padx=3, pady=2)

        # Header catálogo
        cat_head = tk.Frame(catalogo_panel, bg=bg_panel_head)
        cat_head.pack(fill="x", padx=2, pady=2)
        tk.Label(cat_head, text="📦 CATÁLOGO", font=("Segoe UI", 10, "bold"), bg=bg_panel_head, fg=fg_main).pack(side="left", padx=6, pady=4)
        crear_boton(
            cat_head, text="🔄", command=self.refrescar_catalogo_central,
            tipo="info", tam_fuente=7, padx=5, pady=1
        ).pack(side="right", padx=4, pady=2)
        if not self.es_admin and str(self.rol).strip().lower() == "operario":
            crear_boton(
                cat_head, text="➕ Agregar servicio", command=self._abrir_modal_servicio_operario,
                tipo="success", tam_fuente=8, padx=6, pady=2
            ).pack(side="right", padx=5, pady=2)

        # Selector Tipo (Físico vs Servicio) en tiempo real
        cat_sel_frame = tk.Frame(catalogo_panel, bg=bg_panel)
        cat_sel_frame.pack(fill="x", padx=6, pady=2)
        tk.Label(cat_sel_frame, text="Tipo:", font=("Segoe UI", 9, "bold"), bg=bg_panel, fg=fg_main).pack(side="left", padx=(0, 2))
        
        for val, txt in [("Todos", "📑 Todos"), ("Fisico", "📦 Físicos"), ("Servicio", "🛎️ Servicios")]:
            rb = tk.Radiobutton(cat_sel_frame, text=txt, variable=self.tipo_filtro, value=val,
                                bg=bg_panel, activebackground=bg_panel, font=("Segoe UI", 8, "bold"),
                                fg=fg_main, selectcolor=bg_panel_head, command=self.actualizar_catalogo_live)
            rb.pack(side="left", padx=2)

        # Buscador catálogo en vivo
        cat_busq_frame = tk.Frame(catalogo_panel, bg=bg_panel)
        cat_busq_frame.pack(fill="x", padx=6, pady=2)
        tk.Label(cat_busq_frame, text="🔍", font=("Segoe UI", 9), bg=bg_panel, fg=fg_main).pack(side="left", padx=(0, 4))
        self.entry_busq_cat = tk.Entry(cat_busq_frame, textvariable=self.busqueda_catalogo, font=("Segoe UI", 9), bd=1, relief="solid", 
                                       bg=self.t["input_bg"], fg=self.t["input_fg"], insertbackground=self.t["input_insert"])
        self.entry_busq_cat.pack(side="left", fill="x", expand=True)
        self._debounce_cat_live = None
        def _on_cat_search(*args):
            if self._debounce_cat_live:
                try:
                    self.ventana.after_cancel(self._debounce_cat_live)
                except Exception:
                    pass
            self._debounce_cat_live = self.ventana.after(150, self.actualizar_catalogo_live)
        self.busqueda_catalogo.trace_add("write", _on_cat_search)

        # Tabla catálogo
        cat_table_frame = tk.Frame(catalogo_panel, bg=bg_panel, bd=1, relief="solid")
        cat_table_frame.pack(fill="both", expand=True, padx=6, pady=(2, 2))

        cols_cat = ("Código", "Nombre", "Stock", "Precio")
        self.tabla_catalogo = ttk.Treeview(cat_table_frame, columns=cols_cat, show="headings", selectmode="browse")
        anchos_c = {"Código": 65, "Nombre": 160, "Stock": 55, "Precio": 85}
        for c in cols_cat:
            self.tabla_catalogo.heading(c, text=c)
            self.tabla_catalogo.column(c, width=anchos_c.get(c, 80), anchor="center")

        sc_cat_y = ttk.Scrollbar(cat_table_frame, orient="vertical", command=self.tabla_catalogo.yview)
        sc_cat_x = ttk.Scrollbar(cat_table_frame, orient="horizontal", command=self.tabla_catalogo.xview)
        self.tabla_catalogo.configure(yscrollcommand=sc_cat_y.set, xscrollcommand=sc_cat_x.set)

        self.tabla_catalogo.grid(row=0, column=0, sticky="nsew")
        sc_cat_y.grid(row=0, column=1, sticky="ns")
        sc_cat_x.grid(row=1, column=0, sticky="ew")
        cat_table_frame.grid_rowconfigure(0, weight=1)
        cat_table_frame.grid_columnconfigure(0, weight=1)

        self.tabla_catalogo.bind("<Double-1>", self.on_catalogo_doble_click)
        self.tabla_catalogo.bind("<Return>", self.on_catalogo_doble_click)

        tk.Label(catalogo_panel, text="💡 Doble clic para añadir a la venta", font=("Segoe UI", 8, "italic"), 
                 bg=bg_panel, fg=fg_muted).pack(side="bottom", pady=2)

        # =========================================================================
        # COLUMNA 1: PANEL VENTA ACTUAL (CARRITO)
        # =========================================================================
        cart_panel = tk.Frame(self.split_frame, bg=bg_panel, bd=1, relief="solid")
        cart_panel.grid(row=0, column=1, sticky="nsew", padx=3, pady=2)

        # Header carrito
        cart_head = tk.Frame(cart_panel, bg=bg_panel_head)
        cart_head.pack(fill="x", padx=2, pady=2)
        tk.Label(cart_head, text="🛒 VENTA ACTUAL", font=("Segoe UI", 10, "bold"), bg=bg_panel_head, fg=fg_main).pack(side="left", padx=6, pady=4)

        # Inputs: Doc cliente, Código y Botones rápidos
        cart_in_frame = tk.Frame(cart_panel, bg=bg_panel)
        cart_in_frame.pack(fill="x", padx=6, pady=2)

        tk.Label(cart_in_frame, text="👤 Doc:", font=("Segoe UI", 8, "bold"), bg=bg_panel, fg=fg_main).pack(side="left", padx=(0, 2))
        self.entry_doc = tk.Entry(cart_in_frame, textvariable=self.documento, width=10, font=("Segoe UI", 9), 
                                  bg=self.t["input_bg"], fg=self.t["input_fg"], insertbackground=self.t["input_insert"])
        self.entry_doc.pack(side="left", padx=(0, 4))

        tk.Label(cart_in_frame, text="🔢 Cód:", font=("Segoe UI", 8, "bold"), bg=bg_panel, fg=fg_main).pack(side="left", padx=(0, 2))
        self.entry_codigo = tk.Entry(cart_in_frame, textvariable=self.codigo_entrada, width=11, font=("Segoe UI", 9), 
                                     bg=self.t["input_bg"], fg=self.t["input_fg"], insertbackground=self.t["input_insert"])
        self.entry_codigo.pack(side="left", padx=(0, 3))

        btn_escanear = crear_boton(cart_in_frame, "📲", command=self.escanear_codigo, tipo="purple", tam_fuente=8, pady=2, padx=6)
        btn_escanear.pack(side="left", padx=1)

        btn_eliminar = crear_boton(cart_in_frame, "🗑️", command=self.eliminar_seleccionado, tipo="danger", tam_fuente=8, pady=2, padx=6)
        btn_eliminar.pack(side="left", padx=1)

        btn_editar = crear_boton(cart_in_frame, "✏️ Modificar", command=self.editar_item_carrito_click, tipo="secondary", tam_fuente=8, pady=2, padx=6, tooltip="Modificar cantidad o precio del ítem")
        btn_editar.pack(side="left", padx=1)

        if self.puede_procesar_venta:
            btn_abrir_caja = crear_boton(cart_in_frame, "💰 Caja", command=self.gestionar_caja_pos, tipo="warning", tam_fuente=8, pady=2, padx=6)
            btn_abrir_caja.pack(side="right", padx=1)

        # Tabla carrito
        cart_table_frame = tk.Frame(cart_panel, bg=bg_panel, bd=1, relief="solid")
        cart_table_frame.pack(fill="both", expand=True, padx=6, pady=(2, 4))

        cols_cart = ("Producto", "Precio", "Cantidad", "Total")
        self.tabla = ttk.Treeview(cart_table_frame, columns=cols_cart, show="headings")
        anchos_cart = {"Producto": 170, "Precio": 85, "Cantidad": 65, "Total": 85}
        for col in cols_cart:
            self.tabla.heading(col, text=col)
            self.tabla.column(col, width=anchos_cart.get(col, 80), anchor="center")

        sc_cart_y = ttk.Scrollbar(cart_table_frame, orient="vertical", command=self.tabla.yview)
        sc_cart_x = ttk.Scrollbar(cart_table_frame, orient="horizontal", command=self.tabla.xview)
        self.tabla.configure(yscrollcommand=sc_cart_y.set, xscrollcommand=sc_cart_x.set)
        self.tabla.bind("<Double-1>", self.editar_item_carrito_click)
        self.tabla.bind("<Return>", self.editar_item_carrito_click)

        def _on_click_tabla_carrito(event):
            row_id = self.tabla.identify_row(event.y)
            if row_id:
                self.tabla.selection_set(row_id)
                self.tabla.focus(row_id)
                self.editar_item_carrito_click(event)
        self.tabla.bind("<ButtonRelease-1>", _on_click_tabla_carrito)

        self.tabla.grid(row=0, column=0, sticky="nsew")
        sc_cart_y.grid(row=0, column=1, sticky="ns")
        sc_cart_x.grid(row=1, column=0, sticky="ew")
        cart_table_frame.grid_rowconfigure(0, weight=1)
        cart_table_frame.grid_columnconfigure(0, weight=1)

        # =========================================================================
        # COLUMNA 2: PANEL VENTAS DE OPERARIOS (SOLO ADMINISTRADOR - CAJA)
        # =========================================================================
        if self.es_admin:
            operarios_panel = tk.Frame(self.split_frame, bg=bg_panel, bd=1, relief="solid")
            operarios_panel.grid(row=0, column=2, sticky="nsew", padx=3, pady=2)

            op_head = tk.Frame(operarios_panel, bg=bg_panel_head)
            op_head.pack(fill="x", padx=2, pady=2)
            tk.Label(op_head, text="📥 VENTAS OPERARIOS", font=("Segoe UI", 10, "bold"), bg=bg_panel_head, fg=fg_main).pack(side="left", padx=6, pady=4)
            
            self.lbl_badge_operarios = tk.Label(op_head, text="🟢 0 Pend.", font=("Segoe UI", 8, "bold"), bg=bg_panel_head, fg=self.t["btn_success_bg"])
            self.lbl_badge_operarios.pack(side="left", padx=4)

            btn_refresh_op = crear_boton(op_head, "🔄", command=self.actualizar_ventas_operarios, tipo="info", tam_fuente=7, pady=1, padx=4)
            btn_refresh_op.pack(side="right", padx=4)

            tk.Label(operarios_panel, text="Clic en una orden para cobrarla en caja:", font=("Segoe UI", 8), bg=bg_panel, fg=fg_muted).pack(anchor="w", padx=6, pady=(0, 2))

            op_table_frame = tk.Frame(operarios_panel, bg=bg_panel, bd=1, relief="solid")
            op_table_frame.pack(fill="both", expand=True, padx=6, pady=2)

            cols_op = ("Venta", "Operario", "Total", "Hora")
            self.tabla_operarios = ttk.Treeview(op_table_frame, columns=cols_op, show="headings", selectmode="browse")
            anchos_op = {"Venta": 75, "Operario": 120, "Total": 80, "Hora": 65}
            for col in cols_op:
                self.tabla_operarios.heading(col, text=col)
                self.tabla_operarios.column(col, width=anchos_op.get(col, 80), anchor="center")

            sc_op_y = ttk.Scrollbar(op_table_frame, orient="vertical", command=self.tabla_operarios.yview)
            sc_op_x = ttk.Scrollbar(op_table_frame, orient="horizontal", command=self.tabla_operarios.xview)
            self.tabla_operarios.configure(yscrollcommand=sc_op_y.set, xscrollcommand=sc_op_x.set)

            self.tabla_operarios.grid(row=0, column=0, sticky="nsew")
            sc_op_y.grid(row=0, column=1, sticky="ns")
            sc_op_x.grid(row=1, column=0, sticky="ew")
            op_table_frame.grid_rowconfigure(0, weight=1)
            op_table_frame.grid_columnconfigure(0, weight=1)

            self.tabla_operarios.bind("<<TreeviewSelect>>", self.on_operario_venta_select)

            op_btn_frame = tk.Frame(operarios_panel, bg=bg_panel)
            op_btn_frame.pack(fill="x", padx=6, pady=(2, 4))
            btn_descartar = crear_boton(op_btn_frame, "Rechazar Pedido", command=self.descartar_orden_operario, tipo="danger", icono="❌", tam_fuente=8, pady=2)
            btn_descartar.pack(side="right")

        # Cargar catálogo inicial y arrancar sondeo de operarios
        self.actualizar_catalogo_live()
        if self.es_admin:
            self.actualizar_ventas_operarios()
        self.actualizar_estado_caja()
        self.actualizar_indicadores_empleado_pos()

    def refrescar_catalogo_central(self):
        """Recarga el catálogo en tiempo real desde el servidor central."""
        if getattr(self, "_registrando_venta", False):
            return
        self._ultimo_refresh_catalogo = time.time()
        self.productos_inventario = self.obtener_productos()
        self.actualizar_catalogo_live()

    def _on_focus_in_pos(self, event=None):
        """Refresca estado de caja, indicadores y catálogo central al recuperar foco (con debounce)."""
        if event is not None and getattr(event, "widget", None) is not self.ventana:
            return
        if getattr(self, "_registrando_venta", False):
            return
        ahora = time.time()
        if ahora - getattr(self, "_ultimo_refresh_catalogo", 0.0) >= 2.5:
            self._ultimo_refresh_catalogo = ahora
            self.productos_inventario = self.obtener_productos()
            self.actualizar_catalogo_live()
            self.actualizar_estado_caja()
            self.actualizar_indicadores_empleado_pos()

        # Si no hay ningún campo de texto enfocado activamente, mantener el cursor en entry_codigo
        try:
            foco_act = self.ventana.focus_get()
            if foco_act is None or foco_act == self.ventana or foco_act == getattr(self, "tabla", None):
                self.entry_codigo.focus_set()
        except Exception:
            pass

    def configurar_eventos(self):
        """Configurar eventos de teclado y focus continuo para lector de código de barras"""
        self.entry_codigo.bind('<Return>', lambda e: self.escanear_codigo())
        self.entry_codigo.bind('<KeyRelease>', self.on_codigo_change)
        self.entry_doc.bind('<Return>', lambda e: self.entry_codigo.focus_set())

        # Receptor global de teclado (Keyboard Wedge) para escáneres USB
        self.ventana.bind_all('<Key>', self._on_global_key_event, add="+")

        # La pantalla abre lista inmediatamente para escanear en entry_codigo
        self.entry_codigo.focus_set()
        self.actualizar_hora()
        self.ventana.bind('<FocusIn>', self._on_focus_in_pos)
        self._ultimo_refresh_catalogo = time.time()
        self.actualizar_estado_caja()
        self.actualizar_indicadores_empleado_pos()

        # Atajos de teclado globales
        comando_f12 = self.pagar if self.puede_procesar_venta else self.mandar_a_caja
        self.ventana.bind('<F12>', lambda e: comando_f12())
        self.ventana.bind('<F5>', lambda e: self.limpiar_formulario())
        self.ventana.bind('<F7>', lambda e: self.abrir_cajon_manual())

    def abrir_cajon_manual(self, event=None):
        """Abre el cajón monedero conectado a la impresora térmica (F7)."""
        try:
            try:
                from interface.receipt_manager import pulsar_apertura_cajon
            except ImportError:
                from receipt_manager import pulsar_apertura_cajon
            ok, msg = pulsar_apertura_cajon()
            if not ok:
                messagebox.showwarning("Cajón Monedero", f"No se pudo abrir el cajón automáticamente:\n{msg}", parent=self.ventana)
        except Exception as e:
            messagebox.showerror("Error Cajón Monedero", f"Error al abrir cajón: {e}", parent=self.ventana)

    def actualizar_indicadores_empleado_pos(self):
        """
        Actualiza en tiempo real los indicadores de ventas, recaudo de clientes
        y nómina del empleado en la pantalla POS (Fase 6).
        Separa claramente la cartera/recaudo de clientes respecto a la nómina del empleado.
        """
        try:
            try:
                from interface.nomina_manager import obtener_resumen_ventas_y_recaudo_empleado
            except ImportError:
                from nomina_manager import obtener_resumen_ventas_y_recaudo_empleado

            uid = int(self.user_id) if str(self.user_id).isdigit() else None
            resumen = obtener_resumen_ventas_y_recaudo_empleado(
                usuario_id=uid,
                usuario_nombre=self.user_nombre,
                rol=self.rol
            )

            por_cobrar = float(resumen.get("por_cobrar_clientes", 0.0))
            total_pagado = float(resumen.get("total_pagado_clientes", 0.0))
            recaudado_hoy = float(resumen.get("recaudado_hoy", 0.0))

            if hasattr(self, "lbl_ind_por_cobrar"):
                self.lbl_ind_por_cobrar.config(text=f"📝 Por cobrar: {self.formato_peso(por_cobrar)}")
            if hasattr(self, "lbl_ind_total_pagado"):
                self.lbl_ind_total_pagado.config(text=f"✅ Total pagado: {self.formato_peso(total_pagado)}")
            if hasattr(self, "lbl_ind_recaudado_hoy"):
                self.lbl_ind_recaudado_hoy.config(text=f"💰 Recaudado hoy: {self.formato_peso(recaudado_hoy)}")

            if hasattr(self, "lbl_ind_nomina_pend"):
                nom_pend = float(resumen.get("nomina_por_cobrar", 0.0))
                self.lbl_ind_nomina_pend.config(text=f"🧾 Mi Nómina pendiente: {self.formato_peso(nom_pend)}")

            if hasattr(self, "lbl_ind_asistencia"):
                est_asist = resumen.get("asistencia_estado", "No registrada")
                sal_gen = bool(resumen.get("salario_diario_generado_hoy", False))
                if est_asist == "Presente":
                    color_a = "#059669"
                    txt_a = "📅 Asistencia: Confirmada ✅" if sal_gen else "📅 Asistencia: Presente ✅"
                elif "Sin Venta" in str(est_asist):
                    color_a = "#D97706"
                    txt_a = "📅 Asistencia: Marcada (Realiza 1ra venta para activar día)"
                else:
                    color_a = self.t["text_muted"]
                    txt_a = f"📅 Asistencia: {est_asist}"
                self.lbl_ind_asistencia.config(text=txt_a, fg=color_a)
        except Exception as e_ind:
            print("DEBUG: Error actualizando indicadores POS:", e_ind)

    def _on_global_key_event(self, event):
        """
        Receptor global de pulsaciones de teclado para soporte continuo de escáneres USB de código de barras.
        - Detecta ráfagas de alta velocidad (< 65ms entre teclas) enviadas por lectores USB.
        - Protege las ventanas modales de cobro para evitar alterar montos o confirmar accidentalmente.
        - Si un escaneo ocurre mientras el usuario está en otro campo (como documento de cliente),
          restaura el texto original del campo, procesa el código escaneado y reenfoca self.entry_codigo.
        - Si el foco está en self.entry_codigo, procesa normalmente al recibir Enter o al finalizar la ráfaga.
        """
        now = time.time()
        delta = now - getattr(self, "_scanner_last_time", 0.0)
        self._scanner_last_time = now

        # 1. Ignorar teclas modificadoras
        if event.keysym in ("Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", 
                            "Caps_Lock", "Meta_L", "Meta_R", "Super_L", "Super_R"):
            return

        # 2. Protección de modales activos (ej: cobro/pago, autorización de crédito)
        grab_widget = None
        try:
            grab_widget = self.ventana.grab_current()
        except Exception:
            pass

        modal_activo = (grab_widget is not None and grab_widget != self.ventana) or getattr(self, "_dialogo_pago_activo", False)
        if modal_activo:
            if delta < 0.065:
                # Carácter rápido dentro de ventana modal -> ráfaga de escáner accidental
                self._scanner_modal_burst.append(event.char or "")
                return "break"
            if event.keysym in ("Return", "KP_Enter"):
                if len(getattr(self, "_scanner_modal_burst", [])) >= 3:
                    burst_code = "".join(self._scanner_modal_burst)
                    self._scanner_modal_burst = []
                    f_w = None
                    try:
                        f_w = self.ventana.focus_get()
                    except Exception:
                        pass
                    if f_w and hasattr(f_w, "get") and hasattr(f_w, "delete") and hasattr(f_w, "insert"):
                        try:
                            curr_val = f_w.get()
                            if curr_val.endswith(burst_code):
                                f_w.delete(0, tk.END)
                                f_w.insert(0, curr_val[:-len(burst_code)])
                        except Exception:
                            pass
                    return "break"
                self._scanner_modal_burst = []
            return

        focused_widget = None
        try:
            focused_widget = self.ventana.focus_get()
        except Exception:
            pass

        # 3. Tecla Return / Enter (final de escaneo o envío manual)
        if event.keysym in ("Return", "KP_Enter"):
            if getattr(self, "_scanner_no_enter_timer", None):
                try:
                    self.ventana.after_cancel(self._scanner_no_enter_timer)
                except Exception:
                    pass
                self._scanner_no_enter_timer = None

            burst = getattr(self, "_scanner_burst_chars", [])
            burst_str = "".join(burst).strip()
            self._scanner_burst_chars = []

            # Caso A: El foco está en el campo de código de barras
            if focused_widget == self.entry_codigo:
                codigo = self.codigo_entrada.get().strip() or burst_str
                self.escanear_codigo(codigo)
                return "break"

            # Caso B: Ráfaga de escaneo recibida mientras el usuario estaba en otro campo o control
            if burst_str and len(burst_str) >= 3:
                self._limpiar_sufijo_escaneo_en_entradas(burst_str)
                self.escanear_codigo(burst_str)
                try:
                    self.entry_codigo.focus_set()
                except Exception:
                    pass
                return "break"

            return

        # 4. Caracteres individuales
        ch = event.char
        if not ch or ch in ("\r", "\n"):
            return

        if delta <= 0.065:
            # Parte de ráfaga rápida
            self._scanner_burst_chars.append(ch)
            # Temporizador de respaldo para lectores sin tecla Enter
            if getattr(self, "_scanner_no_enter_timer", None):
                try:
                    self.ventana.after_cancel(self._scanner_no_enter_timer)
                except Exception:
                    pass
            self._scanner_no_enter_timer = self.ventana.after(85, self._on_scanner_burst_sin_enter)
        else:
            # Nueva secuencia de teclas
            self._scanner_burst_chars = [ch]
            if focused_widget is not None and focused_widget != self.entry_codigo:
                self._scanner_focused_widget = focused_widget
                if hasattr(focused_widget, "get"):
                    try:
                        self._scanner_widget_initial_val = focused_widget.get()
                    except Exception:
                        self._scanner_widget_initial_val = ""
                else:
                    self._scanner_widget_initial_val = ""
            else:
                self._scanner_focused_widget = None
                self._scanner_widget_initial_val = ""

    def _limpiar_sufijo_escaneo_en_entradas(self, codigo_escaneado):
        """
        Garantiza que el código de barras escaneado no quede incrustado accidentalmente
        en ningún campo de texto de la pantalla (documento del cliente, búsqueda de catálogo, etc.).
        """
        if not codigo_escaneado:
            return
        cod_s = str(codigo_escaneado).strip()
        if not cod_s:
            return

        # 1. Documento del cliente (self.documento y self.entry_doc)
        if hasattr(self, "documento"):
            doc_val = str(self.documento.get() or "")
            if doc_val.endswith(cod_s):
                limpio = doc_val[:-len(cod_s)]
                self.documento.set(limpio)
                if hasattr(self, "entry_doc"):
                    try:
                        self.entry_doc.delete(0, tk.END)
                        self.entry_doc.insert(0, limpio)
                    except Exception:
                        pass
        elif hasattr(self, "entry_doc"):
            try:
                curr = self.entry_doc.get()
                if curr.endswith(cod_s):
                    self.entry_doc.delete(0, tk.END)
                    self.entry_doc.insert(0, curr[:-len(cod_s)])
            except Exception:
                pass

        # 2. Búsqueda de catálogo
        if hasattr(self, "busqueda_catalogo"):
            b_val = str(self.busqueda_catalogo.get() or "")
            if b_val.endswith(cod_s):
                self.busqueda_catalogo.set(b_val[:-len(cod_s)])

        # 3. Widget que tenía foco si es distinto a entry_codigo
        try:
            f_w = self.ventana.focus_get()
            if f_w and f_w != getattr(self, "entry_codigo", None):
                if hasattr(f_w, "get") and hasattr(f_w, "delete") and hasattr(f_w, "insert"):
                    txt = f_w.get()
                    if txt.endswith(cod_s):
                        f_w.delete(0, tk.END)
                        f_w.insert(0, txt[:-len(cod_s)])
        except Exception:
            pass

    def _on_scanner_burst_sin_enter(self):
        """Maneja escáneres ópticos configurados sin envío de tecla Return al final."""
        self._scanner_no_enter_timer = None
        burst = getattr(self, "_scanner_burst_chars", [])
        if len(burst) >= 4:
            burst_str = "".join(burst).strip()
            self._scanner_burst_chars = []
            self._limpiar_sufijo_escaneo_en_entradas(burst_str)
            self.escanear_codigo(burst_str)
            try:
                self.entry_codigo.focus_set()
            except Exception:
                pass
        else:
            self._scanner_burst_chars = []

    def on_codigo_change(self, event):
        """Controlador de eventos de teclado en el campo de código de barras."""
        if event.keysym in ('Return', 'KP_Enter'):
            self.escanear_codigo()

    # ====================================================================================
    #   CATÁLOGO RÁPIDO Y FILTRADO EN TIEMPO REAL
    # ====================================================================================

    def actualizar_catalogo_live(self):
        """Filtra y actualiza la tabla del catálogo en tiempo real según el Tipo y la búsqueda"""
        if not hasattr(self, 'tabla_catalogo'):
            return

        tipo_sel = self.tipo_filtro.get().strip()
        if "Físico" in tipo_sel or "Fisico" in tipo_sel:
            tipo_filtro_clean = "Fisico"
        elif "Servicio" in tipo_sel:
            tipo_filtro_clean = "Servicio"
        else:
            tipo_filtro_clean = "Todos"

        busq = self.busqueda_catalogo.get().strip().lower()

        self.tabla_catalogo.delete(*self.tabla_catalogo.get_children())

        for p in self.productos_inventario:
            cod, nom, stock, precio, t_prod = p[0], p[1], p[2], p[3], p[4]
            es_var = p[8] if len(p) > 8 else False
            cod_barras = str(p[10] or "") if len(p) > 10 else ""

            # Filtro por tipo
            if tipo_filtro_clean != "Todos" and t_prod != tipo_filtro_clean:
                continue

            # Filtro por texto de búsqueda
            if busq and (
                busq not in str(cod).lower()
                and busq not in str(nom).lower()
                and busq not in cod_barras.lower()
            ):
                continue

            precio_str = "Variable" if es_var else self.formato_peso(precio)
            stock_str = "—" if t_prod == "Servicio" else str(stock)
            self.tabla_catalogo.insert("", tk.END, text=str(cod), values=(
                cod,
                nom,
                stock_str,
                precio_str
            ))

    def _abrir_modal_servicio_operario(self):
        """Crea un servicio privado visible únicamente para el operario actual."""
        modal = tk.Toplevel(self.ventana)
        modal.title("Agregar servicio propio")
        modal.transient(self.ventana)
        modal.grab_set()
        t = aplicar_tema(modal)
        modal.configure(bg=t["bg_surface"])
        calcular_geometria_segura(modal, 440, 360, 380, 300)

        body = tk.Frame(modal, bg=t["bg_surface"], padx=18, pady=14)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="➕ NUEVO SERVICIO DEL OPERARIO", font=("Segoe UI", 12, "bold"), bg=t["bg_surface"], fg=t["text_main"]).pack(pady=(0, 12))

        tk.Label(body, text="Nombre:", bg=t["bg_surface"], fg=t["text_main"]).pack(anchor="w")
        nombre = tk.Entry(body, bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_insert"])
        nombre.pack(fill="x", pady=(2, 8))
        tk.Label(body, text="Descripción:", bg=t["bg_surface"], fg=t["text_main"]).pack(anchor="w")
        descripcion = tk.Entry(body, bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_insert"])
        descripcion.pack(fill="x", pady=(2, 8))
        tk.Label(body, text="Precio:", bg=t["bg_surface"], fg=t["text_main"]).pack(anchor="w")
        precio = CurrencyEntry(body, initial_value=0, show_symbol=True, width=30, bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_insert"])
        precio.pack(fill="x", pady=(2, 14))

        def guardar():
            nombre_val = nombre.get().strip()
            precio_val = precio.get_value()
            if not nombre_val or precio_val <= 0:
                messagebox.showwarning("Datos incompletos", "El nombre y el precio son obligatorios.", parent=modal)
                return
            try:
                resp = api.post("/servicios", json={
                    "nombre": nombre_val,
                    "descripcion": descripcion.get().strip(),
                    "precio_venta": precio_val,
                    "tipo_servicio": "Interno",
                    "costo_proveedor": 0,
                    "genera_comision": True,
                    "precio_variable": False
                })
                if resp.status_code not in (200, 201):
                    detalle = resp.json().get("detail", resp.text)
                    messagebox.showerror("Error", str(detalle), parent=modal)
                    return
                modal.destroy()
                self.productos_inventario = self.obtener_productos()
                self.actualizar_catalogo_live()
            except Exception as exc:
                messagebox.showerror("Error de conexión", str(exc), parent=modal)

        botones = tk.Frame(body, bg=t["bg_surface"])
        botones.pack(fill="x")
        crear_boton(botones, text="Cancelar", command=modal.destroy, tipo="secondary", tam_fuente=9).pack(side="left")
        crear_boton(botones, text="Guardar servicio", command=guardar, tipo="success", tam_fuente=9).pack(side="right")

    def on_catalogo_doble_click(self, event=None):
        """Agrega al carrito el producto seleccionado en el catálogo rápido"""
        if not self.verificar_caja_abierta("agregar productos del catálogo"):
            return
        sel = self.tabla_catalogo.selection()
        if not sel:
            return
        cod = self.tabla_catalogo.item(sel[0], "text")
        producto = next((p for p in self.productos_inventario if str(p[0]) == str(cod) or str(p[0]).zfill(5) == str(cod).zfill(5)), None)
        if not producto:
            return

        tipo_prod = producto[4]
        es_var = producto[8] if len(producto) > 8 else False
        precio = producto[3]

        if producto[2] > 0 or tipo_prod == "Servicio":
            if es_var:
                precio_ingresado = self.solicitar_precio_variable(producto[1], precio, parent=self.ventana)
                if precio_ingresado is None:
                    return
                precio = precio_ingresado
            self.agregar_producto(producto[0], producto[1], precio)
        else:
            messagebox.showwarning("Sin Stock", f"El producto '{producto[1]}' no tiene stock disponible.", parent=self.ventana)

    # ====================================================================================
    #   FLUJO CAJA Y OPERARIOS (MANDAR A CAJA / AUTORIZACIÓN ADMIN)
    # ====================================================================================

    def _calcular_fingerprint_carrito(self, metodo_pago: str, total: float, id_cliente=None, doc_cli: str = ""):
        """Construye una huella determinística del intento lógico de venta actual."""
        filas = []
        for i in self.tabla.get_children():
            cod = str(self.tabla.item(i, "text") or "").strip()
            vals = self.tabla.item(i, "values") or ()
            nom = str(vals[0]) if len(vals) > 0 else ""
            pre = round(self.limpiar_precio(vals[1]), 2) if len(vals) > 1 else 0.0
            c_raw = float(vals[2]) if len(vals) > 2 else 1.0
            cant = int(c_raw) if c_raw.is_integer() else round(c_raw, 3)
            filas.append((cod, nom, pre, cant))
        return (
            getattr(self, "orden_id_activa", None),
            str(metodo_pago or ""),
            round(float(total or 0.0), 2),
            str(id_cliente or ""),
            str(doc_cli or "").strip(),
            tuple(filas),
        )

    def _obtener_idempotency_key_venta(self, fingerprint) -> str:
        """
        Devuelve el idempotency_key para el intento actual.
        Si se reintenta exactamente la misma operación tras un error de red, reutiliza la misma clave
        para impedir ventas duplicadas. Si cambia el carrito o se limpia el formulario, genera una nueva.
        """
        if self._venta_idempotency_key and self._venta_fingerprint == fingerprint:
            return self._venta_idempotency_key
        self._venta_idempotency_key = f"pos-{uuid.uuid4()}"
        self._venta_fingerprint = fingerprint
        return self._venta_idempotency_key

    def _restaurar_boton_principal_pos(self):
        """Restaura el botón principal del footer POS según el rol."""
        if not hasattr(self, "btn_accion_principal") or not self.btn_accion_principal:
            return
        try:
            if self.btn_accion_principal.winfo_exists():
                txt = "💳 PROCESAR PAGO (F12)" if self.puede_procesar_venta else "📤 MANDAR A CAJA (F12)"
                self.btn_accion_principal.config(state="normal", text=txt)
        except Exception:
            pass

    def mandar_a_caja(self):
        """Envía la venta actual a Caja en estado Pendiente_Caja para autorización y cobro del Administrador."""
        if getattr(self, "_registrando_venta", False):
            return
        if not self.verificar_caja_abierta("enviar pedidos a caja"):
            return
        if len(self.tabla.get_children()) == 0:
            messagebox.showwarning("Carrito Vacío", "Agregue al menos un producto o servicio antes de mandar a caja.", parent=self.ventana)
            return

        total = self.total_general.get()
        if total <= 0:
            messagebox.showwarning("Total Inválido", "El total de la venta debe ser mayor a cero.", parent=self.ventana)
            return

        confirma = messagebox.askyesno(
            "Confirmar Envío a Caja",
            f"¿Desea enviar esta orden por {self.formato_peso(total)} a Caja?\n\nEl Administrador la cobrará.",
            parent=self.ventana,
        )
        if not confirma:
            return

        try:
            detalles_payload = []
            for i in self.tabla.get_children():
                codigo = self.tabla.item(i, "text")
                valores = self.tabla.item(i, "values")
                nombre = valores[0]
                precio_limpio = self.limpiar_precio(valores[1])
                cantidad = int(float(valores[2]))
                subtotal = precio_limpio * cantidad

                tipo_item = "Producto"
                item_id = None
                costo = 0.0

                for p in self.productos_inventario:
                    cod_p = str(p[0]).strip()
                    cod_c = str(codigo).strip()
                    if cod_p.lower() == cod_c.lower() or cod_p.zfill(5) == cod_c.zfill(5):
                        tipo_item = "Servicio" if p[4] == "Servicio" else "Producto"
                        item_id = p[6]
                        costo = p[7]
                        prov_id = p[5]
                        if tipo_item == "Servicio" and prov_id and (costo is None or float(costo or 0) <= 0):
                            costo = precio_limpio
                        break

                if not item_id:
                    messagebox.showerror("Error", f"No se pudo identificar el producto o servicio con código '{codigo}'.", parent=self.ventana)
                    return

                detalles_payload.append({
                    "tipo_item": tipo_item,
                    "item_id": item_id,
                    "item_codigo": str(codigo),
                    "item_nombre": nombre,
                    "precio_original": precio_limpio,
                    "precio_vendido": precio_limpio,
                    "cantidad": cantidad,
                    "descuento": 0.0,
                    "subtotal": subtotal,
                    "costo_unitario": costo,
                })

            doc_val = self.documento.get().strip()
            cliente_id_val = (
                int(self.cliente_id_seleccionado)
                if getattr(self, "cliente_id_seleccionado", None) and str(self.cliente_id_seleccionado).isdigit()
                else None
            )
            es_esp = getattr(self, "var_turno_especial", None) and self.var_turno_especial.get()
            motivo_esp = (
                getattr(self, "var_motivo_especial", None)
                and self.var_motivo_especial.get()
                or "Cliente solicita específicamente al operario"
            )
            fp = self._calcular_fingerprint_carrito("Pendiente_Caja", total, cliente_id_val, doc_val)
            idem_key = self._obtener_idempotency_key_venta(fp)

            self._registrando_venta = True
            if hasattr(self, "btn_accion_principal") and self.btn_accion_principal:
                self.btn_accion_principal.config(state="disabled", text="⏳ Registrando venta...")
                self.ventana.update_idletasks()

            def _worker_orden():
                try:
                    term_id = api.sincronizar_terminal_id() or api.terminal_id or 1
                    payload = {
                        "idempotency_key": idem_key,
                        "cliente_id": cliente_id_val,
                        "cliente_documento": doc_val if doc_val else None,
                        "terminal_id": term_id,
                        "subtotal": total,
                        "descuento": 0.0,
                        "total": total,
                        "estado": "Pendiente_Caja",
                        "pagos": [],
                        "detalles": detalles_payload,
                        "es_turno_especial": bool(es_esp),
                        "motivo_especial": motivo_esp if es_esp else None,
                    }
                    resp = api.post("/ventas", json=payload, timeout=12.0)
                    if getattr(resp, "is_network_error", False):
                        time.sleep(0.8)
                        if api.esta_disponible(forzar=True):
                            resp_rec = api.get(f"/ventas/por-idempotencia/{idem_key}", timeout=6.0)
                            if resp_rec.status_code == 200:
                                resp = resp_rec
                    self.ventana.after(0, lambda: _finalizar_orden(resp, None))
                except Exception as exc_w:
                    self.ventana.after(0, lambda: _finalizar_orden(None, exc_w))

            def _finalizar_orden(resp, exc_w):
                self._registrando_venta = False
                self._restaurar_boton_principal_pos()
                if exc_w is not None:
                    messagebox.showerror("Error", f"Ocurrió un error al enviar a caja:\n{exc_w}", parent=self.ventana)
                    return
                if resp is not None and resp.status_code in (200, 201):
                    venta_resp = resp.json()
                    numero_venta = venta_resp.get("numero", "")
                    id_central = venta_resp.get("id", "")
                    self._venta_idempotency_key = None
                    self._venta_fingerprint = None
                    self.limpiar_formulario()
                    self.productos_inventario = self.obtener_productos()
                    self.actualizar_catalogo_live()
                    messagebox.showinfo(
                        "✅ Venta Enviada a Caja",
                        f"Venta registrada correctamente en cola de Caja.\n\n"
                        f"🧾 N° de Venta: {numero_venta} (ID #{id_central})\n"
                        f"💸 Monto: {self.formato_peso(total)}\n"
                        f"👤 Operario: {self.user_nombre or 'Operario'}\n\n"
                        f"El Administrador ya puede verla y procesar el cobro en su caja.",
                        parent=self.ventana,
                    )
                else:
                    try:
                        err_msg = resp.json().get("detail", resp.text) if resp is not None else "Sin respuesta del servidor"
                    except Exception:
                        err_msg = resp.text if resp is not None else "Sin respuesta del servidor"
                    messagebox.showerror("Error al Mandar a Caja", f"El servidor respondió con error:\n{err_msg}", parent=self.ventana)

            threading.Thread(target=_worker_orden, daemon=True).start()
        except Exception as e:
            self._registrando_venta = False
            self._restaurar_boton_principal_pos()
            messagebox.showerror("Error", f"Ocurrió un error al enviar a caja:\n{e}", parent=self.ventana)

    def actualizar_ventas_operarios(self):
        """Consulta periódicamente las ventas pendientes de caja enviadas por operarios (solo Admin)"""
        if not getattr(self, 'es_admin', False):
            return

        try:
            resp = api.get("/ventas/pendientes-caja")
            if resp.status_code == 200:
                ventas = resp.json()
                new_cache = {v['id']: v for v in ventas}
                cant = len(ventas)
                prev_cant = len(self.ventas_pendientes_cache)

                # Solo redibujar la tabla si los IDs o la cantidad de órdenes cambiaron (evita parpadeos y re-selección)
                if set(new_cache.keys()) != set(self.ventas_pendientes_cache.keys()):
                    # Si ingresó una nueva orden de operario, emitir campanilla de alerta
                    if cant > prev_cant:
                        try:
                            self.ventana.bell()
                        except:
                            pass

                    sel_prev = self.tabla_operarios.selection()
                    sel_id = self.tabla_operarios.item(sel_prev[0], "text") if sel_prev else None

                    self.tabla_operarios.delete(*self.tabla_operarios.get_children())
                    for v in ventas:
                        v_id = v['id']
                        num = v.get('numero', '')
                        operario = v.get('operario_nombre', f"Operario {v.get('usuario_id')}")
                        total_fmt = self.formato_peso(v.get('total', 0.0))
                        hora = v.get('hora', '')
                        item_row = self.tabla_operarios.insert("", tk.END, text=str(v_id), values=(num, operario, total_fmt, hora))
                        if sel_id and str(v_id) == str(sel_id):
                            self.tabla_operarios.selection_set(item_row)

                self.ventas_pendientes_cache = new_cache

                if cant > 0:
                    self.lbl_badge_operarios.config(text=f"🔴 {cant} Pend.", fg="#DC2626")
                else:
                    self.lbl_badge_operarios.config(text="🟢 0 Pend.", fg="#16A34A")
            else:
                print(f"DEBUG Admin: Error al consultar pendientes de caja: {resp.status_code}")
        except Exception as e:
            print("DEBUG: Error actualizando ventas operarios:", e)
        finally:
            if hasattr(self, '_timer_operarios'):
                try:
                    self.ventana.after_cancel(self._timer_operarios)
                except:
                    pass
            self._timer_operarios = self.ventana.after(3000, self.actualizar_ventas_operarios)

    def on_operario_venta_select(self, event=None):
        """Carga en la caja del Administrador la venta seleccionada enviada por el operario"""
        if not self.verificar_caja_abierta("atender u ordenar cobro de operario"):
            return
        sel = self.tabla_operarios.selection()
        if not sel:
            return
        v_id_str = self.tabla_operarios.item(sel[0], "text")
        try:
            v_id = int(v_id_str)
        except:
            return

        orden = self.ventas_pendientes_cache.get(v_id)
        if not orden:
            return

        # Limpiar carrito actual y cargar los ítems del operario
        self.tabla.delete(*self.tabla.get_children())
        total_calc = 0.0

        for d in orden.get('detalles', []):
            nombre = d.get('item_nombre', '')
            cod = d.get('item_codigo', '')
            p_unit = float(d.get('precio_vendido', 0.0))
            cant = int(float(d.get('cantidad', 1)))
            sub = float(d.get('subtotal', p_unit * cant))
            total_calc += sub
            self.tabla.insert("", tk.END, text=str(cod), values=(
                nombre,
                self.formato_peso(p_unit),
                cant,
                self.formato_peso(sub)
            ))

        self.total_general.set(orden.get('total', total_calc))
        self.actualizar_total()
        
        self.orden_id_activa = orden['id']
        self.orden_numero_activa = orden.get('numero', '')
        self.factura_num = self.orden_numero_activa
        self.lbl_factura.config(text=f"🧾 Factura (Operario): {self.factura_num}")
        self.cliente_id_seleccionado = orden.get('cliente_id')
        doc_mostrar = orden.get('cliente_documento') or ""
        self.documento.set(doc_mostrar)

        # Mostrar banner
        op_nombre = orden.get('operario_nombre', 'Operario')
        self.lbl_banner_orden.config(text=f"👤 ATENDIENDO ORDEN DE: {op_nombre}  |  🧾 {self.orden_numero_activa}  |  💸 {self.formato_peso(self.total_general.get())}")
        self.banner_frame.pack(side="top", fill="x", pady=(0, 4), before=self.split_frame)

    def cancelar_orden_activa(self):
        """Cancela la selección de la orden de operario y vuelve a una venta nueva"""
        self.orden_id_activa = None
        self.orden_numero_activa = None
        if hasattr(self, 'banner_frame'):
            self.banner_frame.pack_forget()
        self.limpiar_formulario()

    def descartar_orden_operario(self):
        """Anula/descarta una orden pendiente enviada por operario si el cliente desistió"""
        sel = self.tabla_operarios.selection()
        if not sel:
            messagebox.showinfo("Aviso", "Seleccione una orden de la lista de operarios para descartar.", parent=self.ventana)
            return
        v_id_str = self.tabla_operarios.item(sel[0], "text")
        try:
            v_id = int(v_id_str)
        except:
            return
        orden = self.ventas_pendientes_cache.get(v_id)
        op_nom = orden.get('operario_nombre', 'Operario') if orden else 'Operario'
        num = orden.get('numero', '') if orden else f"ID {v_id}"

        confirma = messagebox.askyesno("Descartar Orden", 
                                      f"¿Desea rechazar/anular la orden {num} enviada por {op_nom}?\n\nLos productos reservados se devolverán al inventario.",
                                      parent=self.ventana)
        if not confirma:
            return

        try:
            resp = api.post(f"/ventas/{v_id}/anular")
            if resp.status_code in (200, 204):
                messagebox.showinfo("Orden Descartada", f"La orden {num} fue anulada y el stock fue liberado.", parent=self.ventana)
                if getattr(self, 'orden_id_activa', None) == v_id:
                    self.cancelar_orden_activa()
                self.actualizar_ventas_operarios()
                self.productos_inventario = self.obtener_productos()
                self.actualizar_catalogo_live()
            else:
                messagebox.showerror("Error", f"No se pudo anular la orden: {resp.text}", parent=self.ventana)
        except Exception as e:
            messagebox.showerror("Error", f"Error al anular orden: {e}", parent=self.ventana)

    # ====================================================================================
    #   CONTROL DE CAJA Y ARQUEO EN POS (VENDEDORES Y ADMINISTRADORES)
    # ====================================================================================

    def actualizar_estado_caja(self):
        """Actualiza el indicador y banner de estado de la caja."""
        try:
            activa = obtener_sesion_activa()
            if activa and activa.get("id"):
                if hasattr(self, 'btn_estado_caja') and self.btn_estado_caja:
                    self.btn_estado_caja.config(
                        text=f"🟢 Turno #{activa['id']} Abierto",
                        bg="#059669",
                        fg="white"
                    )
                if hasattr(self, 'banner_caja_cerrada') and self.banner_caja_cerrada:
                    self.banner_caja_cerrada.pack_forget()
                return True
            else:
                if hasattr(self, 'btn_estado_caja') and self.btn_estado_caja:
                    self.btn_estado_caja.config(
                        text="🔴 Caja Cerrada [Abrir]",
                        bg="#DC2626",
                        fg="white"
                    )
                if hasattr(self, 'banner_caja_cerrada') and self.banner_caja_cerrada and hasattr(self, 'split_frame'):
                    self.banner_caja_cerrada.pack(side="top", fill="x", pady=(0, 4), before=self.split_frame)
                return False
        except Exception as e:
            print("DEBUG: Error al actualizar estado de caja:", e)
            return False

    def modal_abrir_caja(self):
        """
        Abre el modal de apertura de turno de caja para vendedor o administrador.
        Permite fijar la base inicial en efectivo y activa la sesión en el libro mayor.
        Retorna True si la caja quedó abierta exitosamente, False si fue cancelado.
        """
        activa = obtener_sesion_activa()
        if activa:
            self.actualizar_estado_caja()
            return True

        dlg = tk.Toplevel(self.ventana)
        dlg.title("🟢 Apertura de Turno de Caja - POS")
        t_dlg = aplicar_tema(dlg)
        calcular_geometria_segura(dlg, 440, 310, 380, 260)
        dlg.configure(bg=t_dlg["bg_surface"])
        dlg.transient(self.ventana)
        dlg.grab_set()

        # Header
        h_frame = tk.Frame(dlg, bg="#059669", height=45)
        h_frame.pack(fill="x")
        h_frame.pack_propagate(False)
        tk.Label(
            h_frame, text="🟢 APERTURA DE TURNO DE CAJA",
            font=("Segoe UI", 12, "bold"), bg="#059669", fg="white"
        ).pack(pady=10)

        # Body
        b_frame = tk.Frame(dlg, bg=t_dlg["bg_surface"])
        b_frame.pack(fill="both", expand=True, padx=20, pady=12)

        usuario_actual = self.user_nombre or self.rol or "Vendedor"
        rol_display = "Vendedor" if self.es_vendedor else ("Administrador" if self.es_admin else str(self.rol or "Cajero"))

        tk.Label(
            b_frame, text=f"👤 Responsable: {usuario_actual} ({rol_display})",
            font=("Segoe UI", 10, "bold"), bg=t_dlg["bg_surface"], fg=t_dlg["text_main"]
        ).pack(anchor="w", pady=(0, 6))

        tk.Label(
            b_frame, text="Ingrese el monto base inicial en efectivo para la gaveta:",
            font=("Segoe UI", 9), bg=t_dlg["bg_surface"], fg=t_dlg["text_muted"]
        ).pack(anchor="w", pady=(0, 4))

        entry_base = CurrencyEntry(
            b_frame, initial_value=0, show_symbol=True,
            font=("Segoe UI", 13, "bold"), width=18,
            bg=t_dlg["input_bg"], fg=t_dlg["input_fg"],
            insertbackground=t_dlg["input_insert"], relief="solid", bd=1
        )
        entry_base.pack(pady=10)
        entry_base.focus()

        resultado = {"exito": False}

        def confirmar():
            base_val = entry_base.get_value()
            try:
                sesion_id = abrir_sesion_caja(usuario=usuario_actual, monto_inicial=base_val)
                resultado["exito"] = True
                dlg.destroy()
                self.actualizar_estado_caja()
                messagebox.showinfo(
                    "✅ Caja Abierta",
                    f"Turno de caja #{sesion_id} abierto exitosamente.\n\n"
                    f"Base inicial: ${base_val:,.0f} COP\n"
                    f"Responsable: {usuario_actual}\n\n"
                    f"Ya puede registrar y procesar ventas.",
                    parent=self.ventana
                )
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo abrir la caja: {e}", parent=dlg)

        def abrir_modulo_completo():
            dlg.destroy()
            self._abrir_caja_menu_completo()

        btn_f = tk.Frame(dlg, bg=t_dlg["bg_surface"])
        btn_f.pack(side="bottom", fill="x", padx=15, pady=12)

        crear_boton(btn_f, "Cancelar", dlg.destroy, tipo="secondary", tam_fuente=9).pack(side="left", padx=3)
        crear_boton(btn_f, "🖥️ Módulo Completo", abrir_modulo_completo, tipo="info", tam_fuente=9).pack(side="left", padx=3)
        crear_boton(btn_f, "🟢 Confirmar Apertura", confirmar, tipo="success", tam_fuente=9).pack(side="right", padx=3)

        dlg.bind("<Return>", lambda e: confirmar())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

        self.ventana.wait_window(dlg)
        return resultado["exito"]

    def verificar_caja_abierta(self, accion="realizar ventas") -> bool:
        """
        Verifica si la caja está abierta.
        Si está cerrada:
        1. Muestra un mensaje de error explícito.
        2. Abre inmediatamente el diálogo de apertura de turno de caja.
        Retorna True si la caja quedó abierta, False si continúa cerrada.
        """
        activa = obtener_sesion_activa()
        if activa and activa.get("id"):
            self.actualizar_estado_caja()
            return True

        self.actualizar_estado_caja()

        # Si es un operario, no puede abrir caja física directamente
        if self.es_operario:
            messagebox.showerror(
                "⚠️ Caja Cerrada",
                f"No se puede {accion} porque la caja se encuentra CERRADA.\n\n"
                f"El Administrador o Vendedor debe abrir el turno de caja antes de recibir pedidos.",
                parent=self.ventana
            )
            return False

        # 1. Alerta de error obligatoria para Vendedor o Administrador
        messagebox.showerror(
            "⚠️ Caja Cerrada",
            f"No se puede {accion} porque la caja se encuentra CERRADA.\n\n"
            f"Debe abrir el turno de caja antes de registrar o procesar ventas.\n\n"
            f"Presione ACEPTAR para realizar la apertura de caja ahora mismo.",
            parent=self.ventana
        )

        # 2. Redireccionar de inmediato a la apertura de caja
        return self.modal_abrir_caja()

    def gestionar_caja_pos(self):
        """Gestiona la caja desde el POS (apertura de turno, menú de opciones o gaveta física)."""
        activa = obtener_sesion_activa()
        if not activa:
            self.modal_abrir_caja()
            return

        menu = tk.Menu(self.ventana, tearoff=0)
        menu.add_command(
            label=f"🟢 Turno #{activa['id']} Activo ({activa.get('usuario_apertura', 'Cajero')})",
            state="disabled"
        )
        menu.add_separator()
        menu.add_command(
            label="💵 Abrir Control de Caja Completo (Arqueo / Movimientos)",
            command=self._abrir_caja_menu_completo
        )
        menu.add_command(
            label="⚡ Abrir Gaveta Física (Impresora RJ11)",
            command=self.emergencia_abrir_caja
        )
        try:
            menu.tk_popup(self.ventana.winfo_pointerx(), self.ventana.winfo_pointery())
        except Exception:
            self._abrir_caja_menu_completo()

    def _abrir_caja_menu_completo(self):
        """Abre el módulo caja_menu in-process pasando usuario y rol."""
        try:
            try:
                from interface.caja_menu import iniciar_control_caja
            except ImportError:
                from caja_menu import iniciar_control_caja
            w = iniciar_control_caja(usuario_actual=self.user_nombre or "Vendedor", rol_actual=self.rol or "Vendedor", parent=self.ventana)
            if w:
                try:
                    from interface.session_manager import session_mgr
                except ImportError:
                    from session_manager import session_mgr
                session_mgr.registrar_ventana(w)
                return
        except Exception as e_inp:
            print("Aviso abriendo caja in-process desde ventas:", e_inp)
            if not getattr(sys, 'frozen', False):
                try:
                    caja_path = os.path.join(os.path.dirname(__file__), "caja_menu.py")
                    if os.path.exists(caja_path):
                        args = [sys.executable, caja_path]
                        if self.user_nombre: args.extend(["--usuario", str(self.user_nombre)])
                        if self.rol: args.extend(["--rol", str(self.rol)])
                        if self.user_id: args.extend(["--user_id", str(self.user_id)])
                        subprocess.Popen(args)
                        return
                except Exception as e_sub:
                    print("Error abriendo subproceso caja:", e_sub)
            messagebox.showerror("Error", f"No se pudo abrir el módulo de Control de Caja:\n{e_inp}", parent=self.ventana)

    # ====================================================================================
    #   FUNCIONES DE EMERGENCIA - NUEVAS
    # ====================================================================================
    
    def emergencia_abrir_caja(self):
        """Función de emergencia para abrir caja registradora - CORREGIDA"""
        try:
            print("DEBUG: Botón ABRIR CAJA presionado")
            
            if not self.printer_manager:
                messagebox.showerror("Error", "Sistema de impresión no disponible")
                return
            
            # FORZAR RECONEXIÓN SI ES NECESARIO
            if not self.impresora_conectada:
                print("DEBUG: Reconectando impresora...")
                messagebox.showwarning("Impresora", "Intentando conectar impresora...")
                if not self.printer_manager.conectar_impresora():
                    messagebox.showerror("Error", "No se pudo conectar con la impresora")
                    return
                self.impresora_conectada = True
            
            # INTENTAR ABRIR CAJA CON MANEJO DE ERRORES DETALLADO
            print("DEBUG: Ejecutando comando abrir caja...")
            resultado = self.printer_manager.abrir_caja_registradora()
            
            if resultado:
                print("DEBUG: ✅ Comando enviado exitosamente")
                messagebox.showinfo("✅ Caja Abierta", "💰 Caja registradora abierta exitosamente")
            else:
                print("DEBUG: ❌ Comando falló sin excepción")
                messagebox.showwarning("Advertencia", "Comando enviado pero la caja no respondió.\nVerifica la conexión de la caja.")
            
        except Exception as e:
            error_detallado = str(e)
            print(f"DEBUG: ❌ Error detallado: {error_detallado}")
            
            # MOSTRAR ERROR ESPECÍFICO Y OPCIONES
            error_window = tk.Toplevel(self.ventana)
            error_window.title("❌ Error Apertura Caja")
            error_window.geometry("500x300")
            error_window.configure(bg="#FFB6C1")
            error_window.grab_set()
            
            # Centrar ventana
            x = (self.ventana.winfo_screenwidth() // 2) - 250
            y = (self.ventana.winfo_screenheight() // 2) - 150
            error_window.geometry(f"500x300+{x}+{y}")
            
            tk.Label(error_window, text="❌ ERROR AL ABRIR CAJA", font=("Arial", 14, "bold"),
                    bg="#FFB6C1", fg="#8B0054").pack(pady=10)
            
            tk.Label(error_window, text=f"Error: {error_detallado}", font=("Arial", 10),
                    bg="#FFB6C1", fg="#8B0054", wraplength=450).pack(pady=5)
            
            tk.Label(error_window, text="🔧 Posibles soluciones:", font=("Arial", 10, "bold"),
                    bg="#FFB6C1", fg="#8B0054").pack(pady=(15,5))
            
            soluciones = """• Verifica que la caja esté conectada al puerto de la impresora
• Revisa que el cable de la caja esté bien conectado
• La caja debe estar conectada al puerto RJ11/RJ12 de la impresora
• Algunos modelos requieren configuración específica
• Prueba reiniciar la impresora"""
            
            tk.Label(error_window, text=soluciones, font=("Arial", 9),
                    bg="#FFB6C1", fg="#8B0054", justify="left").pack(pady=5)
            
            def reintentar_caja():
                error_window.destroy()
                print("DEBUG: Reintentando apertura de caja...")
                try:
                    # FORZAR NUEVA CONEXIÓN
                    self.impresora_conectada = False
                    self.emergencia_abrir_caja()
                except Exception as retry_error:
                    messagebox.showerror("Error", f"Reintento falló: {retry_error}")
            
            btn_frame = tk.Frame(error_window, bg="#FFB6C1")
            btn_frame.pack(pady=15)
            
            tk.Button(btn_frame, text="🔄 Reintentar", command=reintentar_caja,
                     bg="#D97706", fg="white", font=("Arial", 10, "bold"), padx=15).pack(side="left", padx=5)
            
            tk.Button(btn_frame, text="✅ Cerrar", command=error_window.destroy,
                     bg="#DB2777", fg="white", font=("Arial", 10, "bold"), padx=15).pack(side="left", padx=5)
    
    def emergencia_reimprimir(self):
        """Función de emergencia para reimprimir última factura"""
        try:
            if not self.printer_manager:
                messagebox.showerror("Error", "Sistema de impresión no disponible")
                return
            
            if not self.printer_manager.ultima_factura:
                messagebox.showwarning("Sin factura", "No hay factura previa para reimprimir")
                return
            
            if not self.impresora_conectada:
                messagebox.showwarning("Impresora", "Intentando conectar impresora...")
                if not self.printer_manager.conectar_impresora():
                    messagebox.showerror("Error", "No se pudo conectar con la impresora")
                    return
                self.impresora_conectada = True
            
            # Mostrar confirmación con datos de la factura
            factura = self.printer_manager.ultima_factura
            confirmacion = f"""¿Reimprimir esta factura?

🧾 Factura: {factura['factura']}
📅 Fecha: {factura['fecha']} {factura['hora']}
👤 Cliente: {factura['cliente']}
💸 Total: ${factura['total']:,.0f}"""
            
            if messagebox.askyesno("Confirmar Reimpresión", confirmacion):
                def callback_reimprimir(exito, mensaje):
                    if exito:
                        self.ventana.after(0, lambda: messagebox.showinfo("✅ Reimpresión", "Factura reimpresa correctamente 🖨️"))
                    else:
                        self.ventana.after(0, lambda: messagebox.showerror("Error Reimpresión", f"Error: {mensaje}"))
                
                self.printer_manager.imprimir_factura(factura, callback_reimprimir)
            
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo reimprimir:\n{str(e)}")

    # ====================================================================================
    #   FUNCIONES DE DATOS Y UTILIDADES
    # ====================================================================================

    def obtener_productos(self):
        """
        Obtiene el catálogo activo directamente desde el Servidor Central (`/inventario/catalogo`).
        Para productos físicos, el stock disponible para venta en mostrador es `stock_vitrina`.
        """
        todos_los_productos = []
        try:
            try:
                from interface.inventario_manager import obtener_catalogo
            except ImportError:
                from inventario_manager import obtener_catalogo
            items = obtener_catalogo(solo_activos=True)
            if items is not None:
                for it in items:
                    cod = str(it.get("codigo", "")).strip()
                    nom = str(it.get("nombre", "")).strip()
                    tipo_p = str(it.get("tipo_producto", "Fisico")).strip()
                    precio_v = float(it.get("precio", 0.0))
                    costo_u = float(it.get("costo", 0.0))
                    prov_id = it.get("proveedor_id")
                    p_id = it.get("id")
                    cod_barras = str(it.get("codigo_barras") or "").strip()

                    if tipo_p == "Servicio":
                        es_var = bool(it.get("precio_variable", 0))
                        todos_los_productos.append(
                            (cod, nom, 9999, precio_v, "Servicio", prov_id, p_id, costo_u, es_var, 0.0, cod_barras)
                        )
                    else:
                        sv = float(it.get("stock_vitrina", 0.0))
                        sb = float(it.get("stock_bodega", 0.0))
                        try:
                            sv_fmt = int(sv) if sv.is_integer() else sv
                        except Exception:
                            sv_fmt = sv
                        es_var_prod = bool(it.get("precio_variable", 0))
                        todos_los_productos.append(
                            (cod, nom, sv_fmt, precio_v, "Fisico", prov_id, p_id, costo_u, es_var_prod, sb, cod_barras)
                        )

                if str(self.rol).strip().lower() == "operario":
                    return [item for item in todos_los_productos if item[4] == "Servicio"]
                return todos_los_productos
        except Exception as e:
            print(f"Aviso consultando catálogo central `/inventario/catalogo`: {e}")

        # Respaldo directo contra `/productos` y `/servicios` centrales
        try:
            resp_prod = api.get("/productos?size=1000")
            resp_serv = api.get("/servicios?size=1000")

            if resp_prod.status_code == 200:
                prod_data = resp_prod.json()
                productos = (
                    prod_data.get("items", [])
                    if isinstance(prod_data, dict)
                    else (prod_data if isinstance(prod_data, list) else [])
                )
                for p in productos:
                    stock_val = p.get("stock_vitrina", p.get("stock", 0))
                    sb_val = float(p.get("stock_bodega", 0.0) or 0.0)
                    try:
                        stock_fmt = int(stock_val) if float(stock_val).is_integer() else stock_val
                    except Exception:
                        stock_fmt = stock_val
                    precio_v = p.get("precio_venta", p.get("precio", 0.0))
                    costo_u = p.get("precio_costo", p.get("costo", 0.0))
                    cod_barras = str(p.get("codigo_barras") or "").strip()
                    todos_los_productos.append(
                        (
                            p.get("codigo", ""),
                            p.get("nombre", ""),
                            stock_fmt,
                            precio_v,
                            "Fisico",
                            p.get("proveedor_id"),
                            p.get("id"),
                            costo_u,
                            bool(p.get("precio_variable", False)),
                            sb_val,
                            cod_barras,
                        )
                    )

            if resp_serv.status_code == 200:
                serv_data = resp_serv.json()
                servicios = (
                    serv_data.get("items", [])
                    if isinstance(serv_data, dict)
                    else (serv_data if isinstance(serv_data, list) else [])
                )
                for s in servicios:
                    precio_s = s.get("precio_venta", s.get("precio", 0.0))
                    costo_s = s.get("costo_proveedor", s.get("costo", 0.0))
                    precio_var = bool(s.get("precio_variable", False))
                    todos_los_productos.append(
                        (
                            s.get("codigo", ""),
                            s.get("nombre", ""),
                            9999,
                            precio_s,
                            "Servicio",
                            s.get("proveedor_id"),
                            s.get("id"),
                            costo_s,
                            precio_var,
                            0.0,
                            "",
                        )
                    )

            if str(self.rol).strip().lower() == "operario":
                return [item for item in todos_los_productos if item[4] == "Servicio"]
            return todos_los_productos
        except Exception as e:
            print(f"Aviso respaldo API productos/servicios: {e}")
            return todos_los_productos

    def formato_peso(self, valor):
        """Formato de pesos colombianos"""
        return f"${int(valor):,.0f} COP"

    def limpiar_precio(self, texto):
        """Convertir texto de precio a número, soportando separadores de miles con coma o punto"""
        if isinstance(texto, (int, float)):
            return float(texto)
        s = str(texto or "").replace("$", "").replace("COP", "").strip()
        if "." in s and "," not in s:
            partes = s.split(".")
            if len(partes) > 1 and all(len(p) == 3 for p in partes[1:]):
                s = "".join(partes)
        s = s.replace(",", "").strip()
        try:
            return float(s or 0.0)
        except Exception:
            return 0.0

    def actualizar_total(self):
        """Actualizar el total general y su etiqueta en pantalla sumando las filas del carrito."""
        total_calculado = 0.0
        for item_id in self.tabla.get_children():
            valores = self.tabla.item(item_id, "values")
            if valores and len(valores) >= 4:
                total_calculado += self.limpiar_precio(valores[3])
        self.total_general.set(round(total_calculado, 2))
        if hasattr(self, "total_label") and self.total_label:
            self.total_label.config(text=self.formato_peso(total_calculado))

    def actualizar_hora(self):
        """Actualizar hora cada segundo"""
        ahora = datetime.now()
        self.lbl_fecha.config(text=f"📅 {ahora.strftime('%d-%m-%Y')}")
        self.lbl_hora.config(text=f"🕒 {ahora.strftime('%H:%M:%S')}")
        self.ventana.after(1000, self.actualizar_hora)

    # ====================================================================================
    #   FUNCIONES DE INTERFAZ - MEJORADAS
    # ====================================================================================

    def solicitar_precio_variable(self, nombre, precio_sugerido=0.0, parent=None):
        """Muestra un modal estilizado para ingresar el precio acordado de un producto o servicio con precio variable"""
        parent_win = parent or self.ventana
        dialog = tk.Toplevel(parent_win)
        dialog.title("💰 Definir Precio de Venta")
        t_d = aplicar_tema(dialog)
        dialog.configure(bg=t_d["bg_surface"])
        dialog.transient(parent_win)
        dialog.grab_set()

        calcular_geometria_segura(dialog, 460, 260, 400, 220)
        dialog.resizable(False, False)

        tk.Label(dialog, text="⚙️ ARTÍCULO CON PRECIO VARIABLE", font=("Segoe UI", 11, "bold"), 
                 bg=t_d["bg_surface"], fg=t_d["bg_header"]).pack(pady=(16, 5))
        tk.Label(dialog, text=f"Ingrese el precio acordado para la venta:\n'{nombre}'", font=("Segoe UI", 10), 
                 bg=t_d["bg_surface"], fg=t_d["text_secondary"], justify="center").pack(pady=(0, 10))

        entry_frame = tk.Frame(dialog, bg=t_d["bg_surface"])
        entry_frame.pack(pady=5)
        tk.Label(entry_frame, text="$", font=("Segoe UI", 14, "bold"), bg=t_d["bg_surface"], fg=t_d["text_main"]).pack(side="left", padx=(0, 5))
        
        entry_monto = CurrencyEntry(
            entry_frame,
            initial_value=precio_sugerido,
            show_symbol=False,
            font=("Segoe UI", 14, "bold"),
            width=15,
            justify="center",
            bd=1,
            relief="solid",
            bg=t_d["input_bg"],
            fg=t_d["input_fg"],
            insertbackground=t_d["input_insert"]
        )
        entry_monto.pack(side="left")
        entry_monto.focus()

        resultado = [None]

        def confirmar(event=None):
            monto = entry_monto.get_value()
            if monto <= 0:
                messagebox.showwarning("Atención", "El precio de venta debe ser mayor a 0", parent=dialog)
                return
            resultado[0] = float(monto)
            dialog.destroy()

        btn_frame = tk.Frame(dialog, bg=t_d["bg_surface"])
        btn_frame.pack(side="bottom", fill="x", padx=15, pady=15)

        btn_canc = crear_boton(btn_frame, "Cancelar", command=dialog.destroy, tipo="secondary", icono="❌", tam_fuente=9)
        btn_canc.pack(side="right", padx=5)

        btn_ok = crear_boton(btn_frame, "Cargar al Carrito", command=confirmar, tipo="success", icono="✅", tam_fuente=9)
        btn_ok.pack(side="right", padx=5)

        dialog.bind("<Return>", confirmar)
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        parent_win.wait_window(dialog)
        try:
            self.entry_codigo.focus_set()
        except Exception:
            pass
        return resultado[0]

    def buscar_producto(self):
        """Ventana de búsqueda de productos con layout responsive y scrollbar"""
        if not self.verificar_caja_abierta("buscar o agregar productos"):
            return
        ventana = tk.Toplevel(self.ventana)
        ventana.title("🔎 Buscar Producto en Catálogo")
        t_b = aplicar_tema(ventana)
        calcular_geometria_segura(ventana, 780, 520, 550, 380)
        ventana.configure(bg=t_b["bg_app"])
        self._dialogo_pago_activo = True
        ventana.grab_set()

        # 1. Header de búsqueda
        top_frame = tk.Frame(ventana, bg=t_b["bg_app"])
        top_frame.pack(side="top", fill="x", padx=15, pady=(10, 4))

        tipo_busq = tk.StringVar(value="Todos")
        f_tipo_m = tk.Frame(top_frame, bg=t_b["bg_app"])
        f_tipo_m.pack(fill="x", pady=(0, 5))
        tk.Label(f_tipo_m, text="🏷️ Tipo:", bg=t_b["bg_app"], fg=t_b["text_main"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 5))
        for val, txt in [("Todos", "📑 Todos"), ("Fisico", "📦 Físicos"), ("Servicio", "🛎️ Servicios")]:
            tk.Radiobutton(f_tipo_m, text=txt, variable=tipo_busq, value=val, bg=t_b["bg_app"], activebackground=t_b["bg_app"],
                           font=("Segoe UI", 9, "bold"), fg=t_b["text_main"], selectcolor=t_b["bg_surface_alt"],
                           command=lambda: actualizar_lista()).pack(side="left", padx=3)

        f_entry_m = tk.Frame(top_frame, bg=t_b["bg_app"])
        f_entry_m.pack(fill="x", pady=(0, 2))
        tk.Label(f_entry_m, text="🔍 Buscar Producto:", bg=t_b["bg_app"], fg=t_b["text_main"], 
                font=("Segoe UI", 11, "bold")).pack(side="left", padx=(0, 10))
        
        filtro = tk.StringVar()
        entry = tk.Entry(f_entry_m, textvariable=filtro, font=("Segoe UI", 10), bd=1, relief="solid", 
                         bg=t_b["input_bg"], fg=t_b["input_fg"], insertbackground=t_b["input_insert"])
        entry.pack(side="left", fill="x", expand=True)
        entry.focus()

        # 2. Footer de acciones (Sticky abajo)
        footer_b = tk.Frame(ventana, bg=t_b["bg_app"])
        footer_b.pack(side="bottom", fill="x", padx=15, pady=10)

        btn_sel = crear_boton(footer_b, "Seleccionar Producto (Enter)", command=lambda: seleccionar(), tipo="success", icono="✨", tam_fuente=10)
        btn_sel.pack(side="right", padx=5)

        btn_cerrar = crear_boton(footer_b, "Cancelar", command=ventana.destroy, tipo="secondary", icono="❌", tam_fuente=10)
        btn_cerrar.pack(side="right", padx=5)

        # 3. Lista de productos con scrollbars (Expandible)
        list_container = tk.Frame(ventana, bg=t_b["bg_surface"], bd=1, relief="solid")
        list_container.pack(side="top", fill="both", expand=True, padx=15, pady=(4, 6))

        cols = ("Código", "Nombre", "Stock", "Precio")
        lista = ttk.Treeview(list_container, columns=cols, show="headings")
        anchos_busq = {"Código": 110, "Nombre": 340, "Stock": 90, "Precio": 130}
        for col in cols:
            lista.heading(col, text=col)
            lista.column(col, width=anchos_busq.get(col, 120), anchor="center")

        scroll_y = ttk.Scrollbar(list_container, orient="vertical", command=lista.yview)
        scroll_x = ttk.Scrollbar(list_container, orient="horizontal", command=lista.xview)
        lista.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        lista.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        list_container.grid_rowconfigure(0, weight=1)
        list_container.grid_columnconfigure(0, weight=1)

        def actualizar_lista():
            lista.delete(*lista.get_children())
            filtro_texto = filtro.get().lower().strip()
            t_sel = tipo_busq.get().strip()
            
            for p in self.productos_inventario:
                if t_sel != "Todos" and p[4] != t_sel:
                    continue
                if not filtro_texto or filtro_texto in f"{p[0]} {p[1]}".lower():
                    es_var = p[8] if len(p) > 8 else False
                    precio_str = "Variable" if es_var else self.formato_peso(p[3])
                    stock_str = "—" if p[4] == "Servicio" else str(p[2])
                    lista.insert("", tk.END, values=(p[0], p[1], stock_str, precio_str))

        def seleccionar():
            item = lista.focus()
            if not item:
                sel = lista.selection()
                if sel:
                    item = sel[0]
            if item:
                valores = lista.item(item)["values"]
                codigo = valores[0]
                nombre = valores[1] 
                stock = float(valores[2])
                
                prod_encontrado = None
                for p in self.productos_inventario:
                    if str(p[0]) == str(codigo) or str(p[0]).zfill(5) == str(codigo).zfill(5):
                        prod_encontrado = p
                        break
                        
                tipo_prod = prod_encontrado[4] if prod_encontrado else "Fisico"
                es_var = prod_encontrado[8] if (prod_encontrado and len(prod_encontrado) > 8) else False
                precio_base = prod_encontrado[3] if prod_encontrado else self.limpiar_precio(valores[3])
                
                if stock > 0 or tipo_prod == "Servicio":
                    if es_var:
                        precio_ingresado = self.solicitar_precio_variable(nombre, precio_base, parent=ventana)
                        if precio_ingresado is None:
                            return
                        precio = precio_ingresado
                    else:
                        precio = precio_base

                    self.agregar_producto(codigo, nombre, precio)
                    ventana.destroy()
                else:
                    messagebox.showwarning("Sin stock", "Producto sin stock disponible", parent=ventana)
            else:
                messagebox.showinfo("Aviso", "Seleccione un producto de la tabla.", parent=ventana)

        actualizar_lista()
        filtro.trace_add("write", lambda *args: actualizar_lista())
        
        lista.bind('<Double-1>', lambda e: seleccionar())
        ventana.bind('<Return>', lambda e: seleccionar())
        ventana.bind('<Escape>', lambda e: ventana.destroy())

    def agregar_producto(self, codigo, nombre, precio):
        """Agregar producto al carrito - Suma cantidades si ya existe, valida stock y mantiene foco en entry_codigo"""
        if not self.verificar_caja_abierta("agregar productos al carrito"):
            return
        # Verificar stock disponible - buscar por código exacto o con formato
        stock_disponible = 0
        stock_bodega = 0
        tipo_prod = "Fisico"
        for p in self.productos_inventario:
            if str(p[0]) == str(codigo) or str(p[0]).zfill(5) == str(codigo).zfill(5):
                stock_disponible = p[2]
                tipo_prod = p[4]
                if len(p) > 9:
                    stock_bodega = p[9]
                break
        
        print(f"DEBUG: Código {codigo}, Stock vitrina: {stock_disponible}, Stock bodega: {stock_bodega}, Tipo: {tipo_prod}")
        
        # BUSCAR SI YA EXISTE EN EL CARRITO CON EL MISMO PRECIO
        cantidad_actual = 0
        item_existente = None
        
        for item in self.tabla.get_children():
            valores = self.tabla.item(item)["values"]
            item_cod = str(self.tabla.item(item, "text") or "").strip()
            if len(valores) >= 4:
                p_unit = self.limpiar_precio(valores[1])
                cod_str = str(codigo).strip()
                coincide_cod = (item_cod and cod_str and (item_cod.lower() == cod_str.lower() or item_cod.zfill(5) == cod_str.zfill(5)))
                coincide_nom = (str(valores[0]).strip().lower() == str(nombre).strip().lower())
                if (coincide_cod or coincide_nom) and abs(p_unit - precio) < 0.01:
                    cantidad_actual = int(float(valores[2]))
                    item_existente = item
                    print(f"DEBUG: Producto encontrado en carrito - Cantidad actual: {cantidad_actual}")
                    break

        # Verificar si se puede agregar una unidad más (solo si NO es servicio)
        if tipo_prod != "Servicio" and (cantidad_actual + 1 > stock_disponible):
            if stock_bodega > 0:
                messagebox.showwarning(
                    "Stock insuficiente en Vitrina", 
                    f"Artículo: {nombre}\n\n"
                    f"Disponible en Vitrina (mostrador): {stock_disponible}\n"
                    f"Disponible en Bodega: {stock_bodega}\n"
                    f"Ya tienes {cantidad_actual} en el carrito.\n\n"
                    f"💡 No hay suficiente mercancía en vitrina para esta venta.\n"
                    f"Por favor realice un traslado de Bodega a Vitrina desde el módulo de Inventario.",
                    parent=self.ventana
                )
            else:
                messagebox.showwarning(
                    "Stock insuficiente", 
                    f"Artículo: {nombre}\n\n"
                    f"Disponible en Vitrina: {stock_disponible}\n"
                    f"Disponible en Bodega: 0\n"
                    f"Ya tienes {cantidad_actual} en el carrito.\n\n"
                    f"El producto está completamente agotado.",
                    parent=self.ventana
                )
            self.codigo_entrada.set("")
            try:
                self.entry_codigo.focus_set()
            except Exception:
                pass
            return

        if item_existente:
            # ACTUALIZAR CANTIDAD EXISTENTE
            nueva_cantidad = cantidad_actual + 1
            nuevo_total = precio * nueva_cantidad
            
            # Actualizar la fila existente
            self.tabla.item(item_existente, values=(
                nombre, 
                self.formato_peso(precio), 
                nueva_cantidad, 
                self.formato_peso(nuevo_total)
            ))
            self.tabla.selection_set(item_existente)
            self.tabla.see(item_existente)
            
            # Sumar solo el precio unitario al total general
            self.total_general.set(self.total_general.get() + precio)
            
            print(f"DEBUG: Producto actualizado - Nueva cantidad: {nueva_cantidad}, Nuevo total item: {nuevo_total}")
        else:
            # Verificar que hay stock para agregar el primer producto
            if tipo_prod != "Servicio" and stock_disponible <= 0:
                if stock_bodega > 0:
                    messagebox.showwarning(
                        "Sin stock en Vitrina",
                        f"El producto '{nombre}' no tiene existencias en Vitrina.\n\n"
                        f"Existen {stock_bodega} unidades almacenadas en Bodega.\n"
                        f"Realice un traslado a vitrina para poder despacharlo.",
                        parent=self.ventana
                    )
                else:
                    messagebox.showwarning("Sin stock", f"El producto '{nombre}' no tiene stock disponible", parent=self.ventana)
                self.codigo_entrada.set("")
                try:
                    self.entry_codigo.focus_set()
                except Exception:
                    pass
                return
            
            # Agregar nuevo producto
            nuevo_item = self.tabla.insert("", tk.END, text=codigo, values=(nombre, self.formato_peso(precio), 1, 
                                                 self.formato_peso(precio)))
            self.tabla.selection_set(nuevo_item)
            self.tabla.see(nuevo_item)
            self.total_general.set(self.total_general.get() + precio)
            
            print(f"DEBUG: Nuevo producto agregado: {nombre}")
        
        self.actualizar_total()
        self.codigo_entrada.set("")
        try:
            self.entry_codigo.focus_set()
        except Exception:
            pass

    def buscar_producto_por_codigo(self, codigo):
        """
        Localiza un producto por código de barras exacto, SKU interno o formato numérico.
        1. Búsqueda directa en memoria (self.productos_inventario).
        2. Si no se encuentra, consulta central a inventario_manager / SQLite local.
        Retorna la tupla de datos del producto, ('INACTIVO', nombre) si está deshabilitado, o None si no existe.
        """
        cod_clean = str(codigo or "").strip()
        if not cod_clean:
            return None

        cod_lower = cod_clean.lower()
        cod_zfill = cod_clean.zfill(5)

        # 1. Búsqueda en caché local de memoria
        for p in self.productos_inventario:
            # p[10] = codigo_barras
            if len(p) > 10 and p[10]:
                cb = str(p[10]).strip()
                if cb and cb.lower() == cod_lower:
                    return p
            # p[0] = SKU interno
            sku = str(p[0]).strip()
            if sku.lower() == cod_lower or sku.zfill(5) == cod_zfill:
                return p

        # 2. Respaldo directo en inventario_manager (API / SQLite)
        try:
            try:
                from interface.inventario_manager import obtener_articulo_por_codigo
            except ImportError:
                from inventario_manager import obtener_articulo_por_codigo

            art = obtener_articulo_por_codigo(cod_clean)
            if art:
                estado = str(art.get("estado", "Activo") or "Activo").strip().lower()
                nom = str(art.get("nombre", cod_clean)).strip()
                if estado in ("inactivo", "desactivado", "bloqueado", "eliminado"):
                    return ("INACTIVO", nom)

                cod = str(art.get("codigo", "")).strip()
                tipo_p = str(art.get("tipo_producto", "Fisico")).strip()
                precio_v = float(art.get("precio", art.get("precio_venta", 0.0)) or 0.0)
                costo_u = float(art.get("costo", art.get("precio_costo", 0.0)) or 0.0)
                prov_id = art.get("proveedor_id")
                p_id = art.get("id")
                cb = str(art.get("codigo_barras") or "").strip()
                es_var = bool(art.get("precio_variable", 0))
                sv = float(art.get("stock_vitrina", art.get("stock", 0.0)) or 0.0)
                sb = float(art.get("stock_bodega", 0.0) or 0.0)
                sv_fmt = int(sv) if sv.is_integer() else sv

                if tipo_p == "Servicio":
                    nuevo_prod = (cod, nom, 9999, precio_v, "Servicio", prov_id, p_id, costo_u, es_var, 0.0, cb)
                else:
                    nuevo_prod = (cod, nom, sv_fmt, precio_v, "Fisico", prov_id, p_id, costo_u, es_var, sb, cb)

                self.productos_inventario.append(nuevo_prod)
                return nuevo_prod
        except Exception as e_lookup:
            print(f"DEBUG: Error consultando artículo '{cod_clean}': {e_lookup}")

        return None

    def escanear_codigo(self, codigo_directo=None):
        """
        Escanea un código interno o código de barras EAN/Code128 y agrega el producto.
        Soporta escaneo continuo desatendido, debounce de hardware y validación de stock.
        """
        if not self.verificar_caja_abierta("escanear o agregar productos"):
            self.codigo_entrada.set("")
            try:
                self.entry_codigo.focus_set()
            except Exception:
                pass
            return

        codigo = str(codigo_directo if codigo_directo is not None else self.codigo_entrada.get()).strip()
        if not codigo:
            try:
                self.entry_codigo.focus_set()
            except Exception:
                pass
            return

        # Debounce de rebote de hardware (< 220ms para el mismo código exacto)
        ahora = time.time()
        if codigo == getattr(self, "_ultimo_escaneo_codigo", "") and (ahora - getattr(self, "_ultimo_escaneo_tiempo", 0.0)) < 0.22:
            print(f"DEBUG: Doble lectura de hardware ignorada (< 220ms): {codigo}")
            self.codigo_entrada.set("")
            try:
                self.entry_codigo.focus_set()
            except Exception:
                pass
            return

        self._ultimo_escaneo_codigo = codigo
        self._ultimo_escaneo_tiempo = ahora

        producto = self.buscar_producto_por_codigo(codigo)

        if isinstance(producto, tuple) and len(producto) == 2 and producto[0] == "INACTIVO":
            messagebox.showwarning(
                "Producto Inactivo",
                f"El artículo '{producto[1]}' se encuentra inactivo y no puede ser vendido.",
                parent=self.ventana
            )
            self.codigo_entrada.set("")
            try:
                self.entry_codigo.focus_set()
            except Exception:
                pass
            return

        if not producto:
            messagebox.showwarning(
                "Código no registrado",
                f"El código '{codigo}' no corresponde a ningún producto o servicio registrado en el inventario.",
                parent=self.ventana
            )
            self.codigo_entrada.set("")
            try:
                self.entry_codigo.focus_set()
            except Exception:
                pass
            return

        # producto: (cod, nom, stock_vitrina, precio, tipo, prov_id, p_id, costo, es_var, stock_bodega, cod_barras)
        cod_prod = producto[0]
        nom_prod = producto[1]
        stock_disp = producto[2]
        precio_base = producto[3]
        tipo_prod = producto[4]
        es_var = bool(producto[8]) if len(producto) > 8 else False
        stock_bod = producto[9] if len(producto) > 9 else 0.0

        if tipo_prod != "Servicio" and stock_disp <= 0:
            if stock_bod > 0:
                messagebox.showwarning(
                    "Sin stock en Vitrina",
                    f"El producto '{nom_prod}' no tiene existencias en Vitrina (mostrador).\n\n"
                    f"Existen {stock_bod} unidades almacenadas en Bodega.\n"
                    f"Realice un traslado a vitrina para poder despacharlo.",
                    parent=self.ventana
                )
            else:
                messagebox.showwarning(
                    "Sin stock",
                    f"El producto '{nom_prod}' no tiene stock disponible.",
                    parent=self.ventana
                )
            self.codigo_entrada.set("")
            try:
                self.entry_codigo.focus_set()
            except Exception:
                pass
            return

        precio = precio_base
        if es_var:
            precio_ingresado = self.solicitar_precio_variable(nom_prod, precio_base, parent=self.ventana)
            if precio_ingresado is None:
                self.codigo_entrada.set("")
                try:
                    self.entry_codigo.focus_set()
                except Exception:
                    pass
                return
            precio = precio_ingresado

        # Agregar o incrementar cantidad en el carrito
        self.agregar_producto(cod_prod, nom_prod, precio)
        self.codigo_entrada.set("")
        try:
            self.entry_codigo.focus_set()
        except Exception:
            pass

    def eliminar_seleccionado(self):
        """Elimina el producto seleccionado del carrito"""
        item = self.tabla.focus() or (self.tabla.selection()[0] if self.tabla.selection() else None)
        if item:
            valores = self.tabla.item(item)["values"]
            self.total_general.set(self.total_general.get() - self.limpiar_precio(valores[3]))
            self.tabla.delete(item)
            self.actualizar_total()

    def editar_item_carrito_click(self, event=None):
        """Permite modificar directamente la cantidad y el precio del producto seleccionado en el carrito."""
        sel = self.tabla.selection()
        if not sel and event and hasattr(event, "y"):
            row_id = self.tabla.identify_row(event.y)
            if row_id:
                sel = (row_id,)
                self.tabla.selection_set(row_id)
        if not sel:
            item_foc = self.tabla.focus()
            if item_foc:
                sel = (item_foc,)
                self.tabla.selection_set(item_foc)

        if not sel:
            hijos = self.tabla.get_children()
            if hijos:
                sel = (hijos[-1],)
                self.tabla.selection_set(hijos[-1])
                self.tabla.focus(hijos[-1])

        if not sel:
            messagebox.showinfo("Modificar Ítem", "Seleccione un producto en la tabla del carrito para modificar su cantidad o precio.", parent=self.ventana)
            return

        item_id = sel[0]
        codigo = self.tabla.item(item_id, "text")
        valores = self.tabla.item(item_id, "values")
        if not valores or len(valores) < 4:
            return

        nombre = str(valores[0])
        precio_actual = self.limpiar_precio(valores[1])
        try:
            cant_actual = float(valores[2])
        except Exception:
            cant_actual = 1.0

        # Buscar información completa del producto en inventario
        prod_encontrado = None
        for p in self.productos_inventario:
            cod_p = str(p[0]).strip()
            cod_c = str(codigo).strip()
            if cod_p.lower() == cod_c.lower() or cod_p.zfill(5) == cod_c.zfill(5):
                prod_encontrado = p
                break

        tipo_prod = prod_encontrado[4] if prod_encontrado else "Fisico"
        stock_vitrina = float(prod_encontrado[2]) if prod_encontrado else 0.0
        stock_bodega = float(prod_encontrado[9]) if prod_encontrado else 0.0
        es_var = bool(prod_encontrado[8]) if (prod_encontrado and len(prod_encontrado) > 8) else False
        precio_maestro = float(prod_encontrado[3]) if prod_encontrado else precio_actual

        # Obtener unidad de medida
        unidad_medida = "Unidad"
        try:
            from interface.inventario_manager import obtener_articulo_por_codigo
        except ImportError:
            try:
                from inventario_manager import obtener_articulo_por_codigo
            except ImportError:
                obtener_articulo_por_codigo = None
        if callable(obtener_articulo_por_codigo):
            try:
                art_data = obtener_articulo_por_codigo(codigo)
                if art_data and art_data.get("unidad_medida"):
                    unidad_medida = art_data.get("unidad_medida")
            except Exception:
                pass

        es_unidad_discreta = unidad_medida in ("Unidad", "Caja", "Paquete", "Docena")

        # Modal de edición estilizado
        dialog = tk.Toplevel(self.ventana)
        dialog.title("✏️ Modificar Cantidad y Precio de Venta")
        t_d = aplicar_tema(dialog)
        dialog.configure(bg=t_d["bg_surface"])
        dialog.transient(self.ventana)
        dialog.grab_set()

        calcular_geometria_segura(dialog, 480, 380, 420, 320)
        dialog.resizable(False, False)

        f_header = tk.Frame(dialog, bg=t_d["bg_surface"], padx=20, pady=12)
        f_header.pack(fill="x")
        tk.Label(f_header, text="✏️ MODIFICAR ÍTEM EN CARRITO", font=("Segoe UI", 11, "bold"),
                 bg=t_d["bg_surface"], fg=t_d["bg_header"]).pack(anchor="w")
        tk.Label(f_header, text=f"Artículo: {nombre} ({codigo})", font=("Segoe UI", 10, "bold"),
                 bg=t_d["bg_surface"], fg=t_d["text_main"]).pack(anchor="w", pady=(2, 0))
        stock_info_txt = f"Presentación: {unidad_medida} | Stock en Vitrina: {stock_vitrina:g} und" if tipo_prod != "Servicio" else f"Presentación: {unidad_medida} (Servicio)"
        tk.Label(f_header, text=stock_info_txt, font=("Segoe UI", 8),
                 bg=t_d["bg_surface"], fg=t_d["text_muted"]).pack(anchor="w")

        f_body = tk.Frame(dialog, bg=t_d["bg_surface"], padx=20, pady=5)
        f_body.pack(fill="both", expand=True)

        # 1. Campo Cantidad
        tk.Label(f_body, text=f"Cantidad ({unidad_medida}):", font=("Segoe UI", 9, "bold"),
                 bg=t_d["bg_surface"], fg=t_d["text_main"]).grid(row=0, column=0, sticky="w", pady=(8, 2))
        var_cant = tk.StringVar(value=str(int(cant_actual) if cant_actual.is_integer() else cant_actual))
        e_cant = tk.Entry(f_body, textvariable=var_cant, font=("Segoe UI", 11), width=15,
                          bg=t_d["input_bg"], fg=t_d["input_fg"], insertbackground=t_d["input_insert"])
        e_cant.grid(row=0, column=1, sticky="w", pady=(8, 2), padx=(10, 0))

        # 2. Campo Precio Unitario
        tk.Label(f_body, text="Precio Unitario ($ COP):", font=("Segoe UI", 9, "bold"),
                 bg=t_d["bg_surface"], fg=t_d["text_main"]).grid(row=1, column=0, sticky="w", pady=(10, 2))
        puede_editar_precio = bool(es_var or self.es_admin)

        e_precio = CurrencyEntry(
            f_body,
            initial_value=precio_actual,
            show_symbol=False,
            font=("Segoe UI", 11, "bold"),
            width=15,
            bg=t_d["input_bg"],
            fg=t_d["input_fg"],
            insertbackground=t_d["input_insert"]
        )
        e_precio.grid(row=1, column=1, sticky="w", pady=(10, 2), padx=(10, 0))

        if not puede_editar_precio:
            e_precio.config(state="disabled")
            tk.Label(f_body, text="🔒 Precio fijo (Requiere perfil Administrador para modificar)",
                     font=("Segoe UI", 8, "italic"), bg=t_d["bg_surface"], fg=t_d["text_muted"]).grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 6))
        else:
            hint_txt = "⚙️ Precio variable habilitado" if es_var else "👑 Modificación autorizada por Administrador"
            tk.Label(f_body, text=hint_txt, font=("Segoe UI", 8, "italic"),
                     bg=t_d["bg_surface"], fg="#10B981" if es_var else "#3B82F6").grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 6))

        # 3. Vista previa del Subtotal
        lbl_sub_prev = tk.Label(f_body, text=f"Nuevo Subtotal: {self.formato_peso(cant_actual * precio_actual)}",
                                font=("Segoe UI", 11, "bold"), bg=t_d["bg_surface"], fg=t_d["text_main"])
        lbl_sub_prev.grid(row=3, column=0, columnspan=2, sticky="w", pady=(12, 5))

        def _recalcular_preview(*a):
            try:
                c_val = float(var_cant.get().strip() or 0.0)
                p_val = float(e_precio.get_value())
                lbl_sub_prev.config(text=f"Nuevo Subtotal: {self.formato_peso(c_val * p_val)}")
            except Exception:
                lbl_sub_prev.config(text="Nuevo Subtotal: —")

        var_cant.trace_add("write", _recalcular_preview)
        e_precio.bind("<KeyRelease>", _recalcular_preview)

        def cerrar_dialogo():
            dialog.destroy()
            try:
                self.entry_codigo.focus_set()
            except Exception:
                pass

        def confirmar_cambios(event=None):
            try:
                c_val = float(var_cant.get().strip())
            except Exception:
                messagebox.showwarning("Cantidad Inválida", "Por favor ingrese una cantidad numérica válida.", parent=dialog)
                e_cant.focus_set()
                return

            if c_val <= 0:
                messagebox.showwarning("Cantidad Inválida", "La cantidad debe ser mayor a cero.", parent=dialog)
                e_cant.focus_set()
                return

            if es_unidad_discreta and not c_val.is_integer():
                messagebox.showwarning(
                    "Unidad No Fraccionable",
                    f"El artículo se despacha por '{unidad_medida}', por lo que no admite cantidades fraccionadas (decimales).",
                    parent=dialog
                )
                e_cant.focus_set()
                return

            if tipo_prod != "Servicio" and c_val > (stock_vitrina + 1e-6):
                msg_st = f"No hay suficiente stock en Vitrina para esta cantidad ({c_val:g} solicitados vs {stock_vitrina:g} disponibles)."
                if stock_bodega > 0:
                    msg_st += f"\n\nExisten {stock_bodega:g} unidades en Bodega. Realice un traslado si requiere más."
                messagebox.showwarning("Stock Insuficiente", msg_st, parent=dialog)
                return

            try:
                p_val = float(e_precio.get_value())
            except Exception:
                p_val = precio_actual

            if p_val <= 0:
                messagebox.showwarning("Precio Inválido", "El precio unitario debe ser mayor a 0.", parent=dialog)
                e_precio.focus_set()
                return

            # Aplicar a la fila del carrito
            cant_fmt = int(c_val) if c_val.is_integer() else round(c_val, 3)
            sub_nuevo = round(p_val * c_val, 2)
            self.tabla.item(item_id, values=(nombre, self.formato_peso(p_val), cant_fmt, self.formato_peso(sub_nuevo)))
            self.actualizar_total()
            cerrar_dialogo()

        f_footer = tk.Frame(dialog, bg=t_d["bg_surface_alt"], padx=15, pady=10, bd=1, relief="ridge")
        f_footer.pack(fill="x", side="bottom")

        def eliminar_item_actual():
            self.tabla.delete(item_id)
            self.actualizar_total()
            cerrar_dialogo()

        crear_boton(f_footer, "Quitar del Carrito", command=eliminar_item_actual, tipo="danger", icono="🗑️").pack(side="left", padx=5)
        crear_boton(f_footer, "Cancelar", command=cerrar_dialogo, tipo="secondary").pack(side="right", padx=5)
        crear_boton(f_footer, "Aplicar Cambios", command=confirmar_cambios, tipo="success", icono="✅").pack(side="right", padx=5)

        dialog.bind("<Return>", confirmar_cambios)
        dialog.bind("<Escape>", lambda e: cerrar_dialogo())
        dialog.protocol("WM_DELETE_WINDOW", cerrar_dialogo)

        try:
            dialog.lift()
            dialog.attributes("-topmost", True)
            dialog.after_idle(lambda: dialog.attributes("-topmost", False))
            dialog.focus_force()
            e_cant.focus_set()
            e_cant.select_range(0, tk.END)
        except Exception:
            pass

    def pagar(self):
        """Abre la ventana para procesar el pago con layout responsive, clientes centrales y confirmación asíncrona idempotente."""
        if getattr(self, "_registrando_venta", False):
            return
        if not self.verificar_caja_abierta("procesar cobros o ventas"):
            return
        if self.total_general.get() <= 0 or len(self.tabla.get_children()) == 0:
            messagebox.showwarning("Carrito Vacío", "Agregue al menos un producto o servicio antes de cobrar.", parent=self.ventana)
            return

        self._exceso_credito_autorizado = False
        ventana = tk.Toplevel(self.ventana)
        ventana.title("💳 Procesar Pago - POS")
        t_p = aplicar_tema(ventana)
        calcular_geometria_segura(ventana, 540, 620, 440, 420)
        ventana.configure(bg=t_p["bg_app"])
        self._dialogo_pago_activo = True
        ventana.grab_set()

        # 1. HEADER (Fijo arriba)
        header_p = tk.Frame(ventana, bg=t_p["bg_header"])
        header_p.pack(side="top", fill="x")
        tk.Label(header_p, text="💖 PROCESAR COBRO", font=("Segoe UI", 14, "bold"), bg=t_p["bg_header"], fg=t_p["text_header"]).pack(pady=(10, 2))
        tk.Label(header_p, text=f"Total: {self.formato_peso(self.total_general.get())}", font=("Segoe UI", 16, "bold"), bg=t_p["bg_header"], fg="#FEF08A").pack(pady=(0, 10))

        # 2. FOOTER ACCIONES (Sticky abajo)
        footer_p = tk.Frame(ventana, bg=t_p["bg_app"])
        footer_p.pack(side="bottom", fill="x", padx=15, pady=12)

        clientes_fiado_map = {}
        total_val = int(round(self.total_general.get()))

        imprimir_ticket_var = tk.BooleanVar(value=True)
        chk_imp = tk.Checkbutton(
            footer_p,
            text="🖨️ Imprimir comprobante",
            variable=imprimir_ticket_var,
            bg=t_p["bg_app"], fg=t_p["text_main"],
            selectcolor=t_p["bg_surface_alt"],
            activebackground=t_p["bg_app"],
            font=("Segoe UI", 9)
        )
        chk_imp.pack(side="left", padx=5)

        def abrir_preview_recibo():
            if getattr(self, "_registrando_venta", False):
                return
            metodo = metodo_var.get()
            monto_ef = entry_efectivo.get_value() if metodo == "Efectivo" else (entry_mix_efectivo.get_value() if metodo == "Mixto" else (0 if metodo == "Fiado" else total_val))
            cid = None
            if metodo in ("Fiado", "Mixto"):
                m_fi = total_val if metodo == "Fiado" else float(entry_mix_fiado.get_value())
                if m_fi > 0:
                    sel = combo_clientes.get()
                    if not sel:
                        messagebox.showerror("Error", "Debe seleccionar un cliente registrado para la porción fiada antes de la vista previa.", parent=ventana)
                        return
                    cid = sel.split(" - ")[0].strip()
                    cli_info = clientes_fiado_map.get(cid)
                    if cli_info:
                        lim = float(cli_info.get("limite_credito") or 0.0)
                        saldo_act = float(cli_info.get("saldo_pendiente") or 0.0)
                        if lim > 0 and (saldo_act + m_fi > lim) and not self._exceso_credito_autorizado:
                            if not self.autorizar_exceso_credito_admin(
                                parent=ventana,
                                cliente_nombre=cli_info.get("nombre", "Cliente"),
                                lim=lim,
                                saldo=saldo_act,
                                total_val=m_fi,
                                exceso=(saldo_act + m_fi) - lim,
                            ):
                                return
                        doc_of = str(cli_info.get("documento") or "").strip()
                        if doc_of:
                            self.documento.set(doc_of)
                        self.cliente_id_seleccionado = int(cid) if cid.isdigit() else None
            self._abrir_dialogo_recibo(ventana, monto_ef, total_val, metodo, cid)

        def completar():
            if getattr(self, "_registrando_venta", False):
                return
            metodo = metodo_var.get()
            imprimir_ticket = bool(imprimir_ticket_var.get())
            texto_btn_prev = btn_confirmar.cget("text")
            try:
                if metodo == "Efectivo":
                    monto_ef = entry_efectivo.get_value()
                    if monto_ef < total_val:
                        messagebox.showwarning(
                            "Efectivo insuficiente",
                            f"El monto recibido (${monto_ef:,.0f}) es menor al total a pagar (${total_val:,.0f}).",
                            parent=ventana,
                        )
                        return
                    self.procesar_venta_completa(
                        recibido=monto_ef,
                        total=total_val,
                        metodo_pago="Efectivo",
                        id_cliente=self.cliente_id_seleccionado,
                        imprimir_recibo=imprimir_ticket,
                        dialogo_pago=ventana,
                        botones_modal=[btn_confirmar, btn_preview, btn_cancelar],
                        boton_principal_modal=btn_confirmar,
                        texto_original_modal=texto_btn_prev,
                    )
                elif metodo == "Transferencia":
                    self.procesar_venta_completa(
                        recibido=total_val,
                        total=total_val,
                        metodo_pago="Transferencia",
                        id_cliente=self.cliente_id_seleccionado,
                        imprimir_recibo=imprimir_ticket,
                        dialogo_pago=ventana,
                        botones_modal=[btn_confirmar, btn_preview, btn_cancelar],
                        boton_principal_modal=btn_confirmar,
                        texto_original_modal=texto_btn_prev,
                    )
                elif metodo == "Fiado":
                    seleccion = combo_clientes.get()
                    if not seleccion:
                        messagebox.showerror("Error", "Debe seleccionar un cliente registrado y autorizado para fiado.", parent=ventana)
                        return
                    cid_str = seleccion.split(" - ")[0].strip()
                    cli_info = clientes_fiado_map.get(cid_str)
                    if not cli_info:
                        messagebox.showerror("Error", f"No se pudo cargar la información central del cliente #{cid_str}.", parent=ventana)
                        return
                    if not cli_info.get("permite_fiado", True):
                        messagebox.showerror("Crédito no habilitado", f"El cliente '{cli_info.get('nombre')}' no tiene habilitado el permiso para comprar fiado.", parent=ventana)
                        return

                    # Validar Límite de Crédito
                    lim = float(cli_info.get("limite_credito") or 0.0)
                    saldo_act = float(cli_info.get("saldo_pendiente") or 0.0)
                    nuevo_saldo = saldo_act + total_val

                    if lim > 0 and (nuevo_saldo > lim) and not self._exceso_credito_autorizado:
                        exceso = nuevo_saldo - lim
                        if not self.autorizar_exceso_credito_admin(
                            parent=ventana,
                            cliente_nombre=cli_info.get("nombre", "Cliente"),
                            lim=lim,
                            saldo=saldo_act,
                            total_val=total_val,
                            exceso=exceso,
                        ):
                            return

                    # Auto-rellenar y vincular el documento e ID oficial del cliente seleccionado
                    doc_oficial = str(cli_info.get("documento") or "").strip()
                    if doc_oficial:
                        self.documento.set(doc_oficial)
                    self.cliente_id_seleccionado = int(cid_str) if cid_str.isdigit() else None

                    self.procesar_venta_completa(
                        recibido=0.0,
                        total=total_val,
                        metodo_pago="Fiado",
                        id_cliente=int(cid_str),
                        imprimir_recibo=imprimir_ticket,
                        nombre_cliente_display=cli_info.get("nombre") or doc_oficial,
                        dialogo_pago=ventana,
                        botones_modal=[btn_confirmar, btn_preview, btn_cancelar],
                        boton_principal_modal=btn_confirmar,
                        texto_original_modal=texto_btn_prev,
                    )
                elif metodo == "Mixto":
                    m_ef = float(entry_mix_efectivo.get_value())
                    m_tr = float(entry_mix_transf.get_value())
                    m_fi = float(entry_mix_fiado.get_value())

                    if m_ef < 0 or m_tr < 0 or m_fi < 0:
                        messagebox.showerror("Error", "Los montos de los métodos no pueden ser negativos.", parent=ventana)
                        return

                    suma_pagos = round(m_ef + m_tr + m_fi, 2)
                    if abs(suma_pagos - total_val) > 0.01:
                        messagebox.showwarning(
                            "Distribución Incompleta",
                            f"La suma de los métodos de pago (${suma_pagos:,.0f} COP) debe ser exactamente igual al total a pagar (${total_val:,.0f} COP).\n\n"
                            f"Diferencia actual: ${abs(total_val - suma_pagos):,.0f} COP.",
                            parent=ventana
                        )
                        return

                    cid_mix = None
                    cli_mix_nom = None
                    if m_fi > 0:
                        seleccion = combo_clientes.get()
                        if not seleccion:
                            messagebox.showerror("Cliente Requerido", "Para la porción fiada debe seleccionar un cliente registrado y autorizado.", parent=ventana)
                            return
                        cid_str = seleccion.split(" - ")[0].strip()
                        cli_info = clientes_fiado_map.get(cid_str)
                        if not cli_info:
                            messagebox.showerror("Error", f"No se pudo cargar la información central del cliente #{cid_str}.", parent=ventana)
                            return
                        if not cli_info.get("permite_fiado", True):
                            messagebox.showerror("Crédito no habilitado", f"El cliente '{cli_info.get('nombre')}' no tiene habilitado el permiso para comprar fiado.", parent=ventana)
                            return

                        lim = float(cli_info.get("limite_credito") or 0.0)
                        saldo_act = float(cli_info.get("saldo_pendiente") or 0.0)
                        nuevo_saldo = saldo_act + m_fi

                        if lim > 0 and (nuevo_saldo > lim) and not self._exceso_credito_autorizado:
                            exceso = nuevo_saldo - lim
                            if not self.autorizar_exceso_credito_admin(
                                parent=ventana,
                                cliente_nombre=cli_info.get("nombre", "Cliente"),
                                lim=lim,
                                saldo=saldo_act,
                                total_val=m_fi,
                                exceso=exceso,
                            ):
                                return

                        doc_oficial = str(cli_info.get("documento") or "").strip()
                        if doc_oficial:
                            self.documento.set(doc_oficial)
                        cid_mix = int(cid_str) if cid_str.isdigit() else None
                        self.cliente_id_seleccionado = cid_mix
                        cli_mix_nom = cli_info.get("nombre") or doc_oficial

                    pagos_list = []
                    if m_ef > 0:
                        pagos_list.append({"metodo": "Efectivo", "monto": m_ef, "recibido": m_ef, "cambio": 0.0})
                    if m_tr > 0:
                        pagos_list.append({"metodo": "Transferencia", "monto": m_tr, "recibido": m_tr, "cambio": 0.0})
                    if m_fi > 0:
                        pagos_list.append({"metodo": "Fiado", "monto": m_fi, "recibido": 0.0, "cambio": 0.0})

                    self.procesar_venta_completa(
                        recibido=m_ef,
                        total=total_val,
                        metodo_pago="Mixto",
                        pagos=pagos_list,
                        id_cliente=cid_mix,
                        imprimir_recibo=imprimir_ticket,
                        nombre_cliente_display=cli_mix_nom,
                        dialogo_pago=ventana,
                        botones_modal=[btn_confirmar, btn_preview, btn_cancelar],
                        boton_principal_modal=btn_confirmar,
                        texto_original_modal=texto_btn_prev,
                    )
            except (tk.TclError, ValueError) as err:
                messagebox.showerror("Error", f"Error en los datos ingresados: {err}", parent=ventana)

        btn_confirmar = crear_boton(footer_p, "Confirmar Venta", command=completar, tipo="success", icono="✅", tam_fuente=11)
        btn_confirmar.pack(side="right", padx=5)

        btn_preview = crear_boton(footer_p, "Vista Previa", command=abrir_preview_recibo, tipo="info", icono="🧾", tam_fuente=10)
        btn_preview.pack(side="right", padx=5)

        def _cerrar_pago():
            if not getattr(self, "_registrando_venta", False):
                self._dialogo_pago_activo = False
                ventana.destroy()
                try:
                    self.entry_codigo.focus_set()
                except Exception:
                    pass

        btn_cancelar = crear_boton(
            footer_p,
            "Cancelar",
            command=_cerrar_pago,
            tipo="secondary",
            icono="❌",
            tam_fuente=10,
        )
        btn_cancelar.pack(side="right", padx=5)

        # 3. CUERPO CENTRAL (Selección de método y campos)
        body_p = tk.Frame(ventana, bg=t_p["bg_app"])
        body_p.pack(side="top", fill="both", expand=True, padx=20, pady=10)

        metodo_var = tk.StringVar(value="Efectivo")

        tk.Label(body_p, text="Seleccione Método de Pago:", font=("Segoe UI", 11, "bold"), bg=t_p["bg_app"], fg=t_p["text_main"]).pack(anchor="w", pady=(0, 5))

        frame_metodos = tk.Frame(body_p, bg=t_p["bg_app"])
        frame_metodos.pack(fill="x", pady=5)

        tk.Radiobutton(frame_metodos, text="💵 Efectivo", variable=metodo_var, value="Efectivo",
                       bg=t_p["bg_app"], fg=t_p["text_main"], selectcolor=t_p["bg_surface_alt"], activebackground=t_p["bg_app"], activeforeground=t_p["text_main"], font=("Segoe UI", 11)).pack(anchor="w", pady=2)
        tk.Radiobutton(frame_metodos, text="💳 Transferencia", variable=metodo_var, value="Transferencia",
                       bg=t_p["bg_app"], fg=t_p["text_main"], selectcolor=t_p["bg_surface_alt"], activebackground=t_p["bg_app"], activeforeground=t_p["text_main"], font=("Segoe UI", 11)).pack(anchor="w", pady=2)
        tk.Radiobutton(frame_metodos, text="📝 Fiado (Crédito)", variable=metodo_var, value="Fiado",
                       bg=t_p["bg_app"], fg=t_p["text_main"], selectcolor=t_p["bg_surface_alt"], activebackground=t_p["bg_app"], activeforeground=t_p["text_main"], font=("Segoe UI", 11)).pack(anchor="w", pady=2)
        tk.Radiobutton(frame_metodos, text="🔀 Pago combinado / Pago mixto", variable=metodo_var, value="Mixto",
                       bg=t_p["bg_app"], fg=t_p["text_main"], selectcolor=t_p["bg_surface_alt"], activebackground=t_p["bg_app"], activeforeground=t_p["text_main"], font=("Segoe UI", 11)).pack(anchor="w", pady=2)

        frame_dinamico = tk.Frame(body_p, bg=t_p["bg_surface"], bd=1, relief="solid", padx=10, pady=10)
        frame_dinamico.pack(fill="both", expand=True, pady=10)

        # Efectivo widgets
        lbl_efectivo = tk.Label(frame_dinamico, text="💵 Efectivo recibido:", font=("Segoe UI", 11, "bold"), bg=t_p["bg_surface"], fg=t_p["text_main"])
        lbl_cambio = tk.Label(frame_dinamico, text="💰 Cambio: $ 0 COP", font=("Segoe UI", 12, "bold"), bg=t_p["bg_surface"], fg="#059669")

        def al_cambiar_efectivo(val_recibido):
            cambio = max(0, val_recibido - total_val)
            lbl_cambio.config(text=f"💰 Cambio: {formatear_cop(cambio)} COP")

        entry_efectivo = CurrencyEntry(
            frame_dinamico,
            initial_value=0,
            show_symbol=True,
            on_change=al_cambiar_efectivo,
            font=("Segoe UI", 13, "bold"),
            width=18,
            bg=t_p["input_bg"],
            fg=t_p["input_fg"],
            insertbackground=t_p["input_insert"],
            relief="solid",
            bd=1
        )
        entry_efectivo.bind("<Return>", lambda e: completar())

        # Fiado widgets & Card de Límites de Crédito
        lbl_fiado = tk.Label(frame_dinamico, text="Cliente Autorizado para Fiado (Servidor Central):", font=("Segoe UI", 10, "bold"), bg=t_p["bg_surface"], fg=t_p["text_main"])
        combo_clientes = ttk.Combobox(frame_dinamico, state="readonly", width=36, font=("Segoe UI", 10))

        card_credito = tk.Frame(frame_dinamico, bg=t_p["bg_card"], bd=1, relief="solid", padx=12, pady=8)
        lbl_cc_cli = tk.Label(card_credito, text="Cliente: —", font=("Segoe UI", 9, "bold"), bg=t_p["bg_card"], fg=t_p["text_main"])
        lbl_cc_cli.pack(anchor="w", pady=1)
        lbl_cc_limites = tk.Label(card_credito, text="Límite: $0 | Saldo actual: $0", font=("Segoe UI", 9), bg=t_p["bg_card"], fg=t_p["text_muted"])
        lbl_cc_limites.pack(anchor="w", pady=1)
        lbl_cc_cupo = tk.Label(card_credito, text="Cupo Disponible: $0", font=("Segoe UI", 10, "bold"), bg=t_p["bg_card"], fg=t_p["btn_success_bg"])
        lbl_cc_cupo.pack(anchor="w", pady=1)
        lbl_cc_alerta = tk.Label(card_credito, text="", font=("Segoe UI", 9, "bold"), bg=t_p["bg_card"], fg=t_p["btn_danger_bg"], wraplength=380, justify="left")
        lbl_cc_alerta.pack(anchor="w", pady=2)

        def al_seleccionar_cliente(event=None):
            sel = combo_clientes.get()
            if not sel:
                return
            cid_str = sel.split(" - ")[0].strip()
            c_info = clientes_fiado_map.get(cid_str)
            if not c_info:
                return

            self._exceso_credito_autorizado = False
            self.cliente_id_seleccionado = int(cid_str) if cid_str.isdigit() else None
            doc = str(c_info.get("documento") or "").strip()
            if doc:
                self.documento.set(doc)

            lim = float(c_info.get("limite_credito") or 0.0)
            saldo = float(c_info.get("saldo_pendiente") or 0.0)
            cupo = max(0.0, lim - saldo) if lim > 0 else float("inf")
            cupo_str = f"${cupo:,.0f} COP" if lim > 0 else "Sin Límite Asignado"

            lbl_cc_cli.config(text=f"👤 {c_info.get('nombre')} | Doc: {doc or '—'} | Tel: {c_info.get('telefono') or '—'}")
            lbl_cc_limites.config(text=f"Límite Total: ${lim:,.0f} COP | Saldo Pendiente: ${saldo:,.0f} COP")
            
            # Monto evaluado para crédito (total venta si es Fiado, o monto_fiado si es Mixto)
            monto_evaluar = total_val
            if metodo_var.get() == "Mixto" and 'entry_mix_fiado' in locals():
                try:
                    monto_evaluar = float(entry_mix_fiado.get_value())
                except Exception:
                    monto_evaluar = total_val

            lbl_cc_cupo.config(
                text=f"Cupo Disponible: {cupo_str}",
                fg=t_p["btn_success_bg"] if (lim == 0 or cupo >= monto_evaluar) else t_p["btn_danger_bg"],
            )

            if lim > 0 and (saldo + monto_evaluar > lim):
                exceso = (saldo + monto_evaluar) - lim
                lbl_cc_alerta.config(text=f"⚠️ VENTA SUPERA EL LÍMITE POR ${exceso:,.0f} COP", fg="#DC2626")
                btn_confirmar.config(text="⚠️ Autorizar y Confirmar")
            else:
                lbl_cc_alerta.config(text="✅ Cupo disponible para procesar la venta", fg="#059669")
                btn_confirmar.config(text="✅ Confirmar Venta")

        combo_clientes.bind("<<ComboboxSelected>>", al_seleccionar_cliente)

        # Widgets de Pago Mixto
        frame_mixto = tk.Frame(frame_dinamico, bg=t_p["bg_surface"])
        
        lbl_mix_info = tk.Label(frame_mixto, text=f"Distribución del Total a Pagar ({self.formato_peso(total_val)}):",
                                font=("Segoe UI", 10, "bold"), bg=t_p["bg_surface"], fg=t_p["text_main"])
        lbl_mix_info.pack(anchor="w", pady=(2, 6))

        f_mix_inputs = tk.Frame(frame_mixto, bg=t_p["bg_surface"])
        f_mix_inputs.pack(fill="x", pady=2)

        def _on_mix_change(val=None):
            try:
                ef = float(entry_mix_efectivo.get_value())
                tr = float(entry_mix_transf.get_value())
                fi = float(entry_mix_fiado.get_value())
                suma = round(ef + tr + fi, 2)
                lbl_mix_sum.config(text=f"Cubierto: ${suma:,.0f} COP de ${total_val:,.0f} COP")

                if abs(suma - total_val) < 0.01:
                    lbl_mix_status.config(text="✅ Total cubierto al 100%", fg="#059669")
                    btn_confirmar.config(text="✅ Confirmar Venta")
                elif suma < total_val:
                    dif = total_val - suma
                    lbl_mix_status.config(text=f"⚠️ Faltan ${dif:,.0f} COP por distribuir", fg="#DC2626")
                else:
                    dif = suma - total_val
                    lbl_mix_status.config(text=f"⚠️ Exceso de ${dif:,.0f} COP", fg="#DC2626")

                if fi > 0:
                    lbl_fiado.pack(in_=frame_mixto, pady=(6, 2))
                    combo_clientes.pack(in_=frame_mixto, pady=(2, 4))
                    card_credito.pack(in_=frame_mixto, fill="x", pady=4)
                    _cargar_clientes_fiado()
                    al_seleccionar_cliente()
                else:
                    lbl_fiado.pack_forget()
                    combo_clientes.pack_forget()
                    card_credito.pack_forget()
            except Exception:
                pass

        # Fila Efectivo
        tk.Label(f_mix_inputs, text="💵 Efectivo:", font=("Segoe UI", 9, "bold"), bg=t_p["bg_surface"], fg=t_p["text_main"]).grid(row=0, column=0, sticky="w", pady=3)
        entry_mix_efectivo = CurrencyEntry(
            f_mix_inputs, initial_value=0, show_symbol=True, on_change=_on_mix_change,
            font=("Segoe UI", 10, "bold"), width=16, bg=t_p["input_bg"], fg=t_p["input_fg"],
            insertbackground=t_p["input_insert"], relief="solid", bd=1
        )
        entry_mix_efectivo.grid(row=0, column=1, sticky="w", padx=(10, 0), pady=3)

        # Fila Transferencia
        tk.Label(f_mix_inputs, text="💳 Transferencia:", font=("Segoe UI", 9, "bold"), bg=t_p["bg_surface"], fg=t_p["text_main"]).grid(row=1, column=0, sticky="w", pady=3)
        entry_mix_transf = CurrencyEntry(
            f_mix_inputs, initial_value=0, show_symbol=True, on_change=_on_mix_change,
            font=("Segoe UI", 10, "bold"), width=16, bg=t_p["input_bg"], fg=t_p["input_fg"],
            insertbackground=t_p["input_insert"], relief="solid", bd=1
        )
        entry_mix_transf.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=3)

        # Fila Fiado
        tk.Label(f_mix_inputs, text="📝 Fiado (Crédito):", font=("Segoe UI", 9, "bold"), bg=t_p["bg_surface"], fg=t_p["text_main"]).grid(row=2, column=0, sticky="w", pady=3)
        entry_mix_fiado = CurrencyEntry(
            f_mix_inputs, initial_value=0, show_symbol=True, on_change=_on_mix_change,
            font=("Segoe UI", 10, "bold"), width=16, bg=t_p["input_bg"], fg=t_p["input_fg"],
            insertbackground=t_p["input_insert"], relief="solid", bd=1
        )
        entry_mix_fiado.grid(row=2, column=1, sticky="w", padx=(10, 0), pady=3)

        lbl_mix_sum = tk.Label(frame_mixto, text=f"Cubierto: $0 COP de ${total_val:,.0f} COP", font=("Segoe UI", 10, "bold"), bg=t_p["bg_surface"], fg=t_p["text_main"])
        lbl_mix_sum.pack(anchor="w", pady=(4, 2))

        lbl_mix_status = tk.Label(frame_mixto, text=f"⚠️ Faltan ${total_val:,.0f} COP por distribuir", font=("Segoe UI", 10, "bold"), bg=t_p["bg_surface"], fg="#DC2626")
        lbl_mix_status.pack(anchor="w", pady=(0, 4))

        def _cargar_clientes_fiado():
            if clientes_fiado_map:
                return
            valores_fiado = []
            doc_previo = self.documento.get().strip()
            idx_preseleccion = 0

            # Consultar Servidor Central (/clientes)
            try:
                resp = api.get("/clientes") if api else None
                if resp and resp.status_code == 200:
                    clientes_api = resp.json()
                    for c in clientes_api:
                        est = str(c.get("estado", "Activo") or "Activo").lower()
                        permite = c.get("permite_fiado") in (True, 1, "1", "true", "True", "t", "T")
                        if est != "inactivo" and permite:
                            cid = str(c.get("id"))
                            doc = str(c.get("documento") or c.get("cedula") or "").strip()
                            nom = str(c.get("nombre") or "").strip()
                            lim = float(c.get("limite_credito") or 0.0)
                            sal = float(c.get("deuda_total") or c.get("saldo_pendiente") or 0.0)
                            tel = str(c.get("telefono") or "").strip()
                            clientes_fiado_map[cid] = {
                                "id": cid,
                                "nombre": nom,
                                "documento": doc,
                                "limite_credito": lim,
                                "saldo_pendiente": sal,
                                "telefono": tel,
                                "permite_fiado": permite,
                            }
                            etiqueta = f"{cid} - {nom} ({doc or 'Sin Doc'})"
                            if (doc_previo and doc == doc_previo) or (
                                self.cliente_id_seleccionado and str(self.cliente_id_seleccionado) == cid
                            ):
                                idx_preseleccion = len(valores_fiado)
                            valores_fiado.append(etiqueta)
            except Exception as e_api:
                print(f"Error consultando clientes Fiado en servidor central: {e_api}")

            if not valores_fiado:
                try:
                    from interface.database_manager import conectar_db
                    c_loc = conectar_db()
                    cur_loc = c_loc.cursor()
                    cur_loc.execute("SELECT id, cedula, nombre, limite_credito, saldo_pendiente, telefono FROM clientes WHERE permite_fiado = 1 AND estado != 'Inactivo'")
                    for r in cur_loc.fetchall():
                        cid = str(r[0])
                        doc = str(r[1] or "")
                        nom = str(r[2] or "")
                        lim = float(r[3] or 0.0)
                        sal = float(r[4] or 0.0)
                        tel = str(r[5] or "")
                        clientes_fiado_map[cid] = {"id": cid, "nombre": nom, "documento": doc, "limite_credito": lim, "saldo_pendiente": sal, "telefono": tel, "permite_fiado": True}
                        valores_fiado.append(f"{cid} - {nom} ({doc or 'Sin Doc'})")
                    c_loc.close()
                except Exception:
                    pass

            combo_clientes["values"] = valores_fiado
            if valores_fiado:
                combo_clientes.current(idx_preseleccion)
                al_seleccionar_cliente()
            else:
                lbl_cc_cli.config(text="No hay clientes habilitados para fiado.")
                lbl_cc_limites.config(text="Cree o autorice clientes con crédito en el módulo Clientes y Fiado.")
                lbl_cc_cupo.config(text="")
                lbl_cc_alerta.config(text="")

        def actualizar_vista(*args):
            if getattr(self, "_registrando_venta", False):
                return
            for w in frame_dinamico.winfo_children():
                w.pack_forget()

            metodo = metodo_var.get()
            btn_confirmar.config(text="✅ Confirmar Venta")
            if metodo == "Efectivo":
                lbl_efectivo.pack(pady=(4, 2))
                entry_efectivo.pack(pady=4)
                lbl_cambio.pack(pady=(4, 2))
                entry_efectivo.focus()
            elif metodo == "Fiado":
                lbl_fiado.pack(in_=frame_dinamico, pady=(4, 2))
                combo_clientes.pack(in_=frame_dinamico, pady=(2, 6))
                card_credito.pack(in_=frame_dinamico, fill="x", pady=6)
                _cargar_clientes_fiado()
                al_seleccionar_cliente()
            elif metodo == "Transferencia":
                tk.Label(
                    frame_dinamico,
                    text="📱 Pago inmediato por Transferencia\n(Nequi, Daviplata, Bancolombia)",
                    font=("Segoe UI", 10, "italic"),
                    bg="#FFE4E1",
                    fg="#2D3436",
                ).pack(pady=15)
            elif metodo == "Mixto":
                frame_mixto.pack(fill="both", expand=True)
                entry_mix_efectivo.set_value(total_val)
                entry_mix_transf.set_value(0)
                entry_mix_fiado.set_value(0)
                _on_mix_change()

        metodo_var.trace_add("write", actualizar_vista)
        actualizar_vista()
        ventana.bind("<Escape>", lambda e: _cerrar_pago())
        ventana.protocol("WM_DELETE_WINDOW", _cerrar_pago)

    def autorizar_exceso_credito_admin(self, parent, cliente_nombre, lim, saldo, total_val, exceso) -> bool:
        """
        Permite validar excepciones de crédito cuando una venta fiada supera el cupo asignado
        autenticando contra el Servidor Central (`/auth/login`) sin sobrescribir la sesión activa.
        """
        es_admin_actual = getattr(self, "es_admin", False) or (getattr(self, "rol", "") or "").lower() in ("administrador", "admin", "gerente")
        if es_admin_actual:
            autorizado = messagebox.askyesno(
                "⚠️ Límite de Crédito Excedido — Autorización Administrador",
                f"El cliente '{cliente_nombre}' ha excedido su límite de crédito:\n\n"
                f"• Límite total asignado: ${lim:,.0f} COP\n"
                f"• Saldo pendiente actual: ${saldo:,.0f} COP\n"
                f"• Valor de esta venta: ${total_val:,.0f} COP\n"
                f"• Nuevo saldo proyectado: ${saldo + total_val:,.0f} COP\n"
                f"• Exceso sobre el límite: ${exceso:,.0f} COP\n\n"
                f"Como Administrador del sistema, ¿desea autorizar excepcionalmente esta venta a crédito?",
                parent=parent,
            )
            if autorizado:
                self._exceso_credito_autorizado = True
            return bool(autorizado)

        from tkinter import simpledialog
        usuario_adm = simpledialog.askstring(
            "Autorización Administrador Requerida",
            f"⚠️ La venta supera el cupo de crédito por ${exceso:,.0f} COP.\n\n"
            f"Ingrese el usuario Administrador del servidor central:",
            initialvalue="admin",
            parent=parent,
        )
        if not usuario_adm:
            return False
        pwd = simpledialog.askstring(
            "Autorización Administrador Requerida",
            f"Ingrese la contraseña del Administrador '{usuario_adm.strip()}':",
            show="*",
            parent=parent,
        )
        if not pwd:
            return False
        try:
            resp_auth = httpx.post(
                f"{api.base_url}/auth/login",
                data={"username": usuario_adm.strip(), "password": pwd},
                timeout=6.0,
            )
            if resp_auth.status_code == 200:
                datos_auth = resp_auth.json()
                rol_auth = str((datos_auth.get("usuario") or {}).get("rol") or "").strip().lower()
                if rol_auth in ("administrador", "admin", "gerente"):
                    self._exceso_credito_autorizado = True
                    messagebox.showinfo("Autorizado", "Excepción de crédito autorizada en el servidor central.", parent=parent)
                    return True
                messagebox.showerror("Autorización Denegada", "El usuario ingresado no posee rol de Administrador.", parent=parent)
                return False
        except Exception as e:
            messagebox.showerror("Error de Red", f"No se pudo verificar credenciales con el servidor central:\n{e}", parent=parent)
            return False
        messagebox.showerror("Autorización Denegada", "Credenciales de Administrador incorrectas.", parent=parent)
        return False

    def _abrir_dialogo_recibo(self, parent, recibido, total, metodo_pago, id_cliente):
        """Confirma impresión y muestra el comprobante completo (con logo, 58mm/80mm/A4 y PDF) antes del registro."""
        try:
            from receipt_manager import mostrar_dialogo_factura
        except ImportError:
            from interface.receipt_manager import mostrar_dialogo_factura

        business_mgr.recargar()
        items_preview = []
        for item_id in self.tabla.get_children():
            codigo = self.tabla.item(item_id, "text")
            valores = self.tabla.item(item_id, "values")
            precio_u = self.limpiar_precio(valores[1])
            cant = int(float(valores[2]))
            items_preview.append({
                "codigo": str(codigo),
                "nombre": str(valores[0]),
                "cantidad": cant,
                "unidad": "Und",
                "precio_unitario": precio_u,
                "descuento": 0.0,
                "subtotal": precio_u * cant,
            })

        cliente_txt = self.documento.get().strip() or "Consumidor Final"
        vendedor_txt = self.user_nombre or self.rol or "Usuario"
        es_fiado = str(metodo_pago).lower() in ("fiado", "crédito", "credito")

        datos_preview = {
            "factura": self.factura_num,
            "fecha": datetime.now().strftime("%Y-%m-%d"),
            "hora": datetime.now().strftime("%H:%M:%S"),
            "cliente": cliente_txt,
            "vendedor": vendedor_txt,
            "items": items_preview,
            "total": float(total),
            "metodo_pago": metodo_pago,
            "recibido": float(recibido),
            "cambio": max(0.0, float(recibido) - float(total)) if not es_fiado else 0.0,
            "saldo_pendiente": float(total) if es_fiado else 0.0,
            "snapshot_negocio": business_mgr.obtener_snapshot_factura(),
        }

        def al_confirmar(imprimir=False, formato_seleccionado=None, dialog_ref=None, on_error_restore=None):
            self.procesar_venta_completa(
                recibido,
                total,
                metodo_pago,
                id_cliente=id_cliente,
                imprimir_recibo=imprimir,
                formato_impresion=formato_seleccionado,
                dialogo_pago=parent,
                dialogo_recibo=dialog_ref,
                on_error_restore=on_error_restore,
            )

        mostrar_dialogo_factura(
            parent,
            datos_preview,
            modo_confirmacion_venta=True,
            on_confirmar_venta=al_confirmar,
        )

    def _mostrar_vista_previa_recibo(self, parent):
        """Compatibilidad para llamadas antiguas al botón de vista previa."""
        self._abrir_dialogo_recibo(parent, self.total_general.get(), self.total_general.get(), "Efectivo", None)

    def procesar_venta_completa(
        self,
        recibido,
        total,
        metodo_pago="Efectivo",
        id_cliente=None,
        imprimir_recibo=False,
        formato_impresion=None,
        nombre_cliente_display=None,
        dialogo_pago=None,
        dialogo_recibo=None,
        botones_modal=None,
        boton_principal_modal=None,
        texto_original_modal="Confirmar Venta",
        on_error_restore=None,
        ejecutar_sincrono=False,
        pagos=None,
    ):
        """
        Procesa la venta exclusivamente contra la API Central de forma asíncrona, no bloqueante e idempotente.
        - Deshabilita inmediatamente el botón y muestra 'Registrando venta...'
        - Impide dobles clics y envíos duplicados mediante bloqueo en memoria + `idempotency_key` único
        - Recupera automáticamente la venta mediante `/ventas/por-idempotencia/{key}` ante micro-cortes de red
        - Nunca registra copias paralelas ni falsos positivos en SQLite local
        """
        if getattr(self, "_registrando_venta", False):
            return None
        if not self.verificar_caja_abierta("registrar o procesar la venta"):
            if callable(on_error_restore):
                on_error_restore()
            return None

        parent_err = (
            dialogo_recibo
            if (dialogo_recibo is not None and getattr(dialogo_recibo, "winfo_exists", lambda: False)())
            else (
                dialogo_pago
                if (dialogo_pago is not None and getattr(dialogo_pago, "winfo_exists", lambda: False)())
                else self.ventana
            )
        )

        try:
            business_mgr.recargar()
            snapshot_actual = business_mgr.obtener_snapshot_factura()
            detalles_payload = []

            for i in self.tabla.get_children():
                codigo = self.tabla.item(i, "text")
                valores = self.tabla.item(i, "values")
                nombre = valores[0]
                precio_limpio = self.limpiar_precio(valores[1])
                c_raw = float(valores[2])
                cantidad = int(c_raw) if c_raw.is_integer() else round(c_raw, 3)
                subtotal = round(precio_limpio * cantidad, 2)

                tipo_item = "Producto"
                item_id = None
                costo = 0.0
                precio_catalogo = precio_limpio
                prov_id = None

                for p in self.productos_inventario:
                    cod_p = str(p[0]).strip()
                    cod_c = str(codigo).strip()
                    nom_p = str(p[1]).strip().lower()
                    nom_c = str(nombre).strip().lower()
                    if cod_p.lower() == cod_c.lower() or cod_p.zfill(5) == cod_c.zfill(5) or (nom_p and nom_p == nom_c):
                        tipo_item = "Servicio" if p[4] == "Servicio" else "Producto"
                        item_id = p[6]
                        costo = p[7]
                        precio_catalogo = float(p[3]) if p[3] is not None else precio_limpio
                        prov_id = p[5]
                        if tipo_item == "Servicio" and prov_id and (costo is None or float(costo or 0) <= 0):
                            costo = precio_limpio
                        break

                if not prov_id:
                    try:
                        from interface.database_manager import conectar_db
                        conn_chk = conectar_db()
                        c_chk = conn_chk.cursor()
                        c_chk.execute("SELECT proveedor_id, costo FROM productos WHERE codigo = ? OR LOWER(nombre) = LOWER(?)", (str(codigo), str(nombre)))
                        r_chk = c_chk.fetchone()
                        if r_chk and r_chk[0]:
                            prov_id = int(r_chk[0])
                            if costo is None or float(costo or 0) <= 0:
                                costo = float(r_chk[1] or 0.0)
                        conn_chk.close()
                    except Exception:
                        pass

                if not item_id and not getattr(self, "orden_id_activa", None):
                    if callable(on_error_restore):
                        on_error_restore()
                    messagebox.showerror(
                        "Error",
                        f"No se pudo identificar en el catálogo central el producto o servicio con código '{codigo}'.",
                        parent=parent_err,
                    )
                    return None

                detalles_payload.append({
                    "tipo_item": tipo_item,
                    "item_id": item_id,
                    "item_codigo": str(codigo),
                    "item_nombre": nombre,
                    "precio_original": precio_catalogo,
                    "precio_vendido": precio_limpio,
                    "cantidad": cantidad,
                    "descuento": 0.0,
                    "subtotal": subtotal,
                    "costo_unitario": costo,
                    "proveedor_id": prov_id,
                })

            if not detalles_payload and not getattr(self, "orden_id_activa", None):
                if callable(on_error_restore):
                    on_error_restore()
                messagebox.showwarning("Carrito Vacío", "Agregue al menos un artículo antes de registrar la venta.", parent=parent_err)
                return None

            doc_cli = self.documento.get().strip()
            # NUNCA convertir la cédula/documento en `cliente_id`: usar únicamente el ID real de la tabla `clientes`
            cliente_id_val = None
            if id_cliente is not None and str(id_cliente).strip().isdigit():
                cliente_id_val = int(str(id_cliente).strip())
            elif getattr(self, "cliente_id_seleccionado", None) and str(self.cliente_id_seleccionado).strip().isdigit():
                cliente_id_val = int(str(self.cliente_id_seleccionado).strip())

            if str(metodo_pago) == "Fiado" and not cliente_id_val and (not doc_cli or doc_cli == "Consumidor Final"):
                if callable(on_error_restore):
                    on_error_restore()
                messagebox.showerror(
                    "Cliente Requerido",
                    "Para registrar una venta FIADA debe seleccionar un cliente válido del servidor central.",
                    parent=parent_err,
                )
                return None

            recibido_payload = 0.0 if str(metodo_pago) == "Fiado" else float(recibido)
            cambio_payload = 0.0 if str(metodo_pago) == "Fiado" else max(0.0, float(recibido) - float(total))
            orden_id_actual = getattr(self, "orden_id_activa", None)
            autorizado_exceso = bool(getattr(self, "_exceso_credito_autorizado", False))
            operario_nombre = getattr(self, "user_nombre", None) or getattr(self, "rol", None) or "Administrador"

            fingerprint = self._calcular_fingerprint_carrito(metodo_pago, total, cliente_id_val, doc_cli)
            idem_key = self._obtener_idempotency_key_venta(fingerprint)

            # Bloqueo inmediato de interfaz y feedback visual 'Registrando venta...'
            self._registrando_venta = True
            try:
                if hasattr(self, "btn_accion_principal") and self.btn_accion_principal and self.btn_accion_principal.winfo_exists():
                    self.btn_accion_principal.config(state="disabled", text="⏳ Registrando venta...")
                for b in botones_modal or []:
                    if b is not None and b.winfo_exists():
                        b.config(state="disabled")
                if boton_principal_modal is not None and boton_principal_modal.winfo_exists():
                    boton_principal_modal.config(state="disabled", text="⏳ Registrando venta...")
                self.ventana.update_idletasks()
            except Exception:
                pass

            def _restaurar_ui_error():
                self._registrando_venta = False
                self._restaurar_boton_principal_pos()
                try:
                    for b in botones_modal or []:
                        if b is not None and b.winfo_exists():
                            b.config(state="normal")
                    if boton_principal_modal is not None and boton_principal_modal.winfo_exists():
                        boton_principal_modal.config(state="normal", text=texto_original_modal)
                except Exception:
                    pass
                if callable(on_error_restore):
                    try:
                        on_error_restore()
                    except Exception:
                        pass

            def _ejecutar_peticion_http():
                term_id = api.sincronizar_terminal_id() or api.terminal_id or 1
                pagos_a_enviar = pagos if (pagos and len(pagos) > 0) else [
                    {
                        "metodo": metodo_pago,
                        "monto": total,
                        "recibido": recibido_payload,
                        "cambio": cambio_payload,
                    }
                ]
                if orden_id_actual:
                    cobro_payload = {
                        "idempotency_key": idem_key,
                        "pagos": pagos_a_enviar,
                        "cliente_id": cliente_id_val,
                        "cliente_documento": doc_cli if doc_cli else None,
                        "autorizado_exceso_credito": autorizado_exceso,
                        "snapshot_negocio": snapshot_actual,
                    }
                    resp_http = api.post(f"/ventas/{orden_id_actual}/autorizar-pago", json=cobro_payload, timeout=12.0)
                else:
                    payload = {
                        "idempotency_key": idem_key,
                        "cliente_id": cliente_id_val,
                        "cliente_documento": doc_cli if doc_cli else None,
                        "terminal_id": term_id,
                        "subtotal": total,
                        "descuento": 0.0,
                        "total": total,
                        "pagos": pagos_a_enviar,
                        "detalles": detalles_payload,
                        "autorizado_exceso_credito": autorizado_exceso,
                        "snapshot_negocio": snapshot_actual,
                    }
                    resp_http = api.post("/ventas", json=payload, timeout=12.0)

                # Recuperación segura ante desconexión o timeout después de haber enviado la solicitud
                if getattr(resp_http, "is_network_error", False):
                    time.sleep(0.8)
                    if api.esta_disponible(forzar=True):
                        resp_verif = api.get(f"/ventas/por-idempotencia/{idem_key}", timeout=6.0)
                        if resp_verif.status_code == 200:
                            return resp_verif
                return resp_http

            def _finalizar_en_ui(resp, exc_bg=None):
                if exc_bg is not None:
                    _restaurar_ui_error()
                    messagebox.showerror(
                        "Error al registrar la venta",
                        f"Ocurrió un fallo de comunicación con el servidor central:\n\n{exc_bg}\n\n"
                        f"Puede presionar nuevamente 'Confirmar Venta' de forma segura (protección anti-duplicado activa).",
                        parent=parent_err,
                    )
                    return None

                if resp is not None and resp.status_code in (200, 201):
                    venta_respuesta = resp.json()
                    id_central = venta_respuesta.get("id")
                    numero_factura = venta_respuesta.get("numero") or self.factura_num
                    doc_final = venta_respuesta.get("cliente_documento") or doc_cli or "Consumidor Final"
                    cli_nombre_final = (
                        venta_respuesta.get("cliente_nombre")
                        or nombre_cliente_display
                        or doc_final
                    )

                    # Cerrar modales de confirmación/pago primero
                    for dlg_w in (dialogo_recibo, dialogo_pago):
                        if dlg_w is not None:
                            try:
                                if dlg_w.winfo_exists():
                                    dlg_w.destroy()
                            except Exception:
                                pass

                    self._dialogo_pago_activo = False
                    self._registrando_venta = False
                    self._venta_idempotency_key = None
                    self._venta_fingerprint = None
                    self._exceso_credito_autorizado = False
                    self.cliente_id_seleccionado = None
                    self._restaurar_boton_principal_pos()

                    if orden_id_actual:
                        self.cancelar_orden_activa()
                    else:
                        self.limpiar_formulario()

                    # Persistencia local en SQLite para Registro de Ventas, auditoría permanente y modo offline
                    try:
                        guardar_venta_sqlite(
                            doc_cliente=doc_final,
                            total=total,
                            metodo_pago=metodo_pago,
                            detalles=detalles_payload,
                            operario_nombre=operario_nombre,
                            cliente_id=cliente_id_val,
                            recibido=recibido_payload,
                            cambio=cambio_payload,
                            numero_factura=numero_factura,
                            snapshot_negocio=snapshot_actual,
                            pagos=pagos
                        )
                    except Exception as e_sq:
                        print(f"Aviso en persistencia local SQLite de venta #{id_central}: {e_sq}")

                    # Actualizar catálogo, existencias, caja e indicadores desde el servidor central
                    self.productos_inventario = self.obtener_productos()
                    self.actualizar_catalogo_live()
                    self.actualizar_estado_caja()
                    self.actualizar_indicadores_empleado_pos()
                    if self.es_admin:
                        self.actualizar_ventas_operarios()

                    msg_asistencia = self.confirmar_asistencia_y_recaudo_vendedor(
                        operario_nombre,
                        total,
                        detalles_payload,
                        id_venta=id_central,
                        metodo_pago=metodo_pago,
                    )

                    datos_venta = {
                        "id_venta": id_central,
                        "factura": numero_factura,
                        "fecha": venta_respuesta.get("fecha") or datetime.now().strftime("%Y-%m-%d"),
                        "hora": venta_respuesta.get("hora") or datetime.now().strftime("%H:%M:%S"),
                        "cliente": cli_nombre_final,
                        "cliente_documento": doc_final if doc_final != "Consumidor Final" else "",
                        "productos": [(d["item_nombre"], d["precio_vendido"], d["cantidad"]) for d in detalles_payload],
                        "items": detalles_payload,
                        "total": total,
                        "metodo_pago": metodo_pago,
                        "recibido": recibido_payload,
                        "cambio": cambio_payload,
                        "saldo_pendiente": float(total) if str(metodo_pago) == "Fiado" else 0.0,
                        "vendedor": operario_nombre,
                        "snapshot_negocio": snapshot_actual,
                    }

                    if self.printer_manager:
                        self.printer_manager.ultima_factura = datos_venta

                    aviso_impresion = ""
                    if imprimir_recibo:
                        cfg_over = {"formato_papel": formato_impresion} if formato_impresion else None
                        try:
                            if self.printer_manager:
                                imp_ok = self.printer_manager.imprimir_factura(datos_venta, config_override=cfg_over)
                                if imp_ok and self.impresora_conectada:
                                    self.printer_manager.abrir_caja_registradora()
                                elif not imp_ok:
                                    aviso_impresion = "\n\n⚠️ Nota: No se detectó impresora física activa; puedes reimprimir o exportar PDF en Historial."
                            else:
                                try:
                                    from receipt_manager import imprimir_factura_unificada
                                except ImportError:
                                    from interface.receipt_manager import imprimir_factura_unificada
                                imp_ok, _ = imprimir_factura_unificada(datos_venta, config_override=cfg_over)
                                if not imp_ok:
                                    aviso_impresion = "\n\n⚠️ Nota: No se detectó impresora física activa; puedes reimprimir o exportar PDF en Historial."
                        except Exception as e_imp:
                            print(f"Aviso en impresión de comprobante: {e_imp}")

                    if not imprimir_recibo and metodo_pago == "Efectivo":
                        try:
                            try:
                                from interface.receipt_manager import pulsar_apertura_cajon
                            except ImportError:
                                from receipt_manager import pulsar_apertura_cajon
                            pulsar_apertura_cajon()
                        except Exception:
                            pass

                    extra_info = f"\n\n{msg_asistencia}" if msg_asistencia else ""
                    extra_info += aviso_impresion

                    if str(metodo_pago) == "Fiado":
                        messagebox.showinfo(
                            "✅ Venta Registrada",
                            f"Venta registrada correctamente. La deuda fue asociada al cliente.\n\n"
                            f"🧾 Número de venta: {numero_factura} (ID #{id_central})\n"
                            f"👤 Cliente: {cli_nombre_final} ({doc_final})\n"
                            f"💸 Saldo pendiente asociado: {self.formato_peso(total)}"
                            f"{extra_info}",
                            parent=self.ventana,
                        )
                    elif str(metodo_pago) == "Efectivo":
                        messagebox.showinfo(
                            "✅ Venta Registrada",
                            f"Venta registrada correctamente.\n\n"
                            f"🧾 Número de venta: {numero_factura} (ID #{id_central})\n"
                            f"💳 Método de pago: Efectivo\n"
                            f"💸 Total: {self.formato_peso(total)}\n"
                            f"💵 Recibido: {self.formato_peso(recibido_payload)}\n"
                            f"💰 Cambio: {self.formato_peso(cambio_payload)}"
                            f"{extra_info}",
                            parent=self.ventana,
                        )
                    else:
                        messagebox.showinfo(
                            "✅ Venta Registrada",
                            f"Venta registrada correctamente.\n\n"
                            f"🧾 Número de venta: {numero_factura} (ID #{id_central})\n"
                            f"💳 Método de pago: {metodo_pago}\n"
                            f"💸 Total: {self.formato_peso(total)}"
                            f"{extra_info}",
                            parent=self.ventana,
                        )
                    return venta_respuesta

                # Caso de error real del servidor o pérdida de red
                _restaurar_ui_error()
                try:
                    error_msg = resp.json().get("detail", "Error desconocido") if resp is not None else "Sin conexión con el servidor"
                except Exception:
                    error_msg = resp.text if resp is not None else "Sin conexión con el servidor"
                messagebox.showerror(
                    "Error al registrar la venta",
                    f"No se pudo registrar la venta en el Servidor Central ({api.base_url}):\n\n"
                    f"• Motivo: {error_msg}\n\n"
                    f"La venta NO fue duplicada ni guardada localmente. Puede verificar los datos o reintentar de forma segura.",
                    parent=parent_err,
                )
                return None

            if ejecutar_sincrono:
                try:
                    r_sync = _ejecutar_peticion_http()
                    return _finalizar_en_ui(r_sync, None)
                except Exception as exc_s:
                    return _finalizar_en_ui(None, exc_s)

            def _worker():
                try:
                    r_bg = _ejecutar_peticion_http()
                    self.ventana.after(0, lambda: _finalizar_en_ui(r_bg, None))
                except Exception as exc_b:
                    self.ventana.after(0, lambda: _finalizar_en_ui(None, exc_b))

            threading.Thread(target=_worker, daemon=True).start()
            return None
        except Exception as e:
            self._registrando_venta = False
            self._restaurar_boton_principal_pos()
            if callable(on_error_restore):
                on_error_restore()
            messagebox.showerror("Error", f"Error preparando la venta: {e}", parent=parent_err)
            return None

    def confirmar_asistencia_y_recaudo_vendedor(self, operario_nombre, total_venta, detalles_payload, id_venta=None, metodo_pago="Efectivo"):
        """
        Confirma la asistencia del vendedor al procesar una venta y verifica los devengos
        procesados por nomina_manager (sin duplicar si ya fueron generados en guardar_venta_sqlite).
        """
        hoy_str = datetime.now().strftime("%Y-%m-%d")
        resultado_msg = None
        
        try:
            try:
                from interface.nomina_manager import procesar_venta_nomina_y_comisiones
            except ImportError:
                from nomina_manager import procesar_venta_nomina_y_comisiones

            uid = int(self.user_id) if getattr(self, 'user_id', None) and str(self.user_id).isdigit() else None
            # procesar_venta_nomina_y_comisiones es idempotente gracias a codigo_unico (SAL- y COM-)
            if id_venta:
                res_nom = procesar_venta_nomina_y_comisiones(
                    id_venta=id_venta,
                    operario_nombre=operario_nombre,
                    usuario_id=uid,
                    total_venta=total_venta,
                    metodo_pago=metodo_pago,
                    detalles_venta=detalles_payload,
                    fecha_venta=hoy_str
                )
            else:
                res_nom = {}

            uid_res = res_nom.get("usuario_id") or uid
            if uid_res:
                try:
                    api.post("/nomina/asistencia", json={"usuario_id": uid_res, "fecha": hoy_str, "estado": "Presente"})
                except Exception as e_api:
                    print("DEBUG: Sincronización API asistencia diferida:", e_api)

            partes_msg = []
            if res_nom.get("asistencia_confirmada") or res_nom.get("salario_generado", 0) > 0:
                sal_m = float(res_nom.get("salario_generado", 0.0))
                if sal_m > 0:
                    partes_msg.append(f"📅 ¡Asistencia confirmada! Salario diario generado: {self.formato_peso(sal_m)}")
                else:
                    partes_msg.append(f"📅 ¡Asistencia de hoy CONFIRMADA con esta venta!")
            if float(res_nom.get("comision_generada", 0.0)) > 0:
                com_m = float(res_nom.get("comision_generada", 0.0))
                partes_msg.append(f"💰 Comisión generada: {self.formato_peso(com_m)}")

            if partes_msg:
                resultado_msg = "\n".join(partes_msg)
        except Exception as e:
            print("Aviso al confirmar asistencia por venta:", e)
            
        return resultado_msg

    def limpiar_formulario(self):
        """Limpia el formulario para una nueva venta"""
        if getattr(self, "_registrando_venta", False):
            return
        self.documento.set("")
        self.codigo_entrada.set("")
        self.total_general.set(0.0)
        self.factura_num = datetime.now().strftime("%Y%m%d%H%M%S")
        self.orden_id_activa = None
        self.orden_numero_activa = None
        self.cliente_id_seleccionado = None
        self._exceso_credito_autorizado = False
        self._venta_idempotency_key = None
        self._venta_fingerprint = None
        if hasattr(self, 'banner_frame'):
            self.banner_frame.pack_forget()
        for item in self.tabla.get_children():
            self.tabla.delete(item)
        self.actualizar_total()
        self.lbl_factura.config(text=f"🧾 Factura: {self.factura_num}")
        if hasattr(self, 'var_turno_especial'):
            self.var_turno_especial.set(False)
        self.actualizar_estado_caja()
        self.actualizar_indicadores_empleado_pos()
        try:
            self.entry_codigo.focus_set()
        except Exception:
            pass

def iniciar_ventas(parent=None, user_id="", rol="", parent_pid="", usuario_nombre=""):
    """
    Punto de entrada in-process para el módulo de ventas de VmPOS.
    Permite abrir la ventana como Toplevel (sin relanzar login ni abrir subprocesos pesados)
    o como Tk independiente.
    """
    if parent:
        ventana = tk.Toplevel(parent)
    else:
        ventana = tk.Tk()

    app = App(ventana, user_id=user_id, rol=rol, parent_pid=parent_pid, usuario_nombre=usuario_nombre)

    def _al_cerrar():
        try:
            ventana.destroy()
        except Exception:
            pass

    ventana.protocol("WM_DELETE_WINDOW", _al_cerrar)

    if not parent:
        ventana.mainloop()
    return app

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Módulo de Ventas VmPOS")
    parser.add_argument("--user_id", default="")
    parser.add_argument("--rol", default="")
    parser.add_argument("--parent_pid", default="")
    parser.add_argument("--usuario", default="")
    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)
    args, _ = parser.parse_known_args()

    iniciar_ventas(user_id=args.user_id, rol=args.rol, parent_pid=args.parent_pid, usuario_nombre=args.usuario)