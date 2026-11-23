"""
Araç denetimi için sahte CLI: sahte_kayitli_cli.py'yi çalıştırır, sonra agy transcript'ini ve Codex oturum
kaydındaki araç olaylarını taklit eder. Ayrıca agy çağrıldığı anda çalışma klasöründe salt okunur kancasının
bulunup bulunmadığını ve --settings değerini bir gözlem dosyasına yazar.
sahte_cli.py ve sahte_kayitli_cli.py değiştirilmez.

Ortam değişkenleri (sahte_kayitli_cli.py'ninkilere ek olarak):
  SAHTE_BEYIN_DIZINI   agy transcript'lerinin yazılacağı kök (brain/ karşılığı)
  SAHTE_AGY_ARAC       yok | reddedildi | calisti | bos_cevap | transcript_yok | bozuk_transcript
  SAHTE_CODEX_ARAC     yok | komut
  SAHTE_GOZLEM         gözlem dosyası (JSON satırları: kanca içeriği, settings)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

BURASI = Path(__file__).resolve().parent
ad = sys.argv[1]
argumanlar = sys.argv[2:]

if ad == "gemini" and "--version" not in argumanlar and os.environ.get("SAHTE_GOZLEM"):
    kanca = Path.cwd() / ".agents" / "hooks.json"
    ayar = argumanlar[argumanlar.index("--settings") + 1] if "--settings" in argumanlar else None
    with open(os.environ["SAHTE_GOZLEM"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"kanca": kanca.read_text(encoding="utf-8") if kanca.is_file() else None,
                            "settings": ayar}, ensure_ascii=False) + "\n")

p = subprocess.run([sys.executable, str(BURASI / "sahte_kayitli_cli.py"), ad, *argumanlar],
                   capture_output=True, text=True, env=os.environ)
out, err, kod = p.stdout, p.stderr, p.returncode


def adim(i, tur, durum, **ek):
    return json.dumps({"step_index": i, "source": "MODEL" if tur != "USER_INPUT" else "USER_EXPLICIT",
                       "type": tur, "status": durum, **ek}, ensure_ascii=False)


if ad == "gemini" and "--version" not in argumanlar:
    mod = os.environ.get("SAHTE_AGY_ARAC", "yok")
    try:
        d = json.loads(out)
    except json.JSONDecodeError:
        d = None
    if isinstance(d, dict) and d.get("conversation_id"):
        kimlik = d["conversation_id"]
        if mod == "bos_cevap":
            d["response"] = ""
            d["denied_actions"] = [{"action": "write_file", "display_name": "Edit"}]
            out = json.dumps(d, ensure_ascii=False)
        satirlar = [adim(0, "USER_INPUT", "DONE", content="soru")]
        araclar = [{"name": "write_file", "args": {"Path": "x"}}, {"name": "run_command", "args": {"CommandLine": "date"}}]
        if mod == "reddedildi":
            satirlar += [adim(1, "PLANNER_RESPONSE", "DONE", tool_calls=araclar),
                         adim(2, "GENERIC", "ERROR", error="tool call denied by pre-tool hook"),
                         adim(3, "GENERIC", "ERROR", error="tool call denied by pre-tool hook"),
                         adim(4, "PLANNER_RESPONSE", "DONE", content=d.get("response", ""))]
        elif mod == "calisti":
            satirlar += [adim(1, "PLANNER_RESPONSE", "DONE", tool_calls=araclar),
                         adim(2, "GENERIC", "DONE", content="Created file."),
                         adim(3, "GENERIC", "ERROR", error="tool call denied by pre-tool hook"),
                         adim(4, "PLANNER_RESPONSE", "DONE", content=d.get("response", ""))]
        elif mod == "bos_cevap":
            satirlar += [adim(1, "PLANNER_RESPONSE", "DONE", tool_calls=araclar[:1]),
                         adim(2, "GENERIC", "ERROR", error="permission check failed for write_file")]
        else:
            satirlar += [adim(1, "PLANNER_RESPONSE", "DONE", content=d.get("response", ""))]
        if mod == "bozuk_transcript":
            satirlar = ["{bozuk", "[]", "null"]
        if mod != "transcript_yok":
            klasor = Path(os.environ["SAHTE_BEYIN_DIZINI"]) / kimlik / ".system_generated" / "logs"
            klasor.mkdir(parents=True, exist_ok=True)
            (klasor / "transcript_full.jsonl").write_text("\n".join(satirlar) + "\n", encoding="utf-8")

if ad == "codex" and "--version" not in argumanlar and os.environ.get("SAHTE_CODEX_ARAC") == "komut":
    kimlik = None
    for satir in out.splitlines():
        if '"thread.started"' in satir:
            kimlik = json.loads(satir)["thread_id"]
    kok = Path(os.environ.get("SAHTE_KAYIT_DIZINI", "."))
    adaylar = list(kok.glob(f"*/*/*/rollout-*-{kimlik}.jsonl")) if kimlik else []
    if adaylar:
        olaylar = [
            {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
                                                  "input": "tools.exec_command({cmd:'printf x > a.txt'})"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
                                                  "arguments": "{\"cmd\":\"ls\"}"}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {
                "type": "CommandExecution", "command": ["/bin/zsh", "-c", "date"], "exit_code": 0}}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {
                "type": "CommandExecution", "command": ["/bin/zsh", "-c", "ls"], "exit_code": 0}}},
        ]
        with open(adaylar[0], "a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(json.dumps(o) for o in olaylar) + "\n")

sys.stdout.write(out)
sys.stderr.write(err)
sys.exit(kod)
