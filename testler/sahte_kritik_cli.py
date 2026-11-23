"""
Sahte CLI (v0.22): sahte_cli.py'yi çalıştırır ve eleştiri çıktısındaki 'önemli' maddeyi 'kritik' yapar (madde satırı ve
JSON sayısı). Böylece testler, erken durmanın artık yalnızca KRİTİK maddeye bakmasını (karar 55) sınayabilir.
sahte_cli.py'ye dokunulmaz. Kullanım: python sahte_kritik_cli.py <claude|codex|gemini> <argümanlar...>
"""
import re
import subprocess
import sys
from pathlib import Path

r = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "sahte_cli.py"), *sys.argv[1:]],
                   capture_output=True, text=True)
cikti = r.stdout.replace("(önem: önemli", "(önem: kritik")
cikti = re.sub(r'(\\?")kritik(\\?"): 0, (\\?")onemli(\\?"): 1', r'\1kritik\2: 1, \3onemli\4: 0', cikti)
sys.stdout.write(cikti)
sys.stderr.write(r.stderr)
sys.exit(r.returncode)
