"""
v0.27: araştırma kapalıyken konseyin gördüğü bütün prompt'lar v0.26 ile birebir aynı kalmalı.
Altın dosya (altin_v026_promptlar.json) v0.27 değişikliklerinden ÖNCE, v0.26 koduyla üretildi.
İki sahte koşu kaydedilir (tarih sabit, --tur 2, araştırma kapalı):
  "madde"  : sahte_cli.py, her cevaba bir önemli madde
  "zengin" : sahte_v023_cli.py, dört alt başlık + kritik madde + RET ve sentez düzeltmesi + ikinci oylama
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
from test_v023_tarih_ve_kurallar import V023Tabani, SAHTE_V023  # noqa: E402

ALTIN = Path(__file__).resolve().parent / "altin_v026_promptlar.json"


class PromptlarAyniTesti(V023Tabani):
    def _kaydet(self, s) -> dict:
        return {a: p for a, p in sorted(self.tum_promptlar(s).items())}

    def _kosular(self) -> dict:
        eski = K.TARIH_SABIT
        K.TARIH_SABIT = "2026-11-20"
        try:
            os.environ["SAHTE_ELESTIRI"] = "madde"
            madde = self._kaydet(self.calistir(tur=2))
            os.environ.clear()
            os.environ.update({k: v for k, v in self.eski_ortam.items() if not k.startswith("SAHTE_")})
            os.environ["SAHTE_V023_ELESTIRI"] = "zengin"
            os.environ["SAHTE_V023_RET_ILK"] = "codex"
            zengin = self._kaydet(self.calistir(tur=2))
        finally:
            K.TARIH_SABIT = eski
        return {"madde": madde, "zengin": zengin}

    def test_promptlar_v026_ile_birebir_ayni(self):
        yeni = self._kosular()
        if os.environ.get("ALTIN_YAZ") == "1":
            ALTIN.write_text(json.dumps(yeni, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
            self.skipTest("altın dosya yazıldı")
        altin = json.loads(ALTIN.read_text("utf-8"))
        for kosu in ("madde", "zengin"):
            self.assertEqual(sorted(yeni[kosu]), sorted(altin[kosu]), f"{kosu}: çağrı dosyaları değişti")
            for ad, p in yeni[kosu].items():
                self.assertEqual(p, altin[kosu][ad], f"{kosu}/{ad}: prompt değişti")
        # Altın dosya gerçekten çeşitli prompt türleri içeriyor mu (boş bir karşılaştırma olmasın)
        for onek in ("tur0_", "tur1_elestiri_", "tur1_duzeltme_", "tur2_elestiri_", "tur2_duzeltme_", "sentez_", "onay_"):
            self.assertTrue(any(a.startswith(onek) for a in altin["zengin"]) or any(a.startswith(onek) for a in altin["madde"]),
                            onek)
        self.assertTrue(any(a.startswith("sentez_duzeltme_") for a in altin["zengin"]))
        self.assertTrue(any(a.startswith("onay2_") for a in altin["zengin"]))


if __name__ == "__main__":
    unittest.main()
