import sys
import io

if not hasattr(sys.stdout, "name") or sys.stdout.name != "vmpos.log":
    try:
        log_file = open("vmpos.log", "a", encoding="utf-8")
        sys.stdout = log_file
        sys.stderr = log_file
    except Exception:
        class DevNull(io.TextIOBase):
            def write(self, msg): pass
        sys.stdout = DevNull()
        sys.stderr = DevNull()

import tkinter as tk
from tkinter import ttk
import subprocess
import datetime
from tkinter import messagebox
import sqlite3
import importlib.util
import os
import sys

# Agregar rutas base
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from client.api_client import api

try:
    from theme_manager import theme_mgr, aplicar_tema, calcular_geometria_segura, calcular_color_texto_optimo, crear_boton, oscurecer_color, aclarar_color, ScrollableContainer
except ImportError:
    from interface.theme_manager import theme_mgr, aplicar_tema, calcular_geometria_segura, calcular_color_texto_optimo, crear_boton, oscurecer_color, aclarar_color, ScrollableContainer

try:
    from business_manager import business_mgr
except ImportError:
    from interface.business_manager import business_mgr

try:
    from session_manager import session_mgr
except ImportError:
    from interface.session_manager import session_mgr

# Configuración de rutas para PyInstaller
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

base_dir = BASE_DIR
database_dir = os.path.join(base_dir, 'database')
ruta_db = os.path.join(database_dir, 'ventas.db')

# Intentar importar el generador de códigos de barras
GENERADOR_DISPONIBLE = False
iniciar_generador_barras = None

try:
    from generador_codigo_barras import iniciar_generador_barras
    GENERADOR_DISPONIBLE = True
    print("✅ Generador de códigos de barras disponible")
except ImportError as e:
    print(f"⚠️ Generador de códigos de barras no disponible: {e}")
    GENERADOR_DISPONIBLE = False


# Importaciones con manejo de errores
try:
    from pantalla_carga import mostrar_carga
except ImportError as e:
    print(f"Warning: pantalla_carga module not found: {e}")
    def mostrar_carga(*args, **kwargs):
        print("Pantalla de carga no disponible")

try:
    from contabilidad_menu import iniciar_contabilidad
except ImportError:
    try:
        from interface.contabilidad_menu import iniciar_contabilidad
    except ImportError:
        def iniciar_contabilidad():
            iniciar_reportes()

try:
    from reportes_menu import iniciar_reportes
except ImportError as e:
    print(f"Warning: reportes_menu module not found: {e}")
    def iniciar_reportes():
        messagebox.showwarning("Módulo no disponible", "El módulo de reportes no está disponible.")

try:
    from clientes_menu import iniciar_clientes
except ImportError as e:
    print(f"Warning: clientes_menu module not found: {e}")
    def iniciar_clientes():
        messagebox.showwarning("Módulo no disponible", "El módulo de clientes no está disponible.")

try:
    from configuracion_menu import iniciar_configuracion
except ImportError as e:
    print(f"Warning: configuracion_menu module not found: {e}")
    def iniciar_configuracion():
        messagebox.showwarning("Módulo no disponible", "El módulo de configuración no está disponible.")

try:
    from usuarios_menu import iniciar_usuarios
except ImportError as e:
    print(f"Warning: usuarios_menu module not found: {e}")
    def iniciar_usuarios():
        messagebox.showwarning("Módulo no disponible", "El módulo de usuarios no está disponible.")

try:
    from inventario_menu import iniciar_inventario
except ImportError as e:
    print(f"Warning: inventario_menu module not found: {e}")
    def iniciar_inventario():
        messagebox.showwarning("Módulo no disponible", "El módulo de inventario no está disponible.")

try:
    from database_manager import inicializar_base_datos, conectar_db as _conectar_db
except ImportError:
    from interface.database_manager import inicializar_base_datos, conectar_db as _conectar_db
inicializar_base_datos()

try:
    from caja_manager import obtener_resumen_financiero
except ImportError:
    try:
        from interface.caja_manager import obtener_resumen_financiero
    except ImportError:
        obtener_resumen_financiero = None

try:
    from ventas_admin_dialog import abrir_gestion_ventas
except ImportError:
    try:
        from interface.ventas_admin_dialog import abrir_gestion_ventas
    except ImportError:
        abrir_gestion_ventas = None

