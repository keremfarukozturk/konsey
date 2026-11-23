"""
v0.29: v0.29 bayraklarıyla (V029_OZELLIKLERI) konseyin gördüğü bütün prompt'lar altın dosyayla (altin_v029_promptlar.json)
birebir aynı kalmalı. v0.26 altın dosyası (altin_v026_promptlar.json) ve onu kilitleyen test DEĞİŞMEDİ: bayraksız Konsey
v0.28 promptlarını üretmeye devam eder.
İki sahte koşu (tarih sabit, --tur 2, araştırma kapalı; sahte_v029_cli.py):
  "uzun" : her kategoriden madde + karışık kararlar (KABUL/KISMEN/RED/ÇÖZÜLEMEDİ) + ÇÖZÜLEMEDİ'li sentez
  "bos"  : boş liste (düzeltme atlanır)
Altın dosyayı yeniden üretmek gerekirse (yalnızca prompt değişikliği bilerek yapıldığında):  ALTIN_YAZ=1 python -m unittest ...
"""
import json
import os
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import konsey as K  # noqa: E402
from test_v023_tarih_ve_kurallar import V023Tabani  # noqa: E402

SAHTE_V029 = str(Path(__file__).resolve().parent / "sahte_v029_cli.py")
ALTIN = Path(__file__).resolve().parent / "altin_v030_promptlar.json"   # v0.30b: Tur 0/sentez/onay promptları değişti; altin_v029 dosyası arşivde


class PromptlarAyniTesti(V023Tabani):
    def setUp(self):
        super().setUp()
        for ad in ("claude", "codex", "gemini"):
            self.ayar["saglayicilar"][ad]["komut"] = [sys.executable, SAHTE_V029, ad]

    def _kosu(self, env: dict) -> dict:
        for k in list(os.environ):
            if k.startswith("SAHTE_V029"):
                del os.environ[k]
        os.environ.update(env)
        self.ayar["kayit_klasoru"] = str(self.kok / f"kayit_{len(self.ayar.setdefault('_kosular', []))}")
        self.ayar["_kosular"].append(env)   # her koşu ayrı kayıt klasörüne yazar (aynı saniyedeki koşular karışmasın)
        s = self.calistir(tur=2, v029=K.V029_OZELLIKLERI)
        return {a: p for a, p in sorted(self.tum_promptlar(s).items())}

    def _kosular(self) -> dict:
        eski = K.TARIH_SABIT
        K.TARIH_SABIT = "2026-11-22"
        try:
            uzun = self._kosu({"SAHTE_V029_ELESTIRI": "uzun", "SAHTE_V029_DUZELTME": "karisik",
                               "SAHTE_V029_BELIRSIZ": "var"})
            bos = self._kosu({"SAHTE_V029_ELESTIRI": "bos"})
        finally:
            K.TARIH_SABIT = eski
        return {"uzun": uzun, "bos": bos}

    def test_promptlar_v030_altin_dosyayla_birebir_ayni(self):
        yeni = self._kosular()
        if os.environ.get("ALTIN_YAZ") == "1":
            ALTIN.write_text(json.dumps(yeni, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
            self.skipTest("altın dosya yazıldı")
        altin = json.loads(ALTIN.read_text("utf-8"))
        for kosu in ("uzun", "bos"):
            self.assertEqual(sorted(yeni[kosu]), sorted(altin[kosu]), f"{kosu}: çağrı dosyaları değişti")
            for ad, p in yeni[kosu].items():
                self.assertEqual(p, altin[kosu][ad], f"{kosu}/{ad}: prompt değişti")
        for onek in ("tur0_", "tur1_elestiri_", "tur1_duzeltme_", "sentez_", "onay_"):
            self.assertTrue(any(a.startswith(onek) for a in altin["uzun"]), onek)
        self.assertTrue(any("AŞIRI GENELLEME" in p for p in altin["uzun"].values()))
        self.assertTrue(any("DAYANAK" in p for p in altin["uzun"].values()))
        self.assertTrue(any("DOĞRULAYAMADIĞI" in p for a, p in altin["uzun"].items() if a.startswith("sentez_")))


if __name__ == "__main__":
    unittest.main()
