"""
Codex web erişimi: engelleme ayarı ve tespit testleri (PROJE.md karar 36, belgeler/guvenlik.md bölüm 9).

Test verisi gerçek Codex 0.169.0 çıktılarından ayıklandı (testler/ornekler/codex_web/):
- web_aramali_*: web araması AÇIKKEN example.com'u açtıran çağrı (--json akışı ve oturum kaydı).
- temiz_*: web araması kapalıyken aynı istek (cevap ERISIM_YOK, web arama olayı yok).
Örnekler tek bir çağrıya dayanır; kullanıcı yolları temizlendi, gizli bilgi yoktur.

Çalıştırma (konsey klasöründe):  python -m unittest discover -s testler -v
"""
import asyncio
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import adaptor as A  # noqa: E402
import konsey as K  # noqa: E402

ORNEK = Path(__file__).resolve().parent / "ornekler" / "codex_web"


def kimlik_al(akis: str) -> str:
    return json.loads(akis.splitlines()[0])["thread_id"]


class CodexWebTesti(unittest.TestCase):
    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        self.kok = Path(self.gecici.name)
        self.kayit = self.kok / "codex_kayitlari"
        self.calisma = self.kok / "oturum"
        self.calisma.mkdir()

    def tearDown(self):
        self.gecici.cleanup()

    def oturum_yaz(self, ad: str, kimlik: str) -> None:
        d = self.kayit / "2026" / "11" / "19"
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy(ORNEK / f"{ad}_oturum.jsonl", d / f"rollout-2026-11-19T00-00-00-{kimlik}.jsonl")

    def sonuc(self, ad: str) -> A.CagriSonucu:
        akis = (ORNEK / f"{ad}_akis.jsonl").read_text(encoding="utf-8")
        s = A.ciktiyi_coz("codex", 0, akis, "")
        s.oturum_kimligi = kimlik_al(akis)
        self.assertTrue(s.basarili, "örnek akış başarılı çağrı gibi çözülmeli (hata denetimden gelmeli)")
        return s

    def ayar(self) -> dict:
        return {"komut": ["codex"], "model": "gpt-6.2-astra", "kayit_dizini": str(self.kayit)}

    # ---- engelleme: komut satırı

    def test_komut_web_aramasini_kapatir_ve_katı_config_ister(self):
        k = A.komut_olustur("codex", {"komut": ["codex"], "model": "gpt-6.2-astra"}, "soru", 60)
        self.assertIn("--strict-config", k)
        i = k.index("-c")
        self.assertEqual(k[i + 1], 'web_search="disabled"')
        self.assertLess(k.index("--strict-config"), len(k) - 1)
        self.assertEqual(k[-1], "soru", "prompt son argüman kalmalı")
        self.assertIn("read-only", k)

    # ---- tespit: web_search_call içeren örnek hata verir

    def test_web_aramali_oturum_ve_akis_hata_verir(self):
        s = self.sonuc("web_aramali")
        self.assertEqual(s.metin, "Example Domain")
        self.oturum_yaz("web_aramali", s.oturum_kimligi)
        A.codex_araclarini_denetle(self.ayar(), s, (ORNEK / "web_aramali_akis.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(s.durum, "error")
        self.assertEqual(s.metin, "", "web erişimli çağrının cevabı kullanılmamalı")
        self.assertTrue(s.hata.startswith(A.CODEX_WEB_ERISIMI), s.hata)
        self.assertEqual(s.arac_denetimi, A.DENETIM_IHLAL)
        self.assertGreaterEqual(len(s.arac_ozeti["web_aramalari"]), 1)
        self.assertIn("web erişimi tespit edildi", A.arac_ozeti_metni(s))

    def test_kayit_okunamasa_da_akistaki_web_olayi_yeter(self):
        s = self.sonuc("web_aramali")  # oturum kaydı yazılmadı
        A.codex_araclarini_denetle(self.ayar(), s, (ORNEK / "web_aramali_akis.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(s.durum, "error")
        self.assertTrue(s.hata.startswith(A.CODEX_WEB_ERISIMI))

    def test_yalniz_oturum_kaydindaki_web_olayi_yeter(self):
        s = self.sonuc("web_aramali")
        self.oturum_yaz("web_aramali", s.oturum_kimligi)
        A.codex_araclarini_denetle(self.ayar(), s, "")  # akış verilmedi
        self.assertEqual(s.durum, "error")
        self.assertTrue(s.hata.startswith(A.CODEX_WEB_ERISIMI))

    # ---- tespit: `curl` içeren eski kayıt (kabuk kapatılmadan önce alınmış) artık hata verir

    def test_curl_iceren_eski_kayit_hata_verir(self):
        s = self.sonuc("temiz")
        self.oturum_yaz("temiz", s.oturum_kimligi)
        A.codex_araclarini_denetle(self.ayar(), s, (ORNEK / "temiz_akis.jsonl").read_text(encoding="utf-8"))
        # v0.16: bu gerçek kayıt kabuk kapatılmadan önce alındı ve bir `curl` komutu içeriyor; komut artık hata
        self.assertEqual(s.durum, "error")
        self.assertEqual(s.metin, "")
        self.assertEqual(s.arac_denetimi, A.DENETIM_IHLAL)
        self.assertEqual(s.arac_ozeti["web_aramalari"], [])
        self.assertNotIn("web erişimi", A.arac_ozeti_metni(s))

    # ---- rapor

    def test_rapor_web_erisimini_yazar(self):
        s = self.sonuc("web_aramali")
        A.codex_araclarini_denetle(self.ayar(), s, (ORNEK / "web_aramali_akis.jsonl").read_text(encoding="utf-8"))
        t = K.arac_toplami([s])
        self.assertEqual(t["codex_web_aramasi"], 1)
        self.assertIn("Codex web erişimi tespit edildi", K.arac_toplami_metni("codex", t))
        t0 = K.arac_toplami([self.sonuc("temiz")])
        self.assertEqual(t0["codex_web_aramasi"], 0)
        self.assertNotIn("tespit edildi", K.arac_toplami_metni("codex", t0))

    # ---- uçtan uca: sahte codex programı gerçek akışı basar

    def uctan_uca(self, ad: str) -> A.CagriSonucu:
        akis = ORNEK / f"{ad}_akis.jsonl"
        betik = self.kok / "sahte_codex.py"
        betik.write_text(f"import sys\nsys.stdout.write(open({str(akis)!r}, encoding='utf-8').read())\n",
                         encoding="utf-8")
        kimlik = kimlik_al(akis.read_text(encoding="utf-8"))
        self.oturum_yaz(ad, kimlik)
        s = {"komut": [sys.executable, str(betik)], "model": "gpt-6.2-astra", "kayit_dizini": str(self.kayit)}
        return asyncio.run(A.cagir("codex", s, "soru", 30, str(self.calisma)))

    def test_cagir_web_aramali_cevabi_hata_sayar(self):
        r = self.uctan_uca("web_aramali")
        self.assertEqual(r.durum, "error")
        self.assertEqual(r.metin, "")
        self.assertTrue(r.hata.startswith(A.CODEX_WEB_ERISIMI))

    def test_cagir_curl_iceren_eski_kayit_hata_verir(self):
        r = self.uctan_uca("temiz")
        self.assertEqual(r.durum, "error")  # v0.16: kayıttaki `curl` komutu artık hata
        self.assertEqual(r.metin, "")


if __name__ == "__main__":
    unittest.main()
