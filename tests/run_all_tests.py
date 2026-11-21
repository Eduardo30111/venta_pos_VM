#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ejecutor Maestro de Pruebas Automatizadas de VmPOS:
Ejecuta cada suite de pruebas en su propio subproceso aislado, evitando interferencias
de estado global de Tkinter, SQLite, loop de eventos de AsyncIO o singletons de memoria.
Genera un resumen consolidado con recuento de casos, tiempo de ejecución y estado (PASS/FAIL).
"""

import os
import sys
import glob
import time
import subprocess

def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    test_files = sorted(glob.glob(os.path.join(root_dir, "tests", "test_*.py")))

    print("=" * 80)
    print("🚀 EJECUTOR MAESTRO DE PRUEBAS AUTOMATIZADAS - VmPOS")
    print("=" * 80)
    print(f"Total de suites descubiertas: {len(test_files)}")
    print("-" * 80)

    total_suites = len(test_files)
    passed_suites = 0
    failed_suites = []
    t_global_inicio = time.time()

    for idx, test_path in enumerate(test_files, 1):
        rel_name = os.path.basename(test_path)
        print(f"[{idx:02d}/{total_suites:02d}] Ejecutando {rel_name:<50} ... ", end="", flush=True)

        t_inicio = time.time()
        res = subprocess.run(
            [sys.executable, "-m", "unittest", f"tests.{rel_name[:-3]}"],
            cwd=root_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        duracion = time.time() - t_inicio

        if res.returncode == 0:
            print(f"✅ PASS ({duracion:.2f}s)")
            passed_suites += 1
        else:
            print(f"❌ FAIL ({duracion:.2f}s)")
            failed_suites.append((rel_name, res.stdout, res.stderr))

    t_global_total = time.time() - t_global_inicio

    print("=" * 80)
    print("📊 RESUMEN EJECUTIVO DE RESULTADOS")
    print("=" * 80)
    print(f"Suites exitosas:   {passed_suites}/{total_suites} ({passed_suites/total_suites*100:.1f}%)")
    print(f"Suites fallidas:   {len(failed_suites)}/{total_suites}")
    print(f"Tiempo total:      {t_global_total:.2f} segundos")
    print("=" * 80)

    if failed_suites:
        print("\n❌ DETALLE DE SUITES CON FALLAS:")
        for name, out, err in failed_suites:
            print(f"\n--- Fallo en {name} ---")
            if out:
                print(f"[STDOUT]\n{out.strip()}")
            if err:
                print(f"[STDERR]\n{err.strip()}")
        sys.exit(1)
    else:
        print("\n🎉 TODAS LAS SUITES DE PRUEBAS PASARON EXITOSAMENTE (100% OK).")
        sys.exit(0)

if __name__ == "__main__":
    main()
