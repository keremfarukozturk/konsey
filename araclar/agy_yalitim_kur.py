#!/usr/bin/env python3
"""Konseyin yalıtılmış agy HOME'unu kurar ve doğrular (karar 44).

Kullanım:
  python3 araclar/agy_yalitim_kur.py            # kur (idempotent) ve doğrula
  python3 araclar/agy_yalitim_kur.py --kontrol  # yalnızca doğrula; hiçbir şey değiştirmez
  python3 araclar/agy_yalitim_kur.py --ayar yol/modeller.json

Yaptıkları: ~/.konsey-agy (modeller.json'daki gemini.home) klasörünü chmod 700 ile oluşturur; içine strict ve
useG1Credits=false içeren settings.json (güvenilen çalışma klasörüyle) yazar; macOS'ta Library/Keychains klasörünü gerçek
Keychains klasörüne sembolik bağlar (giriş bilgisi Keychain'de; yeniden giriş gerekmesin). Gerçek ~/.gemini'ye ve
Keychains hedefine dokunmaz. Giriş yapmaz.
"""
import argparse
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
import adaptor as A  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Konsey agy yalıtımı")
    ap.add_argument("--ayar", default=str(KOK / "modeller.json"))
    ap.add_argument("--kontrol", action="store_true", help="yalnızca doğrula, değiştirme")
    a = ap.parse_args()
    try:
        ayar = A.ayarlari_yukle(a.ayar)
    except (A.AyarHatasi, OSError, KeyError, ValueError) as e:
        print(f"Ayar hatası: {e}")
        return 2
    s = ayar["saglayicilar"].get("gemini")
    if not s or not s.get("home"):
        print("modeller.json'da gemini.home yok; yalıtım yapılandırılmamış.")
        return 2
    if not a.kontrol:
        try:
            for satir in A.agy_yalitimini_kur(s, ayar["calisma_klasoru"]) or ["değişiklik gerekmedi"]:
                print(f"+ {satir}")
        except (A.AyarHatasi, OSError) as e:
            print(f"KURULAMADI: {e}")
            return 1
    sorunlar = A.agy_yalitimini_dogrula(s, ayar["calisma_klasoru"])
    for x in sorunlar:
        print(f"✗ {x}")
    if sorunlar:
        return 1
    print(f"✓ agy yalıtımı tamam: {s['home']}")
    print("  Not: agy'nin oturumu Keychain'de ('gemini' servisi); giriş yoksa konsey çağrısı hata verir, "
          "kullanıcı agy'de bir kez giriş yapmalıdır.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
