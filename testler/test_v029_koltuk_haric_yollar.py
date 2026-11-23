"""v0.29 Aşama 1b (karar 67): koltuk HOME karşılaştırmasından yalnızca iki updater dosyası, tam yol eşleşmesiyle hariç."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import konsey as K  # noqa: E402

U = ".gemini/antigravity-cli/updater/"
DURUM, ZAMAN, KILIT = U + "update_status.json", U + "last_check.timestamp", U + "update.lock"
TABAN = {"a.txt": (1, 10, ""), DURUM: (1, 72, ""), ZAMAN: (1, 20, ""), KILIT: (1, 0, "")}


def rapor(once, sonra):
    with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()) as c:
        ok = K.koltuk_kontrolu_raporla("x", "x", once, sonra, d)
    return ok, c.getvalue()


class KoltukHaricYollar(unittest.TestCase):
    def test_iki_dosya_degisince_kontrol_bozulmaz_ve_bilgi_satiri_cikar(self):
        sonra = dict(TABAN)
        sonra[DURUM] = (9, 99, "")
        sonra[ZAMAN] = (9, 20, "")
        ok, cikti = rapor(TABAN, sonra)
        self.assertTrue(ok)
        self.assertIn(f"bilgi: hariç tutulan dosya değişti (degisen): {DURUM}", cikti)
        self.assertIn(f"bilgi: hariç tutulan dosya değişti (degisen): {ZAMAN}", cikti)

    def test_hariç_dosya_olusur_ya_da_silinirse_de_bozmaz(self):
        once = {k: v for k, v in TABAN.items() if k != ZAMAN}
        self.assertTrue(rapor(once, TABAN)[0])
        self.assertTrue(rapor(TABAN, once)[0])

    def test_ayni_klasordeki_baska_dosya_bozar(self):
        sonra = dict(TABAN)
        sonra[KILIT] = (9, 0, "")
        ok, cikti = rapor(TABAN, sonra)
        self.assertFalse(ok)
        self.assertIn(KILIT, cikti)

    def test_yeni_dosya_ayni_klasorde_bozar(self):
        sonra = dict(TABAN)
        sonra[U + "baska.json"] = (1, 1, "")
        self.assertFalse(rapor(TABAN, sonra)[0])

    def test_desen_ya_da_benzer_yol_hariç_degil(self):
        for yol in (U + "update_status.json.bak", ".gemini/updater/update_status.json",
                    "x/" + DURUM, U + "last_check.timestamp2"):
            once = {"a.txt": (1, 10, ""), yol: (1, 1, "")}
            sonra = {"a.txt": (1, 10, ""), yol: (2, 1, "")}
            self.assertFalse(rapor(once, sonra)[0], yol)

    def test_hariç_liste_tam_iki_yol(self):
        self.assertEqual(K.KOLTUK_HARIC_YOLLAR, {DURUM, ZAMAN})

    def test_hariç_olmayan_degisiklik_hariçle_birlikte_bozar_ve_yalniz_digeri_listelenir(self):
        sonra = dict(TABAN)
        sonra[DURUM] = (9, 99, "")
        sonra["a.txt"] = (5, 10, "")
        ok, cikti = rapor(TABAN, sonra)
        self.assertFalse(ok)
        self.assertIn("değişti (mtime): a.txt", cikti)
        self.assertNotIn("değişti (mtime): " + DURUM, cikti)


# v1.0.1: updater klasörünün kendi mtime farkı yok sayılır (karar 67 kapsamı)
UD = ".gemini/antigravity-cli/updater"
KLASORLU = dict(TABAN)
KLASORLU[UD] = (100, 128, "")


class KlasorMtime(unittest.TestCase):
    def test_yalniz_klasor_mtime_degisince_gecer_ve_bilgi_satiri_cikar(self):
        sonra = dict(KLASORLU)
        sonra[UD] = (200, 128, "")
        ok, cikti = rapor(KLASORLU, sonra)
        self.assertTrue(ok)
        self.assertIn(f"bilgi: klasörün kendi mtime farkı yok sayıldı: {UD}", cikti)

    def test_klasore_yeni_dosya_eklenince_bozulur(self):
        sonra = dict(KLASORLU)
        sonra[UD] = (200, 160, "")
        sonra[U + "yeni.bin"] = (200, 5, "")
        self.assertFalse(rapor(KLASORLU, sonra)[0])
        yalniz_dosya = dict(KLASORLU)
        yalniz_dosya[U + "yeni.bin"] = (200, 5, "")       # klasör mtime'ı aynı kalsa da yeni dosya hata
        self.assertFalse(rapor(KLASORLU, yalniz_dosya)[0])

    def test_klasorde_dosya_silinince_bozulur(self):
        sonra = {k: v for k, v in KLASORLU.items() if k != KILIT}
        sonra[UD] = (200, 96, "")
        self.assertFalse(rapor(KLASORLU, sonra)[0])

    def test_klasordeki_baska_dosya_degisince_bozulur_klasor_mtime_olsa_da(self):
        sonra = dict(KLASORLU)
        sonra[UD] = (200, 128, "")
        sonra[KILIT] = (9, 0, "")
        ok, cikti = rapor(KLASORLU, sonra)
        self.assertFalse(ok)
        self.assertIn(KILIT, cikti)

    def test_klasor_boyutu_degisirse_bozulur(self):
        sonra = dict(KLASORLU)
        sonra[UD] = (200, 160, "")
        self.assertFalse(rapor(KLASORLU, sonra)[0])


if __name__ == "__main__":
    unittest.main()
