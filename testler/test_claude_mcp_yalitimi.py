"""Claude MCP yalıtımı (karar 47): konsey komutunda --strict-mcp-config var; gerçek deneyde (19 Kasım 2026, proje düzeyi
.mcp.json varken) init'te görülen biçimde bağlayıcı/sunucu listesi çağrıyı hata yapar (ikinci savunma hattı)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import adaptor as A  # noqa: E402

ORNEK = Path(__file__).resolve().parent / "ornekler" / "claude_akis" / "temiz_akis.jsonl"
# Gerçek deneyde (bayraksız, proje .mcp.json varken) görülen init.mcp_servers değeri
GERCEK_DENEY_MCP = [
    {"name": "kanarya-proje", "status": "failed", "source": "project"},
    {"name": "claude.ai Claude Docs", "status": "connected", "source": "claudeai"},
    {"name": "claude.ai Notion", "status": "connected", "source": "claudeai"},
    {"name": "claude.ai Google Drive", "status": "needs-auth", "source": "claudeai"},
]


def akis(mcp) -> str:
    ev = [json.loads(x) for x in ORNEK.read_text(encoding="utf-8").splitlines() if x.strip()]
    ev[0]["mcp_servers"] = mcp
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in ev) + "\n"


class ClaudeMcpYalitimTesti(unittest.TestCase):
    def test_komutta_strict_mcp_config_var_mcp_config_yok(self):
        k = A.komut_olustur("claude", {"komut": ["claude"], "model": "opus"}, "soru", 60)
        self.assertIn("--strict-mcp-config", k)
        self.assertNotIn("--mcp-config", k)
        self.assertEqual(k[k.index("--disallowedTools") + 1], "mcp__*")  # eski kemer de duruyor
        self.assertEqual(k[k.index("--tools") + 1], "")

    def test_temiz_init_gecer(self):
        out = akis([])
        s = A.ciktiyi_coz("claude", 0, out, "")
        A.claude_yuzeyini_denetle(out, s)
        self.assertEqual((s.durum, s.arac_denetimi), ("ok", A.DENETIM_KAPALI), s.hata)

    def test_gercek_deneydeki_baglayici_listesi_hata_verir(self):
        out = akis(GERCEK_DENEY_MCP)
        s = A.ciktiyi_coz("claude", 0, out, "")
        A.claude_yuzeyini_denetle(out, s)
        self.assertEqual((s.durum, s.arac_denetimi, s.metin), ("error", A.DENETIM_IHLAL, ""), s.hata)
        self.assertTrue(s.hata.startswith(A.CLAUDE_YUZEYI), s.hata)
        for ad in ("claude.ai Notion", "claude.ai Claude Docs", "kanarya-proje"):
            self.assertIn(ad, s.hata)

    def test_tek_baglayici_bile_hata(self):
        out = akis([{"name": "claude.ai Notion", "status": "connected", "source": "claudeai"}])
        s = A.ciktiyi_coz("claude", 0, out, "")
        A.claude_yuzeyini_denetle(out, s)
        self.assertEqual(s.durum, "error")


if __name__ == "__main__":
    unittest.main()
