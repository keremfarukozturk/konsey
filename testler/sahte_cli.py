"""
Sahte CLI: gerçek claude/codex/agy çıktılarını taklit eder. Testler gerçek kotaya dokunmadan
konseyin hata davranışını sınamak için bunu kullanır.

Kullanım: python sahte_cli.py <claude|codex|gemini> <gerçek CLI argümanları...>
Davranış ortam değişkeniyle seçilir: SAHTE_CLAUDE / SAHTE_CODEX / SAHTE_GEMINI
  ok, kota, giris, zamanasimi, bozuk_cikti, bozuk_pusula, yanlis_surum, ret,
  kota_onay, kota_elestiri, kota_duzeltme, bilinmeyen_model, env_kontrol
v0.21 (karar 50): eleştiri/düzeltme turları. SAHTE_ELESTIRI: yok (varsayılan; maddesiz eleştiri, JSON sıfır),
  madde (her cevaba 1 önemli madde), bozuk_json (JSON yok), bolumsuz (bölüm işareti yok), tutarsiz (JSON 0 ama metinde madde).
  SAHTE_DUZELTME: ok | bozuk (GÜNCEL CEVAP başlığı yok). SAHTE_SIRA_<AD>: "daha_iyi" için yazar sırası.
  "DÜZELTİLDİ" içeren cevaplar görünce eleştiri maddesiz döner (2. turda erken durma).
Claude giriş yöntemi: SAHTE_CLAUDE_AUTH (varsayılan claude.ai)
"""
import json
import os
import re
import subprocess
import sys
import time

ad = sys.argv[1]
argumanlar = sys.argv[2:]
mod = os.environ.get(f"SAHTE_{ad.upper()}", "ok")


def prompt_bul():
    if ad in ("claude", "gemini") and "-p" in argumanlar:
        return argumanlar[argumanlar.index("-p") + 1]
    if ad == "codex":
        return argumanlar[-1]
    return ""


def tur_bul(p):
    if "ÖNERİLEN ORTAK METİN" in p:
        return "onay"
    if "sentez yazarısın" in p:
        return "sentez"
    if "SENİN GÜNCEL CEVABIN" in p:
        return "duzeltme"
    if "=== CEVAP A ===" in p:
        return "tur1"  # eleştiri (v0.21'de Tur 1'in yerini aldı; ad eski testlerle uyumlu)
    if p.strip() == "/usage":
        return "usage"
    if "2+2" in p:
        return "duman"
    return "tur0"


def cevap_uret(p, tur):
    if tur == "duman":
        return "4"
    if tur == "tur0":
        if mod == "env_kontrol":
            return "ANAHTAR_VAR" if os.environ.get("ANTHROPIC_API_KEY") else "ANAHTAR_YOK"
        return f"CEVAP: {ad} cevabı\nGEREKÇE: test\nGÜVEN: 70"
    if tur == "tur1":
        etiketler = re.findall(r"^=== CEVAP (\w) ===$", p, re.M)
        yazarlar = dict(zip(etiketler, re.findall(r"CEVAP: (\w+) cevabı", p)))
        sira = os.environ.get(f"SAHTE_SIRA_{ad.upper()}", "claude,codex,gemini").split(",")
        daha_iyi = min(etiketler, key=lambda e: sira.index(yazarlar[e]) if yazarlar.get(e) in sira else 99)
        biçim = os.environ.get("SAHTE_ELESTIRI", "yok")
        if "DÜZELTİLDİ" in p:
            biçim = "yok"
        madde = biçim in ("madde", "bozuk_json", "bolumsuz", "tutarsiz")
        bolumler = ""
        for e in etiketler:
            govde = ("HATALAR\n- [1] (önem: önemli; güven: yüksek) sahte madde\nEKSİK NOKTALAR\nSorun yok.\n"
                     if madde else "HATALAR\nSorun yok.\nEKSİK NOKTALAR\nSorun yok.\n")
            bolumler += (f"=== CEVAP {e} HAKKINDA ===\n" if biçim != "bolumsuz" else "") + govde + "\n"
        n = 1 if biçim in ("madde", "bozuk_json", "bolumsuz") else 0
        j = {e: {"kritik": 0, "onemli": n, "kucuk": 0} for e in etiketler}
        if len(etiketler) == 2:
            j["daha_iyi"] = daha_iyi
        son = "" if biçim == "bozuk_json" else "```json\n" + json.dumps(j) + "\n```"
        return bolumler + son
    if tur == "duzeltme":
        if os.environ.get("SAHTE_DUZELTME", "ok") == "bozuk":
            return "DEĞİŞİKLİK KAYDI:\n- E1-1 KABUL: x\nCevabı yazmayı unuttum."
        kimlikler = list(dict.fromkeys(re.findall(r"\[(E\d+-\d+)\]", p))) or ["E1-1"]
        satirlar = "\n".join(f"- {k} {'KABUL' if i % 2 == 0 else 'RED'}: sahte" for i, k in enumerate(kimlikler))
        return (f"DEĞİŞİKLİK KAYDI:\n{satirlar}\nGÜNCEL CEVAP:\nCEVAP: {ad} cevabı DÜZELTİLDİ\nGEREKÇE: test\nGÜVEN: 70")
    if tur == "sentez":
        return "ÖZET: ortak sonuç.\nCEVAP: test\nBELİRSİZLİKLER: Yok"
    # onay
    ozet = re.search(r"METİN SÜRÜMÜ: (\w+)", p).group(1)
    if mod == "bozuk_pusula":
        return "Metni kabul ediyorum ama JSON yazmayı unuttum."
    if mod == "yanlis_surum":
        ozet = "000000000000"
    oy = "RET" if mod == "ret" else "KABUL"
    return json.dumps({"metin_surumu": ozet, "oy": oy, "gerekce": "test",
                       "itirazlar": ["önemli hata"] if oy == "RET" else []}, ensure_ascii=False)


