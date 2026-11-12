#!/usr/bin/env bash
# ============================================================
#  build_exe.sh — Aura Home Security Matrix EXE Builder
#  Run this on Linux to compile a Windows .exe via PyInstaller
#  Output: dist/Aura.exe
# ============================================================
set -e

PYINSTALLER="$(command -v pyinstaller || echo "$HOME/.local/bin/pyinstaller")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "  ======================================================"
echo "   AURA HOME SECURITY MATRIX — EXE Builder"
echo "   By Haistellar"
echo "  ======================================================"
echo ""

cd "$SCRIPT_DIR"

# Install / verify dependencies
echo "[STEP 1] Installing Python dependencies..."
pip install -r requirements.txt --break-system-packages --quiet

echo "[STEP 2] Running PyInstaller..."
"$PYINSTALLER" aura.spec \
    --noconfirm \
    --clean

echo ""
echo "  ======================================================"
echo "  [SUCCESS] Build complete!"
echo "  Output: $SCRIPT_DIR/dist/Aura.exe"
echo ""
echo "  To distribute:"
echo "  • Copy  dist/Aura.exe  to the target Windows machine"
echo "  • Run Aura.exe from a folder (it will create .env there)"
echo "  ======================================================"
echo ""
