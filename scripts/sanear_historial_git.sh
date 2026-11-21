#!/usr/bin/env bash
# ==============================================================================
# Playbook de Saneamiento de Historial Git — VmPOS
# Archivo: scripts/sanear_historial_git.sh
#
# PROPÓSITO:
#   Purgar del historial histórico de commits los archivos de bases de datos
#   SQLite (`*.db`, `*.db-wal`, `*.db-shm`) y `config/business_config.json`
#   que quedaron en commits anteriores del repositorio remoto.
#
# ADVERTENCIA CRÍTICA:
#   Este script REESCRIBE el historial de Git (cambia los SHAs de los commits)
#   y requiere coordinación explícita con el propietario del repositorio antes
#   de ejecutar `git push --force-with-lease`.
#   NO SE EJECUTA AUTOMÁTICAMENTE sin confirmación explícita (`--confirmar`).
# ==============================================================================
set -euo pipefail

REPO_URL="${1:-https://github.com/Eduardo30111/venta_pos_VM.git}"
CONFIRM="${2:-}"

if [ "$CONFIRM" != "--confirmar" ]; then
    cat <<'EOF'
====================================================================
  PLAYBOOK DE SANEAMIENTO DE HISTORIAL GIT (MODO SOLO LECTURA)
====================================================================

Archivos históricos identificados en el árbol de commits antiguos:
  - database/ventas.db
  - database/usuarios.db
  - database/vmpos_server.db
  - config/business_config.json
  - backups/*.db (si existiera alguno en commits antiguos)

PRERREQUISITOS OBLIGATORIOS ANTES DE EJECUTAR:
  1. Verificar respaldo offline completo (git bundle) del repositorio.
  2. Coordinar ventana de mantenimiento con todos los colaboradores
     (después de reescribir historial deberán hacer `git clone` limpio).
  3. Rotar credenciales reales que hayan existido en las DB históricas:
     - Cambiar contraseñas de todos los usuarios en producción.
     - Rotar `config/jwt_secret.key` y `POSTGRES_PASSWORD`.
  4. Instalar `git-filter-repo` (`brew install git-filter-repo` o `pip install git-filter-repo`).

PARA EJECUTAR EN UN CLON MIRROR AISLADO:
  bash scripts/sanear_historial_git.sh https://github.com/Eduardo30111/venta_pos_VM.git --confirmar

Nota: Este script nunca ejecuta `git push --force` automáticamente;
deja el espejo saneado listo para inspección y autorización final.
====================================================================
EOF
    exit 0
fi

if ! command -v git-filter-repo > /dev/null 2>&1; then
    echo "❌ ERROR: 'git-filter-repo' no está instalado."
    echo "Instale con: brew install git-filter-repo  (o pip install git-filter-repo)"
    exit 1
fi

WORK_DIR="/tmp/vmpos_git_sanitize_$(date +%Y%m%d_%H%M%S)"
MIRROR_DIR="$WORK_DIR/venta_pos_VM.git"
BUNDLE_BACKUP="$WORK_DIR/backup_pre_sanitize.bundle"
mkdir -p "$WORK_DIR"

echo "[1/4] Clonando mirror completo en $MIRROR_DIR..."
git clone --mirror "$REPO_URL" "$MIRROR_DIR"

echo "[2/4] Creando respaldo completo (git bundle) en $BUNDLE_BACKUP..."
git -C "$MIRROR_DIR" bundle create "$BUNDLE_BACKUP" --all
git -C "$MIRROR_DIR" bundle verify "$BUNDLE_BACKUP"

echo "[3/4] Purgando archivos históricos sensibles con git-filter-repo..."
git -C "$MIRROR_DIR" filter-repo --force \
    --path-glob '*.db' \
    --path-glob '*.db-wal' \
    --path-glob '*.db-shm' \
    --path-glob '*.sqlite' \
    --path-glob '*.sqlite3' \
    --path 'config/business_config.json' \
    --path 'config/jwt_secret.key' \
    --path 'config/token.json' \
    --invert-paths

echo "[4/4] Verificando que no queden blobs .db en el historial saneado..."
REMAINING=$(git -C "$MIRROR_DIR" rev-list --all --objects | grep -E '\.(db|db-wal|db-shm|sqlite|sqlite3|key)$|config/business_config\.json$' || true)
if [ -n "$REMAINING" ]; then
    echo "⚠️ Aún se detectaron referencias:"
    echo "$REMAINING"
    exit 1
fi

echo "===================================================================="
echo "✅ ESPEJO SANEADO VERIFICADO (0 blobs .db/.key en todo el historial)"
echo "   Respaldo previo: $BUNDLE_BACKUP"
echo "   Espejo saneado:  $MIRROR_DIR"
echo ""
echo "PASO MANUAL FINAL (solo tras aprobación del propietario):"
echo "   cd \"$MIRROR_DIR\""
echo "   git remote add origin \"$REPO_URL\""
echo "   git push --force --all origin"
echo "   git push --force --tags origin"
echo "===================================================================="