def yaz_ve_cik(stdout="", stderr="", kod=0):
    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    sys.exit(kod)


# --- yardımcı komutlar
if "--version" in argumanlar:
    yaz_ve_cik(f"{ad} 9.9.9-sahte\n")
if ad == "claude" and argumanlar[:2] == ["auth", "status"]:
    yontem = os.environ.get("SAHTE_CLAUDE_AUTH", "claude.ai")
    yaz_ve_cik(json.dumps({"loggedIn": yontem != "yok", "authMethod": yontem, "subscriptionType": "pro"}))

p = prompt_bul()
tur = tur_bul(p)
kota = (mod == "kota" or (mod == "kota_onay" and tur == "onay") or (mod == "kota_elestiri" and tur == "tur1")
        or (mod == "kota_duzeltme" and tur == "duzeltme"))
if tur == "usage" and ad in ("claude", "gemini"):  # /usage yerel komuttur (v0.21): model çağrısı yok, kota harcamaz
    if mod == "bozuk_cikti":
        yaz_ve_cik("bu JSON değil <<<", "", 0)
    if ad == "claude":
        yaz_ve_cik(json.dumps({"is_error": False, "num_turns": 0, "result": "Current session: 10% used"}))
    yaz_ve_cik(json.dumps({"status": "SUCCESS", "response": "Gemini Models\tFive Hour Limit Remaining\t90%", "num_turns": 0}))

if mod == "zamanasimi":
    cocuk = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    pid_dosyasi = os.environ.get("SAHTE_PID_DOSYASI")
    if pid_dosyasi:
        with open(pid_dosyasi, "w") as f:
            f.write(str(cocuk.pid))
    time.sleep(120)

if mod == "bozuk_cikti":
    yaz_ve_cik("bu JSON değil <<<", "", 0)

if ad == "claude":
    # v0.18: gerçek `claude -p --output-format stream-json --verbose` biçimi (olay başına bir JSON satırı):
    # init (tools: [], mcp_servers: []), asistan olayı, result. Sonuç alanları gerçek çıktıdaki değişmezlerle uyumlu.
    def akis(sonuc_alanlari, kod=0):
        init = {"type": "system", "subtype": "init", "tools": [], "mcp_servers": [], "model": "claude-opus-5-5",
                "apiKeySource": "none"}  # gerçek init'te abonelik girişi için "none" (v0.20)
        son = {"type": "result", "subtype": "success", "num_turns": 1, "permission_denials": [],
               "usage": {"server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0}},
               "modelUsage": {"claude-opus-5-5": {"outputTokens": 10, "webSearchRequests": 0}}, **sonuc_alanlari}
        olaylar = [init]
        if not son.get("is_error"):
            olaylar.append({"type": "assistant", "message": {"content": [{"type": "text", "text": son["result"]}]}})
        olaylar.append(son)
        yaz_ve_cik("\n".join(json.dumps(e, ensure_ascii=False) for e in olaylar) + "\n", "", kod)

    if kota:
        akis({"is_error": True, "result": "Claude AI usage limit reached|1763500000"}, 1)
    if mod == "giris":
        akis({"is_error": True, "result": "Invalid API key · Please run /login"}, 1)
    akis({"is_error": False, "result": cevap_uret(p, tur)})

if ad == "codex":
    uyari = "MCP client for `cua_repl` failed to start: handshaking with MCP server failed\n"
    olaylar = [{"type": "thread.started", "thread_id": "t1"}, {"type": "turn.started"}]
    if kota:
        olaylar.append({"type": "turn.failed",
                        "error": {"message": "You've hit your usage limit. Try again at 01:58."}})
        yaz_ve_cik("\n".join(json.dumps(e) for e in olaylar) + "\n", uyari, 1)
    olaylar += [
        {"type": "item.completed", "item": {"id": "i0", "type": "reasoning", "text": "GİZLİ AKIL YÜRÜTME {"}},
        {"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": cevap_uret(p, tur)}},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}},
    ]
    yaz_ve_cik("\n".join(json.dumps(e, ensure_ascii=False) for e in olaylar) + "\n", uyari, 0)

if ad == "gemini":
    if mod == "bilinmeyen_model":
        yaz_ve_cik(json.dumps({"status": "error", "error": "unknown model: gemini-yok"}), "", 1)
    if kota:
        yaz_ve_cik(json.dumps({"status": "error", "error": "RESOURCE_EXHAUSTED: quota exceeded"}), "", 1)
    yaz_ve_cik(json.dumps({"status": "success", "response": cevap_uret(p, tur), "error": None, "usage": {}},
                          ensure_ascii=False))
