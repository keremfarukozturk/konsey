"""agy yalıtımı (karar 44-45): kurulum, doğrulama, kapalı-başarısız çağrı, sürekli yalıtım kontrolü (duman testi),
çalışma alanı katmanı, kimlik dosyası uyarısı. Gerçek ~/.gemini, ~/.konsey-agy ve Keychain'e DOKUNMAZ (hepsi geçici klasör)."""
import asyncio
import contextlib
import io
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
import konsey as K  # noqa: E402

KLASOR = Path(__file__).resolve().parent
SAHTE_AGY = str(KLASOR / "sahte_agy_yalitim_cli.py")
SAHTE = str(KLASOR / "sahte_denetimli_cli.py")


class Temel(unittest.TestCase):
    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        self.addCleanup(self.gecici.cleanup)
        self.kok = Path(self.gecici.name)
        self.gercek_ev = self.kok / "gercek_ev"
        self.keychains = self.gercek_ev / "Library" / "Keychains"
        self.keychains.mkdir(parents=True)
        (self.keychains / "login.keychain-db").write_text("gizli-sahte", encoding="utf-8")
        self.gercek_gemini = self.gercek_ev / ".gemini"
        (self.gercek_gemini / "config").mkdir(parents=True)
        (self.gercek_gemini / "config" / "mcp_config.json").write_text("", encoding="utf-8")
        (self.gercek_gemini / "antigravity-cli").mkdir()
        (self.gercek_gemini / "antigravity-cli" / "settings.json").write_text('{"trustedWorkspaces": []}', encoding="utf-8")
        self.calisma = self.kok / "oturum"
        (self.calisma / ".agents").mkdir(parents=True)
        (self.calisma / ".agents" / "hooks.json").write_text(A.AGY_HOOK_JSON, encoding="utf-8")
        self.home = self.kok / "konsey-agy"
        self.s = {"komut": ["agy"], "model": "gemini-4-neon-high", "home": str(self.home),
                  "gercek_gemini_dizini": str(self.gercek_gemini)}
        p = mock.patch.object(A, "gercek_ev_dizini", return_value=self.gercek_ev)
        p.start()
        self.addCleanup(p.stop)

    def kur(self):
        return A.agy_yalitimini_kur(self.s, str(self.calisma))

    def dogrula(self):
        return A.agy_yalitimini_dogrula(self.s, str(self.calisma))


class KurulumTesti(Temel):
    def test_kurulum_yapisi_ve_izinler(self):
        yapilan = self.kur()
        self.assertTrue(yapilan)
        self.assertEqual(stat.S_IMODE(self.home.stat().st_mode), 0o700)
        ayar = json.loads((self.home / ".gemini/antigravity-cli/settings.json").read_text(encoding="utf-8"))
        self.assertEqual(ayar["toolPermission"], "strict")
        self.assertIs(ayar["useG1Credits"], False)
        self.assertEqual(ayar["trustedWorkspaces"], [str(self.calisma)])
        bag = self.home / "Library" / "Keychains"
        self.assertTrue(bag.is_symlink())
        self.assertEqual(Path(os.readlink(bag)), self.keychains)
        self.assertEqual(self.dogrula(), [])

    def test_eklenti_ve_mcp_listesi_bos_baslar(self):
        self.kur()
        self.assertFalse((self.home / ".gemini" / "config").exists() and any((self.home / ".gemini" / "config").iterdir()))
        self.assertEqual(A.dizin_ozeti(self.home / ".gemini" / "config"), {})

    def test_idempotent_ikinci_calistirma_degistirmez(self):
        self.kur()
        once = A.dizin_ozeti(self.home)
        self.assertEqual(self.kur(), [])
        self.assertEqual(A.ozet_farki(once, A.dizin_ozeti(self.home)), {"yeni": [], "silinen": [], "degisen": []})

    def test_hedefe_ve_gercek_gemini_ye_dokunmaz(self):
        once_k, once_g = A.dizin_ozeti(self.keychains), A.dizin_ozeti(self.gercek_gemini)
        self.kur()
        self.kur()
        self.assertEqual(A.dizin_ozeti(self.keychains), once_k)
        self.assertEqual(A.dizin_ozeti(self.gercek_gemini), once_g)
        self.assertEqual((self.keychains / "login.keychain-db").read_text(encoding="utf-8"), "gizli-sahte")

    def test_agy_nin_normallestirdigi_ayar_kabul_edilir_ve_korunur(self):
        """agy settings.json'u yeniden yazıp useG1Credits=false'u düşürür; kurulum/doğrulama bunu bozuk saymaz."""
        self.kur()
        yol = self.home / ".gemini/antigravity-cli/settings.json"
        yol.write_text(json.dumps({"toolPermission": "strict", "trustedWorkspaces": [str(self.calisma)],
                                   "baskaAnahtar": 7}), encoding="utf-8")
        self.assertEqual(self.dogrula(), [])
        self.assertEqual(self.kur(), [])
        self.assertEqual(json.loads(yol.read_text(encoding="utf-8"))["baskaAnahtar"], 7)

    def test_gevsetilmis_ayar_duzeltilir(self):
        self.kur()
        yol = self.home / ".gemini/antigravity-cli/settings.json"
        yol.write_text(json.dumps({"toolPermission": "always-proceed", "useG1Credits": True, "trustedWorkspaces": []}),
                       encoding="utf-8")
        self.assertEqual(len(self.dogrula()), 3)
        self.kur()
        self.assertEqual(self.dogrula(), [])

    def test_bozuk_settings_uzerine_yazilmaz(self):
        self.kur()
        yol = self.home / ".gemini/antigravity-cli/settings.json"
        yol.write_text("{bozuk", encoding="utf-8")
        with self.assertRaises(A.AyarHatasi):
            self.kur()
        self.assertEqual(yol.read_text(encoding="utf-8"), "{bozuk")

    def test_home_gercek_ev_ile_cakisirsa_reddedilir(self):
        self.s["home"] = str(self.gercek_ev)
        with self.assertRaises(A.AyarHatasi):
            self.kur()
        self.assertTrue(self.dogrula())

    def test_home_gercek_gemini_ye_isaret_ederse_reddedilir(self):
        self.s["gercek_gemini_dizini"] = str(self.home / ".gemini")
        with self.assertRaises(A.AyarHatasi):
            self.kur()

    def test_baska_hedefe_giden_sembolik_bag_reddedilir(self):
        self.kur()
        bag = self.home / "Library" / "Keychains"
        bag.unlink()
        os.symlink(self.kok, bag)
        with self.assertRaises(A.AyarHatasi):
            self.kur()
        self.assertTrue(self.dogrula())


