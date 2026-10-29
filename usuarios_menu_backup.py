# -*- coding: utf-8 -*-
"""
Archivo: usuarios_menu.py
Interfaz de gestión de usuarios para VmPOS.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import os
import sqlite3

# Importar funciones de la base de datos de usuarios
from usuarios_db import (
    crear_tablas_iniciales, insertar_usuario, obtener_usuarios,
    actualizar_usuario_db, eliminar_usuario_db,
    obtener_permisos_por_usuario, MODULOS_DISPONIBLES, hash_password,
    obtener_usuario_por_credenciales, inicializar_admin_default,
    migrar_usuarios_existentes
)

# 🌐 Variables globales para los widgets de la interfaz
entradas = {}
tabla = None
ventana_usuarios = None
rol_var = None
estado_var = None
comision_var = None
id_usuario_seleccionado = None

def inicializar_sistema_usuarios():
    """Inicializa el sistema de usuarios creando tablas y datos por defecto."""
    print("🔧 Inicializando sistema de usuarios...")
    crear_tablas_iniciales()
    inicializar_admin_default()
    
    # Verificar si hay usuarios en la base de datos
    usuarios = obtener_usuarios()
    if len(usuarios) == 0:
        print("📥 Base de datos vacía, cargando datos de ejemplo...")
        cargar_datos_ejemplo()
    else:
        print(f"✅ Se encontraron {len(usuarios)} usuarios en la base de datos.")

def cargar_datos_ejemplo():
    """Carga datos de ejemplo en la base de datos."""
    usuarios_ejemplo = [
        {"usuario": "admin", "password": "admin123", "rol": "Administrador", "estado": "Activo"},
        {"usuario": "eduardo", "password": "2121", "rol": "Administrador", "estado": "Activo"},
        {"usuario": "andres", "password": "2180", "rol": "Vendedor", "estado": "Activo"},
        {"usuario": "gerente", "password": "manager", "rol": "Gerente", "estado": "Activo"},
        {"usuario": "vendedor1", "password": "pass123", "rol": "Vendedor", "estado": "Activo"}
    ]
    
    for user in usuarios_ejemplo:
        resultado = insertar_usuario(
            user["usuario"],
            user["password"],
            user["rol"],
            user["estado"]
        )
        if resultado:
            print(f"✅ Usuario '{user['usuario']}' creado correctamente.")
        else:
            print(f"⚠️ Usuario '{user['usuario']}' ya existe o hubo un error.")

def actualizar_tabla():
    """
    Actualiza la tabla con los datos más recientes de la base de datos.
    """
    global tabla
    
    if not tabla:
        return
    
    # Limpiar tabla actual
    for item in tabla.get_children():
        tabla.delete(item)

    # Obtener usuarios de la base de datos
    usuarios = obtener_usuarios()
    print(f"📋 Cargando {len(usuarios)} usuarios en la tabla.")

    # Insertar los datos en la tabla
    for usuario in usuarios:
        # Formatear las fechas para mejor visualización
        fecha_registro = usuario['fecha_registro']
        if isinstance(fecha_registro, str):
            try:
                # Intentar parsear la fecha si viene como string
                fecha_obj = datetime.fromisoformat(fecha_registro.replace('Z', '+00:00'))
                fecha_formateada = fecha_obj.strftime("%d/%m/%Y %H:%M")
            except:
                fecha_formateada = fecha_registro
        else:
            fecha_formateada = str(fecha_registro) if fecha_registro else "No disponible"
        
        ultimo_acceso = usuario['ultimo_acceso']
        if ultimo_acceso and ultimo_acceso != "Nunca":
            try:
                if isinstance(ultimo_acceso, str):
                    fecha_obj = datetime.fromisoformat(ultimo_acceso.replace('Z', '+00:00'))
                    ultimo_acceso = fecha_obj.strftime("%d/%m/%Y %H:%M")
            except:
                pass
        
        valores = (
            usuario['id'],
            usuario['usuario'],
            usuario['rol'],
            usuario['estado'],
            ultimo_acceso if ultimo_acceso else "Nunca",
            fecha_formateada
        )
        
        tabla.insert("", "end", values=valores)
    
    print("✅ Tabla actualizada correctamente.")

def seleccionar_usuario(event):
    """
    Carga los datos del usuario seleccionado en los campos de edición.
    """
    global id_usuario_seleccionado
    global entradas, rol_var, estado_var

    item_seleccionado = tabla.focus()
    if not item_seleccionado:
        return
    
    try:
        valores = tabla.item(item_seleccionado, 'values')
        if not valores: return
        
        id_usuario_seleccionado = int(valores[0])
        entradas['Usuario'].delete(0, tk.END)
        entradas['Usuario'].insert(0, valores[1])
        entradas['Password'].delete(0, tk.END)
        entradas['Password'].insert(0, "")
        
        rol_var.set(valores[2])
        estado_var.set(valores[3])

        # Extraer comisión (si existe en los values o consultar db)
        # Como no lo guardamos en la tabla, lo extraemos de obtener_usuarios
        usuarios_db = obtener_usuarios()
        for u in usuarios_db:
            if u['id'] == id_usuario_seleccionado:
                # Comision
                global comision_var
                comision_var.set(str(u.get('comision_porcentaje', 0.0)))
                break
        
        print(f"👤 Usuario seleccionado: {valores[1]} (ID: {id_usuario_seleccionado})")
    except Exception as e:
        print(f"❌ Error al seleccionar usuario: {e}")
        messagebox.showerror("Error", f"Error al cargar datos del usuario: {e}")

def guardar_usuario():
    """
    Guarda o actualiza un usuario en la base de datos.
    """
    global id_usuario_seleccionado, comision_var
    
    usuario = entradas['Usuario'].get().strip()
    password = entradas['Password'].get().strip()
    rol = rol_var.get()
    estado = estado_var.get()
    try:
        comision = float(comision_var.get())
    except ValueError:
        comision = 0.0
    
    if not usuario:
        messagebox.showerror("Error", "El campo Usuario es obligatorio.")
        entradas['Usuario'].focus()
        return
    if rol == "Seleccionar" or not rol:
        messagebox.showerror("Error", "Debes seleccionar un rol.")
        return
    if estado == "Seleccionar" or not estado:
        messagebox.showerror("Error", "Debes seleccionar un estado.")
        return
    
    try:
        if id_usuario_seleccionado:
            print(f"🔄 Actualizando usuario con ID: {id_usuario_seleccionado}")
            resultado = actualizar_usuario_db(
                id_usuario_seleccionado, 
                usuario=usuario, 
                rol=rol, 
                estado=estado, 
                password=password if password else None,
                comision_porcentaje=comision
            )
            if resultado:
                messagebox.showinfo("Éxito", f"Usuario '{usuario}' actualizado correctamente.")
            else:
                messagebox.showerror("Error", "No se pudo actualizar el usuario.")
        else:
            if not password:
                messagebox.showerror("Error", "La contraseña es obligatoria para un nuevo usuario.")
                entradas['Password'].focus()
                return
            print(f"➕ Creando nuevo usuario: {usuario}")
            resultado = insertar_usuario(usuario, password, rol, estado, comision)
            if resultado:
                messagebox.showinfo("Éxito", f"Usuario '{usuario}' creado correctamente.")
            else:
                messagebox.showerror("Error", f"No se pudo crear el usuario. Es posible que ya exista.")
        limpiar_campos()
        actualizar_tabla()
    except Exception as e:
        print(f"❌ Error al guardar usuario: {e}")
        messagebox.showerror("Error de base de datos", f"Ocurrió un error al guardar el usuario:\n{e}")

def eliminar_usuario():
    """
    Elimina el usuario seleccionado de la base de datos.
    """
    global id_usuario_seleccionado
    
    if not id_usuario_seleccionado:
        messagebox.showwarning("Advertencia", "Por favor, selecciona un usuario de la tabla para eliminar.")
        return
    
    # Obtener nombre del usuario para confirmar
    usuario_seleccionado = entradas['Usuario'].get()
    
    # Confirmación
    respuesta = messagebox.askyesno(
        "Confirmar eliminación", 
        f"¿Estás seguro de que quieres eliminar el usuario '{usuario_seleccionado}'?\n\nEsta acción no se puede deshacer."
    )
    
    if not respuesta:
        return
    
    try:
        print(f"🗑️ Eliminando usuario con ID: {id_usuario_seleccionado}")
        resultado = eliminar_usuario_db(id_usuario_seleccionado)
        
        if resultado:
            messagebox.showinfo("Éxito", f"Usuario '{usuario_seleccionado}' eliminado correctamente.")
            limpiar_campos()
            actualizar_tabla()
        else:
            messagebox.showerror("Error", "No se pudo eliminar el usuario.")
            
    except Exception as e:
        print(f"❌ Error al eliminar usuario: {e}")
        messagebox.showerror("Error de base de datos", f"Ocurrió un error al eliminar el usuario:\n{e}")

def limpiar_campos():
    """
    Limpia todos los campos de entrada y restablece la selección.
    """
    global id_usuario_seleccionado
    
    # Limpiar campos de texto
    for campo in ["Usuario", "Password"]:
        if campo in entradas:
            entradas[campo].delete(0, tk.END)
    
    # Restablecer comboboxes
    if rol_var:
        rol_var.set("Seleccionar")
    if estado_var:
        estado_var.set("Seleccionar")

    # Limpiar selección
    id_usuario_seleccionado = None
    
    if tabla and tabla.selection():
        tabla.selection_remove(tabla.selection())
    
    # Focus en el primer campo
    if 'Usuario' in entradas:
        entradas['Usuario'].focus()
    
    print("🧹 Campos limpiados.")

def probar_login():
    """
    Función para probar el sistema de login con las credenciales ingresadas.
    """
    usuario = entradas['Usuario'].get().strip()
    contrasena = entradas['Password'].get().strip()

    if not usuario or not contrasena:
        messagebox.showerror("Error", "Por favor, introduce un usuario y una contraseña para probar.")
        return
        
    print(f"🔐 Probando login para usuario: {usuario}")
    usuario_verificado = obtener_usuario_por_credenciales(usuario, contrasena)

    if usuario_verificado:
        mensaje = f"✅ Login exitoso!\n\n" \
                  f"Usuario: {usuario_verificado['usuario']}\n" \
                  f"Rol: {usuario_verificado['rol']}\n" \
                  f"Estado: {usuario_verificado['estado']}"
        messagebox.showinfo("Login Exitoso", mensaje)
        print(f"✅ Login exitoso para {usuario_verificado['usuario']}")
    else:
        messagebox.showerror("Login Fallido", "❌ Credenciales incorrectas o usuario inactivo.")
        print(f"❌ Login fallido para usuario: {usuario}")

def refrescar_tabla():
    """Refresca la tabla de usuarios."""
    print("🔄 Refrescando tabla...")
    actualizar_tabla()
    messagebox.showinfo("Información", "Tabla actualizada correctamente.")

def abrir_menu_liquidaciones():
    """Abre un modal para gestionar liquidaciones de empleados."""
    modal = tk.Toplevel()
    modal.title("💸 Liquidación de Empleados")
    modal.geometry("800x400")
    modal.configure(bg="#FFE4F1")
    modal.transient(ventana_usuarios)
    modal.grab_set()

    tk.Label(modal, text="Liquidación Pendiente de Empleados", font=("Segoe UI", 16, "bold"), bg="#FFE4F1", fg="#C71585").pack(pady=10)

    columnas = ("ID", "Empleado", "Comisiones", "Solicitado Hace")
    tabla_liq = ttk.Treeview(modal, columns=columnas, show="headings", height=10)
    for col in columnas:
        tabla_liq.heading(col, text=col)
        tabla_liq.column(col, anchor="center")
    tabla_liq.pack(fill="both", expand=True, padx=20, pady=10)

    from usuarios_db import obtener_usuarios, liquidar_comisiones
    import datetime

    def cargar_liquidaciones():
        for item in tabla_liq.get_children():
            tabla_liq.delete(item)
        
        usuarios = obtener_usuarios()
        now = datetime.datetime.now()
        for u in usuarios:
            if u['rol'] == 'Empleado':
                estado = "No solicitado"
                activo = False
                if u.get('solicitud_liquidacion'):
                    try:
                        sol_time = datetime.datetime.fromisoformat(u['solicitud_liquidacion'].split(".")[0])
                        diff = (now - sol_time).total_seconds()
                        if diff <= 300: # 5 minutos
                            estado = f"Hace {int(diff)} seg"
                            activo = True
                        else:
                            estado = "Expirado"
                    except Exception as e:
                        print("Error parsing datetime:", e)
                        pass
                
                tabla_liq.insert("", "end", values=(u['id'], u['usuario'], f"${u.get('comisiones_acumuladas', 0):,.2f}", estado), tags=("activo" if activo else "inactivo",))

        tabla_liq.tag_configure("activo", background="#d4edda")
        tabla_liq.tag_configure("inactivo", background="#f8d7da")

    cargar_liquidaciones()

    def liquidar_seleccionado():
        item = tabla_liq.focus()
        if not item: return
        valores = tabla_liq.item(item, "values")
        tags = tabla_liq.item(item, "tags")
        if "activo" not in tags:
            messagebox.showwarning("Inactivo", "Este empleado no ha solicitado liquidación o el tiempo expiró.")
            return
        
        id_empleado = int(valores[0])
        respuesta = messagebox.askyesno("Confirmar", f"¿Liquidar a {valores[1]}?")
        if respuesta:
            monto = liquidar_comisiones(id_empleado)
            # Agregar el gasto
            from database_manager import conectar_db
            try:
                conn = conectar_db("database/ventas.db")
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO gastos (concepto, valor, fecha, hora) VALUES (?, ?, ?, ?)",
                    (f"Liquidación empleado {valores[1]}", monto, datetime.datetime.now().strftime("%Y-%m-%d"), datetime.datetime.now().strftime("%H:%M:%S"))
                )
                conn.commit()
                conn.close()
            except Exception as e:
                print("Error agregando gasto:", e)

            messagebox.showinfo("Éxito", f"Se liquidaron ${monto:,.2f}.")
            cargar_liquidaciones()

    tk.Button(modal, text="💸 Liquidar Empleado", command=liquidar_seleccionado, bg="#28a745", fg="white", font=("Segoe UI", 12, "bold")).pack(pady=10)


def iniciar_usuarios():
    """
    Función principal que inicializa la ventana de gestión de usuarios.
    """
    global tabla, entradas, ventana_usuarios, rol_var, estado_var
    
    print("🚀 Iniciando ventana de gestión de usuarios...")
    
    # Inicializar sistema de usuarios
    inicializar_sistema_usuarios()
    
    # Crear ventana principal
    ventana_usuarios = tk.Tk()
    ventana_usuarios.title("👥 Gestión de Usuarios - VmPOS")
    ventana_usuarios.geometry("1200x800")
    ventana_usuarios.resizable(True, True)
    ventana_usuarios.configure(bg="#FFE4F1")

    # Centrar ventana
    ventana_usuarios.update_idletasks()
    x = (ventana_usuarios.winfo_screenwidth() // 2) - 600
    y = (ventana_usuarios.winfo_screenheight() // 2) - 400
    ventana_usuarios.geometry(f"1200x800+{x}+{y}")

    # Configurar estilos
    style = ttk.Style()
    style.theme_use('clam')
    style.configure('Feminine.TLabel', background='#FFE4F1', foreground='#C71585', font=('Segoe UI', 10))
    style.configure('Header.TLabel', background='#FF1493', foreground='white', font=('Segoe UI', 16, 'bold'))
    style.configure('Feminine.TButton', background='#FF69B4', foreground='white', font=('Segoe UI', 10, 'bold'), relief="flat")
    
    # Estilo para la tabla
    style.configure("Treeview",
                    background="#FADDEE",
                    foreground="#333",
                    rowheight=25,
                    fieldbackground="#FADDEE")
    style.map('Treeview', background=[('selected', '#fd79a8')], foreground=[('selected', 'white')])
    style.configure("Treeview.Heading",
                    font=("Segoe UI", 10, "bold"),
                    background="#e84393",
                    foreground="white",
                    relief="flat")
    style.map("Treeview.Heading", background=[('active', '#e84393')])

    # 🌸 Header principal
    header_frame = tk.Frame(ventana_usuarios, bg="#FF1493", height=80)
    header_frame.pack(fill="x")


    tk.Label(header_frame, text="👥 Gestión de Usuarios del Sistema",
             font=("Segoe UI", 20, "bold"), bg="#FF1493", fg="white").pack(pady=15)

    # Contenedor principal
    main_frame = tk.Frame(ventana_usuarios, bg="#FFE4F1")
    main_frame.pack(fill="both", expand=True, padx=20, pady=10)

    # Formulario para usuarios
    form_frame = tk.LabelFrame(main_frame, text="✨ Nuevo/Editar Usuario", font=("Segoe UI", 12, "bold"),
                               bg="#FFDDEE", fg="#C71585", padx=15, pady=15, relief="flat")
    form_frame.pack(fill="x", padx=10, pady=10)
    
    # Crear grid para el formulario
    campos = ["Usuario", "Password"]
    roles = ["Admin", "Gerente", "Vendedor", "Operario"]
    estados = ["Activo", "Inactivo"]
    
    global rol_var, estado_var, comision_var
    # Variables de control para Comboboxes
    rol_var = tk.StringVar(value="Seleccionar")
    estado_var = tk.StringVar(value="Seleccionar")
    comision_var = tk.StringVar(value="0")
    tipo_nomina_var = tk.StringVar(value="Porcentual")
    salario_diario_var = tk.StringVar(value="0")
    
    # Campo Usuario
    tk.Label(form_frame, text="👤 Usuario:", font=("Segoe UI", 11, "bold"), 
             bg="#FFDDEE", fg="#C71585").grid(row=0, column=0, padx=5, pady=8, sticky="w")
    entrada_usuario = tk.Entry(form_frame, font=("Segoe UI", 11), width=35, 
                               bg="#FFFFFF", fg="#C71585", bd=1, relief="solid")
    entrada_usuario.grid(row=0, column=1, padx=5, pady=8, sticky="w")
    entradas['Usuario'] = entrada_usuario
    
    # Campo Contraseña
    tk.Label(form_frame, text="🔒 Contraseña:", font=("Segoe UI", 11, "bold"), 
             bg="#FFDDEE", fg="#C71585").grid(row=1, column=0, padx=5, pady=8, sticky="w")
    entrada_password = tk.Entry(form_frame, font=("Segoe UI", 11), width=35, 
                                bg="#FFFFFF", fg="#C71585", bd=1, relief="solid", show="*")
    entrada_password.grid(row=1, column=1, padx=5, pady=8, sticky="w")
    entradas['Password'] = entrada_password
    
        # Campo Nombre
    tk.Label(form_frame, text="📛 Nombre:", font=("Segoe UI", 11, "bold"), 
             bg="#FFDDEE", fg="#C71585").grid(row=2, column=0, padx=5, pady=8, sticky="w")
    entrada_nombre = tk.Entry(form_frame, font=("Segoe UI", 11), width=35, bg="#FFFFFF", fg="#C71585", bd=1, relief="solid")
    entrada_nombre.grid(row=2, column=1, padx=5, pady=8, sticky="w")
    entradas['Nombre'] = entrada_nombre

    # Campo Apellidos
    tk.Label(form_frame, text="📛 Apellidos:", font=("Segoe UI", 11, "bold"), 
             bg="#FFDDEE", fg="#C71585").grid(row=3, column=0, padx=5, pady=8, sticky="w")
    entrada_apellidos = tk.Entry(form_frame, font=("Segoe UI", 11), width=35, bg="#FFFFFF", fg="#C71585", bd=1, relief="solid")
    entrada_apellidos.grid(row=3, column=1, padx=5, pady=8, sticky="w")
    entradas['Apellidos'] = entrada_apellidos
    
    # Campo Rol
    tk.Label(form_frame, text="👑 Rol:", font=("Segoe UI", 11, "bold"), 
             bg="#FFDDEE", fg="#C71585").grid(row=4, column=0, padx=5, pady=8, sticky="w")
    combo_rol = ttk.Combobox(form_frame, textvariable=rol_var, values=roles, 
                             state="readonly", width=32, font=("Segoe UI", 11))
    combo_rol.grid(row=4, column=1, padx=5, pady=8, sticky="w")

    # Campo Tipo Nomina
    lbl_tipo_nomina = tk.Label(form_frame, text="📄 Tipo Nómina:", font=("Segoe UI", 11, "bold"), bg="#FFDDEE", fg="#C71585")
    combo_tipo_nomina = ttk.Combobox(form_frame, textvariable=tipo_nomina_var, values=["Fija", "Porcentual"], state="readonly", width=15, font=("Segoe UI", 11))

    # Campo Comisión / Salario
    lbl_valor_nomina = tk.Label(form_frame, text="💰 Valor:", font=("Segoe UI", 11, "bold"), bg="#FFDDEE", fg="#C71585")
    entrada_valor_nomina = tk.Entry(form_frame, textvariable=salario_diario_var, font=("Segoe UI", 11), width=10, bg="#FFFFFF", fg="#C71585", bd=1, relief="solid")

    def on_rol_change(*args):
        if rol_var.get() in ["Vendedor", "Operario"]:
            lbl_tipo_nomina.grid(row=4, column=2, padx=5, pady=8, sticky="w")
            combo_tipo_nomina.grid(row=4, column=3, padx=5, pady=8, sticky="w")
            lbl_valor_nomina.grid(row=5, column=2, padx=5, pady=8, sticky="w")
            entrada_valor_nomina.grid(row=5, column=3, padx=5, pady=8, sticky="w")
        else:
            lbl_tipo_nomina.grid_remove()
            combo_tipo_nomina.grid_remove()
            lbl_valor_nomina.grid_remove()
            entrada_valor_nomina.grid_remove()
            tipo_nomina_var.set("Porcentual")
            salario_diario_var.set("0")
            
    def on_tipo_nomina_change(*args):
        if tipo_nomina_var.get() == "Fija":
            lbl_valor_nomina.config(text="💰 Salario Diario ($):")
        else:
            lbl_valor_nomina.config(text="💰 Porcentaje (%):")

    rol_var.trace_add("write", on_rol_change)
    tipo_nomina_var.trace_add("write", on_tipo_nomina_change)
    
    # Campo Estado
    tk.Label(form_frame, text="📊 Estado:", font=("Segoe UI", 11, "bold"), 
             bg="#FFDDEE", fg="#C71585").grid(row=6, column=0, padx=5, pady=8, sticky="w")
    combo_estado = ttk.Combobox(form_frame, textvariable=estado_var, values=estados, 
                                state="readonly", width=32, font=("Segoe UI", 11))
    combo_estado.grid(row=6, column=1, padx=5, pady=8, sticky="w")
    
    # Botones de acción
    botones_frame = tk.Frame(form_frame, bg="#FFDDEE")
    botones_frame.grid(row=7, column=0, columnspan=4, pady=15)
    
    btn_guardar = tk.Button(botones_frame, text="💾 Guardar Usuario", command=guardar_usuario, 
                            bg="#FF69B4", fg="white", font=("Segoe UI", 11, "bold"), 
                            relief="flat", padx=15, pady=8, cursor="hand2")
    btn_guardar.pack(side="left", padx=5)
    
    btn_eliminar = tk.Button(botones_frame, text="🗑️ Eliminar", command=eliminar_usuario, 
                             bg="#ff4d4d", fg="white", font=("Segoe UI", 11, "bold"), 
                             relief="flat", padx=15, pady=8, cursor="hand2")
    btn_eliminar.pack(side="left", padx=5)
    
    btn_limpiar = tk.Button(botones_frame, text="🧹 Limpiar", command=limpiar_campos, 
                            bg="#3399ff", fg="white", font=("Segoe UI", 11, "bold"), 
                            relief="flat", padx=15, pady=8, cursor="hand2")
    btn_limpiar.pack(side="left", padx=5)

    btn_login = tk.Button(botones_frame, text="🔑 Probar Login", command=probar_login, 
                          bg="#8B008B", fg="white", font=("Segoe UI", 11, "bold"), 
                          relief="flat", padx=15, pady=8, cursor="hand2")
    btn_login.pack(side="left", padx=5)
    
    btn_refrescar = tk.Button(botones_frame, text="🔄 Refrescar", command=refrescar_tabla, 
                              bg="#17a2b8", fg="white", font=("Segoe UI", 11, "bold"), 
                              relief="flat", padx=15, pady=8, cursor="hand2")
    btn_refrescar.pack(side="left", padx=5)

    # Se removieron los botones de liquidacion, ahora estaran en el modulo de Nomina

    # Marco de la tabla de usuarios
    tabla_frame = tk.LabelFrame(main_frame, text="📋 Lista de Usuarios en Base de Datos", 
                                font=("Segoe UI", 12, "bold"),
                                bg="#FFE4F1", fg="#C71585", padx=15, pady=15, relief="flat")
    tabla_frame.pack(fill="both", expand=True, padx=10, pady=10)

    # Crear la tabla (Treeview)
    columnas = ("ID", "Usuario", "Rol", "Estado", "Último Acceso", "Fecha Registro")
    tabla = ttk.Treeview(tabla_frame, columns=columnas, show="headings", height=15)
    
    # Configurar columnas
    anchos_columnas = {"ID": 60, "Usuario": 150, "Rol": 120, "Estado": 100, "Último Acceso": 150, "Fecha Registro": 150}
    
    for col in columnas:
        tabla.heading(col, text=col)
        tabla.column(col, width=anchos_columnas.get(col, 120), anchor="center")
    
    # Scrollbar para la tabla
    scrollbar = ttk.Scrollbar(tabla_frame, orient="vertical", command=tabla.yview)
    tabla.configure(yscrollcommand=scrollbar.set)
    
    # Empaquetar tabla y scrollbar
    tabla.pack(side="left", fill="both", expand=True, padx=(0, 5), pady=5)
    scrollbar.pack(side="right", fill="y", pady=5)
    
    # Vincular evento de selección
    tabla.bind("<<TreeviewSelect>>", seleccionar_usuario)

    # Información sobre la tabla
    info_frame = tk.Frame(tabla_frame, bg="#FFE4F1")
    info_frame.pack(fill="x", pady=(5, 0))
    
    tk.Label(info_frame, text="💡 Selecciona un usuario de la tabla para editar sus datos", 
             font=("Segoe UI", 10, "italic"), bg="#FFE4F1", fg="#666666").pack()

    # 📊 Footer con información del sistema
    footer = tk.Frame(ventana_usuarios, bg="#e84393", height=60)
    footer.pack(fill="x", side="bottom")


    footer_left = tk.Frame(footer, bg="#e84393")
    footer_left.pack(side="left", padx=20, pady=15)

    footer_right = tk.Frame(footer, bg="#e84393")
    footer_right.pack(side="right", padx=20, pady=15)

    tk.Label(footer_left, text="📍 Puerto Colombia • 📞 +573215545788",
             font=("Segoe UI", 10), bg="#e84393", fg="white").pack()

    # Contador de usuarios
    usuarios_count = len(obtener_usuarios())
    tk.Label(footer_right, text=f"✨ VmPOS v3.1.0 • {usuarios_count} usuarios registrados 💖",
             font=("Segoe UI", 10), bg="#e84393", fg="#ffd3e8").pack()

    # Cargar datos iniciales en la tabla
    actualizar_tabla()
    
    # Focus inicial en el campo usuario
    entradas['Usuario'].focus()
    
    # Vincular teclas de acceso rápido
    ventana_usuarios.bind('<F5>', lambda e: refrescar_tabla())
    ventana_usuarios.bind('<Escape>', lambda e: limpiar_campos())
    ventana_usuarios.bind('<Control-s>', lambda e: guardar_usuario())
    
    print("✅ Ventana de gestión de usuarios iniciada correctamente.")
    ventana_usuarios.mainloop()

if __name__ == "__main__":
    iniciar_usuarios()