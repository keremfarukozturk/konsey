"""
Konsey testleri: gerçek CLI'lar yerine sahte_cli.py kullanılır; gerçek kotaya dokunulmaz.
PROJE.md 7.6'daki altı kabul ölçütünü sınar.

Çalıştırma (konsey klasöründe):  python -m unittest discover -s testler -v
"""
import asyncio
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import adaptor as A  # noqa: E402
import konsey as K  # noqa: E402

SAHTE = str(Path(__file__).resolve().parent / "sahte_cli.py")


def surec_canli(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # Linux: zombi süreç ölü sayılır
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


class KonseyTesti(unittest.TestCase):
    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        kok = Path(self.gecici.name)
        self.ayar = {
            "calisma_klasoru": str(kok / "oturum"),
            "kayit_klasoru": str(kok / "kayitlar"),
            "cagri_zaman_asimi_sn": 30,
            "saglayicilar": {
                "claude": {"komut": [sys.executable, SAHTE, "claude"], "model": "opus"},
                "codex": {"komut": [sys.executable, SAHTE, "codex"], "model": "gpt-6.2-astra"},
                "gemini": {"komut": [sys.executable, SAHTE, "gemini"], "model": "gemini-4-argon-medium"},
            },
        }
        self.eski_ortam = dict(os.environ)
        for k in list(os.environ):
            if k.startswith("SAHTE_"):
                del os.environ[k]

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.eski_ortam)
        self.gecici.cleanup()

    def konsey(self, **kw):
        return K.Konsey(self.ayar, tohum=42, **kw)

    def calistir(self, **kw):
        return asyncio.run(self.konsey(**kw).calistir("Test sorusu?"))

    # --- normal akış
    def test_oybirligi(self):
        s = self.calistir()
        self.assertEqual(s["durum"], "OYBIRLIGI")
        self.assertIsNotNone(s["onaylanan_metin"])
        self.assertEqual(s["cagri_sayisi"], 10)  # 3 bağımsız + 3 değerlendirme + 1 sentez + 3 onay
        self.assertTrue((Path(s["kayit_klasoru"]) / "rapor.md").exists())
        self.assertIn("doğrulanmamış ortak kanaat", s["rapor"])

    # --- Ölçüt 1: giriş abonelikle değilse çalışma durur
    def test_api_anahtariyla_giris_reddedilir(self):
        os.environ["SAHTE_CLAUDE_AUTH"] = "api_key"
        k = self.konsey()
        with self.assertRaises(A.AyarHatasi):
            asyncio.run(k.calistir("Test?"))
        self.assertEqual(k.cagri_sayisi, 0)

    def test_api_anahtari_alt_surece_aktarilmaz(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        os.environ["SAHTE_CLAUDE"] = "env_kontrol"
        s = self.calistir()
        self.assertEqual(s["tur0"]["claude"]["metin"], "ANAHTAR_YOK")

    # --- Ölçüt 2: yanlış model yakalanır
    def test_bilinmeyen_model(self):
        os.environ["SAHTE_GEMINI"] = "bilinmeyen_model"
        s = self.calistir()
        self.assertEqual(s["durum"], "IKIDE_IKI_BIR_EKSIK")
        self.assertIn("gemini", s["eksik_katilim"]["tur0"])
        self.assertIn("model adı", s["eksik_katilim"]["tur0"]["gemini"])

    def test_gemini_koltuguna_baska_model_yazilamaz(self):
        yol = Path(self.gecici.name) / "ayar.json"
        yol.write_text('{"calisma_klasoru": "x", "kayit_klasoru": "y", "saglayicilar": '
                       '{"gemini": {"komut": "agy", "model": "claude-opus-5-5-high"}}}', encoding="utf-8")
        with self.assertRaises(A.AyarHatasi):
            A.ayarlari_yukle(yol)

    # --- Ölçüt 3: kota hatası oy sayılmaz, eksik katılım her turda gösterilir
    def test_kota_oy_sayilmaz(self):
        os.environ["SAHTE_CODEX"] = "kota"
        s = self.calistir()
        self.assertEqual(s["durum"], "IKIDE_IKI_BIR_EKSIK")
        self.assertEqual(s["tur0"]["codex"]["durum"], "rate_limited")
        self.assertNotIn("codex", s["onay"]["pusulalar"])

    def test_onay_turunda_kota_eksik_sayilir(self):
        os.environ["SAHTE_GEMINI"] = "kota_onay"
        s = self.calistir()
        # İki kabul + bir kota hatası: "üçte iki çoğunluk" değil, "ikide iki, bir eksik"
        self.assertEqual(s["durum"], "IKIDE_IKI_BIR_EKSIK")
        self.assertIn("gemini", s["eksik_katilim"]["onay"])

    def test_tek_model_kalirsa_yetersiz_katilim(self):
        os.environ["SAHTE_CODEX"] = "kota"
        os.environ["SAHTE_GEMINI"] = "kota"
        s = self.calistir()
        self.assertEqual(s["durum"], "YETERSIZ_KATILIM")
        self.assertIsNone(s["onaylanan_metin"])

    def test_giris_hatasi_siniflandirilir(self):
        os.environ["SAHTE_CLAUDE"] = "giris"
        s = self.calistir()
        self.assertEqual(s["tur0"]["claude"]["durum"], "auth_error")

    # --- Ölçüt 4: zaman aşımında süreç grubu kapanır
    def test_zaman_asiminda_surec_grubu_kapanir(self):
        pid_dosyasi = Path(self.gecici.name) / "cocuk.pid"
        os.environ["SAHTE_CODEX"] = "zamanasimi"
        os.environ["SAHTE_PID_DOSYASI"] = str(pid_dosyasi)
        Path(self.ayar["calisma_klasoru"]).mkdir(parents=True, exist_ok=True)
        s = asyncio.run(A.cagir("codex", self.ayar["saglayicilar"]["codex"], "test", 2,
                                self.ayar["calisma_klasoru"]))
        self.assertEqual(s.durum, "timeout")
        cocuk = int(pid_dosyasi.read_text())
        for _ in range(50):
            if not surec_canli(cocuk):
                break
            time.sleep(0.1)
        self.assertFalse(surec_canli(cocuk), "Alt süreç zaman aşımından sonra hâlâ çalışıyor")

    # --- Ölçüt 5: bozuk JSON programı çökertmez, çekimser sayılır
    def test_bozuk_pusula_cekimser(self):
        os.environ["SAHTE_CLAUDE"] = "bozuk_pusula"
        s = self.calistir()
        p = s["onay"]["pusulalar"]["claude"]
        self.assertEqual(p["oy"], "CEKIMSER")
        self.assertFalse(p["gecerli"])
        self.assertEqual(s["durum"], "COGUNLUK")

    def test_bozuk_cikti_hata_olur_cevap_olmaz(self):
        os.environ["SAHTE_CLAUDE"] = "bozuk_cikti"
        s = self.calistir()
        self.assertEqual(s["tur0"]["claude"]["durum"], "error")
        self.assertEqual(s["tur0"]["claude"]["metin"], "")

    # --- Ölçüt 6: onaylar metin sürümüne bağlı; yalnızca onaylanan metin gösterilir
    def test_yanlis_surume_oy_gecersiz(self):
        os.environ["SAHTE_GEMINI"] = "yanlis_surum"
        s = self.calistir()
        self.assertEqual(s["onay"]["pusulalar"]["gemini"]["oy"], "CEKIMSER")
        self.assertEqual(s["durum"], "COGUNLUK")

    def test_iki_ret_uzlasi_yok_taslak_onaysiz_etiketle_gosterilir(self):
        # v0.21 (karar 50, kural 7.2 değişti): taslak ana raporda gösterilir, ama açık "ONAYLANMADI" etiketiyle;
        # onaylanan_metin yine boştur (taslak onaylı cevap sayılmaz).
        os.environ["SAHTE_CLAUDE"] = "ret"
        os.environ["SAHTE_CODEX"] = "ret"
        s = self.calistir()
        self.assertEqual(s["durum"], "UZLASI_YOK")
        self.assertIsNone(s["onaylanan_metin"])
        self.assertIn("ONAYLANMADI — konsey bu metinde uzlaşamadı.", s["ozet_rapor"])
        self.assertIn("RET itirazı (Claude): önemli hata", s["ozet_rapor"])
        self.assertIn(s["taslak_metin"], s["ozet_rapor"])

    # --- yardımcılar
    def test_codex_akil_yurutmesi_cevaba_karismaz(self):
        s = self.calistir()
        self.assertNotIn("GİZLİ AKIL YÜRÜTME", s["tur0"]["codex"]["metin"])

    def test_son_json_nesnesi(self):
        self.assertEqual(K.son_json_nesnesi('önce {x} sonra {"oy": "KABUL", "a": {"b": 1}} son'),
                         {"oy": "KABUL", "a": {"b": 1}})
        self.assertEqual(K.son_json_nesnesi('{"tercih": "A"} ve {"baska": 1}', "tercih"), {"tercih": "A"})
        self.assertIsNone(K.son_json_nesnesi("JSON yok"))

    def test_oy_sayimi(self):
        self.assertEqual(K.sonucu_belirle({"a": "KABUL", "b": "KABUL", "c": "KABUL"}), "OYBIRLIGI")
        self.assertEqual(K.sonucu_belirle({"a": "KABUL", "b": "KABUL", "c": "RET"}), "COGUNLUK")
        self.assertEqual(K.sonucu_belirle({"a": "KABUL", "b": "RET", "c": "CEKIMSER"}), "UZLASI_YOK")
        self.assertEqual(K.sonucu_belirle({"a": "KABUL", "b": "KABUL"}), "IKIDE_IKI_BIR_EKSIK")
        self.assertEqual(K.sonucu_belirle({"a": "KABUL", "b": "RET"}), "UZLASI_YOK")
        self.assertEqual(K.sonucu_belirle({"a": "KABUL"}), "YETERSIZ_KATILIM")

    def test_calisma_klasoru_proje_icinde_olamaz(self):
        self.ayar["calisma_klasoru"] = str(KOK / "oturum")
        with self.assertRaises(A.AyarHatasi):
            asyncio.run(self.konsey().calistir("Test?"))


if __name__ == "__main__":
    unittest.main()