class DogrulamaTesti(Temel):
    def test_kurulmamis_home(self):
        self.assertTrue(self.dogrula())

    def test_izin_gevsekse(self):
        self.kur()
        self.home.chmod(0o755)
        self.assertTrue(any("0o700" in x for x in self.dogrula()))

    def test_sembolik_bag_yoksa(self):
        self.kur()
        (self.home / "Library" / "Keychains").unlink()
        self.assertTrue(any("sembolik bağ" in x for x in self.dogrula()))

    def test_calisma_klasoru_guvenilen_degilse(self):
        self.kur()
        self.assertTrue(any("trustedWorkspaces" in x for x in A.agy_yalitimini_dogrula(self.s, str(self.kok / "baska"))))


class CagriTesti(Temel):
    """`cagir`: yalıtım eksikse agy HİÇ çalıştırılmaz; tamamsa agy HOME yalıtılmış ve izler oraya yazılır."""

    def setUp(self):
        super().setUp()
        self.gozlem = self.kok / "ortam.jsonl"
        self.kayit = self.home / ".gemini/antigravity-cli/conversations"
        self.beyin = self.home / ".gemini/antigravity-cli/brain"
        self.s["komut"] = [sys.executable, SAHTE_AGY]
        eski = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(eski)))
        for k in list(os.environ):
            if k.startswith("SAHTE_"):
                del os.environ[k]
        os.environ.update({"SAHTE_ORTAM_DOSYASI": str(self.gozlem), "SAHTE_KAYIT_DIZINI": str(self.kayit),
                           "SAHTE_BEYIN_DIZINI": str(self.beyin), "SAHTE_GOZLEM": str(self.kok / "g.jsonl"),
                           "SAHTE_GERCEK_GEMINI": str(self.gercek_gemini), "SAHTE_AGY_ARAC": "reddedildi"})

    def cagir(self) -> A.CagriSonucu:
        return asyncio.run(A.cagir("gemini", self.s, "2+2 kaç?", 30, str(self.calisma)))

    def test_yalitim_eksikse_agy_calistirilmaz(self):
        r = self.cagir()
        self.assertEqual(r.durum, "error")
        self.assertTrue(r.hata.startswith(A.AGY_YALITIM_HATASI), r.hata)
        self.assertIn("agy_yalitim_kur.py", r.hata)
        self.assertFalse(self.gozlem.exists(), "agy çalıştırılmamalıydı")

    def test_yalitim_tamamsa_home_yalitilmis_ve_dizinler_home_altinda(self):
        self.kur()
        r = self.cagir()
        self.assertEqual(r.durum, "ok", r.hata)
        env = json.loads(self.gozlem.read_text(encoding="utf-8").splitlines()[-1])["env"]
        self.assertEqual(env["HOME"], str(self.home))
        # model doğrulama ve transcript denetimi varsayılan dizinleri (ayarlanmadı) yalıtılmış HOME altında buldu
        self.assertEqual(r.model_dogrulama, A.DOGRULAMA_SUNUCU, r.dogrulama_notu)
        self.assertEqual(r.arac_denetimi, A.DENETIM_TEMIZ)

    def test_home_ayari_yoksa_eski_davranis(self):
        del self.s["home"]
        self.s["kayit_dizini"], self.s["beyin_dizini"] = str(self.kayit), str(self.beyin)
        r = self.cagir()
        self.assertEqual(r.durum, "ok", r.hata)
        env = json.loads(self.gozlem.read_text(encoding="utf-8").splitlines()[-1])["env"]
        self.assertEqual(env["HOME"], os.environ["HOME"])

    def test_varsayilan_dizinler(self):
        self.assertEqual(A.varsayilan_agy_beyin_dizini(self.s), str(self.beyin))
        self.assertEqual(A.varsayilan_kayit_dizini("gemini", self.s), str(self.kayit))
        self.assertEqual(A.varsayilan_kayit_dizini("codex", self.s), A.VARSAYILAN_KAYIT_DIZINI["codex"])
        self.assertEqual(A.varsayilan_kayit_dizini("gemini", {}), A.VARSAYILAN_KAYIT_DIZINI["gemini"])


