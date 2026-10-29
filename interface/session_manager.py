#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gestor Centralizado de Sesión, Ventanas y Ciclo de Vida - VmPOS
Archivo: interface/session_manager.py

Responsabilidades:
1. Control del ciclo de vida de la sesión activa y estado de autenticación.
2. Registro y supervisión de todos los subprocesos hijos (ventas, inventario, caja, etc.).
3. Registro y supervisión de ventanas modales y Toplevels secundarias.
4. Cancelación segura de temporizadores (after) y callbacks de Tkinter.
5. Cierre atómico y ordenado de sesión:
   - Invalidación de tokens y credenciales de entorno.
   - Cierre forzoso y limpio de todas las ventanas secundarias y subprocesos.
   - Retorno limpio a la pantalla de inicio de sesión.
6. Vigilancia de proceso padre (Parent Watcher) para que los procesos hijos
   se autodestruyan si la ventana principal del Dashboard se cierra o muere.
"""

import os
import sys
import subprocess
import time
import platform
import weakref

# Garantizar resolución cruzada de módulos
try:
    from client.api_client import api
except ImportError:
    try:
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from client.api_client import api
    except Exception:
        api = None


def verificar_proceso_vivo(pid):
    """
    Verifica si un proceso con el PID dado sigue existiendo y en ejecución.
    Multiplataforma: compatible con macOS, Linux y Windows sin dependencias externas.
    """
    if not pid or pid <= 0:
        return False
    try:
        if platform.system() == "Windows":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            SYNCHRONIZE = 0x00100000
            process = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
            if not process:
                return False
            # WaitForSingleObject con timeout 0: retorna 0 (WAIT_OBJECT_0) si ya terminó
            wait_res = kernel32.WaitForSingleObject(process, 0)
            kernel32.CloseHandle(process)
            return wait_res != 0  # Si es 258 (WAIT_TIMEOUT), sigue vivo
        else:
            # macOS / Linux / POSIX
            os.kill(int(pid), 0)
            return True
    except (OSError, ProcessLookupError, PermissionError):
        return False
    except Exception:
        return True


class SessionManager:
    """
    Gestor singleton del ciclo de vida de sesiones, procesos hijos y ventanas de VmPOS.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SessionManager, cls).__new__(cls)
            cls._instance._init_manager()
        return cls._instance

    def _init_manager(self):
        self.sesion_activa = False
        self.usuario_actual = ""
        self.rol_actual = ""
        self.user_id_actual = None
        self.inicio_sesion_ts = None
        self._subprocesos = []  # Lista de dicts: {"proc": Popen, "nombre": str, "pid": int}
        self._ventanas = []     # Lista de referencias a Toplevel
        self._timers = []       # Lista de tuplas: (weakref(widget), after_id)

    def iniciar_sesion(self, usuario, rol="Administrador", user_id=None, token=None):
        """Inicializa una sesión válida en el sistema."""
        self.sesion_activa = True
        self.usuario_actual = str(usuario or "").strip()
        self.rol_actual = str(rol or "").strip()
        self.user_id_actual = user_id
        self.inicio_sesion_ts = time.time()
        self._subprocesos.clear()
        self._ventanas.clear()
        self._timers.clear()

        if token and api:
            api.token = token
            os.environ["VMPOS_TOKEN"] = str(token)

        if usuario:
            os.environ["VMPOS_USUARIO"] = str(usuario)
        if rol:
            os.environ["VMPOS_ROL"] = str(rol)
        if user_id:
            os.environ["VMPOS_USER_ID"] = str(user_id)

    def registrar_subproceso(self, proc, nombre="Módulo"):
        """
        Registra un proceso hijo generado con subprocess.Popen para supervisión de ciclo de vida.
        """
        self._limpiar_subprocesos_muertos()
        if proc and hasattr(proc, "poll"):
            self._subprocesos.append({
                "proc": proc,
                "nombre": nombre,
                "pid": getattr(proc, "pid", None)
            })

    @property
    def subprocesos_activos(self):
        """Retorna la lista de procesos hijos que siguen actualmente en ejecución."""
        self._limpiar_subprocesos_muertos()
        return list(self._subprocesos)

    def verificar_proceso_vivo(self, pid):
        """Verifica si un proceso con el PID dado sigue existiendo y en ejecución."""
        return verificar_proceso_vivo(pid)

    def _limpiar_subprocesos_muertos(self):
        """Elimina de la lista interna los procesos que ya terminaron normalmente."""
        activos = []
        for item in self._subprocesos:
            p = item.get("proc")
            if p and p.poll() is None:
                activos.append(item)
        self._subprocesos = activos

    def registrar_ventana(self, toplevel_widget):
        """Registra una ventana secundaria Toplevel o modal in-process."""
        self._limpiar_ventanas_muertas()
        if toplevel_widget and toplevel_widget not in self._ventanas:
            self._ventanas.append(toplevel_widget)

    def _limpiar_ventanas_muertas(self):
        """Elimina ventanas que ya fueron destruidas."""
        vivas = []
        for w in self._ventanas:
            try:
                if w and w.winfo_exists():
                    vivas.append(w)
            except Exception:
                pass
        self._ventanas = vivas

    def registrar_timer(self, widget, after_id):
        """Registra un ID de temporizador (after) para cancelación segura."""
        if widget and after_id:
            self._timers.append((widget, after_id))

    def cancelar_timers(self, root=None):
        """Cancela todos los temporizadores pendientes registrados."""
        for widget, after_id in list(self._timers):
            try:
                if widget and widget.winfo_exists() and after_id:
                    widget.after_cancel(after_id)
            except Exception:
                pass
        self._timers.clear()

    def cerrar_todas_las_ventanas(self):
        """Cierra de forma segura todas las ventanas modales y secundarias in-process."""
        self._limpiar_ventanas_muertas()
        for w in list(self._ventanas):
            try:
                if w and w.winfo_exists():
                    try:
                        w.grab_release()
                    except Exception:
                        pass
                    w.destroy()
            except Exception as e:
                print(f"Aviso destruyendo ventana secundaria: {e}")
        self._ventanas.clear()

    def terminar_subprocesos(self, timeout=1.5):
        """
        Termina todos los subprocesos hijos activos.
        Envía SIGTERM, espera con timeout, y si no responden aplica SIGKILL.
        """
        self._limpiar_subprocesos_muertos()
        procesos_a_esperar = []

        for item in self._subprocesos:
            proc = item.get("proc")
            nombre = item.get("nombre", "Proceso")
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    procesos_a_esperar.append((proc, nombre))
                except Exception as e:
                    print(f"Error al enviar terminate a {nombre}: {e}")

        # Esperar finalización limpia con timeout
        t_inicio = time.time()
        for proc, nombre in procesos_a_esperar:
            tiempo_restante = max(0.1, timeout - (time.time() - t_inicio))
            try:
                proc.wait(timeout=tiempo_restante)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(timeout=0.5)
                except Exception:
                    pass
            except Exception:
                pass

        self._subprocesos.clear()

    def cerrar_sesion(self, root_window=None, lanzar_login=True):
        """
        Cierra completamente la sesión activa:
        1. Marca sesion_activa = False.
        2. Invalida tokens y variables de entorno.
        3. Cierra todas las ventanas secundarias y modales.
        4. Termina todos los subprocesos hijos.
        5. Cancela temporizadores de la ventana raíz.
        6. Destruye la ventana raíz si existe.
        7. Abre la pantalla de inicio de sesión si se solicita.
        """
        self.sesion_activa = False

        # Invalidar autenticación
        if api:
            api.token = None
        for env_k in ["VMPOS_TOKEN", "VMPOS_USUARIO", "VMPOS_ROL", "VMPOS_USER_ID"]:
            os.environ.pop(env_k, None)

        # Cerrar ventanas modales / Toplevels
        self.cerrar_todas_las_ventanas()

        # Terminar subprocesos hijos de la sesión
        self.terminar_subprocesos(timeout=1.5)

        # Cancelar temporizadores
        if root_window:
            self.cancelar_timers(root_window)

        # Destruir ventana raíz
        if root_window:
            try:
                if root_window.winfo_exists():
                    root_window.destroy()
            except Exception as e:
                print(f"Aviso destruyendo ventana principal: {e}")

        # Lanzar pantalla de login limpia
        if lanzar_login:
            try:
                base_dir = os.path.dirname(os.path.abspath(__file__))
                login_script = os.path.join(base_dir, "inicio_sesion.py")
                if os.path.exists(login_script):
                    subprocess.Popen([sys.executable, login_script])
            except Exception as e:
                print(f"Error relanzando inicio de sesión: {e}")

    def iniciar_vigilante_padre(self, root_window, parent_pid=None, intervalo_ms=1500):
        """
        Inicia un ciclo recurrente en una ventana hija (proceso secundario)
        para autodestruirse si el proceso padre (Dashboard) ya no existe.
        """
        pid = parent_pid or os.environ.get("VMPOS_PARENT_PID")
        if not pid:
            return

        try:
            pid_int = int(pid)
        except ValueError:
            return

        def _verificar():
            try:
                if not root_window.winfo_exists():
                    return
                if not verificar_proceso_vivo(pid_int):
                    try:
                        root_window.destroy()
                    except Exception:
                        pass
                    sys.exit(0)
                    return
                root_window.after(intervalo_ms, _verificar)
            except Exception:
                pass

        try:
            root_window.after(intervalo_ms, _verificar)
        except Exception:
            pass


# Instancia singleton global
session_mgr = SessionManager()
