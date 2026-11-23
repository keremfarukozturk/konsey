"""
v0.26 testleri (karar 65): test yalıtımı. Bu dosya adı gereği keşifte ilk yüklenir ve import anında koruma kurulur
(HOME geçici klasöre; gerçek ev klasörüne yazma girişimi BaseException ile testi başarısız yapar).
Yeni dosyadır; mevcut testlere dokunulmadı.
"""
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ev_korumasi as EK  # noqa: E402

EK.kur()   # import anında: ondan sonra yüklenen bütün test modülleri geçici HOME'u görür

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))


class EvKorumasiTesti(unittest.TestCase):
    def deneme_yolu(self) -> Path:
        return EK.GERCEK_EV / f".konsey-test-ev-korumasi-deneme-{uuid.uuid4().hex}"

    def test_koruma_etkin_ve_home_gecici(self):
        self.assertTrue(EK.aktif_mi())
        gecici = EK.gecici_ev()
        self.assertIsNotNone(gecici)
        self.assertEqual(Path(os.environ["HOME"]).resolve(), gecici)
        self.assertEqual(Path.home().resolve(), gecici)
        self.assertEqual(Path(os.path.expanduser("~")).resolve(), gecici)
        self.assertNotEqual(gecici, EK.GERCEK_EV)
        self.assertNotIn(EK.GERCEK_EV, gecici.parents)

    def test_tilde_acilimlari_gecici_homea_gider(self):
        import arastirma as R
        for yol in R.VARSAYILAN_YOLLAR["gemini"].values():
            self.assertTrue(str(Path(yol).expanduser()).startswith(str(EK.gecici_ev())), yol)
        self.assertTrue(str(Path(R.VARSAYILAN_YOLLAR["codex"]["calisma_klasoru"]).expanduser()).startswith(str(EK.gecici_ev())))

    def test_alt_surec_gecici_homeu_gorur(self):
        r = subprocess.run([sys.executable, "-I", "-c", "import os;print(os.path.expanduser('~'))"],
                           capture_output=True, text=True, timeout=30, env=dict(os.environ))
        self.assertEqual(Path(r.stdout.strip()).resolve(), EK.gecici_ev())

    def test_gercek_eve_yazma_girisimi_testi_basarisiz_yapar(self):
        y = self.deneme_yolu()
        for ad, islem in {
            "open w": lambda: open(y, "w"),
            "open a": lambda: open(y, "a"),
            "open x": lambda: open(y, "x"),
            "os.open": lambda: os.open(y, os.O_CREAT | os.O_WRONLY),
            "write_text": lambda: y.write_text("x"),
            "mkdir": lambda: y.mkdir(),
            "symlink": lambda: os.symlink("/tmp", y),
            "rename": lambda: os.rename(Path(tempfile.gettempdir()) / "yok-konsey-test", y),
            "makedirs": lambda: os.makedirs(y / "alt"),
        }.items():
            with self.subTest(ad):
                with self.assertRaises(EK.EvDizinineYazmaGirisimi):
                    islem()
        self.assertFalse(y.exists() or y.is_symlink(), "kanca işlemi gerçekleşmeden önce durdurmalı")
        self.assertTrue(EK.ihlaller())

    def test_ihlal_except_exception_ile_yutulamaz(self):
        y = self.deneme_yolu()
        yutuldu = False
        try:
            try:
                open(y, "w")
            except Exception:       # noqa: BLE001 — yutmamalı: BaseException
                yutuldu = True
        except EK.EvDizinineYazmaGirisimi:
            pass
        self.assertFalse(yutuldu)
        self.assertFalse(issubclass(EK.EvDizinineYazmaGirisimi, Exception))
        self.assertFalse(y.exists())

    def test_gercek_evdeki_sembolik_baga_yazma_da_engellenir(self):
        gecici = EK.gecici_ev()
        hedef = self.deneme_yolu()                # gerçek evde, var olmayan hedef
        bag = gecici / "bag"
        os.symlink(hedef, bag)                    # sembolik bağı geçici HOME'da kurmak serbest
        try:
            with self.assertRaises(EK.EvDizinineYazmaGirisimi):
                open(bag / "dosya", "w")
            with self.assertRaises(EK.EvDizinineYazmaGirisimi):
                open(bag, "w")                    # bağ üzerinden hedefe yazma
            self.assertFalse(hedef.exists())
        finally:
            os.unlink(bag)                        # bağın kendisini silmek (hedefi değil) serbest

    def test_depo_ve_gecici_klasorlere_yazmak_serbest(self):
        with tempfile.TemporaryDirectory() as g:
            (Path(g) / "a.txt").write_text("x")
        (EK.gecici_ev() / "serbest.txt").write_text("x")
        (EK.gecici_ev() / "klasor" / "alt").mkdir(parents=True)
        self.assertTrue(EK.yasak_mi(EK.GERCEK_EV / "baska-bir-yer" / "x"))
        self.assertFalse(EK.yasak_mi(KOK / "kayitlar" / "x"))
        self.assertFalse(EK.yasak_mi(EK.gecici_ev() / "x"))
        self.assertFalse(EK.yasak_mi(Path("/tmp/baska") if not str(Path("/tmp")).startswith(str(EK.GERCEK_EV)) else None))

    def test_codex_oturumlari_salt_okunur_baglidir(self):
        bag = EK.gecici_ev() / ".codex" / "sessions"
        if not (EK.GERCEK_EV / ".codex" / "sessions").is_dir():
            self.skipTest("gerçek ~/.codex/sessions yok")
        self.assertTrue(bag.is_symlink())
        os.listdir(bag)                                   # okuma serbest
        with self.assertRaises(EK.EvDizinineYazmaGirisimi):
            open(bag / f".konsey-test-ev-korumasi-deneme-{uuid.uuid4().hex}", "w")  # bağ üzerinden gerçek eve yazma engelli
        with self.assertRaises(EK.EvDizinineYazmaGirisimi):
            (bag / f".konsey-test-ev-korumasi-deneme-{uuid.uuid4().hex}").mkdir()

    def test_okuma_serbest(self):
        os.listdir(EK.GERCEK_EV)
        (KOK / "konsey.py").read_text(encoding="utf-8")

    def test_ev_goruntusu_degismez_ve_gecici_ev_dahil_degil(self):
        self.assertEqual(EK.ev_goruntusu(), EK.ilk_goruntu())


if __name__ == "__main__":
    unittest.main()
