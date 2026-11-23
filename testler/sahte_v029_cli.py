"""
Sahte CLI (v0.29): sahte_cli.py'yi sarar; v0.29b eleştiri ve düzeltme biçimlerini üretir. sahte_cli.py'ye dokunulmaz.
Kullanım: python sahte_v029_cli.py <claude|codex|gemini> <argümanlar...>

  SAHTE_V029_ELESTIRI=uzun|yalniz_oneri|bos   (yalnızca v0.29 eleştiri promptunu tanır; "DÜZELTİLDİ" gören 2. tur: bos)
     uzun: her kategoriden madde (HATA-V029 kritik, HATAKUCUK-V029, EKSIKSONUC-V029 ("sonucu değiştirir" var),
           EKSIKSONUCSUZ-V029, KANITSIZ-V029, ASIRI-V029, ONERI-V029)
     yalniz_oneri: yalnızca EKSİK'in küçük maddesi ve öneri (v0.30c: düzeltmeye gitmeyenler)
     bos: "Bu cevapta düzeltilmesi gereken bir şey yok." + JSON sıfır
  SAHTE_V029_DUZELTME=dayanakli|dayaksiz|cozulemedi|karisik   (v0.29 dayanak biçimi; yoksa sahte_cli'nin düzeltmesi)
  SAHTE_V029_BELIRSIZ=yok|var   sentezin BELİRSİZLİKLER bölümü ("Yok" ya da ÇÖZÜLEMEDİ maddeleri)
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


def prompt_bul():
    if ad in ("claude", "gemini") and "-p" in arg:
        return arg[arg.index("-p") + 1]
    if ad == "codex":
        return arg[-1]
    return ""


def kacis(t):
    return json.dumps(t, ensure_ascii=False)[1:-1]


def calistir(args, env):
    return subprocess.run([sys.executable, str(BASE), ad, *args], capture_output=True, text=True, env=env)


def bitir(r, stdout=None):
    sys.stdout.write(r.stdout if stdout is None else stdout)
    sys.stderr.write(r.stderr)
    sys.exit(r.returncode)


UZUN = ("HATALAR\n- [1] (önem: kritik; güven: yüksek) HATA-V029\n- [2] (önem: küçük; güven: orta) HATAKUCUK-V029\n"
        "EKSİK NOKTALAR\n- [3] (önem: önemli; güven: orta; sonucu değiştirir: sayıyı iki katına çıkarır) EKSIKSONUC-V029\n"
        "- [4] (önem: önemli; güven: orta) EKSIKSONUCSUZ-V029\n"
        "- [8] (önem: küçük; güven: orta) EKSIKKUCUK-V029\n"
        "KANITSIZ İDDİALAR\n- [5] (önem: önemli; güven: düşük) KANITSIZ-V029\n"
        "AŞIRI GENELLEME / KAPSAM HATASI\n- [6] (önem: önemli; güven: orta) ASIRI-V029\n"
        "İYİLEŞTİRME ÖNERİLERİ\n- [7] (öneri) ONERI-V029\n")
YALNIZ_ONERI = ("EKSİK NOKTALAR\n- [1] (önem: küçük; güven: orta) KUCUKEKSIK-V029\n"
                "İYİLEŞTİRME ÖNERİLERİ\n- [2] (öneri) ONERI-V029\n")
BOS = "Bu cevapta düzeltilmesi gereken bir şey yok.\n"

p = prompt_bul()
env = dict(os.environ)
if "--version" in arg or p.strip() == "/usage" or not p or arg[:2] == ["auth", "status"]:
    bitir(calistir(arg, env))

# --- eleştiri (v0.29 promptu)
if "Bölümde yalnızca sorun bulduğun alt başlıkları yaz" in p and "SENİN GÜNCEL CEVABIN" not in p:
    kip = os.environ.get("SAHTE_V029_ELESTIRI", "bos")
    if "DÜZELTİLDİ" in p:
        kip = "bos"
    etiketler = re.findall(r"^=== CEVAP (\w) ===$", p, re.M)
    govde, sayi = {"uzun": (UZUN, {"kritik": 1, "onemli": 4, "kucuk": 2}),
                   "yalniz_oneri": (YALNIZ_ONERI, {"kritik": 0, "onemli": 0, "kucuk": 1}),
                   "bos": (BOS, {"kritik": 0, "onemli": 0, "kucuk": 0})}[kip]
    j = {e: sayi for e in etiketler}
    if len(etiketler) == 2:
        j["daha_iyi"] = "A"
    yeni = "\n".join(f"=== CEVAP {e} HAKKINDA ===\n{govde}" for e in etiketler) + "```json\n" + json.dumps(j) + "\n```"
    r = calistir(arg, env)
    cikti = re.sub(r'=== CEVAP A HAKKINDA ===.*?\\n```(?=")', lambda m: kacis(yeni), r.stdout, flags=re.S)
    bitir(r, cikti)

# --- düzeltme (v0.29 dayanak biçimi)
if "SENİN GÜNCEL CEVABIN" in p and os.environ.get("SAHTE_V029_DUZELTME"):
    kip = os.environ["SAHTE_V029_DUZELTME"]
    kimlikler = list(dict.fromkeys(re.findall(r"\[(E\d+-\d+)\]", p))) or ["E1-1"]
    satirlar = []
    for i, k in enumerate(kimlikler):
        if kip == "dayanakli":
            satirlar.append(f"- {k} KABUL: doğru, çünkü hesap bunu gösteriyor; değişen: düzeltildi; DAYANAK: hesap: 2+2=4")
        elif kip == "dayaksiz":
            satirlar.append(f"- {k} KABUL: doğru, çünkü öyle görünüyor; değişen: düzeltildi; DAYANAK: ")
        elif kip == "cozulemedi":
            satirlar.append(f"- {k} ÇÖZÜLEMEDİ: iddia kanıt paketinde bulunamadı ve hesaplanamadı; DAYANAK: yok")
        else:  # karisik
            satirlar.append([f"- {k} KABUL: doğru, çünkü hesap; değişen: x; DAYANAK: hesap",
                             f"- {k} KISMEN KABUL: kısmen doğru, çünkü y; değişen: z; kabul edilmeyen: w; DAYANAK: karşı örnek",
                             f"- {k} RED: yanlış; DAYANAK: bilinen olgu",
                             f"- {k} ÇÖZÜLEMEDİ: doğrulanamadı; DAYANAK: yok"][i % 4])
    kayit = "DEĞİŞİKLİK KAYDI:\n" + "\n".join(satirlar) + "\nGÜNCEL CEVAP:"
    r = calistir(arg, env)
    cikti = re.sub(r"DEĞİŞİKLİK KAYDI:\\n.*?\\nGÜNCEL CEVAP:", lambda m: kacis(kayit), r.stdout, flags=re.S)
    bitir(r, cikti)

# --- sentez: BELİRSİZLİKLER bölümü
if "sentez yazarısın" in p and "İTİRAZLAR (kimliksiz)" not in p and os.environ.get("SAHTE_V029_BELIRSIZ") == "var":
    r = calistir(arg, env)
    yeni = "ÖZET: ortak sonuç.\nCEVAP: test\nBELİRSİZLİKLER: Doğrulanamayan eleştiri iddiası taşındı (ÇÖZÜLEMEDİ)."
    bitir(r, r.stdout.replace(kacis(ESKI_SENTEZ), kacis(yeni)))

bitir(calistir(arg, env))
