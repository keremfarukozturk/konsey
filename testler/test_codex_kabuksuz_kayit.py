"""Kabuk kapatıldıktan sonra alınmış, araç olayı içermeyen gerçek Codex kaydı (karar 41).

Örnek: testler/ornekler/codex_kabuksuz/ — 19 Kasım 2026, v0.15 komutuyla (features.shell_tool=false, apps=false,
--ignore-user-config) yapılmış gerçek bir konsey Tur 0 çağrısı (kayitlar/2026-11-19_231121_*/tur0_codex.json).
Hesap kimlikleri ve ev dizini yer tutucuyla değiştirildi, uzun talimat metinleri kısaltıldı; gizli bilgi taraması
(e-posta, JWT, API anahtarı, GitHub token, kullanıcı adı, hesap kimliği) 0 eşleşme verdi."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import adaptor as A  # noqa: E402

ORNEK = Path(__file__).resolve().parent / "ornekler" / "codex_kabuksuz"


class KabuksuzKayitTesti(unittest.TestCase):
    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        self.addCleanup(self.gecici.cleanup)
        self.akis = (ORNEK / "tur0_akis.jsonl").read_text(encoding="utf-8")
        self.kimlik = json.loads(self.akis.splitlines()[0])["thread_id"]
        d = Path(self.gecici.name) / "2026" / "11" / "19"
        d.mkdir(parents=True)
        (d / f"rollout-2026-11-19T00-00-00-{self.kimlik}.jsonl").write_text(
            (ORNEK / "tur0_oturum.jsonl").read_text(encoding="utf-8"), encoding="utf-8")

    def denetle(self) -> A.CagriSonucu:
        s = A.ciktiyi_coz("codex", 0, self.akis, "")
        s.oturum_kimligi = self.kimlik
        self.assertTrue(s.basarili, s.hata)
        A.codex_araclarini_denetle({"kayit_dizini": self.gecici.name}, s, self.akis)
        return s

    def test_temiz_kayit_gecer(self):
        s = self.denetle()
        self.assertEqual((s.durum, s.arac_denetimi), ("ok", A.DENETIM_GORULDU), s.hata)
        self.assertTrue(s.metin.startswith("CEVAP:"))
        o = s.arac_ozeti
        self.assertEqual((o["arac_cagrisi"], o["komutlar"], o["web_aramalari"], o["bilinmeyen_olaylar"]),
                         ([], [], [], {}))
        self.assertNotIn("akis_arac_olaylari", o)
        self.assertEqual(A.arac_ozeti_metni(s), "araç kullanmadı")

    def test_kayit_kabuk_kapaliyken_alinmis(self):
        """Örneğin kanıt değeri: kayıtlı komut kabuğu, bağlayıcıları ve kullanıcı config'ini kapatıyordu."""
        komut = json.loads((ORNEK / "tur0_komut.json").read_text(encoding="utf-8"))
        for ayar in ("features.shell_tool=false", "features.apps=false", "features.plugins=false",
                     'web_search="disabled"'):
            self.assertIn(ayar, komut)
        self.assertIn("--ignore-user-config", komut)
        # Araç listesi: yalnızca yerleşik üç ad alanı, hesap bağlayıcısı (mcp__codex_apps) yok
        for satir in (ORNEK / "tur0_oturum.jsonl").read_text(encoding="utf-8").splitlines():
            yuk = json.loads(satir).get("payload")
            if isinstance(yuk, dict) and yuk.get("type") == "additional_tools":
                self.assertEqual(sorted(t["name"] for t in yuk["tools"]), ["clock", "collaboration", "functions"])
                break
        else:
            self.fail("additional_tools kaydı yok")

    def test_ayni_kayit_bayrak_kapaliyken_de_temiz(self):
        with mock.patch.object(A, "CODEX_BILINEN_ARAC_HATA", False):
            s = self.denetle()
        self.assertEqual(s.durum, "ok", s.hata)

    def test_kayda_komut_eklenirse_hata(self):
        """Aynı gerçek kayda tek bir komut olayı eklenince çağrı hata verir (testin duyarlılığı)."""
        yol = next(Path(self.gecici.name).rglob("rollout-*.jsonl"))
        yol.write_text(yol.read_text(encoding="utf-8") + json.dumps(
            {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
                                                  "arguments": "{\"cmd\":\"date\"}"}}) + "\n", encoding="utf-8")
        s = self.denetle()
        self.assertEqual((s.durum, s.arac_denetimi), ("error", A.DENETIM_IHLAL))
        self.assertTrue(s.hata.startswith(A.CODEX_ARAC_KULLANIMI), s.hata)


if __name__ == "__main__":
    unittest.main()
