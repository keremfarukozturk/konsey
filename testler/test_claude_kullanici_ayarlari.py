"""Claude kullanıcı ayarlarının yalıtımı ve kimlik kaynağı denetimi (karar 48).

Gerçek deney (20 Kasım 2026, scratchpad'de proje düzeyi .claude/settings.json ile ulaşılamayan ANTHROPIC_BASE_URL):
bayraksız ve --safe-mode ile ayar env'i yüklendi (çağrı zaman aşımı); --setting-sources "" ile yüklenmedi ve çağrı
abonelik girişiyle çalıştı (init.apiKeySource = "none"). --bare OAuth/keychain okumadığı için seçilmedi."""
import asyncio
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import adaptor as A  # noqa: E402

ORNEK = Path(__file__).resolve().parent / "ornekler" / "claude_akis" / "temiz_akis.jsonl"


def olaylar() -> list[dict]:
    return [json.loads(x) for x in ORNEK.read_text(encoding="utf-8").splitlines() if x.strip()]


def metin(ev: list[dict]) -> str:
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in ev) + "\n"


def coz(ev: list[dict]) -> A.CagriSonucu:
    out = metin(ev)
    s = A.ciktiyi_coz("claude", 0, out, "")
    A.claude_yuzeyini_denetle(out, s)
    return s


class KomutTesti(unittest.TestCase):
    def setUp(self):
        self.k = A.komut_olustur("claude", {"komut": ["claude"], "model": "opus"}, "soru", 60)

    def test_setting_sources_bos_deger(self):
        i = self.k.index("--setting-sources")
        self.assertEqual(self.k[i + 1], "")  # boş dize argüman olarak korunur (hiçbir kaynak yüklenmez)

    def test_bare_ve_safe_mode_yok(self):
        """--bare OAuth/keychain okumaz (abonelik girişini bozar); --safe-mode settings env'ini yüklemeye devam eder."""
        self.assertNotIn("--bare", self.k)
        self.assertNotIn("--safe-mode", self.k)

    def test_diger_yalitim_bayraklari_yerinde(self):
        for b in ("--strict-mcp-config", "--disallowedTools", "--tools", "--verbose"):
            self.assertIn(b, self.k)
        self.assertEqual(self.k[-2:], ["--tools", ""])
        self.assertEqual(self.k[self.k.index("--disallowedTools") + 1], "mcp__*")
        self.assertEqual(self.k[self.k.index("--output-format") + 1], "stream-json")

    def test_prompt_degisken_uzunluklu_bayraklardan_once(self):
        self.assertEqual(self.k[:3], ["claude", "-p", "soru"])


class KimlikKaynagiTesti(unittest.TestCase):
    def test_gercek_ornekte_kaynak_none(self):
        self.assertEqual(olaylar()[0]["apiKeySource"], "none")

    def test_none_gecer(self):
        s = coz(olaylar())
        self.assertEqual((s.durum, s.arac_denetimi), ("ok", A.DENETIM_KAPALI), s.hata)
        self.assertEqual(s.arac_ozeti["apiKeySource"], "none")

    def test_api_kaynaklari_hata_verir(self):
        for kaynak in ("ANTHROPIC_API_KEY", "apiKeyHelper", "/login managed key", "baska", ""):
            with self.subTest(kaynak=kaynak):
                ev = olaylar()
                ev[0]["apiKeySource"] = kaynak
                s = coz(ev)
                self.assertEqual((s.durum, s.arac_denetimi, s.metin), ("error", A.DENETIM_IHLAL, ""), s.hata)
                self.assertTrue(s.hata.startswith(A.CLAUDE_YUZEYI), s.hata)
                self.assertIn("apiKeySource", s.hata)
                self.assertIn("faturalama", s.hata)

    def test_alan_yoksa_hata_verir(self):
        ev = olaylar()
        del ev[0]["apiKeySource"]
        s = coz(ev)
        self.assertEqual((s.durum, s.arac_denetimi), ("error", A.DENETIM_IHLAL), s.hata)
        self.assertIn("apiKeySource yok", s.hata)

    def test_alan_null_ise_hata(self):
        ev = olaylar()
        ev[0]["apiKeySource"] = None
        self.assertEqual(coz(ev).durum, "error")

    def test_basarisiz_cagrida_durum_degismez_ama_ihlal_isaretlenir(self):
        ev = olaylar()
        ev[0]["apiKeySource"] = "ANTHROPIC_API_KEY"
        son = next(e for e in ev if e.get("type") == "result")
        son["is_error"], son["result"] = True, "Claude AI usage limit reached|1763500000"
        s = coz(ev)
        self.assertEqual((s.durum, s.arac_denetimi), ("rate_limited", A.DENETIM_IHLAL))

    def test_ihlal_arac_ozeti_metninde_gorunur(self):
        ev = olaylar()
        ev[0]["apiKeySource"] = "apiKeyHelper"
        self.assertIn("apiKeySource='apiKeyHelper'", A.arac_ozeti_metni(coz(ev)))


class UctanUcaTesti(unittest.TestCase):
    """Gerçek `cagir` yolu: kayıtlı gerçek akışı basan geçici betik, apiKeySource ortam değişkeniyle bozulur."""

    def cagir(self, kaynak: str | None) -> A.CagriSonucu:
        with tempfile.TemporaryDirectory() as d:
            betik = Path(d) / "claude_sahte.py"
            betik.write_text(
                "import json, os, sys\n"
                f"ev=[json.loads(x) for x in open({str(ORNEK)!r}, encoding='utf-8') if x.strip()]\n"
                "k=os.environ.get('SAHTE_KAYNAK')\n"
                "if k=='__yok__': del ev[0]['apiKeySource']\n"
                "elif k is not None: ev[0]['apiKeySource']=k\n"
                "sys.stdout.write('\\n'.join(json.dumps(e) for e in ev)+'\\n')\n", encoding="utf-8")
            ortam = {"SAHTE_KAYNAK": kaynak} if kaynak is not None else {}
            with mock.patch.dict(os.environ, ortam):
                return asyncio.run(A.cagir("claude", {"komut": [sys.executable, str(betik)], "model": "opus"},
                                           "2+2 kaç?", 30, d))

    def test_abonelik_gecer(self):
        s = self.cagir(None)
        self.assertEqual((s.durum, s.arac_denetimi), ("ok", A.DENETIM_KAPALI), s.hata)

    def test_api_anahtari_kaynagi_cagriyi_hata_yapar(self):
        s = self.cagir("ANTHROPIC_API_KEY")
        self.assertEqual((s.durum, s.metin), ("error", ""), s.hata)
        self.assertIn("apiKeySource='ANTHROPIC_API_KEY'", s.hata)

    def test_kaynak_alani_yoksa_hata(self):
        self.assertEqual(self.cagir("__yok__").durum, "error")


if __name__ == "__main__":
    unittest.main()
