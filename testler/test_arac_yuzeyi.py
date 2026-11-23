"""Araç yüzeyi denetimleri (karar 39–41): Claude init/sonuç değişmezleri, agy DONE/ERROR dışı durumlar,
Codex akış kaynağı ve CODEX_BILINEN_ARAC_HATA. Hepsi sahte/kayıtlı veriyle; gerçek kota harcanmaz.

Claude örneği (ornekler/claude_akis/temiz_akis.jsonl) gerçek bir `claude -p --output-format stream-json
--verbose` çıktısından 19 Kasım 2026'da alındı; oturum kimlikleri ve uzun listeler ayıklandı."""
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
ORNEK = KLASOR / "ornekler" / "claude_akis" / "temiz_akis.jsonl"
SAHTE = KLASOR / "sahte_claude_akis_cli.py"


def olaylar() -> list[dict]:
    return [json.loads(s) for s in ORNEK.read_text(encoding="utf-8").splitlines() if s.strip()]


def metin(ev: list[dict]) -> str:
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in ev) + "\n"


def sonuc_nesnesi(ev: list[dict]) -> dict:
    return next(e for e in ev if e.get("type") == "result")


def coz(ev: list[dict]) -> A.CagriSonucu:
    """Adaptörün çağrı sırası: önce çözümle, sonra yüzey denetimi."""
    out = metin(ev)
    s = A.ciktiyi_coz("claude", 0, out, "")
    A.claude_yuzeyini_denetle(out, s)
    return s


class ClaudeKomutTesti(unittest.TestCase):
    def test_komut_stream_json_ve_verbose_icerir(self):
        k = A.komut_olustur("claude", {"komut": ["claude"], "model": "opus"}, "soru", 60)
        self.assertEqual(k[k.index("--output-format") + 1], "stream-json")
        self.assertIn("--verbose", k)
        self.assertEqual(k[k.index("--tools") + 1], "")
        self.assertEqual(k[k.index("--disallowedTools") + 1], "mcp__*")