class VmPOSDashboard(tk.Tk):
    """
    Clase principal de la aplicación para el Dashboard de VmPOS.
    Hereda de tk.Tk, haciendo que la instancia de la clase sea la ventana principal.
    """
    def __init__(self, usuario="Admin", datos_usuario=None):
        super().__init__()

        business_mgr.recargar()

        self.usuario = usuario
        self.datos_usuario = datos_usuario or {}
        
        # CORRECCIÓN: Obtener rol primero, luego permisos
        rol_raw = self.datos_usuario.get('rol') or self.datos_usuario.get('role') or ''
        if not rol_raw:
            perm = self.datos_usuario.get('permisos') or ''
            if str(perm).lower() in ['admin', 'administrador', 'gerente']:
                rol_raw = 'administrador'
            else:
                rol_raw = 'vendedor'
        self.rol_usuario = rol_raw.lower() if isinstance(rol_raw, str) else 'vendedor'
        self.rol_usuario_display = self.rol_usuario.capitalize()
        
        # Obtener permisos después de definir el rol
        self.permisos = self._get_user_permissions()
        
        # Variables para estadísticas
        self.stats_widgets = {}
        
        # Variables para gastos temporales
        self.entry_concepto = None
        self.entry_valor = None
        self.tree_gastos = None
        self.label_total = None
        
        # Aplicar sistema centralizado de temas VmPOS
        self.t = aplicar_tema(self)

        # Registrar apertura de jornada si es empleado/vendedor/operario (Fase 3)
        if self.rol_usuario in ("empleado", "vendedor", "operario"):
            try:
                try:
                    from interface.nomina_manager import registrar_asistencia_jornada
                except ImportError:
                    from nomina_manager import registrar_asistencia_jornada
                uid_init = self.datos_usuario.get("id")
                registrar_asistencia_jornada(
                    usuario_id=int(uid_init) if uid_init and str(uid_init).isdigit() else None,
                    usuario_nombre=self.usuario,
                    rol=self.rol_usuario,
                    origen="APERTURA_POS",
                    responsable=self.usuario
                )
            except Exception as e_aj:
                print("Aviso registrando jornada inicial en dashboard:", e_aj)

        # Iniciar sesión supervisada en session_mgr
        session_mgr.iniciar_sesion(
            usuario=self.usuario,
            rol=self.rol_usuario,
            user_id=self.datos_usuario.get("id"),
            token=getattr(api, "token", None)
        )
        self.protocol("WM_DELETE_WINDOW", self._on_close_window)

        self._setup_main_window()
        self._create_header()
        self._create_main_content()
        self._create_footer()
        self._bind_shortcuts()
        business_mgr.agregar_listener(self.refrescar_identidad_negocio)
        self.bind("<FocusIn>", lambda e: (self._actualizar_estadisticas(), self._actualizar_estadisticas_empleado()))
        
        # Actualizar estadísticas cada 30 segundos
        self._actualizar_estadisticas()
        
        # Verificar asistencia diaria
        self._verificar_asistencia()
        self.after(30000, self._programa_actualizacion_stats)
        
        # Ocultar la pantalla de carga después de inicializar el dashboard
        if isinstance(self.datos_usuario, dict) and 'ventana_carga' in self.datos_usuario:
            try:
                self.datos_usuario['ventana_carga'].destroy()
            except:
                pass  # Ventana ya destruida

    def _on_close_window(self):
        """Maneja el evento de cierre de ventana desde el sistema operativo (X superior)."""
        if messagebox.askyesno("Salir de VmPOS", "¿Estás seguro que deseas salir del sistema?"):
            session_mgr.cerrar_sesion(root_window=self, lanzar_login=False)

    def _get_user_permissions(self):
        """
        Obtiene los permisos del usuario basados en su rol/api.
        """
        user_rol = getattr(self, "rol_usuario", "").lower() or self.datos_usuario.get("rol", "").lower()
        if user_rol in ["admin", "administrador", "gerente"]:
            return {
                "Ventas": 1, "Inventario": 1, "Clientes": 1, "Reportes": 1, "Contabilidad": 1, "Gastos": 1,
                "Usuarios": 1, "Configuración": 1, "Códigos de Barras": 1, "Nómina": 1,
                "Turnos": 1, "Caja": 1, "Gestión Ventas": 1
            }
        return {
            "Ventas": 1, "Inventario": 0, "Clientes": 0, "Reportes": 0, "Contabilidad": 0, "Gastos": 0,
            "Usuarios": 0, "Configuración": 0, "Códigos de Barras": 0, "Nómina": 0,
            "Turnos": 1 if user_rol == "operario" else 0,
            "Caja": 1, "Gestión Ventas": 0
        }

    def _setup_main_window(self):
        """Configura las propiedades de la ventana principal de forma adaptativa."""
        try:
            self.title(f"{business_mgr.nombre} - Dashboard • {self.usuario} ({self.rol_usuario_display})")
            calcular_geometria_segura(self, 1200, 730, 960, 560)
            self.configure(bg=self.t["bg_app"])
        except Exception as e:
            print(f"Error configurando ventana principal: {e}")

    def _toggle_tema(self):
        """Alterna entre modo claro y oscuro con actualización visual inmediata manteniendo la sesión activa."""
        nuevo = theme_mgr.alternar_tema()
        self.t = aplicar_tema(self)
        self.configure(bg=self.t["bg_app"])

        # Destruir widgets hijos y reconstruir la interfaz con los nuevos tokens
        for widget in self.winfo_children():
            try:
                widget.destroy()
            except Exception:
                pass

        self.stats_widgets = {}
        self.entry_concepto = None
        self.entry_valor = None
        self.tree_gastos = None
        self.label_total = None

        self._setup_main_window()
        self._create_header()
        self._create_main_content()
        self._create_footer()
        self._bind_shortcuts()
        self._actualizar_estadisticas()

    def _renderizar_logo_header(self, bg_h, fg_h):
        """Renderiza o actualiza el logo institucional (o ícono por defecto) en el encabezado."""
        if not hasattr(self, "logo_slot") or not self.logo_slot.winfo_exists():
            return
        for child in self.logo_slot.winfo_children():
            child.destroy()
        self.logo_slot.config(bg=bg_h)
        self._header_logo_img = None

        logo_cargado = False
        ruta_logo = business_mgr.logo_path
        if ruta_logo and os.path.isfile(ruta_logo):
            try:
                from PIL import Image, ImageTk
                with Image.open(ruta_logo) as raw:
                    raw.load()
                    if raw.mode not in ("RGB", "RGBA"):
                        im_vis = raw.convert("RGBA")
                    else:
                        im_vis = raw.copy()
                    im_vis.thumbnail((120, 38), Image.Resampling.LANCZOS)
                    self._header_logo_img = ImageTk.PhotoImage(im_vis, master=self)
                lbl_logo = tk.Label(self.logo_slot, image=self._header_logo_img, bg=bg_h)
                lbl_logo.pack(side="left", padx=(0, 10), pady=6)
                logo_cargado = True
            except Exception as e_l:
                print(f"Aviso cargando logo en header: {e_l}")

        if not logo_cargado:
            tk.Label(self.logo_slot, text="🌸", font=("Segoe UI Emoji", 20), bg=bg_h, fg=fg_h).pack(side="left", pady=8)

    def refrescar_identidad_negocio(self):
        """Actualiza en caliente el encabezado, logo, título y pie de página tras guardar en Configuración."""
        try:
            if not self.winfo_exists():
                return
            business_mgr.recargar()
            self.title(f"{business_mgr.nombre} - Dashboard • {self.usuario} ({self.rol_usuario_display})")

            bg_h = business_mgr.color_barra or self.t["bg_header"]
            fg_h = calcular_color_texto_optimo(bg_h)
            fg_sub = fg_h

            if hasattr(self, "header_frame") and self.header_frame.winfo_exists():
                self.header_frame.config(bg=bg_h)
            if hasattr(self, "header_left") and self.header_left.winfo_exists():
                self.header_left.config(bg=bg_h)
            self._renderizar_logo_header(bg_h, fg_h)

            if hasattr(self, "lbl_header_nombre") and self.lbl_header_nombre.winfo_exists():
                self.lbl_header_nombre.config(text=business_mgr.nombre, bg=bg_h, fg=fg_h)
            if hasattr(self, "lbl_header_subtitulo") and self.lbl_header_subtitulo.winfo_exists():
                sub_txt = f"• {business_mgr.subtitulo}" if business_mgr.subtitulo else ""
                self.lbl_header_subtitulo.config(text=sub_txt, bg=bg_h, fg=fg_sub)

            for attr_f in ("header_right", "user_strip", "info_strip"):
                w_f = getattr(self, attr_f, None)
                if w_f and w_f.winfo_exists():
                    w_f.config(bg=bg_h)
            if hasattr(self, "lbl_user_role") and self.lbl_user_role.winfo_exists():
                self.lbl_user_role.config(bg=bg_h, fg=fg_h)
            if hasattr(self, "lbl_fecha_hora") and self.lbl_fecha_hora.winfo_exists():
                self.lbl_fecha_hora.config(bg=bg_h, fg=fg_sub)
            if hasattr(self, "lbl_comision") and self.lbl_comision and self.lbl_comision.winfo_exists():
                self.lbl_comision.config(bg=bg_h)

            if hasattr(self, "lbl_footer_ubicacion") and self.lbl_footer_ubicacion.winfo_exists():
                self.lbl_footer_ubicacion.config(text=business_mgr.obtener_texto_ubicacion_contacto())
            if hasattr(self, "lbl_footer_marca") and self.lbl_footer_marca.winfo_exists():
                self.lbl_footer_marca.config(text=f"✨ {business_mgr.nombre} • Sistema Activo 💖")
        except Exception as e:
            print(f"Aviso refrescando identidad del negocio en menú de inicio: {e}")

    def _create_header(self):
        """Crea y empaqueta el encabezado compacto de la aplicación con temas y branding."""
        try:
            bg_h = business_mgr.color_barra or self.t["bg_header"]
            fg_h = calcular_color_texto_optimo(bg_h)
            fg_sub = fg_h

            self.header_frame = tk.Frame(self, bg=bg_h)
            self.header_frame.pack(fill="x")

            # Lado izquierdo del encabezado
            self.header_left = tk.Frame(self.header_frame, bg=bg_h)
            self.header_left.pack(side="left", fill="y", padx=20)

            self.logo_slot = tk.Frame(self.header_left, bg=bg_h)
            self.logo_slot.pack(side="left")
            self._renderizar_logo_header(bg_h, fg_h)

            self.lbl_header_nombre = tk.Label(self.header_left, text=business_mgr.nombre, font=("Segoe UI", 18, "bold"), bg=bg_h, fg=fg_h)
            self.lbl_header_nombre.pack(side="left", padx=(6, 0), pady=10)

            sub_txt = f"• {business_mgr.subtitulo}" if business_mgr.subtitulo else ""
            self.lbl_header_subtitulo = tk.Label(self.header_left, text=sub_txt, font=("Segoe UI", 10), bg=bg_h, fg=fg_sub)
            self.lbl_header_subtitulo.pack(side="left", padx=(8, 0), pady=12)

            # Lado derecho del encabezado
            self.header_right = tk.Frame(self.header_frame, bg=bg_h)
            self.header_right.pack(side="right", fill="y", padx=20)
            
            self.user_strip = tk.Frame(self.header_right, bg=bg_h)
            self.user_strip.pack(anchor="e", pady=(6, 2))

            emoji_rol = "👑" if self.rol_usuario in ["admin", "administrador"] else "👨‍🔧" if self.rol_usuario == "empleado" else "👩‍💼"
            self.lbl_user_role = tk.Label(self.user_strip, text=f"👤 {self.usuario} ({emoji_rol} {self.rol_usuario_display})", font=("Segoe UI", 11, "bold"), bg=bg_h, fg=fg_h)
            self.lbl_user_role.pack(side="left", padx=(0, 10))

            # Botón de alternar tema rápido
            txt_btn_tema = "🌙 Modo Oscuro" if not theme_mgr.es_oscuro() else "☀️ Modo Claro"
            btn_tema = tk.Button(self.user_strip, text=txt_btn_tema, font=("Segoe UI", 9, "bold"), 
                                 bg=self.t["btn_secondary_bg"], fg=self.t["btn_secondary_fg"], 
                                 activebackground=self.t["btn_secondary_hover"],
                                 activeforeground=self.t["btn_secondary_fg"],
                                 relief="flat", cursor="hand2", padx=8, pady=3, command=self._toggle_tema)
            btn_tema.pack(side="left", padx=(0, 6))

            btn_cerrar_sesion = tk.Button(self.user_strip, text="🚪 Cerrar Sesión", font=("Segoe UI", 9, "bold"), 
                                          bg=self.t["btn_danger_bg"], fg=self.t["btn_danger_fg"],
                                          activebackground=self.t["btn_danger_hover"],
                                          activeforeground=self.t["btn_danger_fg"],
                                          relief="flat", cursor="hand2", 
                                          padx=8, pady=3, command=self._cerrar_sesion)
            btn_cerrar_sesion.pack(side="left")
            
            # Fecha y hora en tiempo real + alerta admin o comision en una fila compacta
            self.info_strip = tk.Frame(self.header_right, bg=bg_h)
            self.info_strip.pack(anchor="e", pady=(0, 6))

            self.lbl_fecha_hora = tk.Label(self.info_strip, text="", font=("Segoe UI", 9), bg=bg_h, fg=fg_sub)
            self.lbl_fecha_hora.pack(side="left", padx=(0, 10))
            
            if self.rol_usuario in ["empleado", "vendedor", "operario"]:
                self.lbl_comision = tk.Label(self.info_strip, text="💰 Recaudado Hoy: $0 COP", font=("Segoe UI", 10, "bold"), bg=bg_h, fg=fg_h)
                self.lbl_comision.pack(side="left", padx=(0, 8))
                
                btn_pedir = tk.Button(self.info_strip, text="📤 Pedir Liquidación", font=("Segoe UI", 9, "bold"), 
                                      bg=self.t["btn_warning_bg"], fg=self.t["btn_warning_fg"], 
                                      activebackground=self.t["btn_warning_hover"],
                                      activeforeground=self.t["btn_warning_fg"],
                                      relief="flat", cursor="hand2", padx=8, pady=3, command=self._pedir_liquidacion)
                btn_pedir.pack(side="left")
                
                self._actualizar_comision_empleado()
            else:
                # Perfil Administrador: Alerta de solicitudes de liquidación en tiempo real
                self.btn_notif_liq = tk.Button(
                    self.info_strip,
                    text="✅ Sin solicitudes pendientes",
                    font=("Segoe UI", 9, "bold"),
                    bg=self.t["btn_secondary_bg"],
                    fg=self.t["btn_secondary_fg"],
                    activebackground=self.t["btn_secondary_hover"],
                    activeforeground=self.t["btn_secondary_fg"],
                    relief="flat",
                    cursor="hand2",
                    padx=8,
                    pady=3,
                    command=self._abrir_nomina
                )
                self.btn_notif_liq.pack(side="left")
                self._actualizar_notificaciones_admin()

            # Actualizar fecha y hora
            self._actualizar_fecha_hora()
        except Exception as e:
            print(f"Error creando header: {e}")

    def _actualizar_notificaciones_admin(self):
        try:
            if hasattr(self, 'btn_notif_liq') and self.btn_notif_liq.winfo_exists():
                activas = []
                try:
                    try:
                        from interface.nomina_manager import obtener_solicitudes_liquidacion_pendientes
                    except ImportError:
                        from nomina_manager import obtener_solicitudes_liquidacion_pendientes
                    activas = obtener_solicitudes_liquidacion_pendientes()
                except Exception:
                    pass

                if not activas and getattr(api, "token", None):
                    try:
                        resp = api.get("/nomina/solicitudes-pendientes")
                        if resp.status_code == 200:
                            solicitudes = resp.json()
                            activas = [s for s in solicitudes if s.get("activa", True)]
                    except Exception:
                        pass

                if activas:
                    cant = len(activas)
                    nombres = ", ".join((s.get("nombre_completo") or s.get("usuario", "")) for s in activas[:2])
                    total_liq = sum(float(s.get("saldo_pendiente", s.get("comisiones_pendientes", 0.0)) or 0.0) for s in activas)
                    txt = f"🔔 {cant} Solicitud{'es' if cant > 1 else ''}: {nombres} (${total_liq:,.0f}) [Liquidar]"
                    self.btn_notif_liq.config(
                        text=txt,
                        bg=self.t["btn_warning_bg"],
                        fg=self.t["btn_warning_fg"],
                        activebackground=self.t["btn_warning_hover"],
                        activeforeground=self.t["btn_warning_fg"]
                    )
                else:
                    self.btn_notif_liq.config(
                        text="✅ Sin solicitudes pendientes",
                        bg=self.t["btn_secondary_bg"],
                        fg=self.t["btn_secondary_fg"],
                        activebackground=self.t["btn_secondary_hover"],
                        activeforeground=self.t["btn_secondary_fg"]
                    )
        except Exception as e:
            print("Error en notificaciones admin:", e)
        finally:
            if hasattr(self, 'btn_notif_liq') and self.winfo_exists() and session_mgr.sesion_activa:
                self.after(5000, self._actualizar_notificaciones_admin)

    def _cerrar_sesion(self):
        """Cierra la sesión actual y vuelve a la pantalla de login de forma segura."""
        if messagebox.askyesno("Cerrar Sesión", "¿Estás seguro que deseas cerrar sesión?"):
            session_mgr.cerrar_sesion(root_window=self, lanzar_login=True)

    def _actualizar_comision_empleado(self):
        try:
            if hasattr(self, 'lbl_comision') and self.lbl_comision.winfo_exists():
                try:
                    from interface.nomina_manager import obtener_resumen_ventas_y_recaudo_empleado
                except ImportError:
                    from nomina_manager import obtener_resumen_ventas_y_recaudo_empleado
                uid = self.datos_usuario.get("id")
                resumen = obtener_resumen_ventas_y_recaudo_empleado(
                    usuario_id=int(uid) if uid and str(uid).isdigit() else None,
                    usuario_nombre=self.usuario,
                    rol=self.rol_usuario
                )
                recaudo_hoy = float(resumen.get("recaudado_hoy", 0.0))
                nom_pend = float(resumen.get("nomina_por_cobrar", 0.0))
                self.lbl_comision.config(text=f"💰 Recaudado hoy: ${recaudo_hoy:,.0f} COP | Nómina pend.: ${nom_pend:,.0f} COP")
        except Exception as e:
            print("Error actualizando comisión:", e)
        finally:
            if hasattr(self, 'lbl_comision') and self.winfo_exists():
                self.after(5000, self._actualizar_comision_empleado)

    def _pedir_liquidacion(self):
        try:
            try:
                from interface.nomina_manager import solicitar_liquidacion_empleado
            except ImportError:
                from nomina_manager import solicitar_liquidacion_empleado
            uid = self.datos_usuario.get("id")
            res_loc = solicitar_liquidacion_empleado(
                usuario_id=int(uid) if uid and str(uid).isdigit() else None,
                usuario_nombre=self.usuario
            )
            if getattr(api, "token", None):
                try:
                    api.post("/nomina/solicitar-liquidacion")
                except Exception:
                    pass

            if res_loc.get("exito"):
                com_pend = float(res_loc.get("saldo_pendiente", 0.0))
                messagebox.showinfo(
                    "✅ Solicitud Enviada",
                    f"¡Has solicitado tu liquidación con éxito!\n\n"
                    f"💰 Saldo pendiente de nómina: ${com_pend:,.0f} COP\n\n"
                    f"El administrador ha recibido la notificación en su perfil."
                )
            else:
                messagebox.showwarning("Aviso", res_loc.get("mensaje", "No se pudo registrar la solicitud."))
        except Exception as e:
            messagebox.showerror("Error", f"Error al solicitar liquidación: {e}")

    def _actualizar_fecha_hora(self):
        """Actualiza la fecha y hora en tiempo real."""
        try:
            if hasattr(self, 'lbl_fecha_hora') and self.lbl_fecha_hora.winfo_exists():
                now = datetime.datetime.now()
                fecha_actual = now.strftime("%d/%m/%Y")
                hora_actual = now.strftime("%H:%M:%S")
                self.lbl_fecha_hora.config(text=f"📅 {fecha_actual} • 🕐 {hora_actual}")
                # Programar la siguiente actualización en 1 segundo
                self.after(1000, self._actualizar_fecha_hora)
        except Exception as e:
            print(f"Error actualizando fecha/hora: {e}")

    def _obtener_datos_dashboard(self):
        """Obtiene las estadísticas reales del día y mes para el dashboard (API o SQLite)."""
        def _peso(v):
            try: return f"${v:,.0f} COP"
            except: return "$0 COP"

        now = datetime.datetime.now()
        hoy_iso = now.strftime("%Y-%m-%d")
        hoy_dmy = now.strftime("%d-%m-%Y")
        mes_iso = now.strftime("%Y-%m")
        mes_dmy = now.strftime("%m-%Y")

        ventas_hoy = 0.0
        ganancias_hoy = 0.0
        pedidos_hoy = 0
        clientes_hoy = 0
        producto_top = "Sin ventas"
        sub_top = "Sin registros"
        total_productos = 0
        total_clientes = 0
        ventas_mes = 0.0
        ganancias_mes = 0.0
        pedidos_mes = 0

        # 1. Intentar API si hay token activo
        if getattr(api, "token", None):
            try:
                resp = api.get("/reportes/resumen-diario", params={"fecha": hoy_iso})
                if resp.status_code == 200:
                    d = resp.json()
                    v_api = float(d.get("ventas", 0.0))
                    g_api = float(d.get("neto", d.get("caja_efectivo", 0.0)))
                    p_api = int(d.get("pedidos", 0))
                    c_api = int(d.get("clientes", 0))
                    if v_api > 0: ventas_hoy = v_api
                    if g_api > 0: ganancias_hoy = g_api
                    if p_api > 0: pedidos_hoy = p_api
                    if c_api > 0: clientes_hoy = c_api
                    if d.get("producto_top"): producto_top = str(d.get("producto_top"))
            except Exception:
                pass

        # 2. Consultar o complementar con SQLite local (database/ventas.db)
        try:
            if obtener_resumen_financiero:
                try:
                    res_fin = obtener_resumen_financiero(fecha=hoy_iso)
                    if res_fin:
                        ventas_hoy = res_fin.get("ventas_totales_facturadas", 0.0)
                        pedidos_hoy = res_fin.get("cantidad_ventas", 0)
                        ganancias_hoy = res_fin.get("ganancia_neta_estimada", 0.0)
                except Exception as e_rf:
                    print(f"Aviso resumen financiero: {e_rf}")

            conn = _conectar_db()
            if conn:
                cur = conn.cursor()

                # Ventas y pedidos de hoy (con soporte de formato fecha ISO y DMY con o sin hora)
                try:
                    cur.execute("""
                        SELECT COALESCE(SUM(total_venta), 0.0), COUNT(id_venta)
                        FROM ventas
                        WHERE (fecha_venta = ? OR fecha_venta = ? OR fecha_venta LIKE ? OR fecha_venta LIKE ?)
                          AND (estado IS NULL OR estado != 'Anulada')
                    """, (hoy_iso, hoy_dmy, f"{hoy_iso}%", f"{hoy_dmy}%"))
                    row_v = cur.fetchone()
                    if row_v and row_v[0] is not None:
                        v_sql = float(row_v[0])
                        p_sql = int(row_v[1])
                        if v_sql > 0 or ventas_hoy == 0.0:
                            ventas_hoy = max(ventas_hoy, v_sql)
                            pedidos_hoy = max(pedidos_hoy, p_sql)
                except Exception as e_v:
                    print(f"Aviso consultando ventas hoy: {e_v}")

                # Ventas del mes actual para contexto comercial
                try:
                    cur.execute("""
                        SELECT COALESCE(SUM(total_venta), 0.0), COUNT(id_venta)
                        FROM ventas
                        WHERE (fecha_venta LIKE ? OR fecha_venta LIKE ?)
                          AND (estado IS NULL OR estado != 'Anulada')
                    """, (f"{mes_iso}%", f"%-{mes_dmy}%"))
                    row_m = cur.fetchone()
                    if row_m and row_m[0]:
                        ventas_mes = float(row_m[0])
                        pedidos_mes = int(row_m[1])
                except Exception:
                    pass

                # Gastos de hoy y del mes
                gastos_hoy = 0.0
                gastos_mes = 0.0
                try:
                    cur.execute("""
                        SELECT COALESCE(SUM(valor), 0.0) FROM gastos
                        WHERE fecha = ? OR fecha = ? OR fecha LIKE ? OR fecha LIKE ?
                    """, (hoy_dmy, hoy_iso, f"{hoy_dmy}%", f"{hoy_iso}%"))
                    row_g = cur.fetchone()
                    gastos_hoy = float(row_g[0]) if row_g and row_g[0] else 0.0

                    cur.execute("""
                        SELECT COALESCE(SUM(valor), 0.0) FROM gastos
                        WHERE fecha LIKE ? OR fecha LIKE ?
                    """, (f"%-{mes_dmy}%", f"{mes_iso}%"))
                    row_gm = cur.fetchone()
                    gastos_mes = float(row_gm[0]) if row_gm and row_gm[0] else 0.0
                except Exception:
                    pass

                # Ganancia neta calculada
                if ganancias_hoy == 0.0:
                    ganancias_hoy = max(0.0, ventas_hoy - gastos_hoy)
                ganancias_mes = max(0.0, ventas_mes - gastos_mes)

                # Clientes únicos de hoy y total en sistema
                try:
                    cur.execute("""
                        SELECT COUNT(DISTINCT documento_cliente) FROM ventas
                        WHERE (fecha_venta = ? OR fecha_venta = ? OR fecha_venta LIKE ? OR fecha_venta LIKE ?)
                          AND (estado IS NULL OR estado != 'Anulada')
                    """, (hoy_iso, hoy_dmy, f"{hoy_iso}%", f"{hoy_dmy}%"))
                    row_c = cur.fetchone()
                    if row_c and row_c[0]:
                        clientes_hoy = max(clientes_hoy, int(row_c[0]))

                    cur.execute("SELECT COUNT(*) FROM clientes")
                    row_tc = cur.fetchone()
                    total_clientes = int(row_tc[0]) if row_tc else 0
                except Exception:
                    pass

                # Producto Top (hoy -> mes -> histórico)
                try:
                    # 1º Buscar producto más vendido hoy
                    cur.execute("""
                        SELECT dv.nombre_producto, SUM(dv.cantidad) as cant
                        FROM detalle_ventas dv
                        JOIN ventas v ON dv.id_venta = v.id_venta
                        WHERE (v.fecha_venta = ? OR v.fecha_venta = ? OR v.fecha_venta LIKE ? OR v.fecha_venta LIKE ?)
                          AND (v.estado IS NULL OR v.estado != 'Anulada')
                        GROUP BY dv.nombre_producto
                        ORDER BY cant DESC LIMIT 1
                    """, (hoy_iso, hoy_dmy, f"{hoy_iso}%", f"{hoy_dmy}%"))
                    row_top = cur.fetchone()
                    if row_top and row_top[0]:
                        cant_txt = f"{int(row_top[1])} ud" if row_top[1] == 1 else f"{int(row_top[1])} uds"
                        producto_top = f"{row_top[0]} ({cant_txt})"
                        sub_top = "Líder de hoy"
                    else:
                        # 2º Buscar producto más vendido del mes actual
                        cur.execute("""
                            SELECT dv.nombre_producto, SUM(dv.cantidad) as cant
                            FROM detalle_ventas dv
                            JOIN ventas v ON dv.id_venta = v.id_venta
                            WHERE (v.fecha_venta LIKE ? OR v.fecha_venta LIKE ?)
                              AND (v.estado IS NULL OR v.estado != 'Anulada')
                            GROUP BY dv.nombre_producto
                            ORDER BY cant DESC LIMIT 1
                        """, (f"{mes_iso}%", f"%-{mes_dmy}%"))
                        row_top_m = cur.fetchone()
                        if row_top_m and row_top_m[0]:
                            cant_txt = f"{int(row_top_m[1])} ud" if row_top_m[1] == 1 else f"{int(row_top_m[1])} uds"
                            producto_top = f"{row_top_m[0]} ({cant_txt})"
                            sub_top = "Top del mes"
                        else:
                            # 3º Fallback al líder histórico
                            cur.execute("""
                                SELECT dv.nombre_producto, SUM(dv.cantidad) as cant
                                FROM detalle_ventas dv
                                GROUP BY dv.nombre_producto
                                ORDER BY cant DESC LIMIT 1
                            """)
                            row_top_h = cur.fetchone()
                            if row_top_h and row_top_h[0]:
                                cant_txt = f"{int(row_top_h[1])} ud" if row_top_h[1] == 1 else f"{int(row_top_h[1])} uds"
                                producto_top = f"{row_top_h[0]} ({cant_txt})"
                                sub_top = "Top histórico"
                            else:
                                producto_top = "Sin ventas"
                                sub_top = "Sin registros"
                except Exception:
                    pass

                # Total productos en inventario
                try:
                    cur.execute("SELECT COUNT(*) FROM productos")
                    row_p = cur.fetchone()
                    total_productos = int(row_p[0]) if row_p else 0
                except Exception:
                    pass

                conn.close()
        except Exception as e:
            print(f"Aviso obteniendo estadísticas dashboard: {e}")

        # Subtítulos informativos para las tarjetas
        ventas_sub = f"{pedidos_hoy} pedidos hoy" if pedidos_hoy > 0 else (f"Mes: {_peso(ventas_mes)}" if ventas_mes > 0 else "Sin ventas hoy")
        ganancias_sub = "Utilidad neta hoy" if ganancias_hoy > 0 else (f"Mes: {_peso(ganancias_mes)}" if ganancias_mes > 0 else "Sin movimientos")
        pedidos_sub = "Transacciones hoy" if pedidos_hoy > 0 else (f"Mes: {pedidos_mes} pedidos" if pedidos_mes > 0 else "0 en el mes")
        clientes_sub = f"{clientes_hoy} hoy (Total: {total_clientes})"

        return {
            "ventas_hoy": ventas_hoy,
            "ventas_sub": ventas_sub,
            "ganancias": ganancias_hoy,
            "ganancias_sub": ganancias_sub,
            "pedidos": pedidos_hoy,
            "pedidos_sub": pedidos_sub,
            "producto_top": producto_top,
            "producto_top_sub": sub_top,
            "clientes": clientes_hoy,
            "clientes_sub": clientes_sub,
            "productos": total_productos
        }

    def _obtener_ganancias_hoy(self):
        return self._obtener_datos_dashboard().get("ganancias", 0.0)

    def _obtener_total_productos_inventario(self):
        return self._obtener_datos_dashboard().get("productos", 0)

    def _obtener_clientes_unicos_hoy(self):
        return self._obtener_datos_dashboard().get("clientes", 0)

    def _obtener_pedidos_hoy(self):
        return self._obtener_datos_dashboard().get("pedidos", 0)

    def _verificar_asistencia(self):
        """Verifica el estado de asistencia del vendedor / empleado para el día actual (Fase 3)"""
        try:
            try:
                from interface.nomina_manager import obtener_resumen_ventas_y_recaudo_empleado
            except ImportError:
                from nomina_manager import obtener_resumen_ventas_y_recaudo_empleado

            uid = self.datos_usuario.get("id")
            resumen = obtener_resumen_ventas_y_recaudo_empleado(
                usuario_id=int(uid) if uid and str(uid).isdigit() else None,
                usuario_nombre=self.usuario,
                rol=self.rol_usuario
            )
            estado_asist = resumen.get("asistencia_estado", "No registrada")
            sal_gen = bool(resumen.get("salario_diario_generado_hoy", False))

            if hasattr(self, 'lbl_asistencia_status') and self.lbl_asistencia_status.winfo_exists():
                if estado_asist == "Presente":
                    det_sal = " • Salario diario generado" if sal_gen else ""
                    self.lbl_asistencia_status.config(
                        text=f"✅ ASISTENCIA DE HOY CONFIRMADA ({estado_asist}){det_sal} • Recaudo diario activo",
                        fg=self.t.get("btn_success_bg", "#059669")
                    )
                elif "Sin Venta" in str(estado_asist):
                    self.lbl_asistencia_status.config(
                        text="⏳ ASISTENCIA MARCADA (SIN VENTA) • Procesa tu primera venta válida del día para activar tu salario diario.",
                        fg=self.t.get("warning", "#D97706")
                    )
                else:
                    self.lbl_asistencia_status.config(
                        text="⏳ ASISTENCIA PENDIENTE • Para confirmar tu asistencia y cargar tu recaudo diario, procesa al menos una venta.",
                        fg=self.t.get("warning", "#D97706")
                    )
        except Exception as e:
            print("Aviso verificando asistencia:", e)

    def _actualizar_estadisticas(self):
        """Actualiza todas las estadísticas del dashboard en tiempo real."""
        try:
            datos = self._obtener_datos_dashboard()
            widgets_updates = {
                'ventas_hoy': self._formato_peso(datos["ventas_hoy"]),
                'ganancias': self._formato_peso(datos["ganancias"]),
                'pedidos': str(datos["pedidos"]),
                'producto_top': str(datos["producto_top"]),
                'clientes': str(datos["clientes"]),
                'productos': str(datos["productos"])
            }

            sub_updates = {
                'ventas_hoy': datos.get("ventas_sub", ""),
                'ganancias': datos.get("ganancias_sub", ""),
                'pedidos': datos.get("pedidos_sub", ""),
                'producto_top': datos.get("producto_top_sub", ""),
                'clientes': datos.get("clientes_sub", "")
            }

            for key, value in widgets_updates.items():
                try:
                    if key in self.stats_widgets and self.stats_widgets[key] and self.stats_widgets[key].winfo_exists():
                        self.stats_widgets[key].config(text=value)
                except tk.TclError:
                    pass
                except Exception as e:
                    print(f"Error actualizando widget {key}: {e}")

            for key, sub_val in sub_updates.items():
                try:
                    if hasattr(self, 'stats_sub_widgets') and key in self.stats_sub_widgets and self.stats_sub_widgets[key] and self.stats_sub_widgets[key].winfo_exists():
                        self.stats_sub_widgets[key].config(text=sub_val)
                except tk.TclError:
                    pass
                except Exception:
                    pass
        except Exception as e:
            print(f"Error general al actualizar estadísticas: {e}")

    def _formato_peso(self, valor):
        """Formatea un valor numérico al formato peso colombiano."""
        try:
            return f"${valor:,.0f} COP"
        except (ValueError, TypeError):
            return "$0 COP"

    def _programa_actualizacion_stats(self):
        """Programa la próxima actualización de estadísticas."""
        try:
            if self.winfo_exists():
                self._actualizar_estadisticas()
                self.after(30000, self._programa_actualizacion_stats)
        except tk.TclError:
            # Ventana ya cerrada
            pass

    def _create_main_content(self):
        """Crea y empaqueta el área de contenido principal, incluyendo estadísticas y botones."""
        try:
            main_content = tk.Frame(self, bg=self.t["bg_app"])
            main_content.pack(fill="both", expand=True, padx=20, pady=15)

            if self.rol_usuario == "operario":
                self._create_empleado_dashboard(main_content)
            else:
                if self.rol_usuario in ("vendedor", "empleado"):
                    self._create_vendedor_summary_strip(main_content)
                self._create_stats_panel(main_content)
                self._create_buttons_panel(main_content)
                self._create_quick_access_panel(main_content)
                
                # Mostrar información del modo vendedor si aplica
                if self.rol_usuario == "vendedor":
                    permisos_info = tk.Frame(main_content, bg=self.t["bg_surface"], bd=1, relief="solid", height=36)
                    permisos_info.pack(fill="x", pady=(8, 0))

                    tk.Label(permisos_info, text="🛍️ MODO VENDEDOR: Acceso a Ventas, Control de Caja y Mi Nómina (Historial)", 
                             font=("Segoe UI", 9, "bold"), bg=self.t["bg_surface"], fg=self.t["btn_warning_bg"]).pack(pady=6)
        except Exception as e:
            print(f"Error creando contenido principal: {e}")

    def _create_vendedor_summary_strip(self, parent):
        """Barra de indicadores claros para el vendedor en el Dashboard principal (Fase 6)."""
        bg_card = self.t["bg_surface"]
        fg_main = self.t["text_main"]
        fg_muted = self.t["text_muted"]

        self.asistencia_banner = tk.Frame(parent, bg=bg_card, bd=1, relief="solid")
        self.asistencia_banner.pack(fill="x", pady=(0, 6))
        self.lbl_asistencia_status = tk.Label(
            self.asistencia_banner,
            text="⏳ Consultando estado de asistencia...",
            font=("Segoe UI", 9, "bold"),
            bg=bg_card, fg=self.t.get("warning", "#D97706"),
            padx=10, pady=4
        )
        self.lbl_asistencia_status.pack(side="left")

        strip = tk.Frame(parent, bg=self.t["bg_app"])
        strip.pack(fill="x", pady=(0, 8))

        def _mini_card(col_bar, titulo, attr_val, attr_sub=None, on_click=None):
            c = tk.Frame(strip, bg=bg_card, bd=1, relief="solid", cursor="hand2" if on_click else "")
            c.pack(side="left", fill="both", expand=True, padx=4)
            bar = tk.Frame(c, bg=col_bar, height=3)
            bar.pack(fill="x")
            lbl_t = tk.Label(c, text=titulo, font=("Segoe UI", 8, "bold"), bg=bg_card, fg=fg_muted, cursor="hand2" if on_click else "")
            lbl_t.pack(pady=(4, 0))
            lbl_v = tk.Label(c, text="$0 COP", font=("Segoe UI", 12, "bold"), bg=bg_card, fg=fg_main, cursor="hand2" if on_click else "")
            lbl_v.pack(pady=(1, 2))
            setattr(self, attr_val, lbl_v)
            lbl_s = None
            if attr_sub:
                lbl_s = tk.Label(c, text="", font=("Segoe UI", 8), bg=bg_card, fg=fg_muted, cursor="hand2" if on_click else "")
                lbl_s.pack(pady=(0, 4))
                setattr(self, attr_sub, lbl_s)
            if on_click:
                for w in (c, bar, lbl_t, lbl_v, lbl_s):
                    if w is not None:
                        w.bind("<Button-1>", lambda e: on_click())

        _mini_card("#D97706", "📝 Por cobrar (Clientes)", "lbl_emp_por_cobrar")
        _mini_card("#059669", "✅ Total pagado (Clientes)", "lbl_emp_total_pagado")
        _mini_card("#2563EB", "💰 Recaudado hoy", "lbl_emp_comision", "lbl_emp_comision_sub")
        _mini_card("#7C3AED", "🧾 Mi nómina por cobrar (Ver Historial)", "lbl_emp_nomina_pend", "lbl_emp_nomina_pagada_sub", on_click=self._mostrar_nomina_empleado)

        self._actualizar_estadisticas_empleado()

    def _create_empleado_dashboard(self, parent):
        """Diseño específico para el dashboard del empleado con indicadores separados de clientes y nómina (Fase 6)."""
        bg_app = self.t["bg_app"]
        bg_card = self.t["bg_surface"]
        fg_main = self.t["text_main"]
        fg_muted = self.t["text_muted"]

        tk.Label(parent, text=f"✨ Bienvenido/a a tu panel, {self.usuario} ✨", 
                 font=("Segoe UI", 17, "bold"), bg=bg_app, fg=self.t["bg_header"]).pack(pady=(8, 4))

        # Banner de estado de asistencia
        self.asistencia_banner = tk.Frame(parent, bg=bg_card, bd=1, relief="solid")
        self.asistencia_banner.pack(fill="x", pady=(0, 8))
        self.lbl_asistencia_status = tk.Label(
            self.asistencia_banner, 
            text="⏳ Consultando estado de asistencia...",
            font=("Segoe UI", 10, "bold"),
            bg=bg_card, fg=self.t.get("warning", "#D97706"),
            padx=12, pady=5
        )
        self.lbl_asistencia_status.pack(fill="x")
        
        # Fila 1: Indicadores de Ventas y Cobros de Clientes (Fase 6)
        cards_clientes = tk.Frame(parent, bg=bg_app)
        cards_clientes.pack(fill="x", pady=(2, 8))
        
        # Tarjeta 1: Por cobrar (Clientes / Fiados pendientes)
        c_pc = tk.Frame(cards_clientes, bg=bg_card, bd=1, relief="solid")
        c_pc.pack(side="left", fill="both", expand=True, padx=(0, 8))
        tk.Frame(c_pc, bg="#D97706", height=4).pack(fill="x")
        tk.Label(c_pc, text="📝 Por cobrar", font=("Segoe UI", 10, "bold"), bg=bg_card, fg=fg_muted).pack(pady=(8, 0))
        self.lbl_emp_por_cobrar = tk.Label(c_pc, text="$0 COP", font=("Segoe UI", 16, "bold"), bg=bg_card, fg="#D97706")
        self.lbl_emp_por_cobrar.pack(pady=(2, 2))
        tk.Label(c_pc, text="Saldo pendiente de clientes (Fiados)", font=("Segoe UI", 8), bg=bg_card, fg=fg_muted).pack(pady=(0, 8))

        # Tarjeta 2: Total pagado (Clientes)
        c_tp = tk.Frame(cards_clientes, bg=bg_card, bd=1, relief="solid")
        c_tp.pack(side="left", fill="both", expand=True, padx=4)
        tk.Frame(c_tp, bg="#059669", height=4).pack(fill="x")
        tk.Label(c_tp, text="✅ Total pagado", font=("Segoe UI", 10, "bold"), bg=bg_card, fg=fg_muted).pack(pady=(8, 0))
        self.lbl_emp_total_pagado = tk.Label(c_tp, text="$0 COP", font=("Segoe UI", 16, "bold"), bg=bg_card, fg="#059669")
        self.lbl_emp_total_pagado.pack(pady=(2, 2))
        tk.Label(c_tp, text="Total efectivamente pagado por clientes", font=("Segoe UI", 8), bg=bg_card, fg=fg_muted).pack(pady=(0, 8))

        # Tarjeta 3: Recaudado hoy
        c_rh = tk.Frame(cards_clientes, bg=bg_card, bd=1, relief="solid")
        c_rh.pack(side="left", fill="both", expand=True, padx=(8, 0))
        tk.Frame(c_rh, bg="#2563EB", height=4).pack(fill="x")
        tk.Label(c_rh, text="💰 Recaudado hoy", font=("Segoe UI", 10, "bold"), bg=bg_card, fg=fg_muted).pack(pady=(8, 0))
        self.lbl_emp_comision = tk.Label(c_rh, text="$0 COP", font=("Segoe UI", 16, "bold"), bg=bg_card, fg="#2563EB")
        self.lbl_emp_comision.pack(pady=(2, 2))
        self.lbl_emp_comision_sub = tk.Label(c_rh, text="Efectivo + Transferencias + Abonos hoy", font=("Segoe UI", 8), bg=bg_card, fg=fg_muted)
        self.lbl_emp_comision_sub.pack(pady=(0, 8))

        # Fila 2: Indicadores de Nómina del Empleado y Actividad (Claramente etiquetados)
        cards_nomina = tk.Frame(parent, bg=bg_app)
        cards_nomina.pack(fill="x", pady=(2, 10))

        # Tarjeta 4: Ventas Hoy (Cantidad)
        c1 = tk.Frame(cards_nomina, bg=bg_card, bd=1, relief="solid")
        c1.pack(side="left", fill="both", expand=True, padx=(0, 8))
        tk.Frame(c1, bg="#38BDF8", height=4).pack(fill="x")
        tk.Label(c1, text="🛍️ Ventas Hoy", font=("Segoe UI", 10, "bold"), bg=bg_card, fg=fg_muted).pack(pady=(8, 0))
        self.lbl_emp_ventas = tk.Label(c1, text="0", font=("Segoe UI", 15, "bold"), bg=bg_card, fg=fg_main)
        self.lbl_emp_ventas.pack(pady=(2, 8))

        # Tarjeta 5: Mi nómina por cobrar
        c2 = tk.Frame(cards_nomina, bg=bg_card, bd=1, relief="solid")
        c2.pack(side="left", fill="both", expand=True, padx=4)
        tk.Frame(c2, bg="#7C3AED", height=4).pack(fill="x")
        tk.Label(c2, text="🧾 Mi nómina por cobrar", font=("Segoe UI", 10, "bold"), bg=bg_card, fg=fg_muted).pack(pady=(8, 0))
        self.lbl_emp_nomina_pend = tk.Label(c2, text="$0 COP", font=("Segoe UI", 15, "bold"), bg=bg_card, fg="#7C3AED")
        self.lbl_emp_nomina_pend.pack(pady=(2, 2))
        self.lbl_emp_nomina_pagada_sub = tk.Label(c2, text="Devengado hoy: $0 COP", font=("Segoe UI", 8), bg=bg_card, fg=fg_muted)
        self.lbl_emp_nomina_pagada_sub.pack(pady=(0, 8))
        
        # Tarjeta 6: Mi nómina pagada
        c3 = tk.Frame(cards_nomina, bg=bg_card, bd=1, relief="solid")
        c3.pack(side="left", fill="both", expand=True, padx=(8, 0))
        tk.Frame(c3, bg="#FBBF24", height=4).pack(fill="x")
        tk.Label(c3, text="💎 Mi nómina pagada", font=("Segoe UI", 10, "bold"), bg=bg_card, fg=fg_muted).pack(pady=(8, 0))
        self.lbl_emp_mes = tk.Label(c3, text="$0 COP", font=("Segoe UI", 15, "bold"), bg=bg_card, fg=fg_main)
        self.lbl_emp_mes.pack(pady=(2, 8))

        # Estado del turno visible desde el menú principal y actualizado en tiempo real.
        turno_card = tk.Frame(parent, bg=bg_card, bd=1, relief="solid")
        turno_card.pack(fill="x", pady=(0, 10))
        tk.Frame(turno_card, bg="#0284C7", height=4).pack(fill="x")
        turno_body = tk.Frame(turno_card, bg=bg_card, padx=14, pady=8)
        turno_body.pack(fill="x")
        tk.Label(turno_body, text="⏱️ MI TURNO", font=("Segoe UI", 10, "bold"), bg=bg_card, fg=fg_muted).pack(side="left")
        self.lbl_estado_turno = tk.Label(turno_body, text="Consultando...", font=("Segoe UI", 13, "bold"), bg=bg_card, fg=fg_main)
        self.lbl_estado_turno.pack(side="left", padx=(14, 8))
        self.lbl_posicion_turno = tk.Label(turno_body, text="", font=("Segoe UI", 10), bg=bg_card, fg=fg_muted)
        self.lbl_posicion_turno.pack(side="left", padx=(0, 12))
        self.btn_estado_turno = crear_boton(
            turno_body, "🟡 MARCAR OCUPADO", self._alternar_estado_turno,
            tipo="warning", ancho=19, alto=1, tam_fuente=9
        )
        self.btn_estado_turno.pack(side="right", padx=(6, 0))
        self.btn_almuerzo_turno = crear_boton(
            turno_body, "🍱 SALIR A ALMUERZO", self._alternar_almuerzo_turno,
            tipo="danger", ancho=20, alto=1, tam_fuente=9
        )
        self.btn_almuerzo_turno.pack(side="right")
        
        # Botones de Acción con contraste certificado
        btn_frame = tk.Frame(parent, bg=bg_app)
        btn_frame.pack(fill="x", pady=15)
        
        btn_v = crear_boton(btn_frame, "IR A VENTAS", lambda: self._accion("Ventas"), tipo="primary", icono="🛒", ancho=18, alto=2, tam_fuente=11)
        btn_v.pack(side="left", expand=True, padx=8)

        btn_t = crear_boton(btn_frame, "MI TURNO / COLA", lambda: self._accion("Turnos"), tipo="info", icono="⏱️", ancho=20, alto=2, tam_fuente=11)
        btn_t.pack(side="left", expand=True, padx=8)
        
        btn_n = crear_boton(btn_frame, "MI NÓMINA Y COMISIONES", self._mostrar_nomina_empleado, tipo="purple", icono="🧾", ancho=22, alto=2, tam_fuente=11)
        btn_n.pack(side="left", expand=True, padx=8)
                  
        self._actualizar_estadisticas_empleado()
        self._actualizar_estado_turno()

    def _actualizar_estado_turno(self):
        """Actualiza el aviso del turno del operario desde el estado del servidor."""
        try:
            resp = api.get("/turnos/estado-actual")
            if resp.status_code != 200:
                return
            mi_turno = resp.json().get("mi_turno") or {}
            estado = mi_turno.get("estado", "FUERA_DE_TURNO")
            colores = {
                "EN_TURNO": "#2563EB", "DISPONIBLE": "#059669",
                "OCUPADO": "#D97706", "ALMUERZO": "#EA580C",
                "FUERA_DE_TURNO": "#64748B"
            }
            iconos = {"EN_TURNO": "🔵", "DISPONIBLE": "🟢", "OCUPADO": "🟡", "ALMUERZO": "🟠"}
            etiqueta = f"{iconos.get(estado, '⚪')} {estado.replace('_', ' ')}"
            self.lbl_estado_turno.config(text=etiqueta, fg=colores.get(estado, "#64748B"))
            self.lbl_posicion_turno.config(text=f"Turno #{mi_turno.get('posicion', '--')}")

            if estado == "OCUPADO":
                self.btn_estado_turno.config(text="🟢 MARCAR DISPONIBLE")
            else:
                self.btn_estado_turno.config(text="🟡 MARCAR OCUPADO")
            if estado == "ALMUERZO":
                self.btn_almuerzo_turno.config(text="🚀 REGRESÉ DE ALMUERZO")
                self.btn_estado_turno.config(state="disabled")
            else:
                self.btn_almuerzo_turno.config(text="🍱 SALIR A ALMUERZO")
                self.btn_estado_turno.config(state="normal")
        except Exception as e:
            print("Error actualizando estado de turno:", e)
        finally:
            if self.winfo_exists():
                self.after(2500, self._actualizar_estado_turno)

    def _alternar_estado_turno(self):
        try:
            estado_actual = self.lbl_estado_turno.cget("text")
            nuevo_estado = "DISPONIBLE" if "OCUPADO" in estado_actual else "OCUPADO"
            resp = api.post("/turnos/disponibilidad", json={"estado": nuevo_estado, "motivo": "Cambio desde el menú principal"})
            if resp.status_code != 200:
                messagebox.showerror("Turno", resp.json().get("detail", resp.text), parent=self)
            else:
                self._actualizar_estado_turno()
        except Exception as e:
            messagebox.showerror("Turno", str(e), parent=self)

    def _alternar_almuerzo_turno(self):
        try:
            en_almuerzo = "ALMUERZO" in self.lbl_estado_turno.cget("text")
            ruta = "/turnos/almuerzo/finalizar" if en_almuerzo else "/turnos/almuerzo/iniciar"
            resp = api.post(ruta)
            if resp.status_code != 200:
                messagebox.showerror("Almuerzo", resp.json().get("detail", resp.text), parent=self)
            else:
                self._actualizar_estado_turno()
        except Exception as e:
            messagebox.showerror("Almuerzo", str(e), parent=self)

    def _mostrar_nomina_empleado(self):
        """
        Muestra la ventana de Nómina y Comisiones del Empleado (Fase 7 - Solo Lectura).
        Incluye las 5 tarjetas KPI (Salario diario generado, Comisiones generadas,
        Total devengado, Total pagado, Por cobrar de nómina) y las 3 pestañas de detalle
        (Historial de pagos, Detalle de jornadas, Detalle de ventas con comisión y ajustes).
        """
        modal = tk.Toplevel(self)
        session_mgr.registrar_ventana(modal)
        modal.title("🧾 Mi Nómina y Comisiones (Consulta de Empleado)")
        modal.transient(self)

        t_m = aplicar_tema(modal)
        calcular_geometria_segura(modal, 1020, 640, 840, 520)
        modal.configure(bg=t_m["bg_app"])

        # Encabezado
        bg_h = t_m["bg_header"]
        fg_h = t_m["text_header"]
        fg_sub = t_m["text_header_sub"]

        header_frame = tk.Frame(modal, bg=bg_h, height=68)
        header_frame.pack(fill="x")
        header_frame.pack_propagate(False)

        header_content = tk.Frame(header_frame, bg=bg_h)
        header_content.pack(fill="both", expand=True, padx=20, pady=10)

        title_box = tk.Frame(header_content, bg=bg_h)
        title_box.pack(side="left", fill="y")
        tk.Label(title_box, text="🧾 Mi Nómina y Comisiones", font=("Segoe UI", 16, "bold"), bg=bg_h, fg=fg_h).pack(anchor="w")
        nom_user = getattr(self, 'usuario', 'Empleado')
        rol_disp = getattr(self, 'rol_usuario_display', 'Empleado')
        lbl_sub = tk.Label(
            title_box,
            text=f"Empleado: {nom_user} ({rol_disp}) • Modo Solo Lectura",
            font=("Segoe UI", 9), bg=bg_h, fg=fg_sub
        )
        lbl_sub.pack(anchor="w")

        btn_header_box = tk.Frame(header_content, bg=bg_h)
        btn_header_box.pack(side="right", fill="y")

        def pedir_liq_modal():
            self._pedir_liquidacion()
            cargar_datos()

        btn_pedir = tk.Button(btn_header_box, text="📤 Solicitar Liquidación", font=("Segoe UI", 9, "bold"), 
                              bg=t_m["btn_warning_bg"], fg=calcular_color_texto_optimo(t_m["btn_warning_bg"]), 
                              relief="flat", cursor="hand2", padx=10, pady=4, 
                              command=pedir_liq_modal)
        btn_pedir.pack(side="right", padx=(8, 0))

        btn_recargar = tk.Button(btn_header_box, text="🔄 Actualizar", font=("Segoe UI", 9, "bold"), 
                                 bg=t_m["bg_surface"], fg=t_m["text_main"], relief="flat", cursor="hand2", padx=10, pady=4, 
                                 command=lambda: cargar_datos())
        btn_recargar.pack(side="right")

        # 5 Tarjetas de Resumen KPI (Fase 7)
        kpi_frame = tk.Frame(modal, bg=t_m["bg_app"])
        kpi_frame.pack(fill="x", padx=20, pady=(12, 8))

        def _crear_kpi_emp(titulo, color_bar, fg_val):
            card = tk.Frame(kpi_frame, bg=t_m["bg_surface"], bd=1, relief="solid")
            card.pack(side="left", fill="both", expand=True, padx=4)
            tk.Frame(card, bg=color_bar, height=4).pack(fill="x")
            tk.Label(card, text=titulo, font=("Segoe UI", 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_muted"]).pack(pady=(6, 0))
            lbl = tk.Label(card, text="$0 COP", font=("Segoe UI", 13, "bold"), bg=t_m["bg_surface"], fg=fg_val)
            lbl.pack(pady=(2, 6))
            return lbl

        lbl_kpi_salario = _crear_kpi_emp("📅 Salario Diario Generado", "#0284C7", "#0284C7")
        lbl_kpi_comisiones = _crear_kpi_emp("💼 Comisiones Generadas", "#D97706", "#D97706")
        lbl_kpi_devengado = _crear_kpi_emp("📈 Total Devengado", "#4F46E5", "#4F46E5")
        lbl_kpi_liquidado = _crear_kpi_emp("💎 Total Pagado", t_m["btn_purple_bg"], t_m["btn_purple_bg"])
        lbl_kpi_pendiente = _crear_kpi_emp("💰 Por Cobrar de Nómina", t_m["btn_success_bg"], t_m["btn_success_bg"])

        # Notebook (3 Pestañas requeridas en Fase 7)
        notebook_frame = tk.Frame(modal, bg=t_m["bg_app"])
        notebook_frame.pack(fill="both", expand=True, padx=20, pady=(4, 15))

        notebook = ttk.Notebook(notebook_frame)
        notebook.pack(fill="both", expand=True)

        # Tab 1: Historial de Pagos (Liquidaciones, Pagos Parciales y Anticipos)
        tab_pagos = tk.Frame(notebook, bg=t_m["bg_surface"])
        notebook.add(tab_pagos, text=" 🧾 Historial de Pagos ")

        cols_pagos = ("id", "fecha", "tipo", "metodo", "periodo", "monto", "responsable", "observaciones")
        tree_pagos = ttk.Treeview(tab_pagos, columns=cols_pagos, show="headings", selectmode="browse")
        tree_pagos.heading("id", text="# Pago")
        tree_pagos.heading("fecha", text="Fecha y Hora")
        tree_pagos.heading("tipo", text="Tipo de Pago")
        tree_pagos.heading("metodo", text="Medio")
        tree_pagos.heading("periodo", text="Período")
        tree_pagos.heading("monto", text="Monto Pagado")
        tree_pagos.heading("responsable", text="Responsable")
        tree_pagos.heading("observaciones", text="Observaciones")

        tree_pagos.column("id", width=65, anchor="center")
        tree_pagos.column("fecha", width=135, anchor="center")
        tree_pagos.column("tipo", width=130, anchor="center")
        tree_pagos.column("metodo", width=100, anchor="center")
        tree_pagos.column("periodo", width=110, anchor="center")
        tree_pagos.column("monto", width=125, anchor="e")
        tree_pagos.column("responsable", width=110, anchor="center")
        tree_pagos.column("observaciones", width=180, anchor="w")

        scroll_pagos = ttk.Scrollbar(tab_pagos, orient="vertical", command=tree_pagos.yview)
        tree_pagos.configure(yscrollcommand=scroll_pagos.set)
        tree_pagos.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scroll_pagos.pack(side="right", fill="y", padx=(0, 10), pady=10)

        # Tab 2: Detalle de Jornadas y Asistencia
        tab_jornadas = tk.Frame(notebook, bg=t_m["bg_surface"])
        notebook.add(tab_jornadas, text=" 📅 Detalle de Jornadas ")

        cols_jor = ("fecha", "hora", "estado", "primera_venta", "salario_gen", "monto_salario", "observaciones")
        tree_jor = ttk.Treeview(tab_jornadas, columns=cols_jor, show="headings", selectmode="browse")
        tree_jor.heading("fecha", text="Fecha")
        tree_jor.heading("hora", text="Hora Registro")
        tree_jor.heading("estado", text="Estado de Jornada")
        tree_jor.heading("primera_venta", text="1ra Venta #")
        tree_jor.heading("salario_gen", text="Salario Activado")
        tree_jor.heading("monto_salario", text="Salario Diario")
        tree_jor.heading("observaciones", text="Observaciones")

        tree_jor.column("fecha", width=105, anchor="center")
        tree_jor.column("hora", width=100, anchor="center")
        tree_jor.column("estado", width=190, anchor="center")
        tree_jor.column("primera_venta", width=95, anchor="center")
        tree_jor.column("salario_gen", width=115, anchor="center")
        tree_jor.column("monto_salario", width=125, anchor="e")
        tree_jor.column("observaciones", width=220, anchor="w")

        scroll_jor = ttk.Scrollbar(tab_jornadas, orient="vertical", command=tree_jor.yview)
        tree_jor.configure(yscrollcommand=scroll_jor.set)
        tree_jor.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scroll_jor.pack(side="right", fill="y", padx=(0, 10), pady=10)

        # Tab 3: Detalle de Ventas con Comisión y Devengos
        tab_com = tk.Frame(notebook, bg=t_m["bg_surface"])
        notebook.add(tab_com, text=" 💰 Detalle de Ventas con Comisión y Devengos ")

        cols_com = ("id", "fecha", "tipo", "venta", "item", "valor_venta", "porcentaje", "monto", "estado")
        tree_com = ttk.Treeview(tab_com, columns=cols_com, show="headings", selectmode="browse")
        tree_com.heading("id", text="ID")
        tree_com.heading("fecha", text="Fecha")
        tree_com.heading("tipo", text="Categoría")
        tree_com.heading("venta", text="N° Venta")
        tree_com.heading("item", text="Concepto / Producto / Servicio")
        tree_com.heading("valor_venta", text="Valor Base")
        tree_com.heading("porcentaje", text="%")
        tree_com.heading("monto", text="Monto Devengado")
        tree_com.heading("estado", text="Estado")

        tree_com.column("id", width=50, anchor="center")
        tree_com.column("fecha", width=95, anchor="center")
        tree_com.column("tipo", width=130, anchor="center")
        tree_com.column("venta", width=85, anchor="center")
        tree_com.column("item", width=230, anchor="w")
        tree_com.column("valor_venta", width=105, anchor="e")
        tree_com.column("porcentaje", width=55, anchor="center")
        tree_com.column("monto", width=120, anchor="e")
        tree_com.column("estado", width=95, anchor="center")

        scroll_com = ttk.Scrollbar(tab_com, orient="vertical", command=tree_com.yview)
        tree_com.configure(yscrollcommand=scroll_com.set)
        tree_com.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scroll_com.pack(side="right", fill="y", padx=(0, 10), pady=10)

        def cargar_datos():
            try:
                try:
                    from interface.nomina_manager import obtener_detalle_nomina_empleado
                except ImportError:
                    from nomina_manager import obtener_detalle_nomina_empleado

                uid = self.datos_usuario.get("id")
                uid_int = int(uid) if uid and str(uid).isdigit() else None
                det = obtener_detalle_nomina_empleado(
                    usuario_id=uid_int,
                    usuario_nombre=self.usuario,
                    solicitante_id=uid_int,
                    solicitante_rol=self.rol_usuario
                )

                emp_info = det.get("empleado", {})
                if emp_info:
                    lbl_sub.config(
                        text=f"Empleado: {emp_info.get('nombre_completo')} ({emp_info.get('rol')}) • Esquema: {emp_info.get('tipo_nomina')} • Solo Lectura"
                    )

                lbl_kpi_salario.config(text=f"${float(det.get('total_salario_diario', 0.0)):,.0f} COP")
                lbl_kpi_comisiones.config(text=f"${float(det.get('total_comisiones', 0.0)):,.0f} COP")
                lbl_kpi_devengado.config(text=f"${float(det.get('total_devengado', 0.0)):,.0f} COP")
                lbl_kpi_liquidado.config(text=f"${float(det.get('total_pagado', 0.0)):,.0f} COP")
                lbl_kpi_pendiente.config(text=f"${float(det.get('por_cobrar', 0.0)):,.0f} COP")

                # 1. Historial de pagos
                for item in tree_pagos.get_children():
                    tree_pagos.delete(item)
                pagos_loc = det.get("historial_pagos", [])
                if pagos_loc:
                    for p in pagos_loc:
                        p_id = f"#{int(p.get('id', 0)):03d}"
                        fecha = f"{p.get('fecha', '')} {p.get('hora', '')}".strip()
                        tipo_p = p.get("tipo_pago", "LIQUIDACION_TOTAL")
                        metodo_p = p.get("metodo_pago", "Efectivo")
                        periodo = f"{p.get('periodo_inicio', '')} a {p.get('periodo_fin', '')}".strip(" a ") or "General"
                        monto_p = f"${float(p.get('monto_pagado', 0.0)):,.0f} COP"
                        resp_p = p.get("responsable", "Administrador")
                        obs_p = p.get("observaciones", "")
                        tree_pagos.insert("", "end", values=(p_id, fecha, tipo_p, metodo_p, periodo, monto_p, resp_p, obs_p))
                else:
                    tree_pagos.insert("", "end", values=("—", "Sin pagos registrados", "—", "—", "—", "$0 COP", "—", "—"))

                # 2. Detalle de jornadas
                for item in tree_jor.get_children():
                    tree_jor.delete(item)
                jornadas_loc = det.get("detalle_jornadas", [])
                if jornadas_loc:
                    for j in jornadas_loc:
                        f_j = j.get("fecha", "")
                        h_j = j.get("hora_registro", "—")
                        est_j = j.get("estado", "")
                        pv_j = f"#{j['primera_venta_id']}" if j.get("primera_venta_id") else "—"
                        sg_j = "✅ Sí" if j.get("salario_generado") else "⏳ No"
                        ms_j = f"${float(j.get('monto_salario_generado', 0.0)):,.0f} COP"
                        ob_j = j.get("observaciones", "")
                        tree_jor.insert("", "end", values=(f_j, h_j, est_j, pv_j, sg_j, ms_j, ob_j))
                else:
                    tree_jor.insert("", "end", values=("—", "—", "Sin jornadas registradas", "—", "—", "$0 COP", "—"))

                # 3. Detalle de ventas con comisión y devengos
                for item in tree_com.get_children():
                    tree_com.delete(item)
                devengos_loc = det.get("detalle_devengos", [])
                if devengos_loc:
                    for c in devengos_loc:
                        cid = c.get("id")
                        fecha = c.get("fecha", "")
                        tipo = c.get("tipo", "")
                        vnum = f"#{c['id_venta']}" if c.get("id_venta") else "—"
                        inom = c.get("concepto", "")
                        vval = f"${float(c.get('valor_base', 0.0)):,.0f} COP"
                        porc = f"{float(c.get('porcentaje', 0.0)):.1f}%" if float(c.get("porcentaje", 0.0)) > 0 else "—"
                        monto = f"${float(c.get('monto', 0.0)):,.0f} COP"
                        est = c.get("estado", "PENDIENTE")
                        tree_com.insert("", "end", values=(cid, fecha, tipo, vnum, inom, vval, porc, monto, est))
                else:
                    tree_com.insert("", "end", values=("—", "—", "Sin registros", "—", "—", "$0 COP", "—", "$0 COP", "—"))
            except Exception as e:
                print("Error cargando detalle de nómina empleado:", e)

        cargar_datos()

    def _actualizar_estadisticas_empleado(self):
        try:
            self._actualizar_estadisticas_empleado_local()
        except Exception as e:
            print("Error actualizando estadísticas empleado:", e)
        finally:
            try:
                if self.winfo_exists():
                    self.after(10000, self._actualizar_estadisticas_empleado)
            except Exception:
                pass

    def _actualizar_estadisticas_empleado_local(self):
        """Calcula y actualiza en tiempo real los indicadores de clientes y nómina del empleado (Fase 6)."""
        try:
            try:
                from interface.nomina_manager import obtener_resumen_ventas_y_recaudo_empleado
            except ImportError:
                from nomina_manager import obtener_resumen_ventas_y_recaudo_empleado

            usr_id = self.datos_usuario.get("id")
            resumen = obtener_resumen_ventas_y_recaudo_empleado(
                usuario_id=int(usr_id) if usr_id and str(usr_id).isdigit() else None,
                usuario_nombre=self.usuario,
                rol=self.rol_usuario
            )

            ventas_hoy = int(resumen.get("ventas_hoy_cantidad", 0))
            por_cobrar = float(resumen.get("por_cobrar_clientes", 0.0))
            total_pagado = float(resumen.get("total_pagado_clientes", 0.0))
            recaudado_hoy = float(resumen.get("recaudado_hoy", 0.0))
            nomina_pend = float(resumen.get("nomina_por_cobrar", 0.0))
            nomina_pagada = float(resumen.get("nomina_total_pagado", 0.0))
            nomina_hoy = float(resumen.get("nomina_devengado_hoy", 0.0))

            if hasattr(self, 'lbl_emp_por_cobrar') and self.lbl_emp_por_cobrar.winfo_exists():
                self.lbl_emp_por_cobrar.config(text=f"${por_cobrar:,.0f} COP")
            if hasattr(self, 'lbl_emp_total_pagado') and self.lbl_emp_total_pagado.winfo_exists():
                self.lbl_emp_total_pagado.config(text=f"${total_pagado:,.0f} COP")
            if hasattr(self, 'lbl_emp_ventas') and self.lbl_emp_ventas.winfo_exists():
                self.lbl_emp_ventas.config(text=str(ventas_hoy))
            if hasattr(self, 'lbl_emp_comision') and self.lbl_emp_comision.winfo_exists():
                self.lbl_emp_comision.config(text=f"${recaudado_hoy:,.0f} COP")
            if hasattr(self, 'lbl_emp_comision_sub') and self.lbl_emp_comision_sub.winfo_exists():
                self.lbl_emp_comision_sub.config(text=f"Efectivo + Transf. + Abonos hoy")
            if hasattr(self, 'lbl_emp_nomina_pend') and self.lbl_emp_nomina_pend.winfo_exists():
                self.lbl_emp_nomina_pend.config(text=f"${nomina_pend:,.0f} COP")
            if hasattr(self, 'lbl_emp_nomina_pagada_sub') and self.lbl_emp_nomina_pagada_sub.winfo_exists():
                self.lbl_emp_nomina_pagada_sub.config(
                    text=f"Devengado hoy: ${nomina_hoy:,.0f} COP | Pagado: ${nomina_pagada:,.0f} COP"
                )
            if hasattr(self, 'lbl_emp_mes') and self.lbl_emp_mes.winfo_exists():
                self.lbl_emp_mes.config(text=f"${nomina_pagada:,.0f} COP")

            # Actualizar indicador de asistencia
            self._verificar_asistencia()
        except Exception as e:
            print("Error en estadísticas de empleado:", e)

    def _create_stats_panel(self, parent):
        """
        Crea el panel de estadísticas en la parte superior del área de contenido principal.
        """
        try:
            bg_app = self.t["bg_app"]
            bg_card = self.t["bg_surface"]
            fg_main = self.t["text_main"]
            fg_muted = self.t["text_muted"]

            stats_frame = tk.Frame(parent, bg=bg_app)
            stats_frame.pack(fill="x", pady=(0, 10))

            stats = [
                ("💰", "Ventas Hoy", "ventas_hoy", "#059669"),
                ("📈", "Ganancias Hoy", "ganancias", "#EC4899"),
                ("🛍️", "Pedidos Hoy", "pedidos", "#0284C7"),
                ("🏆", "Producto Top", "producto_top", "#D97706"),
                ("👥", "Clientes Hoy", "clientes", "#8B5CF6")
            ]

            self.stats_sub_widgets = {}

            for i, (icono, titulo, key, color) in enumerate(stats):
                stat_card = tk.Frame(stats_frame, bg=bg_card, bd=1, relief="solid")
                stat_card.pack(side="left", fill="both", expand=True, padx=(0 if i == 0 else 8, 0))

                card_header = tk.Frame(stat_card, bg=color, height=4)
                card_header.pack(fill="x")
                card_content = tk.Frame(stat_card, bg=bg_card)
                card_content.pack(fill="both", expand=True, padx=8, pady=8)
                tk.Label(card_content, text=icono, font=("Segoe UI Emoji", 18), bg=bg_card, fg=fg_main).pack()
                tk.Label(card_content, text=titulo, font=("Segoe UI", 9, "bold"), bg=bg_card, fg=fg_muted).pack()
                
                # Crear widget de valor y guardarlo en el diccionario
                valor_inicial = "$0 COP" if "ventas" in key or "ganancias" in key else ("Sin ventas" if key == "producto_top" else "0")
                font_tam = 10 if key == "producto_top" else 13
                valor_widget = tk.Label(card_content, text=valor_inicial, font=("Segoe UI", font_tam, "bold"),
                                        bg=bg_card, fg=fg_main, wraplength=190, justify="center")
                valor_widget.pack(pady=(2, 0))
                self.stats_widgets[key] = valor_widget

                # Subtítulo informativo
                sub_widget = tk.Label(card_content, text="", font=("Segoe UI", 8), bg=bg_card, fg=fg_muted)
                sub_widget.pack(pady=(1, 2))
                self.stats_sub_widgets[key] = sub_widget
        except Exception as e:
            print(f"Error creando panel de estadísticas: {e}")

    def _create_buttons_panel(self, parent):
        """Crea el panel principal con botones de operación, gestión y configuración."""
        try:
            bg_app = self.t["bg_app"]
            bg_panel = self.t["bg_surface"]
            fg_title = self.t["bg_header"]

            buttons_container = tk.Frame(parent, bg=bg_app)
            buttons_container.pack(fill="both", expand=True)

            left_panel = tk.Frame(buttons_container, bg=bg_panel, bd=1, relief="solid")
            left_panel.pack(side="left", fill="both", expand=True, padx=(0, 8))
            tk.Label(left_panel, text="✨ OPERACIONES", font=("Segoe UI", 12, "bold"), bg=bg_panel, fg=fg_title).pack(pady=10)
            self._crear_boton_moderno(left_panel, "Nueva Venta", "💖", "#EC4899", lambda: self._accion("Ventas"), "Ventas")
            self._crear_boton_moderno(left_panel, "Control de Caja", "💵", "#059669", lambda: self._accion("Caja"), "Caja")
            self._crear_boton_moderno(left_panel, "Control del Turno", "⏱️", "#0284C7", lambda: self._accion("Turnos"), "Turnos")
            self._crear_boton_moderno(left_panel, "Clientes", "💎", "#10B981", lambda: self._accion("Clientes"), "Clientes")
            
            center_panel = tk.Frame(buttons_container, bg=bg_panel, bd=1, relief="solid")
            center_panel.pack(side="left", fill="both", expand=True, padx=4)
            tk.Label(center_panel, text="💫 GESTIÓN", font=("Segoe UI", 12, "bold"), bg=bg_panel, fg=fg_title).pack(pady=10)
            self._crear_boton_moderno(center_panel, "Gestionar Inventario", "🎀", "#0EA5E9", lambda: self._accion("Inventario"), "Inventario")
            self._crear_boton_moderno(center_panel, "Contabilidad", "🏛️", "#D97706", lambda: self._accion("Contabilidad"), "Contabilidad")
            self._crear_boton_moderno(center_panel, "Control de Gastos", "🌸", "#DC2626", lambda: self._accion("Gastos"), "Gastos")
            self._crear_boton_moderno(center_panel, "Gestión de Ventas", "🛡️", "#6366F1", lambda: self._accion("Gestión Ventas"), "Gestión Ventas")
            self._crear_boton_moderno(center_panel, "Nómina y Proveedores", "💸", "#0D9488", lambda: self._accion("Nómina"), "Usuarios")
            if self.rol_usuario in ["empleado", "vendedor", "operario"]:
                self._crear_boton_moderno(center_panel, "Mi Nómina (Historial)", "🧾", "#8B5CF6", self._mostrar_nomina_empleado)
            self._crear_boton_moderno(center_panel, "Códigos de Barras", "🔢", "#EA580C", lambda: self._accion("Códigos de Barras"), "Códigos de Barras")

            right_panel = tk.Frame(buttons_container, bg=bg_panel, bd=1, relief="solid")
            right_panel.pack(side="right", fill="both", expand=True, padx=(8, 0))
            tk.Label(right_panel, text="🎨 CONFIGURACIÓN", font=("Segoe UI", 12, "bold"), bg=bg_panel, fg=fg_title).pack(pady=10)
            self._crear_boton_moderno(right_panel, "Configuración", "✨", "#8B5CF6", lambda: self._accion("Configuración"), "Configuración")
            self._crear_boton_moderno(right_panel, "Usuarios", "👸", "#DB2777", lambda: self._accion("Usuarios"), "Usuarios")
        except Exception as e:
            print(f"Error creando panel de botones: {e}")

    def _create_quick_access_panel(self, parent):
        """Crea el panel de acceso rápido en la parte inferior del área de contenido principal."""
        try:
            bg_bar = self.t["bg_header"]
            fg_bar = self.t["text_header"]

            quick_access = tk.Frame(parent, bg=bg_bar)
            quick_access.pack(fill="x", pady=(10, 0))

            tk.Label(quick_access, text="💫 ACCESO RÁPIDO", font=("Segoe UI", 11, "bold"), bg=bg_bar, fg=fg_bar).pack(side="left", padx=15, pady=12)
            quick_frame = tk.Frame(quick_access, bg=bg_bar)
            quick_frame.pack(side="right", padx=15, pady=8)

            quick_buttons = [
                ("🌟", "Nueva Factura", "#EC4899", "Ventas", lambda: self._accion("Ventas")),
                ("💎", "Consultar Stock", "#0284C7", "Inventario", lambda: self._accion("Inventario")),
                ("🔢", "Generar Código", "#EA580C", "Códigos de Barras", lambda: self._accion("Códigos de Barras")),
                ("🎀", "Backup", "#10B981", "Configuración", lambda: self._accion("Configuración")),
                ("✨", "Sincronizar", "#D97706", "Configuración", lambda: self._actualizar_estadisticas())
            ]
            
            for icono, texto, color, modulo, comando in quick_buttons:
                tiene_permiso = self.permisos.get(modulo, 0) == 1 if modulo != "Configuración" or texto != "Sincronizar" else True
                color_final = color if tiene_permiso else self.t["btn_disabled_bg"]
                cursor_final = "hand2" if tiene_permiso else "arrow"
                fg_final = calcular_color_texto_optimo(color_final) if tiene_permiso else self.t["btn_disabled_fg"]

                def _on_click(cmd, has_perm):
                    return lambda: cmd() if has_perm else self._mostrar_alerta_sin_permisos()

                quick_btn = tk.Button(quick_frame, text=f"{icono}\n{texto}",
                                     font=("Segoe UI", 8, "bold"), bg=color_final, fg=fg_final,
                                     activebackground=color_final, activeforeground=fg_final,
                                     disabledforeground=self.t["btn_disabled_fg"],
                                     bd=0, cursor=cursor_final, relief="flat", width=11, height=2,
                                     command=_on_click(comando, tiene_permiso))
                quick_btn.pack(side="left", padx=4)
        except Exception as e:
            print(f"Error creando panel de acceso rápido: {e}")

    def _create_footer(self):
        """Crea y empaqueta el pie de página de la aplicación."""
        try:
            bg_f = self.t["bg_footer"]
            fg_f = self.t["text_header"]
            fg_sub = self.t["text_header_sub"]

            self.footer_frame = tk.Frame(self, bg=bg_f)
            self.footer_frame.pack(fill="x")

            footer_left = tk.Frame(self.footer_frame, bg=bg_f)
            footer_left.pack(side="left", padx=20, pady=6)
            self.lbl_footer_ubicacion = tk.Label(
                footer_left,
                text=business_mgr.obtener_texto_ubicacion_contacto(),
                font=("Segoe UI", 9),
                bg=bg_f,
                fg=fg_f
            )
            self.lbl_footer_ubicacion.pack()

            footer_right = tk.Frame(self.footer_frame, bg=bg_f)
            footer_right.pack(side="right", padx=20, pady=6)
            self.lbl_footer_marca = tk.Label(
                footer_right,
                text=f"✨ {business_mgr.nombre} • Sistema Activo 💖",
                font=("Segoe UI", 9),
                bg=bg_f,
                fg=fg_sub
            )
            self.lbl_footer_marca.pack()
        except Exception as e:
            print(f"Error creando footer: {e}")

    def _bind_shortcuts(self):
        """Vincula los atajos de teclado para un acceso rápido."""
        try:
            self.bind("<KeyPress>", self._shortcuts)
            self.focus_set()
        except Exception as e:
            print(f"Error vinculando shortcuts: {e}")

    def _shortcuts(self, event):
        """Maneja los atajos de teclado."""
        try:
            key = event.keysym.lower()
            if event.state & 4:  # Verifica si Ctrl está presionado
                if key == 'v' and self.permisos.get("Ventas", 0) == 1:
                    self._accion("Ventas")
                elif key == 'i' and self.permisos.get("Inventario", 0) == 1:
                    self._accion("Inventario")
                elif key == 'c' and self.permisos.get("Clientes", 0) == 1:
                    self._accion("Clientes")
                elif key == 'r' and (self.permisos.get("Contabilidad", 0) == 1 or self.permisos.get("Reportes", 0) == 1):
                    self._accion("Contabilidad")
                elif key == 'b' and self.permisos.get("Códigos de Barras", 0) == 1:
                    self._accion("Códigos de Barras")
            elif key == 'f5':  # F5 para actualizar estadísticas
                self._actualizar_estadisticas()
        except Exception as e:
            print(f"Error en shortcuts: {e}")

    def _mostrar_alerta_sin_permisos(self):
        """Muestra una alerta personalizada cuando un usuario no tiene permisos."""
        try:
            alerta = tk.Toplevel(self)
            session_mgr.registrar_ventana(alerta)
            alerta.title("🚫 Acceso Denegado")
            alerta.configure(bg=self.t["bg_app"])
            alerta.resizable(False, False)
            alerta.grab_set()

            # Centrar la ventana de alerta
            alerta.update_idletasks()
            x = (alerta.winfo_screenwidth() // 2) - (400 // 2)
            y = (alerta.winfo_screenheight() // 2) - (250 // 2)
            alerta.geometry(f"400x250+{x}+{y}")

            main_frame = tk.Frame(alerta, bg=self.t["bg_surface"], bd=1, relief="solid")
            main_frame.pack(fill="both", expand=True, padx=15, pady=15)
            header_frame = tk.Frame(main_frame, bg=self.t["btn_danger_bg"], height=55)
            header_frame.pack(fill="x")

            tk.Label(header_frame, text="🚫", font=("Segoe UI Emoji", 22), bg=self.t["btn_danger_bg"], fg=self.t["btn_danger_fg"]).pack(pady=12)
            content_frame = tk.Frame(main_frame, bg=self.t["bg_surface"])
            content_frame.pack(expand=True, fill="both", padx=20, pady=15)
            tk.Label(content_frame, text="ACCESO DENEGADO", font=("Segoe UI", 13, "bold"), bg=self.t["bg_surface"], fg=self.t["btn_danger_bg"]).pack(pady=(0, 6))
            tk.Label(content_frame, text="No tienes permisos para acceder\na este módulo del sistema.", font=("Segoe UI", 10), bg=self.t["bg_surface"], fg=self.t["text_secondary"], justify="center").pack()
            btn_ok = tk.Button(content_frame, text="🔒 Entendido", font=("Segoe UI", 9, "bold"), 
                               bg=self.t["btn_danger_bg"], fg=self.t["btn_danger_fg"], 
                               activebackground=self.t["btn_danger_hover"], activeforeground=self.t["btn_danger_fg"],
                               bd=0, pady=6, cursor="hand2", command=alerta.destroy, relief="flat", width=14)
            btn_ok.pack(pady=(12, 0))
            alerta.after(3000, alerta.destroy)
        except Exception as e:
            print(f"Error mostrando alerta de permisos: {e}")

    def _crear_boton_moderno(self, parent, texto, icono, color, comando, modulo=None):
        """
        Crea un botón con estilo con verificación de permisos, cálculo estricto de contraste WCAG y hover.
        """
        try:
            tiene_permiso = self.permisos.get(modulo, 0) == 1 if modulo else True
            btn_frame = tk.Frame(parent, bg=self.t["bg_surface"])
            btn_frame.pack(fill="x", padx=12, pady=4)
            
            if not tiene_permiso:
                color_final = self.t["btn_disabled_bg"]
                texto_final = f"🔒   {texto}"
                cursor_final = "arrow"
                fg_final = self.t["btn_disabled_fg"]
            else:
                color_final = color
                texto_final = f"{icono}   {texto}"
                cursor_final = "hand2"
                fg_final = calcular_color_texto_optimo(color_final)

            btn = tk.Button(btn_frame, text=texto_final,
                            font=("Segoe UI", 10, "bold"), bg=color_final, fg=fg_final,
                            activebackground=color_final, activeforeground=fg_final,
                            disabledforeground=self.t["btn_disabled_fg"],
                            bd=0, pady=10, cursor=cursor_final,
                            command=lambda: comando() if tiene_permiso else self._mostrar_alerta_sin_permisos(),
                            relief="flat", anchor="w", padx=15)
            btn.pack(fill="x")

            # Efectos de hover con recálculo dinámico de contraste
            if tiene_permiso:
                color_hover = oscurecer_color(color_final, 0.88) if not theme_mgr.es_oscuro() else aclarar_color(color_final, 1.15)
                fg_hover = calcular_color_texto_optimo(color_hover)

                def on_enter(e):
                    btn.config(bg=color_hover, fg=fg_hover)
                def on_leave(e):
                    btn.config(bg=color_final, fg=fg_final)

                btn.bind("<Enter>", on_enter)
                btn.bind("<Leave>", on_leave)
        except Exception as e:
            print(f"Error creando botón moderno: {e}")

    def _lanzar_modulo_subproceso(self, script_name, nombre_display, extra_args=None):
        """Lanza un módulo en subproceso supervisado por session_mgr con parent_pid."""
        try:
            base_d = os.path.dirname(os.path.abspath(__file__))
            script_path = os.path.join(base_d, script_name)
            if not os.path.exists(script_path):
                messagebox.showwarning("⚠️ Archivo no encontrado", f"No se encontró el archivo {script_name} en:\n{script_path}")
                return None

            args = [sys.executable, script_path, "--parent_pid", str(os.getpid())]
            if extra_args:
                args.extend(extra_args)

            env = os.environ.copy()
            project_root = os.path.dirname(base_d)
            env["PYTHONPATH"] = project_root + (os.pathsep + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else "")
            env["VMPOS_PARENT_PID"] = str(os.getpid())
            if getattr(api, "token", None):
                env["VMPOS_TOKEN"] = api.token
            if self.usuario:
                env["VMPOS_USUARIO"] = str(self.usuario)
            if self.rol_usuario:
                env["VMPOS_ROL"] = str(self.rol_usuario)

            proc = subprocess.Popen(args, env=env)
            session_mgr.registrar_subproceso(proc, nombre=nombre_display)
            return proc
        except Exception as e:
            messagebox.showerror("❌ Error", f"No se pudo abrir {nombre_display}:\n{e}")
            return None

    def _abrir_ventas(self):
        """Abre el módulo de ventas."""
        extra = []
        uid = self.datos_usuario.get("id", "")
        if uid:
            extra.extend(["--user_id", str(uid)])
        if self.rol_usuario:
            extra.extend(["--rol", self.rol_usuario])
        self._lanzar_modulo_subproceso("ventas_menu.py", "Nueva Venta", extra)

    def _abrir_inventario(self):
        """Abre el módulo de inventario."""
        self._lanzar_modulo_subproceso("inventario_menu.py", "Gestionar Inventario")

    def _abrir_usuarios(self):
        """Abre el módulo de gestión de usuarios."""
        self._lanzar_modulo_subproceso("usuarios_menu.py", "Usuarios")

    def _abrir_clientes(self):
        """Abre el módulo de clientes."""
        self._lanzar_modulo_subproceso("clientes_menu.py", "Clientes")

    def _abrir_generador_codigo_barras(self):
        """Abre el generador de códigos de barras."""
        try:
            if GENERADOR_DISPONIBLE and iniciar_generador_barras:
                gen = iniciar_generador_barras(parent=self)
                if gen and hasattr(gen, "ventana"):
                    session_mgr.registrar_ventana(gen.ventana)
                elif gen and isinstance(gen, (tk.Toplevel, tk.Tk)):
                    session_mgr.registrar_ventana(gen)
            else:
                self._lanzar_modulo_subproceso("generador_codigo_barras.py", "Códigos de Barras")
        except Exception as e:
            messagebox.showerror("❌ Error", f"No se pudo abrir el generador de códigos de barras:\n{e}")

    def _abrir_control_gastos(self):
        """Abre el módulo de control de gastos."""
        self._lanzar_modulo_subproceso("gastos_menu.py", "Control de Gastos")

    def _mostrar_ventana_gastos_temporal(self):
        """Muestra una ventana temporal para el control de gastos."""
        try:
            ventana_gastos = tk.Toplevel(self)
            session_mgr.registrar_ventana(ventana_gastos)
            ventana_gastos.title("🌸 Control de Gastos - Temporal")
            ventana_gastos.geometry("600x400")
            ventana_gastos.configure(bg="#FFF3E0")
            ventana_gastos.transient(self)
            ventana_gastos.grab_set()

            # Centrar ventana
            ventana_gastos.update_idletasks()
            x = (ventana_gastos.winfo_screenwidth() // 2) - (600 // 2)
            y = (ventana_gastos.winfo_screenheight() // 2) - (400 // 2)
            ventana_gastos.geometry(f"600x400+{x}+{y}")

            # Header
            header_frame = tk.Frame(ventana_gastos, bg="#FF5722", height=60)
            header_frame.pack(fill="x")

            
            tk.Label(header_frame, text="🌸 CONTROL DE GASTOS", 
                    font=("Segoe UI", 16, "bold"), bg="#FF5722", fg="white").pack(pady=18)

            # Contenido principal
            main_frame = tk.Frame(ventana_gastos, bg="#FFF3E0")
            main_frame.pack(fill="both", expand=True, padx=20, pady=20)

            # Formulario para agregar gasto
            form_frame = tk.LabelFrame(main_frame, text="Agregar Nuevo Gasto", 
                                      bg="#FFF3E0", fg="#E65100", font=("Segoe UI", 12, "bold"))
            form_frame.pack(fill="x", pady=10)
            self.tree_gastos = ttk.Treeview(lista_frame, columns=("Concepto", "Valor", "Hora"), show="headings")
            self.tree_gastos.pack(fill="both", expand=True, padx=10, pady=10)

            self.tree_gastos.heading("Concepto", text="Concepto")
            self.tree_gastos.heading("Valor", text="Valor")
            self.tree_gastos.heading("Hora", text="Hora")

            self.tree_gastos.column("Concepto", width=250)
            self.tree_gastos.column("Valor", width=150)
            self.tree_gastos.column("Hora", width=100)

            # Cargar gastos del día
            self._cargar_gastos_hoy()

            # Total del día
            self.label_total = tk.Label(lista_frame, text="Total gastos hoy: $0 COP", 
                                       bg="#FFF3E0", fg="#E65100", font=("Segoe UI", 12, "bold"))
            self.label_total.pack(pady=10)
        except Exception as e:
            print(f"Error mostrando ventana de gastos temporal: {e}")

    def _guardar_gasto_temporal(self):
        """Guarda un gasto en la base de datos temporal."""
        try:
            if not hasattr(self, 'entry_concepto') or not hasattr(self, 'entry_valor'):
                messagebox.showerror("❌ Error", "Error en el formulario de gastos.")
                return
                
            concepto = self.entry_concepto.get().strip()
            valor_text = self.entry_valor.get().strip()

            if not concepto or not valor_text:
                messagebox.showwarning("⚠️ Campos vacíos", "Por favor, complete todos los campos.")
                return

            try:
                valor = float(valor_text.replace(",", "").replace("$", ""))
                
                # Crear directorio de base de datos si no existe
                if not os.path.exists(os.path.dirname(ruta_db)):
                    os.makedirs(os.path.dirname(ruta_db), exist_ok=True)
                
                # Conectar a la base de datos y crear tabla si no existe
                conn = _conectar_db()
                cursor = conn.cursor()
                
                # Crear tabla gastos si no existe
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS gastos (
                        id_gasto INTEGER PRIMARY KEY AUTOINCREMENT,
                        concepto TEXT NOT NULL,
                        valor REAL NOT NULL,
                        fecha TEXT NOT NULL,
                        hora TEXT NOT NULL,
                        fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Insertar el gasto
                fecha_hoy = datetime.date.today().strftime('%d-%m-%Y')
                hora_actual = datetime.datetime.now().strftime('%H:%M:%S')
                
                cursor.execute("""
                    INSERT INTO gastos (concepto, valor, fecha, hora)
                    VALUES (?, ?, ?, ?)
                """, (concepto, valor, fecha_hoy, hora_actual))
                
                conn.commit()
                conn.close()

                # Limpiar formulario
                self.entry_concepto.delete(0, tk.END)
                self.entry_valor.delete(0, tk.END)

                # Recargar lista
                self._cargar_gastos_hoy()
                
                # Actualizar estadísticas del dashboard principal
                self._actualizar_estadisticas()

                messagebox.showinfo("✅ Gasto Guardado", f"Gasto guardado exitosamente:\n{concepto} - ${valor:,.0f}")

            except ValueError:
                messagebox.showerror("❌ Error", "El valor debe ser un número válido.")
        except Exception as e:
            messagebox.showerror("❌ Error", f"Error al guardar gasto: {e}")

    def _cargar_gastos_hoy(self):
        """Carga los gastos del día actual."""
        try:
            if not hasattr(self, 'tree_gastos') or not self.tree_gastos:
                return
                
            # Limpiar tree
            for item in self.tree_gastos.get_children():
                self.tree_gastos.delete(item)

            if not os.path.exists(ruta_db):
                if hasattr(self, 'label_total') and self.label_total:
                    self.label_total.config(text="Total gastos hoy: $0 COP")
                return

            conn = _conectar_db()
            cursor = conn.cursor()
            
            # Verificar si existe la tabla gastos
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='gastos'
            """)
            
            tabla_existe = cursor.fetchone()
            total_dia = 0
            
            if tabla_existe:
                fecha_hoy = datetime.date.today().strftime('%d-%m-%Y')
                cursor.execute("""
                    SELECT concepto, valor, hora FROM gastos
                    WHERE fecha = ?
                    ORDER BY hora DESC
                """, (fecha_hoy,))
                
                gastos = cursor.fetchall()
                
                for concepto, valor, hora in gastos:
                    self.tree_gastos.insert("", tk.END, values=(concepto, f"${valor:,.0f}", hora))
                    total_dia += valor

            # Verificar que el widget existe antes de actualizarlo
            if hasattr(self, 'label_total') and self.label_total:
                self.label_total.config(text=f"Total gastos hoy: ${total_dia:,.0f} COP")
            
            conn.close()

        except Exception as e:
            print(f"Error al cargar gastos: {e}")

    def _accion(self, nombre):
        """Función centralizada para manejar todas las acciones de los botones."""
        # Verificar permisos aquí como un respaldo
        perm_check = self.permisos.get(nombre, 0)
        if nombre == "Contabilidad" and perm_check == 0:
            perm_check = self.permisos.get("Reportes", 0)
        if perm_check == 0:
            self._mostrar_alerta_sin_permisos()
            return

        try:
            # Diccionario para el manejo de acciones - CORREGIDO
            actions = {
                "Ventas": self._abrir_ventas,
                "Caja": self._abrir_caja,
                "Gestión Ventas": self._abrir_gestion_ventas,
                "Inventario": self._abrir_inventario,
                "Clientes": self._abrir_clientes,
                "Contabilidad": self._abrir_contabilidad,
                "Reportes": self._abrir_contabilidad,
                "Configuración": lambda: iniciar_configuracion(parent=self, on_save_callback=self.refrescar_identidad_negocio) if 'iniciar_configuracion' in globals() else messagebox.showwarning("⚠️ Módulo no disponible", "El módulo de configuración no está disponible."),
                "Usuarios": self._abrir_usuarios,
                "Gastos": self._abrir_control_gastos,
                "Nómina": self._abrir_nomina,
                "Turnos": self._abrir_turnos,
                "Códigos de Barras": self._abrir_generador_codigo_barras  # ACCIÓN CORREGIDA
            }
            
            action = actions.get(nombre)
            if action:
                # Actualizar estadísticas antes de abrir módulo
                if nombre in ["Ventas", "Inventario", "Gastos", "Caja", "Gestión Ventas", "Contabilidad"]:
                    self.after(1000, self._actualizar_estadisticas)
                action()
            else:
                messagebox.showwarning("⚠️ Módulo no disponible", f"El módulo {nombre} no está disponible aún.")
                
        except Exception as e:
            messagebox.showerror("❌ Error", f"Error al abrir {nombre}:\n{str(e)}")

    def _abrir_contabilidad(self):
        """Abre el módulo central de Contabilidad e Inteligencia Financiera."""
        self._lanzar_modulo_subproceso("contabilidad_menu.py", "Contabilidad")

    def _abrir_caja(self):
        """Abre el módulo de Control de Caja y Arqueo Físico."""
        extra = []
        if self.usuario:
            extra.extend(["--usuario", str(self.usuario)])
        if self.rol_usuario:
            extra.extend(["--rol", str(self.rol_usuario)])
        id_usuario = self.datos_usuario.get("id", "")
        if id_usuario:
            extra.extend(["--user_id", str(id_usuario)])
        self._lanzar_modulo_subproceso("caja_menu.py", "Control de Caja", extra)

    def _abrir_gestion_ventas(self):
        """Abre la supervisión y control de ventas con anulación y auditoría."""
        try:
            if abrir_gestion_ventas:
                dlg = abrir_gestion_ventas(parent=self, usuario_actual=self.usuario)
                if dlg:
                    session_mgr.registrar_ventana(dlg)
            else:
                self._lanzar_modulo_subproceso("ventas_admin_dialog.py", "Gestión de Ventas")
        except Exception as e:
            messagebox.showerror("❌ Error", f"No se pudo abrir la gestión de ventas:\n{e}")

    def _abrir_nomina(self):
        """Abre el módulo de nómina y liquidación usando subprocess supervisado."""
        self._lanzar_modulo_subproceso("nomina_menu.py", "Nómina y Proveedores")

    def _abrir_turnos(self):
        """Abre el módulo de Control del Turno (Operarios / Administrador)."""
        extra = []
        id_usuario = self.datos_usuario.get("id", "")
        if id_usuario:
            extra.extend(["--user_id", str(id_usuario)])
        if self.rol_usuario:
            extra.extend(["--rol", self.rol_usuario])
        if self.usuario:
            extra.extend(["--nombre", str(self.usuario)])
        self._lanzar_modulo_subproceso("turnos_menu.py", "Control del Turno", extra)

# --- Punto de entrada desde el login ---
def iniciar_dashboard(usuario, datos_usuario):
    """
    Función de entrada principal para lanzar el dashboard.
    Esta es la función que se llamaría desde la pantalla de login.
    """
    try:
        app = VmPOSDashboard(usuario=usuario, datos_usuario=datos_usuario)
        app.mainloop()
    except Exception as e:
        print(f"Error iniciando dashboard: {e}")
        messagebox.showerror("Error Fatal", f"Error iniciando el dashboard:\n{e}")


# --- Punto de entrada principal para pruebas independientes ---
if __name__ == "__main__":
    try:
        # Simular una llamada desde la pantalla de login
        # para probar los diferentes roles.
        
        # Usuario Administrador
        mock_admin_data = {'usuario': 'Eduardo', 'permisos': 'admin', 'rol': 'Administrador'}
        print(f"Probando con usuario: {mock_admin_data['usuario']} ({mock_admin_data['rol']})")
        iniciar_dashboard(mock_admin_data['usuario'], mock_admin_data)

        # # Usuario Vendedor (descomenta para probar)
        # mock_vendedor_data = {'usuario': 'Andres', 'permisos': 'vendedor'}
        # print(f"Probando con usuario: {mock_vendedor_data['usuario']} ({mock_vendedor_data['permisos']})")
        # iniciar_dashboard(mock_vendedor_data['usuario'], mock_vendedor_data)
    except Exception as e:
        print(f"Error fatal en punto de entrada: {e}")
        import traceback
        traceback.print_exc()