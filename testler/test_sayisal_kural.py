"""Tur 0 sayısal uzlaşı kuralı (sayisal.py): birim, tolerans, çok satır, okunamayan sonuç. Model ya da CLI çağrılmaz."""
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import sayisal as S  # noqa: E402

def ok(metin):
    return {"durum": "ok", "metin": metin}


class KuralTesti(unittest.TestCase):
    def u(self, a, b, c, tol=0.01):
        return S.tur0_uzlasi({"claude": ok(a), "codex": ok(b), "gemini": ok(c)}, tol)

    def test_uyumlu(self):
        r = self.u("x\nSONUÇ: 15.59 V", "SONUÇ: 15.60 V", "SONUÇ: 15.58 V")
        self.assertTrue(r["uzlasi"])
        self.assertEqual((r["ortanca"], r["birim"], r["saglanmayan"]), (15.59, "V", []))

    def test_birimsiz_esdeger(self):
        r = self.u("SONUÇ: 0.3 -", "SONUÇ: 0.3 birimsiz", "SONUÇ: 0.3")
        self.assertTrue(r["uzlasi"])
        self.assertEqual(r["birim"], "birimsiz")

    def test_V_ile_mV_farkli(self):
        r = self.u("SONUÇ: 5 V", "SONUÇ: 5 V", "SONUÇ: 5 mV")
        self.assertFalse(r["uzlasi"])
        self.assertEqual(r["saglanmayan"], ["c_birim_ayni"])
        self.assertFalse(self.u("SONUÇ: 5 MV", "SONUÇ: 5 mV", "SONUÇ: 5 mV")["uzlasi"])  # büyük/küçük harf korunur

    def test_birim_ile_birimsiz_farkli(self):
        self.assertFalse(self.u("SONUÇ: 5 V", "SONUÇ: 5 V", "SONUÇ: 5")["uzlasi"])

    def test_mikro_isaretleri_ayni(self):
        self.assertTrue(self.u("SONUÇ: 54 µH", "SONUÇ: 54 μH", "SONUÇ: 54 µH")["uzlasi"])

    def test_tolerans(self):
        self.assertFalse(self.u("SONUÇ: 100 V", "SONUÇ: 100 V", "SONUÇ: 102 V")["uzlasi"])
        self.assertTrue(self.u("SONUÇ: 100 V", "SONUÇ: 100 V", "SONUÇ: 102 V", tol=0.05)["uzlasi"])

    def test_iki_deger_sifir_esit_biri_sifir_degil(self):
        self.assertTrue(self.u("SONUÇ: 0 V", "SONUÇ: 0 V", "SONUÇ: 0 V")["uzlasi"])
        self.assertFalse(self.u("SONUÇ: 0 V", "SONUÇ: 0 V", "SONUÇ: 0.001 V")["uzlasi"])

    def test_birden_cok_satirda_sonuncu(self):
        r = self.u("SONUÇ: 1 V\nilk tahmindi\nSONUÇ: 2 V", "SONUÇ: 2 V", "SONUÇ: 2 V")
        self.assertTrue(r["uzlasi"])
        self.assertEqual(r["ortanca"], 2.0)

    def test_okunamayanlar(self):
        for kotu in ("cevap SONUÇ satırı içermiyor", "SONUÇ: 0,275 V", "SONUÇ: <sayı> <birim>", "SONUÇ: yaklaşık beş V"):
            r = self.u(kotu, "SONUÇ: 5 V", "SONUÇ: 5 V")
            self.assertFalse(r["uzlasi"], kotu)
            self.assertEqual(r["saglanmayan"], ["b_sonuc_okunur", "c_birim_ayni", "d_tolerans_icinde"], kotu)

    def test_basarisiz_cagri(self):
        r = S.tur0_uzlasi({"claude": ok("SONUÇ: 5 V"), "codex": ok("SONUÇ: 5 V"),
                           "gemini": {"durum": "error", "metin": ""}})
        self.assertFalse(r["uzlasi"])
        self.assertIn("a_durum_ok", r["saglanmayan"])

    def test_uc_koltuk_gerekli(self):
        self.assertFalse(S.tur0_uzlasi({"claude": ok("SONUÇ: 5 V"), "codex": ok("SONUÇ: 5 V")})["uzlasi"])



if __name__ == "__main__":
    unittest.main()
