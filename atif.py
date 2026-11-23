"""v0.31: araştırma paketi / kullanıcı kanıtı için [K#] atıfları: kimlikleme, ayrıştırma, KOD denetimi ve rapor bölümleri.

Saf işlevler (model çağrısı, ağ ve dosya erişimi yok). Orkestratör hiçbir kaynağa HTTP isteği atmaz; denetim yalnızca paket
maddelerinin kendi alanlarından (etiketler, kaynak türü) yapılır.
"""
from __future__ import annotations

import re

# v1.0: TARİH_BUGÜN artık zayıflık sayılmaz (yalnızca bilgi etiketi); TEKRAR_KAYNAK da sayılmaz
ZAYIF_ETIKETLER = ("YÖNLENDİRME_ADRESİ", "BAŞLIK_ALINTISI", "NİCEL_İDDİA_ALINTIDA_YOK")
ZAYIF_KAYNAK_TURU = "VİDEO_SOSYAL"
KULLANICI_ETIKETI = "KULLANICI_KANITI"

KOD_BLOGU = re.compile(r"```.*?(?:```|\Z)", re.S)
SATIR_ICI_KOD = re.compile(r"`[^`\n]*`")
ATIF_KALIBI = re.compile(r"\[\s*(K\d+(?:\s*[,;]\s*K\d+)*)\s*\]")
KIMLIK = re.compile(r"K\d+")
BASLIK_SATIRI = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def kanit_kimlikle(ham: str, baslangic: int = 0) -> tuple[str, list[dict]]:
    """Kullanıcı kanıtını başlıklarına (Markdown #) göre maddelere böler (başlık yoksa tek madde); her maddeye K kimliği ve
    "KULLANICI_KANITI" etiketi verir. Dönüş: (kimlikli metin, [{"kimlik","tur":"kullanici","baslik","etiketler"}]).
    Kimlikler baslangic+1'den başlar."""
    ham = (ham or "").strip()
    if not ham:
        return "", []
    parcalar: list[tuple[str, list[str]]] = []
    baslik, govde = "", []
    for satir in ham.splitlines():
        m = BASLIK_SATIRI.match(satir)
        if m:
            if baslik or any(s.strip() for s in govde):
                parcalar.append((baslik, govde))
            baslik, govde = m.group(2).strip(), []
        else:
            govde.append(satir)
    if baslik or any(s.strip() for s in govde):
        parcalar.append((baslik, govde))
    metinler, maddeler = [], []
    for i, (b, g) in enumerate(parcalar, baslangic + 1):
        kimlik = f"K{i}"
        metinler.append(f"{kimlik}. {KULLANICI_ETIKETI}" + (f" — {b}" if b else "") + "\n" + "\n".join(g).strip())
        maddeler.append({"kimlik": kimlik, "tur": "kullanici", "baslik": b, "etiketler": [KULLANICI_ETIKETI]})
    return "\n\n".join(metinler), maddeler


def paket_maddeleri(arastirma: dict | None) -> list[dict]:
    """Araştırma sonucunun (R.arastir çıktısı) maddelerinden denetim kaydı: kimlik, başlık, alan adı, URL, tarih, etiketler,
    kaynak türü. Kimliği olmayan madde (eski paket biçimi) alınmaz."""
    sonuc = []
    for m in (arastirma or {}).get("maddeler") or []:
        if not m.get("kimlik"):
            continue
        url = m.get("url", "")
        alan = m.get("kaynak_alani") or re.sub(r"^www\.", "", (re.match(r"^[a-z]+://([^/:?#]+)", url or "", re.I) or [None, ""])[1].lower())
        sonuc.append({"kimlik": m["kimlik"], "tur": "paket", "baslik": m.get("baslik", ""), "alan": alan, "url": url,
                      "tarih": m.get("tarih", ""), "etiketler": list(m.get("etiketler") or []),
                      "kaynak_turu": m.get("kaynak_turu", "DİĞER")})
    return sonuc


def zayiflik(madde: dict) -> list[str]:
    """Zayıf dayanak nedenleri (boşsa zayıf değil). Kullanıcı kanıtı zayıf sayılmaz."""
    if madde.get("tur") == "kullanici":
        return []
    nedenler = [e for e in madde.get("etiketler") or [] if e in ZAYIF_ETIKETLER]
    if madde.get("kaynak_turu") == ZAYIF_KAYNAK_TURU:
        nedenler.append(f"KAYNAK_TÜRÜ={ZAYIF_KAYNAK_TURU}")
    return nedenler