class ClaudeYuzeyTesti(unittest.TestCase):
    def test_gercek_ornek_dogrulanir(self):
        s = coz(olaylar())
        self.assertEqual((s.durum, s.arac_denetimi), ("ok", A.DENETIM_KAPALI), s.hata)
        self.assertTrue(s.metin.strip())
        self.assertEqual(s.arac_ozeti["tools"], [])
        self.assertEqual(s.arac_ozeti["mcp_servers"], [])
        self.assertEqual(s.arac_ozeti["num_turns"], 1)
        self.assertEqual(s.arac_ozeti["ihlaller"], [])
        self.assertIn("claude-opus", s.gercek_model)

    def hata_bekle(self, s: A.CagriSonucu, parca: str):
        self.assertEqual((s.durum, s.arac_denetimi, s.metin), ("error", A.DENETIM_IHLAL, ""), s.hata)
        self.assertTrue(s.hata.startswith(A.CLAUDE_YUZEYI), s.hata)
        self.assertIn(parca, s.hata)
        self.assertIn("ihlal", A.arac_ozeti_metni(s))

    def test_init_araci_beklenenden_farkliysa_hata(self):
        ev = olaylar()
        ev[0]["tools"] = ["Bash", "Read"]
        self.hata_bekle(coz(ev), "beklenmeyen araç: Bash, Read")

    def test_init_mcp_sunucusu_varsa_hata(self):
        ev = olaylar()
        ev[0]["mcp_servers"] = [{"name": "claude.ai Notion", "status": "connected"}]
        self.hata_bekle(coz(ev), "beklenmeyen MCP sunucusu: claude.ai Notion")

    def test_init_listesi_okunamazsa_hata(self):
        ev = olaylar()
        ev[0]["tools"] = "yok"
        self.hata_bekle(coz(ev), "init.tools okunamadı")

    def test_birden_cok_tur_hata(self):
        ev = olaylar()
        sonuc_nesnesi(ev)["num_turns"] = 2
        self.hata_bekle(coz(ev), "num_turns=2")

    def test_izin_reddi_hata(self):
        ev = olaylar()
        sonuc_nesnesi(ev)["permission_denials"] = [{"tool_name": "Bash"}]
        self.hata_bekle(coz(ev), "permission_denials")

    def test_sunucu_tarafi_web_arama_sayaci_hata(self):
        ev = olaylar()
        sonuc_nesnesi(ev)["usage"]["server_tool_use"]["web_search_requests"] = 1
        self.hata_bekle(coz(ev), "usage.server_tool_use")

    def test_sunucu_tarafi_web_getirme_sayaci_hata(self):
        ev = olaylar()
        sonuc_nesnesi(ev)["usage"]["server_tool_use"]["web_fetch_requests"] = 2
        self.hata_bekle(coz(ev), "usage.server_tool_use")

    def test_model_kullanimindaki_web_arama_hata(self):
        ev = olaylar()
        for m in sonuc_nesnesi(ev)["modelUsage"].values():
            m["webSearchRequests"] = 3
        self.hata_bekle(coz(ev), "webSearchRequests=3")

    def test_asistan_olayinda_arac_blogu_hata(self):
        ev = olaylar()
        asistan = next(e for e in ev if e.get("type") == "assistant")
        asistan["message"]["content"].append({"type": "tool_use", "name": "Bash", "input": {}})
        self.hata_bekle(coz(ev), "1 araç bloğu")

    def test_init_varken_eksik_alan_hata(self):
        for alan in ("num_turns", "permission_denials", "usage", "modelUsage"):
            with self.subTest(alan=alan):
                ev = olaylar()
                del sonuc_nesnesi(ev)[alan]
                s = coz(ev)
                self.assertEqual((s.durum, s.arac_denetimi), ("error", A.DENETIM_IHLAL), s.hata)

    def test_akista_result_olayi_yoksa_hata(self):
        ev = [e for e in olaylar() if e.get("type") != "result"]
        out = metin(ev)
        s = A.ciktiyi_coz("claude", 0, out, "")
        self.assertEqual(s.durum, "error")
        self.assertIn("result olayı yok", s.hata)

    def test_init_zorunlu_varsayilan_acik(self):
        self.assertTrue(A.CLAUDE_INIT_ZORUNLU)

    def test_init_olmayan_cikti_hata_verir(self):
        """Akış var ama init olayı yok: araç/MCP listesi doğrulanamaz, çağrı hata (kapalı-başarısız)."""
        ev = [e for e in olaylar() if e.get("type") != "system"]
        s = coz(ev)
        self.assertEqual((s.durum, s.arac_denetimi, s.metin), ("error", A.DENETIM_IHLAL, ""), s.hata)
        self.assertTrue(s.hata.startswith(A.CLAUDE_YUZEYI), s.hata)
        self.assertIn("init olayı yok", s.hata)
        self.assertFalse(s.arac_ozeti["akis"])

    def test_eski_tek_json_cikti_hata_verir(self):
        """CLI akış biçimini bırakıp eski tek JSON'a dönerse sessizce 'araçlar kapalı' denmez."""
        eski = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "OK",
                           "modelUsage": {"claude-opus-5-5": {"outputTokens": 10}}})
        s = A.ciktiyi_coz("claude", 0, eski, "")
        A.claude_yuzeyini_denetle(eski, s)
        self.assertEqual((s.durum, s.arac_denetimi), ("error", A.DENETIM_IHLAL), s.hata)
        self.assertIn("init olayı yok", s.hata)

    def test_bayrak_kapaliysa_yalnizca_gorulen_ihlaller_hata(self):
        """Bayrak elle kapatılırsa (önerilmez) init olmayan çıktı geçer, ama görülen değişmez ihlali yine hata."""
        ev = [e for e in olaylar() if e.get("type") != "system"]
        with mock.patch.object(A, "CLAUDE_INIT_ZORUNLU", False):
            s = coz(ev)
            self.assertEqual(s.durum, "ok", s.hata)
            sonuc_nesnesi(ev)["num_turns"] = 3
            s = coz(ev)
        self.assertEqual((s.durum, s.arac_denetimi), ("error", A.DENETIM_IHLAL), s.hata)

    def test_basarisiz_cagri_durumunu_degistirmez(self):
        ev = olaylar()
        ev[0]["tools"] = ["Bash"]
        r = sonuc_nesnesi(ev)
        r["is_error"] = True
        r["result"] = "Claude AI usage limit reached|1763500000"
        s = coz(ev)
        self.assertEqual(s.durum, "rate_limited")
        self.assertEqual(s.arac_denetimi, A.DENETIM_IHLAL)


