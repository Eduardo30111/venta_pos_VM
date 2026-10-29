import re

with open("interface/ventas_menu.py", "r") as f:
    content = f.read()

# Make sure conectar_usuarios_db is imported
if "from usuarios_db import conectar_usuarios_db" not in content:
    content = content.replace(
        "from database_manager import conectar_db",
        "from database_manager import conectar_db\nfrom usuarios_db import conectar_usuarios_db"
    )

old_block = '''                # Procesar proveedor y comisiones
                if codigo in prod_info:
                    tipo, prov_id, costo = prod_info[codigo]
                    if prov_id is not None:
                        # Si tiene proveedor, todo el subtotal de venta se va como saldo a su favor
                        cursor.execute("UPDATE proveedores SET saldo_acumulado = saldo_acumulado + ? WHERE id = ?", (subtotal, prov_id))
                    
                    if tipo == 'Servicio' and self.user_id and self.rol.lower() == 'empleado':
                        # Si es empleado y vende un servicio, darle comisión
                        cursor.execute("SELECT comision_porcentaje FROM usuarios WHERE id = ?", (self.user_id,))
                        u_res = cursor.fetchone()
                        if u_res:
                            porcentaje = u_res[0] or 0.0
                            if porcentaje > 0:
                                comision = subtotal * (porcentaje / 100.0)
                                cursor.execute("UPDATE usuarios SET comisiones_acumuladas = comisiones_acumuladas + ? WHERE id = ?", (comision, self.user_id))'''

new_block = '''                # Procesar proveedor y comisiones
                if codigo in prod_info:
                    tipo, prov_id, costo = prod_info[codigo]
                    costo_num = costo if costo else 0.0
                    
                    if prov_id is not None:
                        # El proveedor gana el costo pactado del producto * cantidad
                        saldo_prov = costo_num * cantidad
                        cursor.execute("UPDATE proveedores SET saldo_acumulado = saldo_acumulado + ? WHERE id = ?", (saldo_prov, prov_id))
                    
                    # COMISIONES (Aplica a Operarios o Vendedores)
                    if tipo == 'Servicio' and self.user_id and self.rol.lower() in ['operario', 'vendedor']:
                        try:
                            # Conectar a la DB de usuarios
                            conn_usr = conectar_usuarios_db()
                            cur_usr = conn_usr.cursor()
                            cur_usr.execute("SELECT comision_porcentaje, tipo_nomina FROM usuarios WHERE id = ?", (self.user_id,))
                            u_res = cur_usr.fetchone()
                            
                            if u_res and u_res[1] == "Porcentual":
                                porcentaje = u_res[0] or 0.0
                                if porcentaje > 0:
                                    utilidad_unitaria = precio - costo_num
                                    if utilidad_unitaria > 0:
                                        comision_generada = (utilidad_unitaria * cantidad) * (porcentaje / 100.0)
                                        cur_usr.execute("UPDATE usuarios SET comisiones_acumuladas = comisiones_acumuladas + ? WHERE id = ?", (comision_generada, self.user_id))
                                        conn_usr.commit()
                            conn_usr.close()
                        except Exception as ex_comision:
                            print(f"Error calculando comision: {ex_comision}")'''

content = content.replace(old_block, new_block)

with open("interface/ventas_menu.py", "w") as f:
    f.write(content)
