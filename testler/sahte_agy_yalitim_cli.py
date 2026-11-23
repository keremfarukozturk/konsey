"""Sahte agy (yalıtım testleri): `agy mcp list` / `agy plugin list` cevaplar, çağrı sırasında ortamı kaydeder, moda göre
$HOME ve (kötü modda) gerçek ~/.gemini yerine geçen klasöre dosya yazar; gerisini sahte_denetimli_cli.py'ye (gemini) devreder.
SAHTE_AGY_YALITIM: iyi (varsayılan) | gercek_yaz | log_yok | kimlik | hicbiri_yazma
SAHTE_GERCEK_GEMINI: 'gerçek' ~/.gemini yerine geçen klasör. SAHTE_ORTAM_DOSYASI: ortamın JSON dökümü yazılacak yol."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BOS = {"mcp": "No MCP servers configured.", "plugin": "No plugins installed."}
a = sys.argv[1:]
if os.environ.get("SAHTE_ORTAM_DOSYASI"):
    with open(os.environ["SAHTE_ORTAM_DOSYASI"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": a, "env": dict(os.environ)}) + "\n")
home = Path(os.environ.get("HOME", "."))
mod = os.environ.get("SAHTE_AGY_YALITIM", "iyi")
if a[:2] in (["mcp", "list"], ["plugin", "list"]):
    sys.stdout.write(os.environ.get(f"SAHTE_AGY_{a[0].upper()}", BOS[a[0]]) + "\n")
    sys.exit(0)
if mod != "hicbiri_yazma":
    if mod != "log_yok":
        log = home / ".gemini" / "antigravity-cli" / "log"
        log.mkdir(parents=True, exist_ok=True)
        (log / f"cli-{time.time_ns()}.log").write_text("sahte log\n", encoding="utf-8")
    if mod == "gercek_yaz" and os.environ.get("SAHTE_GERCEK_GEMINI"):
        g = Path(os.environ["SAHTE_GERCEK_GEMINI"]) / "antigravity-cli" / "log"
        g.mkdir(parents=True, exist_ok=True)
        (g / f"cli-{time.time_ns()}.log").write_text("gerçeğe sızdı\n", encoding="utf-8")
    if mod == "kimlik":
        (home / ".gemini" / "antigravity-cli").mkdir(parents=True, exist_ok=True)
        (home / ".gemini" / "antigravity-cli" / "oauth_token.json").write_text("{}", encoding="utf-8")
p = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "sahte_denetimli_cli.py"), "gemini", *a],
                   env=os.environ)
sys.exit(p.returncode)
