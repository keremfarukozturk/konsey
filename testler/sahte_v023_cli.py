"""
Sahte CLI (v0.23): sahte_cli.py'yi sarar ve v0.23 davranışlarını (karar 59–62) sınamak için çıktıyı ayarlar.
sahte_cli.py'ye dokunulmaz. Kullanım: python sahte_v023_cli.py <claude|codex|gemini> <argümanlar...>

Ortam değişkenleri (hepsi isteğe bağlı):
  SAHTE_V023_ELESTIRI=zengin   eleştiri dört alt başlıkla gelir (1. tur: kritik madde var; "DÜZELTİLDİ" gören 2. tur:
                               yalnızca önemli/küçük madde). Maddelerin metni HATA*/EKSIK*/KANITSIZ*/ONERI* içerir.
  SAHTE_V023_ESKI_BICIM=1      düzeltme KABUL satırları eski biçimde kalır ("KABUL: sahte"); varsayılan yeni biçim.
  SAHTE_V023_RET_ILK=a,b       ilk oylamada bu sağlayıcılar RET verir (itiraz: "önemli hata"), diğerleri KABUL.
  SAHTE_V023_RET_IKINCI=a,b    düzeltilmiş metnin ("DÜZELTİLDİ-SENTEZ") oylamasında RET verecek sağlayıcılar.
  SAHTE_V023_ITIRAZSIZ=1       RET oylarının "itirazlar" alanı boş.
  SAHTE_V023_SENTEZ_DUZ=ok|bozuk|ayni|hata   sentez düzeltmesi çağrısının davranışı (varsayılan ok).
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


def prompt_degistir(yeni):
    a = list(arg)
    if ad == "codex":
        a[-1] = yeni
    else:
        a[a.index("-p") + 1] = yeni
    return a


def kacis(t):
    return json.dumps(t, ensure_ascii=False)[1:-1]


def calistir(args, env):
    return subprocess.run([sys.executable, str(BASE), ad, *args], capture_output=True, text=True, env=env)


def bitir(r, stdout=None):
    sys.stdout.write(r.stdout if stdout is None else stdout)
    sys.stderr.write(r.stderr)
    sys.exit(r.returncode)


def liste(ad_env):
    return [x for x in os.environ.get(ad_env, "").split(",") if x]


p = prompt_bul()
env = dict(os.environ)

if "--version" in arg or p.strip() == "/usage" or not p or arg[:2] == ["auth", "status"]:
    bitir(calistir(arg, env))

# --- sentez düzeltmesi (karar 62)
if "İTİRAZLAR (kimliksiz)" in p:
    kip = os.environ.get("SAHTE_V023_SENTEZ_DUZ", "ok")
    if kip == "hata":
        env[f"SAHTE_{ad.upper()}"] = "kota"
        bitir(calistir(arg, env))
    n = len(re.findall(r"^\[R\d+\]", p, re.M))
    r = calistir(prompt_degistir("sentez yazarısın"), env)
    if kip == "bozuk":
        metin = "İTİRAZ KAYDI:\n- R1 KABUL: x\nDüzeltilmiş metni yazmayı unuttum."
    elif kip == "ayni":
        metin = ("İTİRAZ KAYDI:\n" + "\n".join(f"- R{i} RED: haksız itiraz" for i in range(1, n + 1))
                 + "\nDÜZELTİLMİŞ METİN:\n" + ESKI_SENTEZ)
    else:
        satirlar = ["- R1 KABUL: doğru, çünkü itiraz metindeki sayıyı yanlış bulduğunu gösteriyor; değişen: sayı düzeltildi"]
        satirlar += [f"- R{i} RED: kanıtsız itiraz" for i in range(2, n + 1)]
        metin = ("İTİRAZ KAYDI:\n" + "\n".join(satirlar) +
                 "\nDÜZELTİLMİŞ METİN:\nÖZET: düzeltilmiş ortak sonuç.\nCEVAP: test DÜZELTİLDİ-SENTEZ\nBELİRSİZLİKLER: Yok")
    bitir(r, r.stdout.replace(kacis(ESKI_SENTEZ), kacis(metin)))

# --- onay (oylama)
if "ÖNERİLEN ORTAK METİN" in p:
    ikinci = "DÜZELTİLDİ-SENTEZ" in p
    ret = liste("SAHTE_V023_RET_IKINCI" if ikinci else "SAHTE_V023_RET_ILK")
    env[f"SAHTE_{ad.upper()}"] = "ret" if ad in ret else "ok"
    r = calistir(arg, env)
    cikti = r.stdout
    if os.environ.get("SAHTE_V023_ITIRAZSIZ"):
        cikti = re.sub(r'\[\\?"önemli hata\\?"\]', "[]", cikti)
    bitir(r, cikti)

# --- eleştiri (zengin) ve düzeltme (yeni KABUL biçimi)
elestiri = ("=== CEVAP A ===" in p and "SENİN GÜNCEL CEVABIN" not in p and "sentez yazarısın" not in p)
if elestiri and os.environ.get("SAHTE_V023_ELESTIRI") == "zengin":
    etiketler = re.findall(r"^=== CEVAP (\w) ===$", p, re.M)
    ikinci_tur = "DÜZELTİLDİ" in p
    bolumler = []
    for e in etiketler:
        if ikinci_tur:
            govde = ("HATALAR\n- [1] (önem: önemli; güven: yüksek) HATA2-MADDESI\n"
                     "EKSİK NOKTALAR\n- [2] (önem: önemli; güven: orta) EKSIK2-MADDESI\n"
                     "KANITSIZ İDDİALAR\n- [3] (önem: küçük; güven: düşük) KANITSIZ2-MADDESI\n"
                     "İYİLEŞTİRME ÖNERİLERİ\n- [4] (öneri) ONERI2-MADDESI\n")
        else:
            govde = ("HATALAR\n- [1] (önem: kritik; güven: yüksek) HATA1-MADDESI\n"
                     "EKSİK NOKTALAR\n- [2] (önem: önemli; güven: orta) EKSIK1-MADDESI\n"
                     "KANITSIZ İDDİALAR\nSorun yok.\n"
                     "İYİLEŞTİRME ÖNERİLERİ\n- [3] (öneri) ONERI1-MADDESI\n")
        bolumler.append(f"=== CEVAP {e} HAKKINDA ===\n{govde}")
    sayi = ({"kritik": 0, "onemli": 2, "kucuk": 1} if ikinci_tur else {"kritik": 1, "onemli": 1, "kucuk": 0})
    j = {e: sayi for e in etiketler}
    if len(etiketler) == 2:
        j["daha_iyi"] = "A"
    yeni = "\n".join(bolumler) + "```json\n" + json.dumps(j) + "\n```"
    r = calistir(arg, env)
    cikti = re.sub(r'=== CEVAP A HAKKINDA ===.*?\\n```(?=")', lambda m: kacis(yeni), r.stdout, flags=re.S)
    bitir(r, cikti)

r = calistir(arg, env)
cikti = r.stdout
if "SENİN GÜNCEL CEVABIN" in p and not os.environ.get("SAHTE_V023_ESKI_BICIM"):
    cikti = cikti.replace("KABUL: sahte", "KABUL: doğru, çünkü sahte gerekçe yeterince uzun; değişen: sahte değişiklik")
bitir(r, cikti)
