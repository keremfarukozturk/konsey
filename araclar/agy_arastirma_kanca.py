#!/usr/bin/env python3
"""agy araştırmacısının PreToolUse kancası (karar 64): yalnızca `search_web`'e izin verir, her şeyi (read_url_content dahil)
reddeder. Girdi: agy'nin stdin'e yazdığı JSON (`toolCall.name`). Kapalı-başarısız: okunamayan/eksik girdi, bilinmeyen araç
adı ya da herhangi bir hata `deny` verir. Konsey koltuğunun "her şeyi reddet" kancasından (adaptor.AGY_HOOK_JSON) ayrıdır."""
import json
import sys

IZINLI = "search_web"


def karar(ham: str) -> dict:
    try:
        d = json.loads(ham)
        ad = d["toolCall"]["name"]
    except Exception:
        return {"decision": "deny", "reason": "Araştırmacı kancası: girdi okunamadı."}
    if ad == IZINLI:
        return {"decision": "allow", "reason": "Araştırmacı: yalnızca search_web."}
    return {"decision": "deny", "reason": "Araştırmacı: yalnızca search_web izinli."}


if __name__ == "__main__":
    try:
        girdi = sys.stdin.read()
    except Exception:
        girdi = ""
    sys.stdout.write(json.dumps(karar(girdi)))
