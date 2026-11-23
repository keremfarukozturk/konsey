"""
Kayıt yazan sahte CLI: sahte_cli.py'yi çalıştırır, çıktısına oturum kimliği ekler ve
agy'nin konuşma veritabanını ya da Codex'in oturum kaydını taklit eden dosyayı yazar.
Model doğrulama ve kota okuma testleri bunu kullanır; sahte_cli.py değiştirilmez.

Kullanım: python sahte_kayitli_cli.py <claude|codex|gemini> <gerçek CLI argümanları...>
Ortam değişkenleri:
  SAHTE_KAYIT_DIZINI          kayıtların yazılacağı kök klasör (gemini: doğrudan, codex: YYYY/MM/DD altı)
  SAHTE_GEMINI_YANIT_MODELI   response_model alanı (varsayılan gemini-4-neon)
  SAHTE_GEMINI_NON_GEMINI     used_non_gemini_model değeri (varsayılan false)
  SAHTE_GEMINI_KAYIT          normal | yok | bozuk_blob | tablo_yok | cop_dosya | alan_yok
  SAHTE_CODEX_ISTEMCI_MODELI  turn_context.model (varsayılan: -m ile istenen model)
  SAHTE_CODEX_KAYIT           normal | yok | cop_satirlar | turn_context_yok
  SAHTE_CODEX_KOTA            normal | yok | sinirda
Diğer davranışlar sahte_cli.py ile aynıdır (SAHTE_CLAUDE / SAHTE_CODEX / SAHTE_GEMINI).
"""
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

BURASI = Path(__file__).resolve().parent
ad = sys.argv[1]
argumanlar = sys.argv[2:]

p = subprocess.run([sys.executable, str(BURASI / "sahte_cli.py"), ad, *argumanlar],
                   capture_output=True, text=True, env=os.environ)
out, err, kod = p.stdout, p.stderr, p.returncode
kok = Path(os.environ.get("SAHTE_KAYIT_DIZINI", "."))


# --------------------------------------------------------------------------- protobuf yazımı


def varint(n: int) -> bytes:
    b = bytearray()
    while True:
        x = n & 0x7F
        n >>= 7
        if n:
            b.append(x | 0x80)
        else:
            b.append(x)
            return bytes(b)


def alan_bayt(no: int, veri: bytes) -> bytes:
    return varint(no << 3 | 2) + varint(len(veri)) + veri


def alan_sayi(no: int, n: int) -> bytes:
    return varint(no << 3 | 0) + varint(n)


def anahtar_deger(k: str, v: str) -> bytes:
    return alan_bayt(20, alan_bayt(1, k.encode()) + alan_bayt(2, v.encode()))


def agy_kaydi_yaz(kimlik: str) -> None:
    durum = os.environ.get("SAHTE_GEMINI_KAYIT", "normal")
    if durum == "yok":
        return
    kok.mkdir(parents=True, exist_ok=True)
    yol = kok / f"{kimlik}.db"
    if durum == "cop_dosya":
        yol.write_bytes(b"bu bir sqlite dosyasi degil")
        return
    con = sqlite3.connect(yol)
    if durum != "tablo_yok":
        con.execute("CREATE TABLE gen_metadata (idx integer PRIMARY KEY, data blob, size integer)")
        if durum == "bozuk_blob":
            veri = b"\x0a\xff\xff\xff\x0f\x01\x02"  # uzunluk taşması
        else:
            ic = alan_sayi(3, 1532) + alan_bayt(4, alan_sayi(2, 9557) + alan_bayt(11, b"YanitKimligi"))
            if durum != "alan_yok":
                ic += alan_bayt(19, os.environ.get("SAHTE_GEMINI_YANIT_MODELI", "gemini-4-neon").encode())
            ic += anahtar_deger("used_non_gemini_model", os.environ.get("SAHTE_GEMINI_NON_GEMINI", "false"))
            ic += anahtar_deger("used_claude", "false")
            ic += alan_bayt(21, b"Gemini 4 Neon (High)")
            veri = alan_bayt(1, ic) + alan_bayt(3, alan_bayt(28, b"gemini-4-neon-high")) + alan_bayt(4, b"x")
        con.execute("INSERT INTO gen_metadata VALUES (0, ?, ?)", (veri, len(veri)))
    else:
        con.execute("CREATE TABLE baska (x integer)")
    con.commit()
    con.close()


def codex_kaydi_yaz(kimlik: str, istenen: str) -> None:
    durum = os.environ.get("SAHTE_CODEX_KAYIT", "normal")
    if durum == "yok":
        return
    klasor = kok / "2026" / "11" / "19"
    klasor.mkdir(parents=True, exist_ok=True)
    satirlar = [json.dumps({"type": "session_meta", "payload": {"id": kimlik, "model_provider": "openai"}})]
    if durum == "cop_satirlar":
        satirlar += ["{bozuk json", "[]", "null"]
    if durum != "turn_context_yok":
        model = os.environ.get("SAHTE_CODEX_ISTEMCI_MODELI", istenen)
        satirlar.append(json.dumps({"type": "turn_context", "payload": {"model": model, "effort": "high"}}))
    kota = os.environ.get("SAHTE_CODEX_KOTA", "normal")
    if kota != "yok":
        rl = {"limit_id": "codex",
              "primary": {"used_percent": 100.0 if kota == "sinirda" else 4.0, "window_minutes": 300,
                          "resets_at": 1795049819},
              "secondary": {"used_percent": 1.0, "window_minutes": 10080, "resets_at": 1795636619},
              "plan_type": "plus",
              "rate_limit_reached_type": "primary" if kota == "sinirda" else None}
        satirlar.append(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {},
                                                                      "rate_limits": rl}}))
    satirlar.append('{"type": "event_msg", "payload": {"type": "task_comp')  # yarım kalmış son satır
    (klasor / f"rollout-2026-11-19T00-00-00-{kimlik}.jsonl").write_text("\n".join(satirlar), encoding="utf-8")


# --------------------------------------------------------------------------- çıktı düzenleme

if ad == "gemini" and "--version" not in argumanlar:
    kimlik = str(uuid.uuid4())
    try:
        d = json.loads(out)
        if isinstance(d, dict):
            d["conversation_id"] = kimlik
            out = json.dumps(d, ensure_ascii=False)
            agy_kaydi_yaz(kimlik)
    except json.JSONDecodeError:
        pass  # bozuk çıktı modu: olduğu gibi bırak

if ad == "codex" and "--version" not in argumanlar:
    kimlik = str(uuid.uuid4())
    istenen = argumanlar[argumanlar.index("-m") + 1] if "-m" in argumanlar else ""
    if '"thread.started"' in out:
        out = out.replace('"thread_id": "t1"', f'"thread_id": "{kimlik}"')
        codex_kaydi_yaz(kimlik, istenen)

sys.stdout.write(out)
sys.stderr.write(err)
sys.exit(kod)
