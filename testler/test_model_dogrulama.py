"""
Model doğrulama ve Codex kota okuma testleri (PROJE.md 6.2, açık soru 9; 8.5 kota sayacının ilk adımı).
Gerçek CLI yerine sahte_kayitli_cli.py kullanılır; gerçek kotaya ve gerçek ~/.gemini, ~/.codex klasörlerine dokunulmaz.

Çalıştırma (konsey klasöründe):  python -m unittest discover -s testler -v
"""
import asyncio
import contextlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import adaptor as A  # noqa: E402
import konsey as K  # noqa: E402

SAHTE = str(Path(__file__).resolve().parent / "sahte_kayitli_cli.py")


class ModelDogrulamaTesti(unittest.TestCase):
    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        kok = Path(self.gecici.name)
        self.gemini_dizini = kok / "agy_konusmalari"
        self.codex_dizini = kok / "codex_oturumlari"
        self.ayar = {
            "calisma_klasoru": str(kok / "oturum"),
            "kayit_klasoru": str(kok / "kayitlar"),
            "cagri_zaman_asimi_sn": 30,
            "saglayicilar": {
                "claude": {"komut": [sys.executable, SAHTE, "claude"], "model": "opus"},
                "codex": {"komut": [sys.executable, SAHTE, "codex"], "model": "gpt-6.2-astra",
                          "kayit_dizini": str(self.codex_dizini)},
                "gemini": {"komut": [sys.executable, SAHTE, "gemini"], "model": "gemini-4-neon-high",
                           "kayit_dizini": str(self.gemini_dizini)},
            },
        }
        Path(self.ayar["calisma_klasoru"]).mkdir(parents=True)
        self.eski_ortam = dict(os.environ)
        for k in list(os.environ):
            if k.startswith("SAHTE_"):
                del os.environ[k]

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.eski_ortam)
        self.gecici.cleanup()

    def cagir(self, ad: str, prompt: str = "2+2 kaç?") -> A.CagriSonucu:
        if ad == "gemini":
            os.environ["SAHTE_KAYIT_DIZINI"] = str(self.gemini_dizini)
        elif ad == "codex":
            os.environ["SAHTE_KAYIT_DIZINI"] = str(self.codex_dizini)
        return asyncio.run(A.cagir(ad, self.ayar["saglayicilar"][ad], prompt, 30, self.ayar["calisma_klasoru"]))

    # --- Gemini: sunucunun bildirdiği model (response_model)
    def test_gemini_sunucu_dogrulamasi(self):
        s = self.cagir("gemini")
        self.assertEqual(s.durum, "ok")
        self.assertEqual(s.model_dogrulama, A.DOGRULAMA_SUNUCU)
        self.assertEqual(s.gercek_model, "gemini-4-neon")
        self.assertTrue(s.oturum_kimligi)

    def test_gemini_model_uyusmazligi_hata(self):
        os.environ["SAHTE_GEMINI_YANIT_MODELI"] = "gemini-4-argon"
        s = self.cagir("gemini")
        self.assertEqual(s.durum, "error")
        self.assertTrue(s.hata.startswith(A.MODEL_UYUSMAZLIGI))
        self.assertIn("gemini-4-argon", s.hata)
        self.assertEqual(s.metin, "", "Uyuşmayan modelin cevabı kullanılmamalı")

    def test_gemini_efor_eki_ayni_seri_farkli_surum_uyusmaz(self):
        os.environ["SAHTE_GEMINI_YANIT_MODELI"] = "gemini-4-neon-lite"
        s = self.cagir("gemini")
        self.assertEqual(s.durum, "error")

    def test_gemini_non_gemini_hata(self):
        os.environ["SAHTE_GEMINI_NON_GEMINI"] = "true"
        s = self.cagir("gemini")
        self.assertEqual(s.durum, "error")
        self.assertIn("used_non_gemini_model", s.hata)

    def test_gemini_okunamayan_kayitlar_dogrulanamadi_olur(self):
        for durum in ("yok", "bozuk_blob", "tablo_yok", "cop_dosya", "alan_yok"):
            with self.subTest(kayit=durum):
                os.environ["SAHTE_GEMINI_KAYIT"] = durum
                s = self.cagir("gemini")
                self.assertEqual(s.durum, "ok", s.hata)
                self.assertEqual(s.model_dogrulama, A.DOGRULAMA_YOK)
                self.assertEqual(s.metin.strip(), "4")

    def test_kayit_dizini_yoksa_dogrulanamadi(self):
        self.ayar["saglayicilar"]["gemini"]["kayit_dizini"] = str(Path(self.gecici.name) / "yok")
        self.ayar["saglayicilar"]["codex"]["kayit_dizini"] = str(Path(self.gecici.name) / "yok")
        self.assertEqual(self.cagir("gemini").model_dogrulama, A.DOGRULAMA_YOK)
        s = self.cagir("codex")
        self.assertEqual((s.durum, s.model_dogrulama, s.kota), ("ok", A.DOGRULAMA_YOK, {}))

    # --- Codex: istemcinin gönderdiği model (turn_context.model) ve kota
    def test_codex_istemci_dogrulamasi_ve_kota(self):
        s = self.cagir("codex")
        self.assertEqual(s.durum, "ok")
        self.assertEqual(s.model_dogrulama, A.DOGRULAMA_ISTEMCI)
        self.assertEqual(s.kota["5_saat"]["kullanilan_yuzde"], 4.0)
        self.assertEqual(s.kota["haftalik"]["kullanilan_yuzde"], 1.0)
        self.assertTrue(s.kota["5_saat"]["sifirlanma"])
        self.assertEqual(s.kota["plan"], "plus")

    def test_codex_istemci_uyusmazligi_hata(self):
        os.environ["SAHTE_CODEX_ISTEMCI_MODELI"] = "gpt-6.1-sol"
        s = self.cagir("codex")
        self.assertEqual(s.durum, "error")
        self.assertTrue(s.hata.startswith(A.MODEL_UYUSMAZLIGI))
        self.assertIn("gpt-6.1-sol", s.hata)

    def test_codex_bozuk_kayit_cokertmez(self):
        for durum in ("yok", "cop_satirlar", "turn_context_yok"):
            with self.subTest(kayit=durum):
                os.environ["SAHTE_CODEX_KAYIT"] = durum
                s = self.cagir("codex")
                self.assertEqual(s.durum, "ok", s.hata)
                beklenen = A.DOGRULAMA_ISTEMCI if durum == "cop_satirlar" else A.DOGRULAMA_YOK
                self.assertEqual(s.model_dogrulama, beklenen)

    def test_codex_kota_kaydi_yoksa_bos(self):
        os.environ["SAHTE_CODEX_KOTA"] = "yok"
        s = self.cagir("codex")
        self.assertEqual((s.durum, s.model_dogrulama, s.kota), ("ok", A.DOGRULAMA_ISTEMCI, {}))

    def test_codex_kota_hatasinda_kota_okunur(self):
        os.environ["SAHTE_CODEX"] = "kota"
        os.environ["SAHTE_CODEX_KOTA"] = "sinirda"
        s = self.cagir("codex")
        self.assertEqual(s.durum, "rate_limited")
        self.assertEqual(s.model_dogrulama, "")
        self.assertEqual(s.kota["5_saat"]["kullanilan_yuzde"], 100.0)
        self.assertEqual(s.kota["sinira_ulasildi"], "primary")

    # --- Claude
    def test_claude_sunucu_dogrulamasi(self):
        s = self.cagir("claude")
        self.assertEqual((s.durum, s.model_dogrulama), ("ok", A.DOGRULAMA_SUNUCU))

    # --- yardımcılar
    def test_protobuf_cozucu_bozuk_veride_hata_firlatir(self):
        for veri in (b"\x0a\xff\xff\xff\x0f", b"\x00", b"\x0b", b"\x0a\x05ab"):
            with self.subTest(veri=veri):
                with self.assertRaises(ValueError):
                    A.protobuf_alanlari(veri)
        self.assertEqual(A.protobuf_alanlari(b"\x08\x96\x01\x12\x02hi"), [(1, 0, 150), (2, 2, b"hi")])

    def test_kimlik_yol_enjeksiyonuna_karsi_reddedilir(self):
        for kimlik in ("../gizli", "a/b", "", "x" * 200, "..", "abc;rm"):
            with self.subTest(kimlik=kimlik):
                self.assertIsNone(A.agy_kaydini_oku(str(self.gemini_dizini), kimlik))
                self.assertIsNone(A.codex_kaydini_oku(str(self.codex_dizini), kimlik))

    def test_blob_olmayan_kayit_cokertmez(self):
        self.gemini_dizini.mkdir(parents=True)
        kimlik = "12345678-aaaa-bbbb-cccc-1234567890ab"
        con = sqlite3.connect(self.gemini_dizini / f"{kimlik}.db")
        con.execute("CREATE TABLE gen_metadata (idx integer PRIMARY KEY, data blob)")
        con.execute("INSERT INTO gen_metadata VALUES (0, 'metin, blob değil')")
        con.commit()
        con.close()
        self.assertIsNone(A.agy_kaydini_oku(str(self.gemini_dizini), kimlik))

    def test_dogrulama_ozeti(self):
        self.assertEqual(K.dogrulama_ozeti(["sunucu", "sunucu"]), "sunucu")
        self.assertEqual(K.dogrulama_ozeti([]), "başarılı çağrı yok")
        self.assertIn("karışık", K.dogrulama_ozeti(["sunucu", "doğrulanamadı"]))

    # --- konsey ve duman testi
    def test_konseyde_uyusmazlik_eksik_katilim_sayilir(self):
        os.environ["SAHTE_GEMINI_YANIT_MODELI"] = "gemini-4-argon"
        os.environ["SAHTE_KAYIT_DIZINI"] = str(self.gemini_dizini)
        # codex kayıtları da aynı köke düşer; codex için kayıt dizinini buna eşitle
        self.ayar["saglayicilar"]["codex"]["kayit_dizini"] = str(self.gemini_dizini)
        s = asyncio.run(K.Konsey(self.ayar, tohum=42).calistir("Test sorusu?"))
        self.assertEqual(s["durum"], "IKIDE_IKI_BIR_EKSIK")
        self.assertIn("istenen model değil", s["eksik_katilim"]["tur0"]["gemini"])
        self.assertNotIn("gemini", s["model_dogrulama"])
        self.assertEqual(s["model_dogrulama"]["codex"], A.DOGRULAMA_ISTEMCI)
        self.assertEqual(s["model_dogrulama"]["claude"], A.DOGRULAMA_SUNUCU)
        self.assertIn("model doğrulama: istemci", s["rapor"])
        self.assertIn("GPT kotası (Codex oturum kaydından): 5 saatlik %4 kullanıldı", s["rapor"])

    def test_duman_ciktisinda_dogrulama_duzeyleri_ve_kota(self):
        os.environ["SAHTE_KAYIT_DIZINI"] = str(self.gemini_dizini)
        self.ayar["saglayicilar"]["codex"]["kayit_dizini"] = str(self.gemini_dizini)
        cikti = io.StringIO()
        with contextlib.redirect_stdout(cikti):
            kod = asyncio.run(K.duman_testi(self.ayar, 30))
        metin = cikti.getvalue()
        self.assertEqual(kod, 0, metin)
        self.assertIn("model doğrulama: sunucu", metin)
        self.assertIn("model doğrulama: istemci", metin)
        self.assertIn("GPT kotası: 5 saatlik %4 kullanıldı", metin)
        self.assertIn("haftalık %1 kullanıldı", metin)

    def test_duman_ciktisinda_dogrulanamadi_gorunur(self):
        os.environ["SAHTE_KAYIT_DIZINI"] = str(self.gemini_dizini)
        os.environ["SAHTE_GEMINI_KAYIT"] = "bozuk_blob"
        cikti = io.StringIO()
        with contextlib.redirect_stdout(cikti):
            kod = asyncio.run(K.duman_testi(self.ayar, 30))
        self.assertEqual(kod, 0)
        self.assertRegex(cikti.getvalue(), r"Gemini.*\n\s+model doğrulama: doğrulanamadı")


if __name__ == "__main__":
    unittest.main()
