"""Sağlayıcıya özel ortam temizliği (karar 46): çağrıyı API faturalandırmasına, başka sunucuya/sağlayıcıya/hesaba ya da
başka yapılandırma klasörüne yönlendirebilecek değişkenler alt süreçten silinir; ağ taşıma ayarları silinmez."""
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

KLASOR = Path(__file__).resolve().parent
SAHTE = str(KLASOR / "sahte_agy_yalitim_cli.py")
NETWORK = {"HTTP_PROXY": "p", "HTTPS_PROXY": "p", "ALL_PROXY": "p", "NO_PROXY": "n", "SSL_CERT_FILE": "c",
           "NODE_EXTRA_CA_CERTS": "c", "REQUESTS_CA_BUNDLE": "c", "CODEX_CA_CERTIFICATE": "c"}
SAKLANACAK = {"PATH": "/usr/bin", "HOME": "/h", "LANG": "tr_TR.UTF-8", "USER": "u", **NETWORK}


def kirli(ad: str) -> dict:
    """Sağlayıcının listelerindeki bütün adlardan + önek örneklerinden oluşan kirli ortam."""
    adlar, onekler = A.SAGLAYICI_ORTAMI[ad]
    e = {k: "x" for k in adlar}
    e.update({o + "ORNEK": "x" for o in onekler})
    e.update(SAKLANACAK)
    return e


