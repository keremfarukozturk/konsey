"""
Codex denetimi: izin listesi testleri (PROJE.md karar 37, belgeler/guvenlik.md 9.2).

Kural: Listede olmayan HER olay türü, adı bilinmese de, araç kullanımı sayılır ve çağrı hata verir;
raporda olay türünün adı görünür. Bilinen araç olayları (komut, exec) karar 27'deki gibi sayılıp raporlanır.

Test verisi: testler/ornekler/codex_izin/ gerçek pilot çağrısından (P02, 4 Codex çağrısı) ayıklandı; uzun
metinler kısaltıldı, kullanıcı yolları temizlendi. Yerel kayitlar/ klasörü varsa (depoda yok) hepsi de taranır.

Çalıştırma (konsey klasöründe):  python -m unittest discover -s testler -v
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import adaptor as A  # noqa: E402
import konsey as K  # noqa: E402

ORNEK = Path(__file__).resolve().parent / "ornekler" / "codex_izin"
PILOT = ["tur0", "tur1", "sentez", "onay"]


def oku(ad: str) -> str:
    return (ORNEK / ad).read_text(encoding="utf-8")


def kimlik_al(akis: str) -> str:
    return json.loads(akis.splitlines()[0])["thread_id"]


class IzinListesiTesti(unittest.TestCase):
    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        self.kayit = Path(self.gecici.name) / "codex_kayitlari"

    def tearDown(self):
        self.gecici.cleanup()

    def ayar(self) -> dict:
        return {"komut": ["codex"], "model": "gpt-6.2-astra", "kayit_dizini": str(self.kayit)}

    def hazirla(self, akis: str, oturum: str) -> A.CagriSonucu:
        """Akış ve oturum kaydı metninden, adaptörün ayrıştırdığı başarılı bir sonuç kurar."""
        s = A.ciktiyi_coz("codex", 0, akis, "")
        s.oturum_kimligi = kimlik_al(akis)
        self.assertTrue(s.basarili, s.hata)
        d = self.kayit / "2026" / "11" / "19"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"rollout-2026-11-19T00-00-00-{s.oturum_kimligi}.jsonl").write_text(oturum, encoding="utf-8")
        return s

    def denetle(self, s: A.CagriSonucu, akis: str) -> A.CagriSonucu:
        A.codex_araclarini_denetle(self.ayar(), s, akis)
        return s

    def pilot(self, tur: str) -> tuple[str, str]:
        return oku(f"pilot_P02_{tur}_codex_akis.jsonl"), oku(f"pilot_P02_{tur}_codex_oturum.jsonl")

    # ---- gerçek pilot kayıtları geçer

    def test_gercek_pilot_kayitlari_gecer(self):
        for tur in PILOT:
            with self.subTest(tur=tur):
                akis, oturum = self.pilot(tur)
                s = self.denetle(self.hazirla(akis, oturum), akis)
                self.assertEqual(s.durum, "ok", s.hata)
                self.assertEqual(s.arac_denetimi, A.DENETIM_GORULDU)
                self.assertEqual(s.arac_ozeti["bilinmeyen_olaylar"], {})
                self.assertEqual(s.arac_ozeti["web_aramalari"], [])
                self.assertEqual((s.arac_ozeti["arac_cagrisi"], s.arac_ozeti["komutlar"]), ([], []))
                self.assertEqual(A.arac_ozeti_metni(s), "araç kullanmadı")

    def test_yerel_kayitlar_klasorundeki_tum_codex_cagrilari_gecer(self):
        kayitlar = KOK / "kayitlar"
        dosyalar = sorted(kayitlar.glob("*/*codex*.json")) if kayitlar.is_dir() else []
        if not dosyalar:
            self.skipTest("kayitlar/ yok (depoda tutulmuyor)")
        taranan = 0
        for f in dosyalar:
            d = json.loads(f.read_text(encoding="utf-8"))
            kimlik = (d.get("sonuc") or {}).get("oturum_kimligi")
            kayit = next(iter(Path("~/.codex/sessions").expanduser().glob(f"*/*/*/rollout-*-{kimlik}.jsonl")), None) \
                if kimlik else None
            if kayit is None:
                continue
            s = A.ciktiyi_coz("codex", 0, d["stdout"], "")
            if not s.basarili:
                continue
            s.oturum_kimligi = kimlik
            with self.subTest(dosya=f.parent.name + "/" + f.name):
                shutil.rmtree(self.kayit, ignore_errors=True)
                self.hazirla(d["stdout"], kayit.read_text(encoding="utf-8", errors="replace"))
                self.denetle(s, d["stdout"])
                self.assertEqual(s.durum, "ok", s.hata)
                taranan += 1
        self.assertGreater(taranan, 0)

    # ---- bilinmeyen olay türü → hata

    def test_oturum_kaydinda_bilinmeyen_tur_hata_verir_ve_adi_gorunur(self):
        akis, oturum = self.pilot("tur0")
        oturum += json.dumps({"type": "response_item", "payload": {"type": "yeni_arac_xyz", "name": "x"}}) + "\n"
        s = self.denetle(self.hazirla(akis, oturum), akis)
        self.assertEqual(s.durum, "error")
        self.assertEqual(s.metin, "", "cevap kullanılmamalı")
        self.assertTrue(s.hata.startswith(A.CODEX_BILINMEYEN_OLAY), s.hata)
        self.assertIn("response_item/yeni_arac_xyz", s.hata)
        self.assertEqual(s.arac_denetimi, A.DENETIM_IHLAL)
        self.assertIn("response_item/yeni_arac_xyz", A.arac_ozeti_metni(s))

    def test_bilinmeyen_ust_tur_ve_event_msg_ve_oge_turu(self):
        akis, oturum = self.pilot("tur0")
        for olay, beklenen in [
            ({"type": "garip_ust_tur"}, "garip_ust_tur"),
            ({"type": "event_msg", "payload": {"type": "mcp_tool_call_begin"}}, "event_msg/mcp_tool_call_begin"),
            ({"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "Plan"}}},
             "event_msg/item_completed:Plan"),
            ({"type": "response_item", "payload": {"type": "message", "role": "tool"}},
             "response_item/message:tool"),
            ({"payload": {"type": "tursuz"}}, "None/tursuz"),
        ]:
            with self.subTest(beklenen=beklenen):
                shutil.rmtree(self.kayit, ignore_errors=True)
                s = self.denetle(self.hazirla(akis, oturum + json.dumps(olay) + "\n"), akis)
                self.assertEqual(s.durum, "error", s.hata)
                self.assertIn(beklenen, s.hata)

    def test_akista_bilinmeyen_tur_hata_verir(self):
        akis, oturum = self.pilot("tur0")
        bozuk = akis.rstrip("\n") + "\n" + json.dumps({"type": "item.completed", "item": {"id": "z", "type": "gizli_arac"}}) + "\n"
        s = self.denetle(self.hazirla(akis, oturum), bozuk)
        self.assertEqual(s.durum, "error")
        self.assertIn("akış:item.completed:gizli_arac", s.hata)
        # üst düzey bilinmeyen akış olayı
        s = self.denetle(self.hazirla(akis, oturum), akis + json.dumps({"type": "tool.requested"}) + "\n")
        self.assertEqual(s.durum, "error")
        self.assertIn("akış:tool.requested", s.hata)

    def test_kayit_okunamasa_da_akistaki_bilinmeyen_tur_yeter(self):
        akis, _ = self.pilot("tur0")
        s = A.ciktiyi_coz("codex", 0, akis, "")
        s.oturum_kimligi = kimlik_al(akis)  # oturum kaydı yazılmadı
        bozuk = akis + json.dumps({"type": "item.started", "item": {"id": "q", "type": "bilinmeyen_oge"}}) + "\n"
        self.denetle(s, bozuk)
        self.assertEqual(s.durum, "error")
        self.assertIn("bilinmeyen_oge", s.hata)

    # ---- yalnızca beklenen olaylar → geçer (bozuk satırlar çökertmez)

    def test_yalnizca_beklenen_olaylar_gecer(self):
        akis, _ = self.pilot("tur0")
        oturum = "\n".join(json.dumps(o) for o in [
            {"type": "session_meta", "payload": {"id": "x"}},
            {"type": "turn_context", "payload": {"model": "gpt-6.2-astra"}},
            {"type": "world_state", "payload": {}},
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "event_msg", "payload": {"type": "thread_settings_applied"}},
            {"type": "response_item", "payload": {"type": "additional_tools", "tools": []}},
            {"type": "response_item", "payload": {"type": "message", "role": "developer"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user"}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage"}}},
            {"type": "response_item", "payload": {"type": "reasoning"}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "Reasoning"}}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant"}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "AgentMessage"}}},
            {"type": "token_usage_record", "payload": {}},
            {"type": "event_msg", "payload": {"type": "token_count"}},
            {"type": "event_msg", "payload": {"type": "task_complete"}},
        ]) + "\n{bozuk json\n[]\nnull\n"
        s = self.denetle(self.hazirla(akis, oturum), akis)
        self.assertEqual(s.durum, "ok", s.hata)
        self.assertEqual(s.arac_ozeti["bilinmeyen_olaylar"], {})

    # ---- bilinen araç olayları: sayılır, varsayılan olarak hata değil (karar 27); anahtarla hata

    def test_bilinen_arac_olayi_sayilir_ve_anahtarla_hata_olur(self):
        akis, oturum = self.pilot("tur0")
        oturum += json.dumps({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
                                                                    "input": "text(1)"}}) + "\n"
        s = self.denetle(self.hazirla(akis, oturum), akis)
        self.assertEqual(s.durum, "error", s.hata)  # v0.16: varsayılan artık hata (CODEX_BILINEN_ARAC_HATA=True)
        self.assertEqual(len(s.arac_ozeti["arac_cagrisi"]), 1)
        self.assertEqual(s.arac_ozeti["bilinmeyen_olaylar"], {})
        s = self.hazirla(akis, oturum)
        with mock.patch.object(A, "CODEX_BILINEN_ARAC_HATA", True):
            self.denetle(s, akis)
        self.assertEqual(s.durum, "error")
        self.assertEqual(s.metin, "")

    # ---- rapor

    def test_rapor_bilinmeyen_olay_adini_gosterir(self):
        akis, oturum = self.pilot("tur0")
        oturum += json.dumps({"type": "response_item", "payload": {"type": "yeni_arac_xyz"}}) + "\n"
        s = self.denetle(self.hazirla(akis, oturum), akis)
        t = K.arac_toplami([s])
        self.assertEqual(t["codex_bilinmeyen_olaylar"], {"response_item/yeni_arac_xyz": 1})
        self.assertIn("`response_item/yeni_arac_xyz` ×1", K.arac_toplami_metni("codex", t))
        temiz = K.arac_toplami([self.denetle(*self._temiz())])
        self.assertNotIn("Bilinmeyen olay türü", K.arac_toplami_metni("codex", temiz))

    def _temiz(self):
        shutil.rmtree(self.kayit, ignore_errors=True)
        akis, oturum = self.pilot("tur1")
        return self.hazirla(akis, oturum), akis

    # ---- komut satırı: araç yüzeyi kapalı

    def test_komut_arac_yuzeyini_kapatir(self):
        k = A.komut_olustur("codex", {"komut": ["codex"], "model": "gpt-6.2-astra"}, "soru", 60)
        self.assertIn("--ignore-user-config", k)
        self.assertIn("--strict-config", k)
        cler = [k[i + 1] for i, x in enumerate(k) if x == "-c"]
        for ozellik in A.CODEX_KAPALI_OZELLIKLER:
            self.assertIn(f"features.{ozellik}=false", cler)
        for gerekli in ("shell_tool", "apps", "plugins"):
            self.assertIn(gerekli, A.CODEX_KAPALI_OZELLIKLER)
        self.assertIn('web_search="disabled"', cler)
        self.assertIn('model_reasoning_effort="high"', cler, "kullanıcı config'i yüklenmediği için açık verilmeli")
        self.assertEqual(k[-1], "soru")


if __name__ == "__main__":
    unittest.main()
