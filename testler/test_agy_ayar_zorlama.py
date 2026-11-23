"""agy ayarları her çağrıda --settings ile zorlanır; dosyadaki değere güvenilmez ama dosya da denetlenir (karar 49).

Gerçek deney (20 Kasım 2026, scratch HOME'da dosya toolPermission="always-proceed"): --settings olmadan `touch` komutu
çalıştı (pozitif kontrol); --settings {"toolPermission":"strict",...} ile reddedildi ve dosya oluşmadı."""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import adaptor as A  # noqa: E402

KLASOR = Path(__file__).resolve().parent
SAHTE_AGY = str(KLASOR / "sahte_agy_yalitim_cli.py")


def ayari_al(komut: list[str]) -> dict:
    return json.loads(komut[komut.index("--settings") + 1])


class AyarZorlamaTesti(unittest.TestCase):
    def test_komut_her_cagrida_strict_ve_g1_zorlar(self):
        k = A.komut_olustur("gemini", {"komut": ["agy"], "model": "gemini-4-neon-high"}, "soru", 60)
        self.assertEqual(ayari_al(k), {"toolPermission": "strict", "useG1Credits": False})

    def test_ayar_sabiti_ve_yalitim_ayari_tutarli(self):
        self.assertEqual(json.loads(A.AGY_AYARLARI), A.AGY_YALITIM_AYARLARI)

    def test_home_ayari_olsa_da_olmasa_da_zorlanir(self):
        for s in ({"komut": ["agy"], "model": "m"}, {"komut": ["agy"], "model": "m", "home": "/x"}):
            self.assertEqual(ayari_al(A.komut_olustur("gemini", s, "soru", 60))["toolPermission"], "strict")

    def test_komut_degiskeni_dosya_degerinden_bagimsiz(self):
        """Komut yalnızca sabitten kurulur; settings.json'daki değer komuta sızmaz."""
        with tempfile.TemporaryDirectory() as d:
            ayar = Path(d) / ".gemini/antigravity-cli/settings.json"
            ayar.parent.mkdir(parents=True)
            ayar.write_text(json.dumps({"toolPermission": "always-proceed", "useG1Credits": True}), encoding="utf-8")
            k = A.komut_olustur("gemini", {"komut": ["agy"], "model": "m", "home": d}, "soru", 60)
        self.assertEqual(ayari_al(k), {"toolPermission": "strict", "useG1Credits": False})


class DosyaKontroluKaliyorTesti(unittest.TestCase):
    """Dosya gevşetilmişse (always-proceed) yalıtım doğrulaması hata verir ve agy hiç çalıştırılmaz."""

    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        self.addCleanup(self.gecici.cleanup)
        self.kok = Path(self.gecici.name)
        self.gercek_ev = self.kok / "gercek_ev"
        (self.gercek_ev / "Library" / "Keychains").mkdir(parents=True)
        self.calisma = self.kok / "oturum"
        self.calisma.mkdir()
        self.home = self.kok / "konsey-agy"
        self.s = {"komut": [sys.executable, SAHTE_AGY], "model": "gemini-4-neon-high", "home": str(self.home),
                  "gercek_gemini_dizini": str(self.gercek_ev / ".gemini")}
        p = mock.patch.object(A, "gercek_ev_dizini", return_value=self.gercek_ev)
        p.start()
        self.addCleanup(p.stop)
        A.agy_yalitimini_kur(self.s, str(self.calisma))
        self.dosya = self.home / ".gemini/antigravity-cli/settings.json"
        self.gozlem = self.kok / "ortam.jsonl"

    def cagir(self):
        with mock.patch.dict(os.environ, {"SAHTE_ORTAM_DOSYASI": str(self.gozlem)}):
            return asyncio.run(A.cagir("gemini", self.s, "2+2 kaç?", 30, str(self.calisma)))

    def test_gevsetilmis_dosya_cagriyi_engeller(self):
        ayar = json.loads(self.dosya.read_text(encoding="utf-8"))
        ayar["toolPermission"] = "always-proceed"
        self.dosya.write_text(json.dumps(ayar), encoding="utf-8")
        sorunlar = A.agy_yalitimini_dogrula(self.s, str(self.calisma))
        self.assertTrue(any("toolPermission" in x for x in sorunlar), sorunlar)
        r = self.cagir()
        self.assertEqual(r.durum, "error")
        self.assertTrue(r.hata.startswith(A.AGY_YALITIM_HATASI), r.hata)
        self.assertFalse(self.gozlem.exists(), "agy çalıştırılmamalıydı")

    def test_dosyada_true_g1_cagriyi_engeller(self):
        ayar = json.loads(self.dosya.read_text(encoding="utf-8"))
        ayar["useG1Credits"] = True
        self.dosya.write_text(json.dumps(ayar), encoding="utf-8")
        self.assertTrue(any("useG1Credits" in x for x in A.agy_yalitimini_dogrula(self.s, str(self.calisma))))

    def test_saglam_dosya_ve_zorlanan_komut_birlikte(self):
        self.assertEqual(A.agy_yalitimini_dogrula(self.s, str(self.calisma)), [])
        self.cagir()
        self.assertTrue(self.gozlem.exists())
        argv = json.loads(self.gozlem.read_text(encoding="utf-8").splitlines()[-1])["argv"]
        self.assertEqual(ayari_al(argv), {"toolPermission": "strict", "useG1Credits": False})


if __name__ == "__main__":
    unittest.main()