def atiflari_oku(metin: str) -> list[str]:
    """Metindeki [K3] ve [K3, K7] biçimli atıfların kimlikleri (sırayla, tekrarlar dahil). Boşluk/virgül/noktalı virgül
    farklarına dayanıklıdır; ``` blokları ve `satır içi kod` içindekiler sayılmaz."""
    t = KOD_BLOGU.sub(" ", metin or "")
    t = SATIR_ICI_KOD.sub(" ", t)
    sonuc = []
    for m in ATIF_KALIBI.finditer(t):
        sonuc += KIMLIK.findall(m.group(1))
    return sonuc


def denetle(metin: str, maddeler: list[dict]) -> dict:
    """Tek metnin atıf denetimi: {"atif": sayı, "idler": [...], "uydurma": [kimlikler], "zayif": [{"kimlik","nedenler"}]}.
    Uydurma: kimlik pakette yok. Zayıf: kimlik var ama madde zayıf dayanaklı. Her kimlik bir kez listelenir."""
    tablo = {m["kimlik"]: m for m in maddeler}
    idler = atiflari_oku(metin)
    uydurma, zayif = [], []
    for k in dict.fromkeys(idler):
        if k not in tablo:
            uydurma.append(k)
        else:
            n = zayiflik(tablo[k])
            if n:
                zayif.append({"kimlik": k, "nedenler": n})
    return {"atif": len(idler), "idler": list(dict.fromkeys(idler)), "uydurma": uydurma, "zayif": zayif}


def kimlik_sirasi(k: str) -> int:
    return int(k[1:])


def denetim_hesapla(asamalar: dict[str, dict[str, str]], nihai: str | None, maddeler: list[dict]) -> dict:
    """asamalar: {aşama adı: {model: metin}} (tur0, tur1_duzeltme, sentez ...); nihai: nihai metin. Dönüş kayda yazılacak sözlük."""
    sonuc = {"madde_sayisi": len(maddeler), "paket_madde_sayisi": sum(1 for m in maddeler if m["tur"] == "paket"),
             "kullanici_madde_sayisi": sum(1 for m in maddeler if m["tur"] == "kullanici"), "asamalar": {}}
    for asama, metinler in asamalar.items():
        sonuc["asamalar"][asama] = {model: denetle(t, maddeler) for model, t in metinler.items() if t}
    d = denetle(nihai or "", maddeler)
    sonuc["nihai"] = d
    sonuc["nihai_kullanilan"] = sorted(d["idler"], key=kimlik_sirasi)
    tablo = {m["kimlik"] for m in maddeler}
    sonuc["nihai_kullanilan_gecerli"] = [k for k in sonuc["nihai_kullanilan"] if k in tablo]
    sonuc["kullanilmayan_sayisi"] = len(maddeler) - len(sonuc["nihai_kullanilan_gecerli"])
    sonuc["uydurma_toplam"] = sum(len(v["uydurma"]) for a in sonuc["asamalar"].values() for v in a.values()) + len(d["uydurma"])
    sonuc["zayif_toplam"] = sum(len(v["zayif"]) for a in sonuc["asamalar"].values() for v in a.values()) + len(d["zayif"])
    return sonuc


def uyari_satiri(denetim: dict | None) -> str | None:
    """Nihai metinde uydurma atıf varsa raporun en üstündeki uyarı; yoksa None. (Durum hesabı değişmez.)"""
    u = (denetim or {}).get("nihai", {}).get("uydurma")
    if not u:
        return None
    return f"Nihai metinde pakette olmayan kaynak atfı var ({', '.join(u)})."


def kaynaklar_bolumu(denetim: dict | None, maddeler: list[dict]) -> list[str]:
    """Rapora KODLA eklenen "Kaynaklar" bölümü: yalnızca nihai metinde atıf yapılan (geçerli) maddeler; atıf yapılmayanlar
    listelenmez, sayısı yazılır."""
    if not denetim or not maddeler:
        return []
    tablo = {m["kimlik"]: m for m in maddeler}
    kul = denetim["nihai_kullanilan_gecerli"]
    toplam = denetim["madde_sayisi"]
    sat = ["## Kaynaklar", ""]
    for k in kul:
        m = tablo[k]
        if m["tur"] == "kullanici":
            sat.append(f"- **{k}** — {m.get('baslik') or 'kullanıcı kanıtı'} · KULLANICI_KANITI (--kanit)")
        else:
            et = [e for e in m["etiketler"]] + [f"KAYNAK_TÜRÜ={m.get('kaynak_turu', 'DİĞER')}"]
            sat.append(f"- **{k}** — {m.get('baslik') or '(başlık yok)'} · {m.get('alan') or '?'} · {m.get('url', '')} · "
                       f"{m.get('tarih') or 'tarih yok'} · {'; '.join(et)}")
    if not kul:
        sat.append("- Nihai metinde hiçbir maddeye atıf yapılmadı.")
    sat += ["", f"Pakette {toplam} madde vardı; {len(kul)}'ine atıf yapıldı." if toplam else "Pakette madde yoktu.", ""]
    return sat


