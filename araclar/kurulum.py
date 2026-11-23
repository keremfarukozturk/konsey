#!/usr/bin/env python3
"""Konsey ilk kurulum betiği (idempotent; var olan dosyaları ezmez).

Kullanım:
  python3 araclar/kurulum.py            # kur ve denetle
  python3 araclar/kurulum.py --kontrol  # yalnızca denetle, hiçbir şey değiştirme

Yaptıkları:
  1. Python sürümünü ve `claude`, `codex`, `agy` komutlarının bulunduğunu denetler (kurmaz, giriş yapmaz).
  2. Oturum klasörünü oluşturur (varsayılan ~/konsey-oturum; KONSEY_OTURUM ile değişir).
  3. Oturum klasörüne salt okunur agy kancasını (.agents/hooks.json) yazar. Dosya varsa ve içeriği beklenenden
     farklıysa ÜZERİNE YAZMAZ; uyarı verir (silip betiği yeniden çalıştırabilirsiniz).
  4. agy yalıtımını `araclar/agy_yalitim_kur.py` ile kurar ve doğrular (varsayılan ~/.konsey-agy; KONSEY_AGY_HOME ile değişir).
Giriş (login) elle yapılır: `claude`, `codex` ve `agy` komutlarında bir kez oturum açın.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
import adaptor as A  # noqa: E402

EN_AZ_PYTHON = (3, 10)


def main() -> int:
    ap = argparse.ArgumentParser(description="Konsey ilk kurulum betiği")
    ap.add_argument("--ayar", default=str(KOK / "modeller.json"))
    ap.add_argument("--kontrol", action="store_true", help="yalnızca denetle, değiştirme")
    a = ap.parse_args()
    sorun = 0

    if sys.version_info < EN_AZ_PYTHON:
        print(f"✗ Python {'.'.join(map(str, EN_AZ_PYTHON))} veya üzeri gerekir; çalışan sürüm: {sys.version.split()[0]}")
        return 1
    print(f"✓ Python {sys.version.split()[0]}")

    try:
        ayar = A.ayarlari_yukle(a.ayar)
    except (A.AyarHatasi, OSError, KeyError, ValueError) as e:
        print(f"✗ Ayar dosyası okunamadı: {e}")
        return 2

    for ad, s in ayar["saglayicilar"].items():
        komut = s["komut"][0]
        yol = komut if os.sep in komut else shutil.which(komut)
        if yol and os.path.isfile(yol) and os.access(yol, os.X_OK):
            print(f"✓ {ad}: {yol}")
        else:
            print(f"✗ {ad}: '{komut}' bulunamadı; CLI'ı kurun ya da modeller.json'daki 'komut' yolunu düzeltin")
            sorun += 1

    cal = Path(ayar["calisma_klasoru"])
    if cal.resolve() == KOK or KOK in cal.resolve().parents:
        print(f"✗ Oturum klasörü depo klasörünün içinde olamaz: {cal}")
        return 2
    kanca = cal / ".agents" / "hooks.json"
    if a.kontrol:
        print(("✓" if cal.is_dir() else "✗") + f" oturum klasörü: {cal}")
        if kanca.is_file() and kanca.read_text(encoding="utf-8") == A.AGY_HOOK_JSON:
            print("✓ agy kancası yerinde")
        else:
            print("✗ agy kancası yok ya da beklenenden farklı")
            sorun += 1
    else:
        cal.mkdir(parents=True, exist_ok=True)
        print(f"✓ oturum klasörü: {cal}")
        if kanca.exists() and kanca.read_text(encoding="utf-8") != A.AGY_HOOK_JSON:
            print(f"✗ {kanca} var ama içeriği beklenenden farklı; ezilmedi. İçeriği kontrol edin; gerekirse silip betiği yeniden çalıştırın.")
            sorun += 1
        else:
            ok, mesaj = A.agy_kancasini_hazirla(str(cal))
            print(("✓ " if ok else "✗ ") + mesaj)
            sorun += 0 if ok else 1

    komut = [sys.executable, str(KOK / "araclar" / "agy_yalitim_kur.py"), "--ayar", a.ayar]
    if a.kontrol:
        komut.append("--kontrol")
    sonuc = subprocess.run(komut)
    if sonuc.returncode != 0:
        sorun += 1

    print()
    if sorun:
        print(f"{sorun} sorun var; yukarıdaki ✗ satırlarına bakın.")
        return 1
    print("Kurulum tamam. Girişleri (claude, codex, agy) yaptıysanız: python3 konsey.py --duman")
    return 0


if __name__ == "__main__":
    sys.exit(main())
