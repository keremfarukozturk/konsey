"""
Salt okunurluk ve araç denetimi testleri (PROJE.md Bölüm 9, 6.6; açık soru 10).
Gerçek CLI yerine sahte_denetimli_cli.py kullanılır; gerçek kotaya, ~/.gemini ve ~/.codex'e dokunulmaz.

Çalıştırma (konsey klasöründe):  python -m unittest discover -s testler -v
"""
import asyncio
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import adaptor as A  # noqa: E402
import konsey as K  # noqa: E402

SAHTE = str(Path(__file__).resolve().parent / "sahte_denetimli_cli.py")


class AracDenetimiTesti(unittest.TestCase):
    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        kok = Path(self.gecici.name)
        self.kayitlar = kok / "cli_kayitlari"   # agy konuşmaları ve codex oturumları aynı köke yazılır
        self.beyin = kok / "agy_beyin"
        self.gozlem = kok / "gozlem.jsonl"
        self.calisma = kok / "oturum"
        self.calisma.mkdir()
        self.ayar = {
            "calisma_klasoru": str(self.calisma),
            "kayit_klasoru": str(kok / "kayitlar"),
            "cagri_zaman_asimi_sn": 30,
            "saglayicilar": {
                "claude": {"komut": [sys.executable, SAHTE, "claude"], "model": "opus"},
                "codex": {"komut": [sys.executable, SAHTE, "codex"], "model": "gpt-6.2-astra",
                          "kayit_dizini": str(self.kayitlar)},
                "gemini": {"komut": [sys.executable, SAHTE, "gemini"], "model": "gemini-4-neon-high",
                           "kayit_dizini": str(self.kayitlar), "beyin_dizini": str(self.beyin)},
            },
        }
        self.eski_ortam = dict(os.environ)
        for k in list(os.environ):
            if k.startswith("SAHTE_"):
                del os.environ[k]
        os.environ.update({"SAHTE_KAYIT_DIZINI": str(self.kayitlar), "SAHTE_BEYIN_DIZINI": str(self.beyin),
                           "SAHTE_GOZLEM": str(self.gozlem)})

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.eski_ortam)
        self.gecici.cleanup()

    def cagir(self, ad: str) -> A.CagriSonucu:
        return asyncio.run(A.cagir(ad, self.ayar["saglayicilar"][ad], "2+2 kaç?", 30, str(self.calisma)))

    def gozlemler(self) -> list[dict]:
        if not self.gozlem.exists():
            return []
        return [json.loads(x) for x in self.gozlem.read_text(encoding="utf-8").splitlines() if x.strip()]

    # --- engel katmanları: kanca ve --settings
    def test_agy_komutunda_strict_ve_kredi_kapali(self):
        komut = A.komut_olustur("gemini", {"komut": ["agy"], "model": "gemini-4-neon-high"}, "soru", 60)
        ayar = json.loads(komut[komut.index("--settings") + 1])
        self.assertEqual(ayar, {"toolPermission": "strict", "useG1Credits": False})
        self.assertIs(ayar["useG1Credits"], False, "Metin değer ('off') agy'yi hata ile durdurur")

    def test_kanca_agy_cagrilmadan_once_yerinde(self):
        s = self.cagir("gemini")
        self.assertEqual(s.durum, "ok", s.hata)
        g = self.gozlemler()
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0]["kanca"], A.AGY_HOOK_JSON)
        self.assertEqual(g[0]["settings"], A.AGY_AYARLARI)

    def test_kanca_icerigi_her_seye_deny_doner(self):
        h = json.loads(A.AGY_HOOK_JSON)["konsey-salt-okunur"]["PreToolUse"][0]
        self.assertEqual(h["matcher"], "*")
        komut = h["hooks"][0]["command"]
        self.assertTrue(komut.startswith("printf '%s' '"), "Kanca dış betik çalıştırmamalı")
        cevap = json.loads(komut[len("printf '%s' '"):-1])
        self.assertEqual(cevap["decision"], "deny")

    def test_bozulmus_kanca_yeniden_yazilir(self):
        yol = self.calisma / ".agents" / "hooks.json"
        yol.parent.mkdir()
        yol.write_text('{"baska": {}}', encoding="utf-8")
        self.assertEqual(self.cagir("gemini").durum, "ok")
        self.assertEqual(yol.read_text(encoding="utf-8"), A.AGY_HOOK_JSON)

    def test_kanca_yazilamazsa_agy_cagrilmaz(self):
        (self.calisma / ".agents").write_text("klasör yerine dosya", encoding="utf-8")
        s = self.cagir("gemini")
        self.assertEqual(s.durum, "error")
        self.assertTrue(s.hata.startswith(A.KANCA_HATASI))
        self.assertEqual(self.gozlemler(), [], "Kanca yokken agy çalıştırılmamalı")

    def test_kanca_codex_ve_claude_icin_gerekmez(self):
        (self.calisma / ".agents").write_text("klasör yerine dosya", encoding="utf-8")
        self.assertEqual(self.cagir("codex").durum, "ok")
        self.assertEqual(self.cagir("claude").durum, "ok")

    # --- agy çağrı sonrası denetim
    def test_agy_arac_kullanmadi_temiz(self):
        s = self.cagir("gemini")
        self.assertEqual((s.durum, s.arac_denetimi), ("ok", A.DENETIM_TEMIZ))

    def test_agy_reddedilen_araclar_temiz_sayilir(self):
        os.environ["SAHTE_AGY_ARAC"] = "reddedildi"
        s = self.cagir("gemini")
        self.assertEqual((s.durum, s.arac_denetimi), ("ok", A.DENETIM_TEMIZ))
        self.assertEqual((len(s.arac_ozeti["denenen"]), s.arac_ozeti["reddedilen"]), (2, 2))
        self.assertIn("denenen araç 2, reddedilen 2, çalışan 0", A.arac_ozeti_metni(s))

    def test_agy_calisan_arac_ihlal_ve_hata(self):
        os.environ["SAHTE_AGY_ARAC"] = "calisti"
        s = self.cagir("gemini")
        self.assertEqual(s.durum, "error")
        self.assertEqual(s.arac_denetimi, A.DENETIM_IHLAL)
        self.assertTrue(s.hata.startswith(A.ARAC_IHLALI))
        self.assertEqual(s.metin, "", "İhlal eden çağrının cevabı kullanılmamalı")

    def test_agy_arac_denemesi_bos_cevap_ayri_siniflanir(self):
        os.environ["SAHTE_AGY_ARAC"] = "bos_cevap"
        s = self.cagir("gemini")
        self.assertEqual(s.durum, "error")
        self.assertTrue(s.hata.startswith(A.ARAC_DENEMESI_BOS), s.hata)
        self.assertIn("write_file", s.hata)
        self.assertEqual(s.arac_denetimi, A.DENETIM_TEMIZ)
        self.assertEqual(K.eksik_ipucu(s), "araç denemesi nedeniyle boş cevap")

    def test_bos_cevap_denied_actions_yoksa_eski_hata(self):
        r = A.ciktiyi_coz("gemini", 0, json.dumps({"status": "SUCCESS", "response": ""}), "")
        self.assertEqual(r.hata, "agy boş cevap döndürdü")

    def test_agy_transcript_okunamazsa_yapilamadi_cagri_gecerli(self):
        for mod in ("transcript_yok", "bozuk_transcript"):
            with self.subTest(mod=mod):
                os.environ["SAHTE_AGY_ARAC"] = mod
                s = self.cagir("gemini")
                self.assertEqual((s.durum, s.arac_denetimi), ("ok", A.DENETIM_YOK), s.hata)

    def test_agy_denetimi_yol_enjeksiyonunu_reddeder(self):
        for kimlik in ("../x", "a/b", ""):
            self.assertIsNone(A.agy_transcript_denetle(str(self.beyin), kimlik))

    # --- Codex: komutlar sayılır, hata sayılmaz
    def test_codex_komutlari_sayilir_hata_olmaz(self):
        os.environ["SAHTE_CODEX_ARAC"] = "komut"
        s = self.cagir("codex")
        # v0.16 (karar 41): komut çalıştırma kapalı; bilinen araç olayı artık sayılmakla kalmaz, hata verir
        self.assertEqual((s.durum, s.arac_denetimi), ("error", A.DENETIM_IHLAL), s.hata)
        self.assertEqual(len(s.arac_ozeti["arac_cagrisi"]), 2)
        self.assertEqual([k["komut"] for k in s.arac_ozeti["komutlar"]], ["date", "ls"])
        self.assertIn("2 araç çağrısı, 2 kayıtlı komut", A.arac_ozeti_metni(s))

    def test_codex_arac_kullanmadi(self):
        s = self.cagir("codex")
        self.assertEqual(A.arac_ozeti_metni(s), "araç kullanmadı")

    def test_codex_kaydi_yoksa_yapilamadi(self):
        os.environ["SAHTE_CODEX_KAYIT"] = "yok"
        s = self.cagir("codex")
        self.assertEqual((s.durum, s.arac_denetimi), ("ok", A.DENETIM_YOK))

    def test_claude_araclar_kapali(self):
        self.assertEqual(self.cagir("claude").arac_denetimi, A.DENETIM_KAPALI)

    # --- rapor ve duman testi
    def test_raporda_bos_cevap_sayisi_ve_codex_komutlari(self):
        os.environ["SAHTE_AGY_ARAC"] = "bos_cevap"
        os.environ["SAHTE_CODEX_ARAC"] = "komut"
        s = asyncio.run(K.Konsey(self.ayar, tohum=42).calistir("Test sorusu?"))
        # v0.16: Codex komutu artık hata; Gemini boş cevap + Codex hata -> yalnızca Claude katılır
        self.assertEqual(s["durum"], "YETERSIZ_KATILIM")
        self.assertEqual(s["arac_denetimi"]["gemini"]["bos_cevap_arac_denemesi"], 1)
        self.assertIn("araç denemesi nedeniyle boş cevap: 1", s["rapor"])
        self.assertIn("araç denemesi nedeniyle boş cevap", s["eksik_katilim"]["tur0"]["gemini"])
        self.assertIn("Komut ve araç kullanımı hata sayılır", s["rapor"])
        self.assertIn("`date` (çıkış 0)", s["rapor"])
        self.assertEqual(list(s["arac_denetimi"]["claude"]["duzeyler"]), [A.DENETIM_KAPALI])

    def test_duman_ciktisinda_arac_denetimi(self):
        os.environ["SAHTE_AGY_ARAC"] = "reddedildi"
        cikti = io.StringIO()
        with contextlib.redirect_stdout(cikti):
            kod = asyncio.run(K.duman_testi(self.ayar, 30))
        metin = cikti.getvalue()
        self.assertEqual(kod, 0, metin)
        self.assertEqual(metin.count("araç denetimi:"), 3)
        self.assertIn("araç denetimi: araçlar kapalı", metin)
        self.assertIn("araç denetimi: araç kullanmadı", metin)
        self.assertIn("araç denetimi: temiz (denenen araç 2, reddedilen 2, çalışan 0)", metin)

    def test_duman_ciktisinda_ihlal_gorunur(self):
        os.environ["SAHTE_AGY_ARAC"] = "calisti"
        cikti = io.StringIO()
        with contextlib.redirect_stdout(cikti):
            kod = asyncio.run(K.duman_testi(self.ayar, 30))
        self.assertEqual(kod, 1)
        self.assertIn("araç çalıştırdı (salt okunurluk ihlali)", cikti.getvalue())
        self.assertIn("araç denetimi: ihlal", cikti.getvalue())


if __name__ == "__main__":
    unittest.main()
