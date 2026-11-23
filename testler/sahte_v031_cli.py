"""
Sahte CLI (v0.31): sahte_cli.py'yi sarar; cevaplara [K#] atıfları ekler. sahte_cli.py'ye dokunulmaz.
  SAHTE_V031_TUR0=<metin>      Tur 0 cevabının sonuna eklenir (örn. "[K1]")
  SAHTE_V031_DUZELTME=<metin>  düzeltilmiş cevabın sonuna eklenir
  SAHTE_V031_SENTEZ=<metin>    sentezin CEVAP satırının sonuna eklenir
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent / "sahte_cli.py"
ad = sys.argv[1]
arg = sys.argv[2:]
ESKI_SENTEZ = "ÖZET: ortak sonuç.\nCEVAP: test\nBELİRSİZLİKLER: Yok"


def kacis(t):
    return json.dumps(t, ensure_ascii=False)[1:-1]


def prompt_bul():
    if ad in ("claude", "gemini") and "-p" in arg:
        return arg[arg.index("-p") + 1]
    return arg[-1] if ad == "codex" else ""


p = prompt_bul()
r = subprocess.run([sys.executable, str(BASE), ad, *arg], capture_output=True, text=True, env=dict(os.environ))
c = r.stdout
if "--version" in arg or not p or p.strip() == "/usage" or arg[:2] == ["auth", "status"]:
    pass
elif "ÖNERİLEN ORTAK METİN" in p or "İTİRAZLAR (kimliksiz)" in p or "=== CEVAP A ===" in p:
    pass
elif "SENİN GÜNCEL CEVABIN" in p:
    ek = os.environ.get("SAHTE_V031_DUZELTME")
    if ek:
        c = c.replace("cevabı DÜZELTİLDİ", "cevabı DÜZELTİLDİ " + kacis(ek))
elif "sentez yazarısın" in p:
    ek = os.environ.get("SAHTE_V031_SENTEZ")
    if ek:
        c = c.replace(kacis(ESKI_SENTEZ), kacis(ESKI_SENTEZ.replace("CEVAP: test", "CEVAP: test " + ek)))
else:
    ek = os.environ.get("SAHTE_V031_TUR0")
    if ek and "cevabı\\nGEREKÇE" in c:
        c = c.replace("cevabı\\nGEREKÇE", "cevabı " + kacis(ek) + "\\nGEREKÇE")
sys.stdout.write(c)
sys.stderr.write(r.stderr)
sys.exit(r.returncode)