class OzetTesti(unittest.TestCase):
    def test_yeni_degisen_silinen(self):
        with tempfile.TemporaryDirectory() as d:
            k = Path(d)
            (k / "config").mkdir()
            (k / "config" / "a.json").write_text("1", encoding="utf-8")
            (k / "baska.txt").write_text("x", encoding="utf-8")
            once = A.dizin_ozeti(k)
            (k / "config" / "a.json").write_text("2", encoding="utf-8")  # aynı boyut, farklı içerik: hash yakalar
            os.utime(k / "config" / "a.json", ns=(once["config/a.json"][0], once["config/a.json"][0]))
            (k / "yeni.txt").write_text("y", encoding="utf-8")
            (k / "baska.txt").unlink()
            fark = A.ozet_farki(once, A.dizin_ozeti(k))
            self.assertEqual(fark, {"yeni": ["yeni.txt"], "silinen": ["baska.txt"], "degisen": ["config/a.json"]})

    def test_klasor_yoksa_bos(self):
        self.assertEqual(A.dizin_ozeti("/yok/boyle/bir/yer"), {})

    def test_sembolik_bag_izlenmez(self):
        with tempfile.TemporaryDirectory() as d:
            hedef, kok = Path(d) / "hedef", Path(d) / "kok"
            hedef.mkdir(); kok.mkdir()
            (hedef / "gizli").write_text("x", encoding="utf-8")
            os.symlink(hedef, kok / "bag")
            self.assertEqual(sorted(A.dizin_ozeti(kok)), ["bag"])

    def test_yalitim_sorunlari(self):
        bos = {"yeni": [], "silinen": [], "degisen": []}
        iyi_iz = {"yeni": [".gemini/antigravity-cli/log/c.log", ".gemini/antigravity-cli/conversations/x.db"],
                  "silinen": [], "degisen": []}
        self.assertEqual(A.agy_yalitim_sorunlari(bos, iyi_iz), [])
        self.assertTrue(A.agy_yalitim_sorunlari({**bos, "yeni": ["antigravity-cli/log/x.log"]}, iyi_iz))
        self.assertTrue(A.agy_yalitim_sorunlari({**bos, "degisen": ["config/config.json"]}, iyi_iz))
        self.assertTrue(A.agy_yalitim_sorunlari({**bos, "silinen": ["a"]}, iyi_iz))
        self.assertTrue(any("log" in x for x in A.agy_yalitim_sorunlari(bos, {**iyi_iz, "yeni": [".gemini/antigravity-cli/brain/b"]})))
        self.assertTrue(any("konuşma" in x for x in A.agy_yalitim_sorunlari(bos, {**iyi_iz, "yeni": [".gemini/antigravity-cli/log/c.log"]})))


