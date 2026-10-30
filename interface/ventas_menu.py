# ====================================================================================
#   SISTEMA DE VENTAS - VARIEDADES MARCE - VERSIÓN MEJORADA Y CORREGIDA
# ====================================================================================

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import os
import threading
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from client.api_client import api

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
except ImportError:
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
    snapshot_negocio=None
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
            print("ERROR: Intento de guardar venta en SQLite con caja cerrada.")
            conn.close()
            return None
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

        saldo_pend_venta = float(total) if str(metodo_pago) == "Fiado" else 0.0

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
            cant = int(d.get("cantidad", 1))
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
            d_copy["costo_unitario"] = costo_unit
            detalles_enriquecidos.append(d_copy)

            # Si el ítem es un Servicio asociado a un proveedor habitual, registrar la Cuenta por Pagar
            if tipo_prod == "Servicio":
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
            if str(metodo_pago) == "Efectivo":
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
    def __init__(self, ventana, user_id="", rol="", parent_pid=""):
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
        self.user_nombre = ""
        
        # Obtener información del usuario desde la API si no vino completa
        try:
            me = api.get("/auth/me")
            if me.status_code == 200:
                me_data = me.json()
                self.user_id = self.user_id or str(me_data.get("id", ""))
                self.rol = self.rol or me_data.get("rol", "")
                self.user_nombre = f"{me_data.get('nombre', '')} {me_data.get('apellidos', '')}".strip() or me_data.get("usuario", "")
        except Exception as e:
            print("DEBUG: Error obteniendo perfil:", e)

        # Fallback local a usuarios.db si estamos offline o falta información
        if not self.user_nombre or not self.rol:
            try:
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
        self.busqueda_catalogo.trace_add("write", lambda *args: self.actualizar_catalogo_live())

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

    def configurar_eventos(self):
        """Configurar eventos de teclado y focus"""
        self.entry_codigo.bind('<Return>', lambda e: self.escanear_codigo())
        self.entry_codigo.bind('<KeyRelease>', self.on_codigo_change)
        self.entry_doc.focus()
        self.actualizar_hora()
        self.ventana.bind('<FocusIn>', lambda e: (self.actualizar_estado_caja(), self.actualizar_indicadores_empleado_pos()))
        self.actualizar_estado_caja()
        self.actualizar_indicadores_empleado_pos()

        # Atajos de teclado globales
        comando_f12 = self.pagar if self.puede_procesar_venta else self.mandar_a_caja
        self.ventana.bind('<F12>', lambda e: comando_f12())
        self.ventana.bind('<F5>', lambda e: self.limpiar_formulario())

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


    def on_codigo_change(self, event):
        """Detecta cuando se escanea un código de barras completo - MEJORADO"""
        codigo = self.codigo_entrada.get().strip()
        
        # Si se presiona Enter, procesar inmediatamente
        if event.keysym == 'Return' and len(codigo) >= 1:
            self.escanear_codigo()
            return
        
        # Auto-escanear si se detecta un código largo (típico de scanners)
        if len(codigo) >= 8:
            # Cancelar cualquier timer anterior
            if hasattr(self, '_scan_timer'):
                self.ventana.after_cancel(self._scan_timer)
            
            # Programar escaneo automático con delay mínimo
            self._scan_timer = self.ventana.after(50, self.escanear_codigo)

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

            # Filtro por tipo
            if tipo_filtro_clean != "Todos" and t_prod != tipo_filtro_clean:
                continue

            # Filtro por texto de búsqueda
            if busq and (busq not in str(cod).lower() and busq not in str(nom).lower()):
                continue

            precio_str = "Variable" if (t_prod == "Servicio" and es_var) else self.formato_peso(precio)
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
            if tipo_prod == "Servicio" and es_var:
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

    def mandar_a_caja(self):
        """Envía la venta actual a Caja en estado Pendiente_Caja para autorización y cobro del Administrador"""
        if not self.verificar_caja_abierta("enviar pedidos a caja"):
            return
        if len(self.tabla.get_children()) == 0:
            messagebox.showwarning("Carrito Vacío", "Agregue al menos un producto o servicio antes de mandar a caja.", parent=self.ventana)
            return

        total = self.total_general.get()
        if total <= 0:
            messagebox.showwarning("Total Inválido", "El total de la venta debe ser mayor a cero.", parent=self.ventana)
            return

        confirma = messagebox.askyesno("Confirmar Envío a Caja", 
                                      f"¿Desea enviar esta orden por {self.formato_peso(total)} a Caja?\n\nEl Administrador la cobrará.", 
                                      parent=self.ventana)
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
                    "costo_unitario": costo
                })

            doc_val = self.documento.get().strip()
            cliente_id_val = int(doc_val) if doc_val and doc_val.isdigit() else None
            es_esp = getattr(self, "var_turno_especial", None) and self.var_turno_especial.get()
            motivo_esp = getattr(self, "var_motivo_especial", None) and self.var_motivo_especial.get() or "Cliente solicita específicamente al operario"

            payload = {
                "cliente_id": cliente_id_val,
                "cliente_documento": doc_val if doc_val else None,
                "terminal_id": 1,
                "subtotal": total,
                "descuento": 0.0,
                "total": total,
                "estado": "Pendiente_Caja",
                "pagos": [],
                "detalles": detalles_payload,
                "es_turno_especial": bool(es_esp),
                "motivo_especial": motivo_esp if es_esp else None
            }

            print(f"DEBUG: Enviando orden a caja -> Total: {total}, Doc: {doc_val}, Items: {len(detalles_payload)}")
            resp = api.post("/ventas", json=payload)
            print(f"DEBUG: Respuesta servidor mandar a caja -> Status: {resp.status_code}")
            if resp.status_code in (200, 201):
                venta_resp = resp.json()
                numero_venta = venta_resp.get("numero", "")
                messagebox.showinfo("✅ Venta Enviada a Caja", 
                                    f"💖 ¡VENTA ENVIADA A CAJA! 💖\n\n"
                                    f"🧾 N° de Venta: {numero_venta}\n"
                                    f"💸 Monto: {self.formato_peso(total)}\n"
                                    f"👤 Operario: {self.user_nombre or 'Operario'}\n\n"
                                    f"El Administrador ya puede verla y procesar el cobro en su caja.",
                                    parent=self.ventana)
                self.limpiar_formulario()
                self.productos_inventario = self.obtener_productos()
                self.actualizar_catalogo_live()
            else:
                try:
                    err_msg = resp.json().get("detail", resp.text)
                except:
                    err_msg = resp.text
                messagebox.showerror("Error al Mandar a Caja", f"El servidor respondió con error:\n{err_msg}", parent=self.ventana)
        except Exception as e:
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
        
        doc_mostrar = orden.get('cliente_documento') or (str(orden.get('cliente_id')) if orden.get('cliente_id') else "")
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
        """Abre el módulo independiente caja_menu.py pasando usuario y rol."""
        try:
            caja_path = os.path.join(os.path.dirname(__file__), "caja_menu.py")
            if os.path.exists(caja_path):
                args = [sys.executable, caja_path]
                if self.user_nombre:
                    args.extend(["--usuario", str(self.user_nombre)])
                if self.rol:
                    args.extend(["--rol", str(self.rol)])
                if self.user_id:
                    args.extend(["--user_id", str(self.user_id)])
                env = os.environ.copy()
                if api.token:
                    env["VMPOS_TOKEN"] = api.token
                if self.user_nombre:
                    env["VMPOS_USUARIO"] = str(self.user_nombre)
                if self.rol:
                    env["VMPOS_ROL"] = str(self.rol)
                subprocess.Popen(args, env=env)
            else:
                try:
                    from caja_menu import iniciar_control_caja
                    iniciar_control_caja(usuario_actual=self.user_nombre or "Vendedor", rol_actual=self.rol or "Vendedor")
                except Exception:
                    messagebox.showwarning("⚠️ Archivo no encontrado", f"No se encontró caja_menu.py en:\n{caja_path}", parent=self.ventana)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir el módulo de Control de Caja:\n{e}", parent=self.ventana)

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
        Obtener productos del inventario en modo Local-First.
        Para productos físicos, el stock disponible para venta en mostrador es stock_vitrina.
        """
        todos_los_productos = []
        try:
            from interface.inventario_manager import obtener_catalogo
            items = obtener_catalogo(solo_activos=True)
            if items:
                for it in items:
                    cod = str(it.get("codigo", "")).strip()
                    nom = str(it.get("nombre", "")).strip()
                    tipo_p = str(it.get("tipo_producto", "Fisico")).strip()
                    precio_v = float(it.get("precio", 0.0))
                    costo_u = float(it.get("costo", 0.0))
                    prov_id = it.get("proveedor_id")
                    p_id = it.get("id")
                    
                    if tipo_p == "Servicio":
                        es_var = bool(it.get("precio_variable", 0))
                        todos_los_productos.append((cod, nom, 9999, precio_v, "Servicio", prov_id, p_id, costo_u, es_var, 0.0))
                    else:
                        sv = float(it.get("stock_vitrina", 0.0))
                        sb = float(it.get("stock_bodega", 0.0))
                        try:
                            sv_fmt = int(sv) if sv.is_integer() else sv
                        except Exception:
                            sv_fmt = sv
                        todos_los_productos.append((cod, nom, sv_fmt, precio_v, "Fisico", prov_id, p_id, costo_u, False, sb))

                if str(self.rol).strip().lower() == "operario":
                    return [item for item in todos_los_productos if item[4] == "Servicio"]
                return todos_los_productos
        except Exception as e:
            print(f"Aviso consultando inventario local SQLite: {e}")

        # Fallback remoto API si por alguna razón SQLite estuviera vacío
        try:
            resp_prod = api.get("/productos?size=1000")
            resp_serv = api.get("/servicios?size=1000")
            
            if resp_prod.status_code == 200:
                prod_data = resp_prod.json()
                productos = prod_data.get("items", []) if isinstance(prod_data, dict) else (prod_data if isinstance(prod_data, list) else [])
                for p in productos:
                    stock_val = p.get("stock", 0)
                    try:
                        stock_fmt = int(stock_val) if float(stock_val).is_integer() else stock_val
                    except Exception:
                        stock_fmt = stock_val
                    precio_v = p.get("precio_venta", p.get("precio", 0.0))
                    costo_u = p.get("precio_costo", p.get("costo", 0.0))
                    todos_los_productos.append((p.get("codigo", ""), p.get("nombre", ""), stock_fmt, precio_v, "Fisico", p.get("proveedor_id"), p.get("id"), costo_u, False, 0.0))

            if resp_serv.status_code == 200:
                serv_data = resp_serv.json()
                servicios = serv_data.get("items", []) if isinstance(serv_data, dict) else (serv_data if isinstance(serv_data, list) else [])
                for s in servicios:
                    precio_s = s.get("precio_venta", s.get("precio", 0.0))
                    costo_s = s.get("costo_proveedor", s.get("costo", 0.0))
                    precio_var = bool(s.get("precio_variable", False))
                    todos_los_productos.append((s.get("codigo", ""), s.get("nombre", ""), 9999, precio_s, "Servicio", s.get("proveedor_id"), s.get("id"), costo_s, precio_var, 0.0))

            if str(self.rol).strip().lower() == "operario":
                return [item for item in todos_los_productos if item[4] == "Servicio"]
            return todos_los_productos
        except Exception as e:
            print(f"Aviso fallback API: {e}")
            return todos_los_productos

    def formato_peso(self, valor):
        """Formato de pesos colombianos"""
        return f"${int(valor):,.0f} COP"

    def limpiar_precio(self, texto):
        """Convertir texto de precio a número"""
        if isinstance(texto, (int, float)):
            return float(texto)
        return float(texto.replace("$", "").replace("COP", "").replace(",", "").strip() or 0)

    def actualizar_total(self):
        """Actualizar el display del total"""
        self.total_label.config(text=self.formato_peso(self.total_general.get()))

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
        """Muestra un modal estilizado para ingresar el precio de un servicio con precio variable"""
        parent_win = parent or self.ventana
        dialog = tk.Toplevel(parent_win)
        dialog.title("💰 Definir Precio de Servicio")
        t_d = aplicar_tema(dialog)
        dialog.configure(bg=t_d["bg_surface"])
        dialog.transient(parent_win)
        dialog.grab_set()

        calcular_geometria_segura(dialog, 460, 260, 400, 220)
        dialog.resizable(False, False)

        tk.Label(dialog, text="⚙️ SERVICIO CON PRECIO VARIABLE", font=("Segoe UI", 11, "bold"), 
                 bg=t_d["bg_surface"], fg=t_d["bg_header"]).pack(pady=(16, 5))
        tk.Label(dialog, text=f"Ingrese el monto a cobrar por el servicio:\n'{nombre}'", font=("Segoe UI", 10), 
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
                messagebox.showwarning("Atención", "El precio debe ser mayor a 0", parent=dialog)
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
                    es_var = p[8] if (p[4] == "Servicio" and len(p) > 8) else False
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
                    if tipo_prod == "Servicio" and es_var:
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
        """Agregar producto al carrito - CORREGIDO PARA SUMAR CANTIDADES"""
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
            if len(valores) >= 4:
                # Coincidir por nombre del producto y mismo precio unitario
                p_unit = self.limpiar_precio(valores[1])
                if str(valores[0]).strip().lower() == str(nombre).strip().lower() and abs(p_unit - precio) < 0.01:
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
            return

        if item_existente:
            # ACTUALIZAR CANTIDAD EXISTENTE - ESTE ES EL FIX PRINCIPAL
            nueva_cantidad = cantidad_actual + 1
            nuevo_total = precio * nueva_cantidad
            
            # Actualizar la fila existente
            self.tabla.item(item_existente, values=(
                nombre, 
                self.formato_peso(precio), 
                nueva_cantidad, 
                self.formato_peso(nuevo_total)
            ))
            
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
                return
            
            # Agregar nuevo producto
            self.tabla.insert("", tk.END, text=codigo, values=(nombre, self.formato_peso(precio), 1, 
                                                 self.formato_peso(precio)))
            self.total_general.set(self.total_general.get() + precio)
            
            print(f"DEBUG: Nuevo producto agregado: {nombre}")
        
        self.actualizar_total()

    def escanear_codigo(self):
        """Escanea un código de barras y agrega el producto"""
        if not self.verificar_caja_abierta("escanear o agregar productos"):
            return
        codigo = self.codigo_entrada.get().strip()
        if not codigo:
            return
        producto = next((p for p in self.productos_inventario if str(p[0]) == codigo or str(p[0]).zfill(5) == codigo.zfill(5)), None)
        
        if producto:
            # producto[2] es stock, producto[4] es tipo_producto, producto[8] es precio_variable
            tipo_prod = producto[4]
            es_var = producto[8] if len(producto) > 8 else False
            
            if producto[2] > 0 or tipo_prod == "Servicio":
                precio = producto[3]
                if tipo_prod == "Servicio" and es_var:
                    precio_ingresado = self.solicitar_precio_variable(producto[1], precio, parent=self.ventana)
                    if precio_ingresado is None:
                        self.codigo_entrada.set("")
                        return
                    precio = precio_ingresado
                    
                self.agregar_producto(producto[0], producto[1], precio)
                self.codigo_entrada.set("")
                self.entry_codigo.focus()
            else:
                messagebox.showerror("Sin stock", "El producto no tiene stock disponible", parent=self.ventana)
                self.codigo_entrada.set("")
        else:
            messagebox.showerror("No encontrado", "El código del producto no existe", parent=self.ventana)
            self.codigo_entrada.set("")

    def eliminar_seleccionado(self):
        """Elimina el producto seleccionado del carrito"""
        item = self.tabla.focus()
        if item:
            valores = self.tabla.item(item)["values"]
            self.total_general.set(self.total_general.get() - self.limpiar_precio(valores[3]))
            self.tabla.delete(item)
            self.actualizar_total()

    def pagar(self):
        """Abre la ventana para procesar el pago con layout responsive y footer de confirmación sticky"""
        if not self.verificar_caja_abierta("procesar cobros o ventas"):
            return
        if self.total_general.get() <= 0 or len(self.tabla.get_children()) == 0:
            messagebox.showwarning("Carrito Vacío", "Agregue al menos un producto o servicio antes de cobrar.", parent=self.ventana)
            return
        ventana = tk.Toplevel(self.ventana)
        ventana.title("💳 Procesar Pago - POS")
        t_p = aplicar_tema(ventana)
        calcular_geometria_segura(ventana, 500, 520, 420, 390)
        ventana.configure(bg=t_p["bg_app"])
        ventana.grab_set()

        # 1. HEADER (Fijo arriba)
        header_p = tk.Frame(ventana, bg=t_p["bg_header"])
        header_p.pack(side="top", fill="x")
        tk.Label(header_p, text="💖 PROCESAR COBRO", font=("Segoe UI", 14, "bold"), bg=t_p["bg_header"], fg=t_p["text_header"]).pack(pady=(10, 2))
        tk.Label(header_p, text=f"Total: {self.formato_peso(self.total_general.get())}", font=("Segoe UI", 16, "bold"), bg=t_p["bg_header"], fg="#FEF08A").pack(pady=(0, 10))

        # 2. FOOTER ACCIONES (Sticky abajo)
        footer_p = tk.Frame(ventana, bg=t_p["bg_app"])
        footer_p.pack(side="bottom", fill="x", padx=15, pady=12)

        imprimir_var = tk.BooleanVar(value=False)

        def completar():
            metodo = metodo_var.get()
            total_val = int(round(self.total_general.get()))
            try:
                if metodo == "Efectivo":
                    monto_ef = entry_efectivo.get_value()
                    if monto_ef >= total_val:
                        self._abrir_dialogo_recibo(ventana, monto_ef, total_val, metodo, None)
                    else:
                        messagebox.showwarning("Efectivo insuficiente", f"El monto recibido (${monto_ef:,.0f}) es menor al total a pagar (${total_val:,.0f}).", parent=ventana)
                elif metodo == "Transferencia":
                    self._abrir_dialogo_recibo(ventana, total_val, total_val, metodo, None)
                elif metodo == "Fiado":
                    seleccion = combo_clientes.get()
                    if not seleccion:
                        messagebox.showerror("Error", "Debe seleccionar un cliente habilitado para fiado.", parent=ventana)
                        return
                    id_cliente = seleccion.split(" - ")[0]
                    self._abrir_dialogo_recibo(ventana, 0, total_val, metodo, id_cliente)
            except (tk.TclError, ValueError):
                messagebox.showerror("Error", "Error en los datos ingresados.", parent=ventana)

        btn_confirmar = crear_boton(footer_p, "Confirmar Venta", command=completar, tipo="success", icono="✅", tam_fuente=11)
        btn_confirmar.pack(side="right", padx=5)

        btn_cancelar = crear_boton(footer_p, "Cancelar", command=ventana.destroy, tipo="secondary", icono="❌", tam_fuente=11)
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
        
        frame_dinamico = tk.Frame(body_p, bg=t_p["bg_surface"], bd=1, relief="solid", padx=10, pady=10)
        frame_dinamico.pack(fill="both", expand=True, pady=10)
        
        # Efectivo widgets con CurrencyEntry (eliminado el problema de '0.0')
        lbl_efectivo = tk.Label(frame_dinamico, text="💵 Efectivo recibido:", font=("Segoe UI", 11, "bold"), bg=t_p["bg_surface"], fg=t_p["text_main"])
        lbl_cambio = tk.Label(frame_dinamico, text="💰 Cambio: $ 0 COP", font=("Segoe UI", 12, "bold"), bg=t_p["bg_surface"], fg="#059669")
        
        total_a_pagar = int(round(self.total_general.get()))
        def al_cambiar_efectivo(val_recibido):
            cambio = max(0, val_recibido - total_a_pagar)
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
        
        # Fiado widgets
        lbl_fiado = tk.Label(frame_dinamico, text="Cliente Autorizado para Fiado:", font=("Segoe UI", 10, "bold"), bg=t_p["bg_surface"], fg=t_p["text_main"])
        combo_clientes = ttk.Combobox(frame_dinamico, state="readonly", width=30, font=("Segoe UI", 10))
        
        def actualizar_vista(*args):
            for w in frame_dinamico.winfo_children():
                w.pack_forget()
                
            metodo = metodo_var.get()
            if metodo == "Efectivo":
                lbl_efectivo.pack(pady=(4, 2))
                entry_efectivo.pack(pady=4)
                lbl_cambio.pack(pady=(4, 2))
                entry_efectivo.focus()
            elif metodo == "Fiado":
                lbl_fiado.pack(pady=4)
                combo_clientes.pack(pady=4)
                valores_fiado = []
                try:
                    resp = api.get("/clientes")
                    if resp.status_code == 200:
                        clientes_api = resp.json()
                        clientes_fiado = [c for c in clientes_api if c.get("permite_fiado", False)]
                        valores_fiado = [f"{c.get('id')} - {c.get('nombre')} ({c.get('cedula', '')})" for c in clientes_fiado]
                except Exception as e:
                    print(f"Error cargando clientes API: {e}")

                if not valores_fiado:
                    try:
                        conn_c = conectar_db()
                        if conn_c:
                            cur_c = conn_c.cursor()
                            cur_c.execute("SELECT id, nombre, cedula FROM clientes WHERE permite_fiado = 1 ORDER BY nombre")
                            valores_fiado = [f"{r[0]} - {r[1]} ({r[2] or ''})" for r in cur_c.fetchall()]
                            conn_c.close()
                    except Exception as e_cli:
                        print(f"Error cargando clientes SQLite: {e_cli}")

                combo_clientes['values'] = valores_fiado
                if valores_fiado:
                    combo_clientes.current(0)
            elif metodo == "Transferencia":
                tk.Label(frame_dinamico, text="📱 Pago inmediato por Transferencia\n(Nequi, Daviplata, Bancolombia)", 
                         font=("Segoe UI", 10, "italic"), bg="#FFE4E1", fg="#2D3436").pack(pady=15)
        
        metodo_var.trace_add("write", actualizar_vista)
        actualizar_vista()
        ventana.bind('<Escape>', lambda e: ventana.destroy())

    def _abrir_dialogo_recibo(self, parent, recibido, total, metodo_pago, id_cliente):
        """Confirma impresión y muestra el comprobante completo (con logo, 58mm/80mm/A4 y PDF) después del pago."""
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
                "subtotal": precio_u * cant
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
            "snapshot_negocio": business_mgr.obtener_snapshot_factura()
        }

        def al_confirmar(imprimir=False, formato_seleccionado=None):
            try:
                if parent and parent.winfo_exists():
                    parent.destroy()
            except Exception:
                pass
            self.procesar_venta_completa(
                recibido,
                total,
                metodo_pago,
                id_cliente=id_cliente,
                imprimir_recibo=imprimir,
                formato_impresion=formato_seleccionado
            )

        mostrar_dialogo_factura(
            parent,
            datos_preview,
            modo_confirmacion_venta=True,
            on_confirmar_venta=al_confirmar
        )

    def _mostrar_vista_previa_recibo(self, parent):
        """Compatibilidad para llamadas antiguas al botón de vista previa."""
        self._abrir_dialogo_recibo(parent, self.total_general.get(), self.total_general.get(), "Efectivo", None)

    def procesar_venta_completa(self, recibido, total, metodo_pago="Efectivo", id_cliente=None, imprimir_recibo=False, formato_impresion=None):
        """Procesa la venta, guarda el snapshot histórico del negocio e imprime o exporta el comprobante."""
        if not self.verificar_caja_abierta("registrar o procesar la venta"):
            return
        try:
            business_mgr.recargar()
            snapshot_actual = business_mgr.obtener_snapshot_factura()
            detalles_payload = []
            
            # Obtener datos de productos
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
                
                if not item_id and not getattr(self, 'orden_id_activa', None):
                    messagebox.showerror("Error", f"No se pudo identificar el producto o servicio con código '{codigo}'.")
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
                    "costo_unitario": costo
                })

            doc_cli = self.documento.get().strip()
            cliente_id_val = int(id_cliente) if id_cliente and str(id_cliente).isdigit() else (int(doc_cli) if doc_cli and doc_cli.isdigit() else None)

            if getattr(self, 'orden_id_activa', None):
                cobro_payload = {
                    "pagos": [
                        {
                            "metodo": metodo_pago,
                            "monto": total,
                            "recibido": recibido,
                            "cambio": recibido - total
                        }
                    ],
                    "cliente_id": cliente_id_val,
                    "cliente_documento": doc_cli if doc_cli else None
                }
                resp = api.post(f"/ventas/{self.orden_id_activa}/autorizar-pago", json=cobro_payload)
            else:
                payload = {
                    "cliente_id": cliente_id_val,
                    "cliente_documento": doc_cli if doc_cli else None,
                    "terminal_id": 1,
                    "subtotal": total,
                    "descuento": 0.0,
                    "total": total,
                    "pagos": [
                        {
                            "metodo": metodo_pago,
                            "monto": total,
                            "recibido": recibido,
                            "cambio": recibido - total
                        }
                    ],
                    "detalles": detalles_payload
                }
                resp = api.post("/ventas", json=payload)
            
            operario_nombre = getattr(self, 'user_nombre', None) or getattr(self, 'rol', None) or "Administrador"
            venta_exitosa = False
            numero_factura = self.factura_num
            id_local = None
            cambio_calc = max(0.0, float(recibido) - float(total))

            if resp.status_code in (200, 201):
                venta_respuesta = resp.json()
                numero_factura = venta_respuesta.get("numero", self.factura_num)
                id_local = guardar_venta_sqlite(
                    self.documento.get(), total, metodo_pago, detalles_payload,
                    operario_nombre, cliente_id=cliente_id_val,
                    recibido=recibido, cambio=cambio_calc,
                    numero_factura=numero_factura, snapshot_negocio=snapshot_actual
                )
                venta_exitosa = True
            else:
                id_local = guardar_venta_sqlite(
                    self.documento.get(), total, metodo_pago, detalles_payload,
                    operario_nombre, cliente_id=cliente_id_val,
                    recibido=recibido, cambio=cambio_calc,
                    numero_factura="", snapshot_negocio=snapshot_actual
                )
                if id_local:
                    pref = snapshot_actual.get("prefijo_comprobante", "") or "FAC-"
                    numero_factura = f"{pref}{id_local:05d}"
                    venta_exitosa = True

            if venta_exitosa:
                msg_asistencia = self.confirmar_asistencia_y_recaudo_vendedor(
                    operario_nombre, total, detalles_payload,
                    id_venta=id_local, metodo_pago=metodo_pago
                )

                datos_venta = {
                    'id_venta': id_local,
                    'factura': numero_factura,
                    'fecha': datetime.now().strftime('%Y-%m-%d'),
                    'hora': datetime.now().strftime('%H:%M:%S'),
                    'cliente': self.documento.get().strip() or 'Consumidor Final',
                    'productos': [(d["item_nombre"], d["precio_vendido"], d["cantidad"]) for d in detalles_payload],
                    'items': detalles_payload,
                    'total': total,
                    'metodo_pago': metodo_pago,
                    'recibido': recibido,
                    'cambio': cambio_calc,
                    'saldo_pendiente': float(total) if str(metodo_pago) == "Fiado" else 0.0,
                    'vendedor': operario_nombre,
                    'snapshot_negocio': snapshot_actual
                }

                if self.printer_manager:
                    self.printer_manager.ultima_factura = datos_venta

                aviso_impresion = ""
                if imprimir_recibo:
                    cfg_over = {"formato_papel": formato_impresion} if formato_impresion else None
                    if self.printer_manager:
                        imp_ok = self.printer_manager.imprimir_factura(datos_venta, config_override=cfg_over)
                        if imp_ok and self.impresora_conectada:
                            self.printer_manager.abrir_caja_registradora()
                        elif not imp_ok:
                            aviso_impresion = "\n\n⚠️ Nota: No se detectó impresora física activa; puedes reimprimir o exportar el PDF desde Gestión de Ventas."
                    else:
                        try:
                            from receipt_manager import imprimir_factura_unificada
                        except ImportError:
                            from interface.receipt_manager import imprimir_factura_unificada
                        imp_ok, _ = imprimir_factura_unificada(datos_venta, config_override=cfg_over)
                        if not imp_ok:
                            aviso_impresion = "\n\n⚠️ Nota: No se detectó impresora física activa; puedes reimprimir o exportar el PDF desde Gestión de Ventas."
                
                extra_info = f"\n\n{msg_asistencia}" if msg_asistencia else ""
                extra_info += aviso_impresion
                if metodo_pago == "Efectivo":
                    vuelto = recibido - total
                    messagebox.showinfo("✅ Pago Completado", f"💖 VENTA COMPLETADA 💖\n🧾 Comprobante: {numero_factura}\n💸 Total: {self.formato_peso(total)}\n💵 Recibido: {self.formato_peso(recibido)}\n💰 Cambio: {self.formato_peso(vuelto)}{extra_info}\n🌸 ¡Gracias! 🌸", parent=self.ventana)
                elif metodo_pago == "Fiado":
                    messagebox.showinfo("✅ Pago Completado", f"💖 VENTA FIADA 💖\n🧾 Comprobante: {numero_factura}\n💸 Saldo pendiente: {self.formato_peso(total)}{extra_info}\n🌸 ¡Gracias! 🌸", parent=self.ventana)
                else:
                    messagebox.showinfo("✅ Pago Completado", f"💖 VENTA POR TRANSFERENCIA 💖\n🧾 Comprobante: {numero_factura}\n💸 Total: {self.formato_peso(total)}{extra_info}\n🌸 ¡Gracias! 🌸", parent=self.ventana)
                
                if getattr(self, 'orden_id_activa', None):
                    self.cancelar_orden_activa()
                else:
                    self.limpiar_formulario()

                self.productos_inventario = self.obtener_productos()
                self.actualizar_catalogo_live()
                self.actualizar_indicadores_empleado_pos()
                if self.es_admin:
                    self.actualizar_ventas_operarios()
            else:
                try:
                    error_msg = resp.json().get("detail", "Error desconocido")
                except:
                    error_msg = resp.text
                messagebox.showerror("Error al Procesar Venta", f"No se pudo guardar la venta:\n{error_msg}", parent=self.ventana)
        except Exception as e:
            messagebox.showerror("Error", f"Error procesando venta: {e}", parent=self.ventana)

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
        self.documento.set("")
        self.codigo_entrada.set("")
        self.total_general.set(0.0)
        self.factura_num = datetime.now().strftime("%Y%m%d%H%M%S")
        self.orden_id_activa = None
        self.orden_numero_activa = None
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
        self.entry_doc.focus()

def iniciar_ventas(parent=None, user_id="", rol="", parent_pid=""):
    """
    Punto de entrada in-process para el módulo de ventas de VmPOS.
    Permite abrir la ventana como Toplevel (sin relanzar login ni abrir subprocesos pesados)
    o como Tk independiente.
    """
    if parent:
        ventana = tk.Toplevel(parent)
    else:
        ventana = tk.Tk()

    app = App(ventana, user_id=user_id, rol=rol, parent_pid=parent_pid)

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
    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)
    args, _ = parser.parse_known_args()

    iniciar_ventas(user_id=args.user_id, rol=args.rol, parent_pid=args.parent_pid)