def denetim_bolumu(denetim: dict | None) -> list[str]:
    """Rapora KODLA eklenen "Atıf denetimi" bölümü (v1.0: yalnızca ÖZET, tek satır): toplam atıf, uydurma atıflar, zayıf dayanaklı
    kimlikler. Aşama × model × kimlik ayrıntısı ayrinti.md'dedir (`ayrinti_tablosu`)."""
    if not denetim:
        return []
    toplam = sum(d["atif"] for a in denetim["asamalar"].values() for d in a.values())   # Tur 0, düzeltme, sentez metinleri (nihai metin ayrıca parantezde)
    uydurma = sorted({k for a in denetim["asamalar"].values() for d in a.values() for k in d["uydurma"]}
                     | set(denetim["nihai"]["uydurma"]), key=lambda k: kimlik_sirasi(k))
    zayif = sorted({z["kimlik"] for z in denetim["nihai"]["zayif"]}, key=kimlik_sirasi)
    return ["## Atıf denetimi", "",
            f"Toplam atıf: {toplam} (nihai metinde {denetim['nihai']['atif']}); uydurma atıf: "
            f"{', '.join(uydurma) if uydurma else 'yok'}; nihai metinde zayıf dayanaklı kimlikler: "
            f"{', '.join(zayif) + f' ({len(zayif)})' if zayif else 'yok'}. "
            "Kodla üretildi; ayrıntı (aşama × model × kimlik): ayrinti.md. Uydurma atıflı iddiaya güvenme; kaynağı kendin kontrol et.", ""]


def ayrinti_detay(denetim: dict | None) -> list[str]:
    """ayrinti.md: uydurma ve zayıf dayanaklı atıfların aşama × model × kimlik dökümü."""
    if not denetim:
        return []
    uydurma, zayif = [], []
    for asama, modeller in denetim["asamalar"].items():
        for model, d in modeller.items():
            uydurma += [(f"{asama} / {model}", k) for k in d["uydurma"]]
            zayif += [(f"{asama} / {model}", z) for z in d["zayif"]]
    uydurma += [("nihai metin", k) for k in denetim["nihai"]["uydurma"]]
    zayif += [("nihai metin", z) for z in denetim["nihai"]["zayif"]]
    sat = ["", "### Atıf denetimi ayrıntısı (uydurma ve zayıf dayanaklı atıflar)", "",
           f"- Uydurma atıf (pakette olmayan kimlik): {len(uydurma)}"]
    sat += [f"  - {yer}: {k}" for yer, k in uydurma]
    sat.append(f"- Zayıf dayanaklı atıf: {len(zayif)}")
    sat += [f"  - {yer}: {z['kimlik']} ({', '.join(z['nedenler'])})" for yer, z in zayif]
    return sat


def ayrinti_tablosu(denetim: dict | None) -> list[str]:
    """ayrinti.md: model × aşama başına atıf, uydurma, zayıf sayıları ve kullanılan/kullanılmayan madde sayısı."""
    if not denetim:
        return []
    sat = ["", "## Atıf denetimi (kod; [K#] atıfları)", "",
           f"- Paket/kanıt maddesi: {denetim['madde_sayisi']} (paket {denetim['paket_madde_sayisi']}, kullanıcı kanıtı "
           f"{denetim['kullanici_madde_sayisi']}); nihai metinde atıf yapılan: {len(denetim['nihai_kullanilan_gecerli'])}, "
           f"kullanılmayan: {denetim['kullanilmayan_sayisi']}",
           f"- Toplam uydurma atıf: {denetim['uydurma_toplam']}; toplam zayıf dayanaklı atıf: {denetim['zayif_toplam']}", "",
           "| aşama | model | atıf | uydurma | zayıf dayanak |", "|---|---|---|---|---|"]
    for asama, modeller in denetim["asamalar"].items():
        for model, d in modeller.items():
            sat.append(f"| {asama} | {model} | {d['atif']} | {len(d['uydurma'])} | {len(d['zayif'])} |")
    n = denetim["nihai"]
    sat.append(f"| nihai metin | — | {n['atif']} | {len(n['uydurma'])} | {len(n['zayif'])} |")
    return sat + ayrinti_detay(denetim)
