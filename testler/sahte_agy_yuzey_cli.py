"""Sahte agy: `agy mcp list` ve `agy plugin list` cevaplar, gerisini sahte_denetimli_cli.py'ye (gemini) devreder.
SAHTE_AGY_MCP / SAHTE_AGY_PLUGIN: metin (varsayılan: gerçek agy'nin 'boş' mesajı). SAHTE_AGY_YUZEY_KOD: çıkış kodu."""
import os
import subprocess
import sys
from pathlib import Path

BOS = {"mcp": "No MCP servers configured.", "plugin": "No plugins installed."}
a = sys.argv[1:]
if a[:2] in (["mcp", "list"], ["plugin", "list"]):
    ad = a[0]
    if os.environ.get("SAHTE_AGY_YUZEY") == "zaman_asimi":
        import time
        time.sleep(60)
    sys.stdout.write(os.environ.get(f"SAHTE_AGY_{ad.upper()}", BOS[ad]) + "\n")
    sys.exit(int(os.environ.get("SAHTE_AGY_YUZEY_KOD", "0")))
p = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "sahte_denetimli_cli.py"), "gemini", *a],
                   env=os.environ)
sys.exit(p.returncode)