class OrtamTemizligiTesti(unittest.TestCase):
    def test_her_saglayici_kendi_listesini_siler(self):
        for ad in ("claude", "codex", "gemini"):
            with self.subTest(ad=ad):
                e = kirli(ad)
                kalan = A.temiz_ortam(ad, e)
                adlar, onekler = A.SAGLAYICI_ORTAMI[ad]
                self.assertFalse(set(adlar) & set(kalan), set(adlar) & set(kalan))
                self.assertFalse([k for k in kalan if k.startswith(onekler)])
                for k, v in SAKLANACAK.items():
                    self.assertEqual(kalan.get(k), v, f"{k} silinmemeliydi")

    def test_istenen_adlar_listelerde(self):
        """Projenin ve resmi belgenin açıkça saydığı adlar."""
        for ad in ("AGY_ADC_AUTH", "GOOGLE_GEMINI_BASE_URL"):
            self.assertIn(ad, A.silinen_ortam_degiskenleri("gemini", {ad: "1"}))
        self.assertIn("ANTIGRAVITY_HERHANGI", A.silinen_ortam_degiskenleri("gemini", {"ANTIGRAVITY_HERHANGI": "1"}))
        for ad in ("ANTHROPIC_BASE_URL", "ANTHROPIC_VERTEX_BASE_URL", "ANTHROPIC_BEDROCK_BASE_URL",
                   "AWS_BEARER_TOKEN_BEDROCK", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
                   "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR",
                   "ENABLE_CLAUDEAI_MCP_SERVERS", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_FOUNDRY_API_KEY"):
            self.assertIn(ad, A.silinen_ortam_degiskenleri("claude", {ad: "1"}), ad)
        for ad in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_HOME", "CODEX_ACCESS_TOKEN",
                   "CODEX_OSS_BASE_URL", "OPENAI_PROJECT"):
            self.assertIn(ad, A.silinen_ortam_degiskenleri("codex", {ad: "1"}), ad)

    def test_ag_tasima_ayarlari_silinmez(self):
        for ad in ("claude", "codex", "gemini"):
            self.assertEqual(A.silinen_ortam_degiskenleri(ad, dict(NETWORK)), [], ad)

    def test_claude_oturum_degiskenleri_yalniz_digerlerinden_silinir(self):
        e = {"CLAUDE_CODE_MESSAGING_TOKEN": "t", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "s"}
        self.assertEqual(A.silinen_ortam_degiskenleri("claude", e), [])
        self.assertEqual(A.silinen_ortam_degiskenleri("codex", e), sorted(e))
        self.assertEqual(A.silinen_ortam_degiskenleri("gemini", e), sorted(e))

    def test_adsiz_cagri_eski_davranis(self):
        e = {"ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "k", "GEMINI_API_KEY": "k", "AGY_ADC_AUTH": "1", "PATH": "/x"}
        with mock.patch.dict(os.environ, e, clear=True):
            self.assertEqual(sorted(A.temiz_ortam()), ["AGY_ADC_AUTH", "PATH"])

    def test_eski_api_anahtarlari_her_zaman_silinir(self):
        for ad in (None, "claude", "codex", "gemini"):
            kalan = A.temiz_ortam(ad, {k: "x" for k in A.API_ANAHTARI_DEGISKENLERI})
            self.assertEqual(kalan, {}, ad)

    def test_agy_home_ayari(self):
        with mock.patch.dict(os.environ, {"HOME": "/gercek"}, clear=True):
            self.assertEqual(A.saglayici_ortami("gemini", {"home": "/yalitilmis"})["HOME"], "/yalitilmis")
            self.assertEqual(A.saglayici_ortami("gemini", {})["HOME"], "/gercek")
            self.assertEqual(A.saglayici_ortami("claude", {"home": "/yalitilmis"})["HOME"], "/gercek")


class UctanUcaOrtamTesti(unittest.TestCase):
    """Gerçek `cagir` yolunda alt sürecin gördüğü ortam (sahte CLI ortamını dosyaya döker)."""

    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        self.addCleanup(self.gecici.cleanup)
        self.kok = Path(self.gecici.name)
        self.dok = self.kok / "ortam.jsonl"
        self.calisma = self.kok / "oturum"
        self.calisma.mkdir()
        self.gercek_ev = self.kok / "gercek_ev"
        (self.gercek_ev / "Library" / "Keychains").mkdir(parents=True)

    def calistir(self, ad: str, ek_ortam: dict, s: dict | None = None) -> dict:
        s = {"komut": [sys.executable, SAHTE], "model": "m", **(s or {})}
        ortam = {"SAHTE_ORTAM_DOSYASI": str(self.dok), "SAHTE_AGY_YALITIM": "hicbiri_yazma", **ek_ortam}
        with mock.patch.dict(os.environ, ortam):
            asyncio.run(A.cagir(ad, s, "2+2 kaç?", 30, str(self.calisma)))
        satirlar = [json.loads(x) for x in self.dok.read_text(encoding="utf-8").splitlines()]
        return satirlar[-1]["env"]

    def test_claude_alt_sureci_yonlendirme_degiskenlerini_gormez(self):
        kirli_env = {"ANTHROPIC_BASE_URL": "http://kotu", "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CONFIG_DIR": "/baska",
                     "ENABLE_CLAUDEAI_MCP_SERVERS": "true", "ANTHROPIC_DEFAULT_OPUS_MODEL": "baska", "HTTPS_PROXY": "p"}
        env = self.calistir("claude", kirli_env)
        for k in kirli_env:
            if k != "HTTPS_PROXY":
                self.assertNotIn(k, env, k)
        self.assertEqual(env.get("HTTPS_PROXY"), "p")

    def test_codex_alt_sureci_gormez(self):
        kirli_env = {"OPENAI_BASE_URL": "http://kotu", "CODEX_HOME": "/baska", "CODEX_API_KEY": "k",
                     "CLAUDE_CODE_MESSAGING_TOKEN": "t"}
        env = self.calistir("codex", kirli_env)
        for k in kirli_env:
            self.assertNotIn(k, env, k)

    def test_agy_alt_sureci_gormez_ve_home_yalitilmistir(self):
        home = self.kok / "konsey-agy"
        s = {"home": str(home), "gercek_gemini_dizini": str(self.gercek_ev / ".gemini")}
        with mock.patch.object(A, "gercek_ev_dizini", return_value=self.gercek_ev):
            A.agy_yalitimini_kur(s, str(self.calisma))
            kirli_env = {"AGY_ADC_AUTH": "1", "GOOGLE_GEMINI_BASE_URL": "http://kotu", "ANTIGRAVITY_X": "1",
                         "GOOGLE_APPLICATION_CREDENTIALS": "/k.json", "CLAUDE_CODE_MESSAGING_TOKEN": "t"}
            env = self.calistir("gemini", kirli_env, s)
        for k in kirli_env:
            self.assertNotIn(k, env, k)
        self.assertEqual(env["HOME"], str(home))


if __name__ == "__main__":
    unittest.main()
