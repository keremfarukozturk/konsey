"""Sahte Claude (stream-json): kayıtlı gerçek akışı basar. SAHTE_CLAUDE_AKIS: temiz | mcp | arac."""
import json
import os
import sys
from pathlib import Path

ORNEK = Path(__file__).resolve().parent / "ornekler" / "claude_akis" / "temiz_akis.jsonl"
mod = os.environ.get("SAHTE_CLAUDE_AKIS", "temiz")
olaylar = [json.loads(s) for s in ORNEK.read_text(encoding="utf-8").splitlines() if s.strip()]
if mod == "mcp":
    olaylar[0]["mcp_servers"] = [{"name": "claude.ai Notion", "status": "connected"}]
elif mod == "arac":
    olaylar[0]["tools"] = ["Bash"]
sys.stdout.write("\n".join(json.dumps(e, ensure_ascii=False) for e in olaylar) + "\n")