class ClaudeUctanUcaTesti(unittest.TestCase):
    """Gerçek `cagir` yolu; sahte_claude_akis_cli.py kayıtlı gerçek akışı (ya da bozulmuş halini) basar."""

    def cagir(self, mod: str) -> A.CagriSonucu:
        os.environ["SAHTE_CLAUDE_AKIS"] = mod
        self.addCleanup(os.environ.pop, "SAHTE_CLAUDE_AKIS", None)
        with tempfile.TemporaryDirectory() as d:
            s = {"komut": [sys.executable, str(SAHTE)], "model": "opus"}
            return asyncio.run(A.cagir("claude", s, "2+2 kaç?", 30, d))

    def test_temiz_akis(self):
        s = self.cagir("temiz")
        self.assertEqual((s.durum, s.arac_denetimi), ("ok", A.DENETIM_KAPALI), s.hata)

    def test_mcp_sunucusu_gelirse_cagri_hata(self):
        s = self.cagir("mcp")
        self.assertEqual((s.durum, s.arac_denetimi, s.metin), ("error", A.DENETIM_IHLAL, ""), s.hata)
        self.assertIn("beklenmeyen MCP sunucusu", s.hata)

    def test_arac_gelirse_cagri_hata(self):
        s = self.cagir("arac")
        self.assertEqual((s.durum, s.arac_denetimi), ("error", A.DENETIM_IHLAL), s.hata)
        self.assertIn("beklenmeyen araç", s.hata)


class AgyDurumTesti(unittest.TestCase):
    KIMLIK = "abcd-1234-efgh"

    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        self.addCleanup(self.gecici.cleanup)

    def transcript(self, adimlar: list[dict]) -> dict | None:
        yol = Path(self.gecici.name) / self.KIMLIK / ".system_generated" / "logs"
        yol.mkdir(parents=True, exist_ok=True)
        (yol / "transcript_full.jsonl").write_text("\n".join(json.dumps(a) for a in adimlar) + "\n", encoding="utf-8")
        return A.agy_transcript_denetle(self.gecici.name, self.KIMLIK)

    TEMEL = [{"type": "USER_INPUT", "status": "DONE"}, {"type": "PLANNER_RESPONSE", "status": "DONE"}]

    def test_error_adimi_reddedilen_sayilir_ihlal_degil(self):
        k = self.transcript(self.TEMEL + [{"type": "GENERIC", "status": "ERROR"}])
        self.assertEqual((k["reddedilen"], k["calisan"]), (1, []))

    def test_done_adimi_ihlal(self):
        k = self.transcript(self.TEMEL + [{"type": "RUN_COMMAND", "status": "DONE", "content": "date"}])
        self.assertEqual(len(k["calisan"]), 1)

    def test_done_ve_error_disindaki_durumlar_ihlal(self):
        for durum in ("RUNNING", "PENDING", "WAITING", "CANCELED", "", None):
            with self.subTest(durum=durum):
                adim = {"type": "SOME_NEW_TOOL"} if durum is None else {"type": "SOME_NEW_TOOL", "status": durum}
                k = self.transcript(self.TEMEL + [adim])
                self.assertEqual(len(k["calisan"]), 1)
                self.assertTrue(k["calisan"][0].startswith(A.AGY_BELIRSIZ_ADIM), k["calisan"])

    def test_bilinmeyen_tur_error_ise_ihlal_degil(self):
        k = self.transcript(self.TEMEL + [{"type": "YENI_TUR", "status": "ERROR"}])
        self.assertEqual((k["reddedilen"], k["calisan"]), (1, []))

    def test_cagri_hataya_donusur_ve_neden_belirtilir(self):
        self.transcript(self.TEMEL + [{"type": "SOME_NEW_TOOL", "status": "RUNNING"}])
        sonuc = A.CagriSonucu("gemini", "ok", metin="cevap", oturum_kimligi=self.KIMLIK)
        A.agy_araclarini_denetle({"beyin_dizini": self.gecici.name}, sonuc)
        self.assertEqual((sonuc.durum, sonuc.arac_denetimi, sonuc.metin), ("error", A.DENETIM_IHLAL, ""))
        self.assertIn(A.ARAC_IHLALI, sonuc.hata)
        self.assertIn("DONE/ERROR dışı durumda", sonuc.hata)

    def test_gercek_transcriptler_temiz_kalir(self):
        """Makinede kayıtlı gerçek agy transcript'leri yeni kuralla ihlal vermemeli (yoksa atlanır)."""
        beyin = Path(A.VARSAYILAN_AGY_BEYIN_DIZINI).expanduser()
        yollar = list(beyin.glob("*/.system_generated/logs/transcript_full.jsonl")) if beyin.is_dir() else []
        if not yollar:
            self.skipTest("gerçek agy transcript'i yok")
        for yol in yollar:
            k = A.agy_transcript_denetle(str(beyin), yol.parents[2].name)
            if k is None:
                continue
            self.assertFalse([x for x in k["calisan"] if x.startswith(A.AGY_BELIRSIZ_ADIM)], str(yol))


