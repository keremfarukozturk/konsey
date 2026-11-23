"""Duman testi agy yüzey kontrolü (karar 43): `agy mcp list` ve `agy plugin list` boş olmalı.
Sahte agy: testler/sahte_agy_yuzey_cli.py (`agy` adlı bir sarmalayıcı betikle çağrılır)."""
import asyncio
import contextlib
import io
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import adaptor as A  # noqa: E402
import konsey as K  # noqa: E402

KLASOR = Path(__file__).resolve().parent
SAHTE_AGY = str(KLASOR / "sahte_agy_yuzey_cli.py")
SAHTE = str(KLASOR / "sahte_denetimli_cli.py")


class YuzeyKontroluTesti(unittest.TestCase):
    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        self.addCleanup(self.gecici.cleanup)
        kok = Path(self.gecici.name)
        self.agy = kok / "bin" / "agy"
        self.agy.parent.mkdir()
        self.agy.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{SAHTE_AGY}" "$@"\n', encoding="utf-8")
        self.agy.chmod(self.agy.stat().st_mode | stat.S_IXUSR)
        self.calisma = kok / "oturum"
        self.calisma.mkdir()
        self.kayitlar, self.beyin = kok / "cli_kayitlari", kok / "agy_beyin"
        self.ayar = {
            "calisma_klasoru": str(self.calisma), "kayit_klasoru": str(kok / "kayitlar"), "cagri_zaman_asimi_sn": 30,
            "saglayicilar": {
                "claude": {"komut": [sys.executable, SAHTE, "claude"], "model": "opus"},
                "codex": {"komut": [sys.executable, SAHTE, "codex"], "model": "gpt-6.2-astra",
                          "kayit_dizini": str(self.kayitlar)},
                "gemini": {"komut": [str(self.agy)], "model": "gemini-4-neon-high",
                           "kayit_dizini": str(self.kayitlar), "beyin_dizini": str(self.beyin)},
            },
        }
        eski = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(eski)))
        for k in list(os.environ):
            if k.startswith("SAHTE_"):
                del os.environ[k]
        os.environ.update({"SAHTE_KAYIT_DIZINI": str(self.kayitlar), "SAHTE_BEYIN_DIZINI": str(self.beyin),
                           "SAHTE_GOZLEM": str(kok / "gozlem.jsonl")})

    def yokla(self) -> dict:
        s = self.ayar["saglayicilar"]["gemini"]
        return {k["komut"]: k for k in asyncio.run(A.agy_yuzeyini_yokla(s, str(self.calisma), 5))}

    def duman(self) -> tuple[int, str]:
        cikti = io.StringIO()
        with contextlib.redirect_stdout(cikti):
            kod = asyncio.run(K.duman_testi(self.ayar, 30))
        return kod, cikti.getvalue()

    # --- yoklama işlevi
    def test_agy_gercek_mi(self):
        self.assertTrue(A.agy_gercek_mi({"komut": ["~/.local/bin/agy"]}))
        self.assertTrue(A.agy_gercek_mi({"komut": [str(self.agy)]}))
        self.assertFalse(A.agy_gercek_mi({"komut": [sys.executable, SAHTE, "gemini"]}))

    def test_ikisi_bos(self):
        r = self.yokla()
        self.assertEqual({k: v["durum"] for k, v in r.items()},
                         {"agy mcp list": A.YUZEY_BOS, "agy plugin list": A.YUZEY_BOS})

    def test_mcp_dolu_gosterilir(self):
        os.environ["SAHTE_AGY_MCP"] = "notion  https://mcp.notion.example/mcp  enabled"
        r = self.yokla()
        self.assertEqual(r["agy mcp list"]["durum"], A.YUZEY_DOLU)
        self.assertIn("notion", r["agy mcp list"]["cikti"])
        self.assertEqual(r["agy plugin list"]["durum"], A.YUZEY_BOS)

    def test_plugin_dolu_gosterilir(self):
        os.environ["SAHTE_AGY_PLUGIN"] = "my-plugin  1.0.0  enabled"
        self.assertEqual(self.yokla()["agy plugin list"]["durum"], A.YUZEY_DOLU)

    def test_tanimsiz_cikti_bos_sayilmaz(self):
        os.environ["SAHTE_AGY_MCP"] = "bir şey"
        os.environ["SAHTE_AGY_PLUGIN"] = "No plugins installed. (1 built-in)"
        r = self.yokla()
        self.assertEqual((r["agy mcp list"]["durum"], r["agy plugin list"]["durum"]), (A.YUZEY_DOLU, A.YUZEY_DOLU))

    def test_hata_kodu_yoklanamadi(self):
        os.environ["SAHTE_AGY_YUZEY_KOD"] = "2"
        r = self.yokla()
        self.assertEqual({v["durum"] for v in r.values()}, {A.YUZEY_YOKLANAMADI})

    def test_zaman_asimi_yoklanamadi(self):
        os.environ["SAHTE_AGY_YUZEY"] = "zaman_asimi"
        s = self.ayar["saglayicilar"]["gemini"]
        k = asyncio.run(A.agy_yuzeyini_yokla(s, str(self.calisma), 1))
        self.assertEqual({v["durum"] for v in k}, {A.YUZEY_YOKLANAMADI})

    def test_program_yoksa_yoklanamadi(self):
        k = asyncio.run(A.agy_yuzeyini_yokla({"komut": [str(self.agy) + "-yok"]}, str(self.calisma), 5))
        self.assertEqual({v["durum"] for v in k}, {A.YUZEY_YOKLANAMADI})

    # --- duman testi
    def test_duman_bos_yuzeyle_basarili(self):
        os.environ["SAHTE_AGY_ARAC"] = "reddedildi"
        kod, metin = self.duman()
        self.assertEqual(kod, 0, metin)
        self.assertIn("✓ agy mcp list: boş", metin)
        self.assertIn("✓ agy plugin list: boş", metin)

    def test_duman_dolu_mcp_basarisiz_ve_bulunani_gosterir(self):
        os.environ["SAHTE_AGY_ARAC"] = "reddedildi"
        os.environ["SAHTE_AGY_MCP"] = "notion  https://mcp.notion.example/mcp"
        kod, metin = self.duman()
        self.assertEqual(kod, 1, metin)
        self.assertIn("✗ agy mcp list: BOŞ DEĞİL, bulunan:", metin)
        self.assertIn("notion  https://mcp.notion.example/mcp", metin)
        self.assertIn("✓ agy plugin list: boş", metin)
        self.assertIn("agy yüzey kontrolü BAŞARISIZ", metin)

    def test_duman_dolu_plugin_basarisiz(self):
        os.environ["SAHTE_AGY_ARAC"] = "reddedildi"
        os.environ["SAHTE_AGY_PLUGIN"] = "my-plugin"
        kod, metin = self.duman()
        self.assertEqual(kod, 1, metin)
        self.assertIn("✗ agy plugin list: BOŞ DEĞİL, bulunan:\n    my-plugin", metin)

    def test_duman_yoklanamazsa_basarisiz(self):
        os.environ["SAHTE_AGY_ARAC"] = "reddedildi"
        os.environ["SAHTE_AGY_YUZEY_KOD"] = "3"
        kod, metin = self.duman()
        self.assertEqual(kod, 1, metin)
        self.assertIn("YOKLANAMADI", metin)

    def test_duman_sahte_komutla_atlanir(self):
        os.environ["SAHTE_AGY_ARAC"] = "reddedildi"
        self.ayar["saglayicilar"]["gemini"]["komut"] = [sys.executable, SAHTE, "gemini"]
        kod, metin = self.duman()
        self.assertEqual(kod, 0, metin)
        self.assertIn("agy yüzey kontrolü: atlandı", metin)


if __name__ == "__main__":
    unittest.main()
