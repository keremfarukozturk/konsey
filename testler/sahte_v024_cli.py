"""
Sahte CLI (v0.24, karar 63): sahte_v023_cli.py'yi sarar; RET veren sağlayıcıların itirazlarını önem dereceli nesne olarak yazar.
Ortam değişkenleri (JSON; yalnızca RET veren sağlayıcıların pusulasındaki "önemli hata" itirazını değiştirir):
  SAHTE_V024_ITIRAZ_ILK     ilk oylama için itiraz listesi, örn. [{"onem":"küçük","metin":"ifade"}]
  SAHTE_V024_ITIRAZ_IKINCI  ikinci oylama için itiraz listesi (kaynak alanıyla)
RET veren sağlayıcılar sahte_v023_cli.py değişkenleriyle (SAHTE_V023_RET_ILK / _IKINCI) seçilir.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

V023 = Path(__file__).resolve().parent / "sahte_v023_cli.py"
ad = sys.argv[1]
arg = sys.argv[2:]
r = subprocess.run([sys.executable, str(V023), ad, *arg], capture_output=True, text=True, env=dict(os.environ))
cikti = r.stdout
p = " ".join(arg)
if "ÖNERİLEN ORTAK METİN" in p:
    ikinci = "DÜZELTİLDİ-SENTEZ" in p
    ham = os.environ.get("SAHTE_V024_ITIRAZ_IKINCI" if ikinci else "SAHTE_V024_ITIRAZ_ILK")
    if ham:
        dizi = json.dumps(json.loads(ham), ensure_ascii=False)

        def degistir(m):
            return dizi.replace('"', '\\"') if m.group(1) else dizi

        cikti = re.sub(r'\[(\\?)"önemli hata\\?"\]', degistir, cikti)
sys.stdout.write(cikti)
sys.stderr.write(r.stderr)
sys.exit(r.returncode)