class CodexAkisKaynagiTesti(unittest.TestCase):
    """Oturum kaydı okunamasa bile --json akışındaki araç öğeleri hata sayılır."""

    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        self.addCleanup(self.gecici.cleanup)
        self.ayar = {"kayit_dizini": str(Path(self.gecici.name) / "yok")}

    def akis(self, *ogeler: dict) -> str:
        satirlar = [{"type": "thread.started", "thread_id": "t1abc"}, {"type": "turn.started"}]
        for o in ogeler:
            satirlar.append({"type": "item.started", "item": dict(o)})
            satirlar.append({"type": "item.completed", "item": dict(o)})
        satirlar.append({"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}})
        satirlar.append({"type": "turn.completed"})
        return "\n".join(json.dumps(s) for s in satirlar) + "\n"

    def denetle(self, akis: str) -> A.CagriSonucu:
        s = A.ciktiyi_coz("codex", 0, akis, "")
        s.oturum_kimligi = "t1abc"
        self.assertTrue(s.basarili, s.hata)
        A.codex_araclarini_denetle(self.ayar, s, akis)
        return s

    def test_temiz_akis_gecer(self):
        s = self.denetle(self.akis())
        self.assertEqual(s.durum, "ok", s.hata)

    def test_komut_ogesi_kayit_okunamasa_da_hata(self):
        for tur in ("command_execution", "mcp_tool_call", "file_change"):
            with self.subTest(tur=tur):
                s = self.denetle(self.akis({"id": "i1", "type": tur, "command": "date"}))
                self.assertEqual((s.durum, s.metin, s.arac_denetimi), ("error", "", A.DENETIM_IHLAL))
                self.assertTrue(s.hata.startswith(A.CODEX_ARAC_KULLANIMI), s.hata)
                self.assertEqual(s.arac_ozeti["akis_arac_olaylari"], {f"akış:item.completed:{tur}": 1})

    def test_bayrak_kapaliysa_yalnizca_sayilir(self):
        with mock.patch.object(A, "CODEX_BILINEN_ARAC_HATA", False):
            s = self.denetle(self.akis({"id": "i1", "type": "command_execution", "command": "date"}))
        self.assertEqual(s.durum, "ok", s.hata)

    def test_varsayilan_bayrak_aciktir(self):
        self.assertTrue(A.CODEX_BILINEN_ARAC_HATA)

    def test_bilinmeyen_tur_ve_web_oncelikli_kalir(self):
        s = self.denetle(self.akis({"id": "i1", "type": "garip_oge"}))
        self.assertTrue(s.hata.startswith(A.CODEX_BILINMEYEN_OLAY), s.hata)
        s = self.denetle(self.akis({"id": "i2", "type": "web_search", "query": "x"}))
        self.assertTrue(s.hata.startswith(A.CODEX_WEB_ERISIMI), s.hata)


if __name__ == "__main__":
    unittest.main()