class KimlikDosyasiTesti(unittest.TestCase):
    def test_bulur_ve_beklenenleri_atlar(self):
        with tempfile.TemporaryDirectory() as d:
            k = Path(d)
            for yol in (".gemini/antigravity-cli/oauth_creds.json", ".gemini/antigravity-cli/secrets.db",
                        ".gemini/antigravity-cli/settings.json", ".gemini/antigravity-cli/log/cli.log",
                        ".gemini/antigravity-cli/builtin/skills/auth-rehberi/SKILL.md", "Library/Keychains/token-x"):
                (k / yol).parent.mkdir(parents=True, exist_ok=True)
                (k / yol).write_text("x", encoding="utf-8")
            self.assertEqual(A.agy_kimlik_dosyalari(k), [".gemini/antigravity-cli/oauth_creds.json",
                                                         ".gemini/antigravity-cli/secrets.db"])
            self.assertEqual(A.agy_kimlik_dosyalari(k / "yok"), [])


class CalismaAlaniTesti(unittest.TestCase):
    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        self.addCleanup(self.gecici.cleanup)
        self.cal = Path(self.gecici.name) / "oturum"
        (self.cal / ".agents").mkdir(parents=True)
        (self.cal / ".agents" / "hooks.json").write_text(A.AGY_HOOK_JSON, encoding="utf-8")

    def test_temiz(self):
        self.assertEqual(A.calisma_alani_sorunlari(self.cal), [])

    def test_fazla_dosyalar(self):
        (self.cal / "AGENTS.md").write_text("kural", encoding="utf-8")
        self.assertTrue(any("beklenmeyen öğeler: AGENTS.md" in x for x in A.calisma_alani_sorunlari(self.cal)))
        (self.cal / ".agents" / "plugins.json").write_text("{}", encoding="utf-8")
        self.assertTrue(any("hooks.json dışında" in x for x in A.calisma_alani_sorunlari(self.cal)))

    def test_hooks_degismisse(self):
        (self.cal / ".agents" / "hooks.json").write_text("{}", encoding="utf-8")
        self.assertTrue(any("farklı" in x for x in A.calisma_alani_sorunlari(self.cal)))

    def test_hooks_yoksa(self):
        (self.cal / ".agents" / "hooks.json").unlink()
        self.assertTrue(any("hooks.json yok" in x for x in A.calisma_alani_sorunlari(self.cal)))

    def test_git_koku(self):
        (self.cal / ".git").mkdir()
        sorunlar = A.calisma_alani_sorunlari(self.cal)
        self.assertTrue(any(".git var" in x for x in sorunlar) and any("beklenmeyen" in x for x in sorunlar))

    def test_ust_klasorde_git_koku(self):
        (self.cal.parent / ".git").mkdir()
        self.assertTrue(any(".git var" in x for x in A.calisma_alani_sorunlari(self.cal)))

    def test_klasor_yoksa(self):
        self.assertTrue(A.calisma_alani_sorunlari(self.cal / "yok"))


