#!/bin/bash
# Bot Office: double-click to install (first time) and open the office in your browser.
cd "$(dirname "$0")"
echo ""
echo "  ===  Bot Office  ==="
echo ""
if ! command -v python3 >/dev/null 2>&1; then
  echo "  Wala pang Python sa computer na ito."
  echo "  I-download sa https://www.python.org/downloads/ tapos i-double-click ulit ang file na ito."
  (open https://www.python.org/downloads/ || xdg-open https://www.python.org/downloads/) >/dev/null 2>&1
  read -r -p "  Pindutin ang Enter para isara..."
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "  Unang beses: nag-i-install... (1-3 minuto)"
  python3 -m venv .venv || { echo "  Hindi nagawa ang .venv"; read -r; exit 1; }
fi
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt || { echo "  May problema sa pag-install."; read -r; exit 1; }
echo ""
echo "  Bukas na ang opisina sa browser mo: http://localhost:8800"
echo "  Huwag isara ang window na ito habang ginagamit. Para ihinto: Ctrl+C o isara ang window."
echo ""
BOT_OFFICE_OPEN=1 .venv/bin/python server.py
