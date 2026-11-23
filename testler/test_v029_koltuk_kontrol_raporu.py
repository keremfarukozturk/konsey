"""v0.29: duman testindeki koltuk kontrolü (karar 64) ayrıntılı rapor verir; geçti/kaldı kararı değişmez.
Gerçek ev klasörüne dokunmaz (geçici klasör)."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import konsey as K  # noqa: E402

O1 = {"a.txt": (1, 10, ""), "b/c.json": (2, 20, "h")}


def calistir(*arg):
    with tempfile.TemporaryDirectory() as d:
        cikti = io.StringIO()
        with contextlib.redirect_stdout(cikti):
            ok = K.koltuk_kontrolu_raporla(*arg, d)
        kayit = Path(d) / "koltuk_kontrol.json"
        return ok, cikti.getvalue(), json.loads(kayit.read_text(encoding="utf-8")) if kayit.exists() else None


class KoltukKontrolRaporu(unittest.TestCase):
    def test_ayni_gecer_ve_ozet_kaydedilir(self):
        ok, cikti, kayit = calistir("x", "x", O1, dict(O1))
        self.assertTrue(ok)
        self.assertIn("✓", cikti)
        self.assertTrue(kayit["sonuc"]["tamam"])
        self.assertIn("a.txt", kayit["home_ozeti_once"])
        self.assertIn("a.txt", kayit["home_ozeti_sonra"])

    def test_home_yok_yalnizca_kanca(self):
        self.assertTrue(calistir("x", "x", None, None)[0])
        self.assertFalse(calistir("x", "y", None, None)[0])

    def test_kanca_degisti(self):
        ok, cikti, kayit = calistir("x", "y", O1, dict(O1))
        self.assertFalse(ok)
        self.assertIn("kanca hash'i", cikti)
        self.assertNotIn("HOME özeti", cikti)
        self.assertFalse(kayit["sonuc"]["kanca_ayni"])

    def test_home_farklari_yazilir(self):
        sonra = {"a.txt": (5, 10, ""), "b/c.json": (2, 99, "h"), "yeni.log": (3, 1, "")}
        ok, cikti, kayit = calistir("x", "x", O1, sonra)
        self.assertFalse(ok)
        self.assertIn("bozulan parça: HOME özeti", cikti)
        self.assertNotIn("kanca hash'i", cikti.split("bozulan parça:")[1].splitlines()[0])
        self.assertIn("eklendi: yeni.log", cikti)
        self.assertIn("değişti (mtime): a.txt", cikti)
        self.assertIn("değişti (boyut): b/c.json", cikti)
        sonra2 = {"a.txt": (1, 10, "")}
        self.assertIn("silindi: b/c.json", calistir("x", "x", O1, sonra2)[1])

    def test_ikisi_birden(self):
        ok, cikti, kayit = calistir("x", "y", O1, {})
        self.assertFalse(ok)
        self.assertIn("kanca hash'i, HOME özeti", cikti)
        self.assertEqual(sorted(kayit["sonuc"]["home_fark"]["silinen"]), ["a.txt", "b/c.json"])

    def test_karar_eski_kuralla_ayni(self):
        for kanca_ayni in (True, False):
            for home in (None, True, False):
                once = None if home is None else O1
                sonra = None if home is None else (O1 if home else {})
                beklenen = (True if kanca_ayni else False) and (home is None or home)
                self.assertEqual(K.koltuk_karsilastir("x", "x" if kanca_ayni else "y", once, sonra)["tamam"], beklenen)


if __name__ == "__main__":
    unittest.main()