class DumanYalitimTesti(Temel):
    """Duman testinin sürekli yalıtım kontrolü (karar 45), sahte `agy` sarmalayıcısıyla uçtan uca."""

    def setUp(self):
        super().setUp()
        self.agy = self.kok / "bin" / "agy"
        self.agy.parent.mkdir()
        self.agy.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{SAHTE_AGY}" "$@"\n', encoding="utf-8")
        self.agy.chmod(self.agy.stat().st_mode | stat.S_IXUSR)
        self.kayitlar = self.home / ".gemini/antigravity-cli/conversations"
        self.beyin = self.home / ".gemini/antigravity-cli/brain"
        self.s["komut"] = [str(self.agy)]
        self.s["kayit_dizini"] = str(self.kayitlar)  # sahte codex de buraya yazar
        self.ayar = {
            "calisma_klasoru": str(self.calisma), "kayit_klasoru": str(self.kok / "kayitlar"), "cagri_zaman_asimi_sn": 30,
            "saglayicilar": {
                "claude": {"komut": [sys.executable, SAHTE, "claude"], "model": "opus"},
                "codex": {"komut": [sys.executable, SAHTE, "codex"], "model": "gpt-6.2-astra",
                          "kayit_dizini": str(self.kok / "codex_kayitlari")},
                "gemini": self.s,
            },
        }
        eski = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(eski)))
        for k in list(os.environ):
            if k.startswith("SAHTE_"):
                del os.environ[k]
        os.environ.update({"SAHTE_KAYIT_DIZINI": str(self.kok / "codex_kayitlari"), "SAHTE_BEYIN_DIZINI": str(self.beyin),
                           "SAHTE_GOZLEM": str(self.kok / "g.jsonl"), "SAHTE_GERCEK_GEMINI": str(self.gercek_gemini),
                           "SAHTE_AGY_ARAC": "reddedildi"})
        # agy konuşma kayıtları (sahte_kayitli) yalıtılmış HOME altına, codex'inki dışına yazılsın: aynı değişken ikisini
        # de kontrol eder, bu yüzden agy kaydı için ayrı kök kullanılamaz; model doğrulama yine de 'doğrulanamadı' olabilir.
        self.kur()

    def duman(self) -> tuple[int, str]:
        cikti = io.StringIO()
        with contextlib.redirect_stdout(cikti):
            kod = asyncio.run(K.duman_testi(self.ayar, 30))
        return kod, cikti.getvalue()

    def test_iyi_yalitim_basarili(self):
        kod, metin = self.duman()
        self.assertEqual(kod, 0, metin)
        self.assertIn("✓ agy yalıtım kontrolü", metin)
        self.assertIn("✓ agy mcp list: boş", metin)
        self.assertNotIn("UYARI", metin)

    def test_gercek_gemini_ye_yazilirsa_basarisiz(self):
        os.environ["SAHTE_AGY_YALITIM"] = "gercek_yaz"
        kod, metin = self.duman()
        self.assertEqual(kod, 1, metin)
        self.assertIn("agy yalıtım kontrolü BAŞARISIZ", metin)
        self.assertIn("gerçek ~/.gemini'de yeni dosya", metin)

    def test_gercek_gemini_degisirse_basarisiz_kullanici_degisikligi_de_yakalanir(self):
        """Duman sırasında gerçek ~/.gemini'de bir yapılandırma dosyası değişirse (hash) yakalanır."""
        yol = self.gercek_gemini / "config" / "mcp_config.json"
        orijinal = A.agy_yuzeyini_yokla

        async def yoklarken_degistir(*a, **k):
            yol.write_text('{"mcpServers": {"x": {}}}', encoding="utf-8")
            return await orijinal(*a, **k)

        with mock.patch.object(A, "agy_yuzeyini_yokla", yoklarken_degistir):
            kod, metin = self.duman()
        self.assertEqual(kod, 1, metin)
        self.assertIn("gerçek ~/.gemini'de değişen dosya: config/mcp_config.json", metin)

    def test_log_olusmazsa_basarisiz(self):
        os.environ["SAHTE_AGY_YALITIM"] = "log_yok"
        kod, metin = self.duman()
        self.assertEqual(kod, 1, metin)
        self.assertIn("yeni agy log dosyası oluşmadı", metin)

    def test_kimlik_dosyasi_uyari_verir_ama_basarisizlik_degil(self):
        os.environ["SAHTE_AGY_YALITIM"] = "kimlik"
        kod, metin = self.duman()
        self.assertEqual(kod, 0, metin)
        self.assertIn("UYARI", metin)
        self.assertIn("oauth_token.json", metin)

    def test_calisma_alani_kirliyse_basarisiz(self):
        (self.calisma / "GEMINI.md").write_text("kural", encoding="utf-8")
        kod, metin = self.duman()
        self.assertEqual(kod, 1, metin)
        self.assertIn("çalışma alanı: çalışma klasöründe beklenmeyen öğeler: GEMINI.md", metin)

    def test_home_yoksa_atlanir(self):
        del self.s["home"]
        kod, metin = self.duman()
        self.assertIn("agy yalıtım kontrolü: atlandı", metin)

    def test_ortam_temizligi_duman_ciktisinda_gorunur(self):
        os.environ["AGY_ADC_AUTH"] = "1"
        os.environ["ANTHROPIC_BASE_URL"] = "http://kotu"
        kod, metin = self.duman()
        self.assertIn("Ortam temizliği (Gemini)", metin)
        self.assertIn("AGY_ADC_AUTH", metin)
        self.assertIn("ANTHROPIC_BASE_URL", metin.split("Ortam temizliği (Claude)")[1] if "Ortam temizliği (Claude)" in metin else "")
        self.assertNotIn("http://kotu", metin, "değerler yazılmamalı")


class GercekAyarTesti(unittest.TestCase):
    def test_modeller_json_gemini_home(self):
        ayar = A.ayarlari_yukle(KLASOR.parent / "modeller.json")
        s = ayar["saglayicilar"]["gemini"]
        self.assertEqual(s["home"], str(Path("~/.konsey-agy").expanduser()))

    def test_komut_claude_strict_mcp(self):
        k = A.komut_olustur("claude", {"komut": ["claude"], "model": "opus"}, "soru", 60)
        self.assertIn("--strict-mcp-config", k)
        self.assertNotIn("--mcp-config", k)


if __name__ == "__main__":
    unittest.main()
