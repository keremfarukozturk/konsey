"""
SONUÇ satırı ayrıştırma ve Tur 0 sayısal uzlaşı kuralı (konsey.py erken çıkışı + pilot/puanla.py ortak kullanır).

Satır biçimi: "SONUÇ: <sayı> <birim>" (ondalık ayırıcı nokta). Tahmin yoktur: okunamayan her durum
None döndürür ve nedenini açıklar. puanla.py bu modülden `sonuc_cikar`ı aynı arayüzle kullanır.
"""
from __future__ import annotations

import re

SONUC_SATIRI = re.compile(r"^[\s>*_`#-]*SONU[ÇC]\s*:\s*(.*)$", re.I | re.M)
SAYI = re.compile(r"^[-−]?\d+(?:\.\d+)?(?![\d,])")
VIRGULLU = re.compile(r"^[-−]?\d+,\d")
# v0.30: birimsiz sonuç yazımları ("-", "1", "boyutsuz", boş) eşdeğerdir.
BIRIMSIZ_YAZIMLAR = {"", "birimsiz", "-", "—", "–", "1", "boyutsuz", "dimensionless"}
BIRIM_ESLEME = {
    "": set(BIRIMSIZ_YAZIMLAR),
    "V": {"v", "volt"},
    "%": {"%", "yüzde", "yuzde"},
    "µH": {"uh", "µh", "μh", "mikrohenri"},
}


# --------------------------------------------------------------------------- SONUÇ çıkarma


def _birim_norm(b: str) -> str:
    return b.strip().strip("*_`.,;").strip().lower().replace("µ", "µ")


def sonuc_satir_sayisi(metin: str) -> int:
    """Metindeki `SONUÇ:` satırı sayısı (kayda yazılır; birden çoksa sonuncusu kullanılır)."""
    return len(SONUC_SATIRI.findall(metin or ""))


def sonuc_oku(metin: str, sonuncu: bool = True) -> tuple[float | None, str, str]:
    """(değer, birim_metni, not); değer None ise okunamadı ve not nedeni açıklar. Birim denetlenmez.

    sonuncu=True (varsayılan, v0.30): birden çok SONUÇ satırı varsa yalnızca SONUNCUSU okunur (türetme sırasında yazılan
    "SONUÇ: ..." satırları sayılmaz); satır sayısı `sonuc_satir_sayisi` ile kayda yazılır.
    sonuncu=False (eski kural): birden çok SONUÇ satırı varsa hepsi aynı değerde olmalıdır."""
    satirlar = SONUC_SATIRI.findall(metin or "")
    if not satirlar:
        return None, "", "SONUÇ satırı yok"
    if sonuncu:
        satirlar = satirlar[-1:]
    degerler, birimler = [], []
    for s in satirlar:
        s = s.strip().strip("*_`").strip()
        s = s.replace("\\(", "").replace("\\)", "").strip()
        if VIRGULLU.match(s):
            return None, "", f"virgüllü sayı: '{s[:40]}'"
        m = SAYI.match(s)
        if not m:
            return None, "", f"sayı okunamadı: '{s[:40]}'"
        degerler.append(float(m.group(0).replace("−", "-")))
        birimler.append(s[m.end():].strip())
    if max(degerler) != min(degerler):
        return None, "", f"birden çok SONUÇ satırı farklı değerde: {degerler}"
    return degerler[-1], birimler[-1], ""


def sonuc_cikar(metin: str, beklenen_birim: str) -> tuple[float | None, str, str]:
    """(değer, birim_metni, not) döndürür; değer None ise 'elle' ve not nedeni açıklar."""
    deger, birim, neden = sonuc_oku(metin)
    if deger is None:
        return None, birim, neden
    kabul = BIRIM_ESLEME.get(beklenen_birim, {beklenen_birim.lower()})
    if birim and _birim_norm(birim) not in kabul:
        return None, birim, f"birim beklenenden ('{beklenen_birim}') farklı: '{birim[:30]}'"
    return deger, birim, ""


# --------------------------------------------------------------------------- Tur 0 sayısal uzlaşı (erken çıkış)

BIRIMSIZ = BIRIMSIZ_YAZIMLAR  # erken çıkışta (ve puanlamada) birbirine eşdeğer sayılan "birim yok" yazımları


def birim_anahtari(birim: str) -> str:
    """Erken çıkış için birim karşılaştırma anahtarı: büyük/küçük harf KORUNUR ("V" ile "mV", "MV" farklı);
    yalnızca süs karakterleri atılır, µ (U+00B5) ve μ (U+03BC) aynı sayılır, boş/"birimsiz"/"-" tek anahtar olur."""
    b = birim.strip().strip("*_`.,;").strip().replace("\u03bc", "\u00b5")
    return "" if b.lower() in BIRIMSIZ else b


def goreli_fark(a: float, b: float) -> float:
    """|a-b| / max(|a|,|b|); iki değer de sıfırsa 0."""
    if a == b:
        return 0.0
    return abs(a - b) / max(abs(a), abs(b))


def tur0_uzlasi(tur0: dict[str, dict], tolerans: float = 0.01) -> dict:
    """Tur 0 erken çıkış kuralı. tur0: {koltuk: {"durum": "ok"|..., "metin": str}}.

    Koşullar (hepsi sağlanmalı): a) her çağrının durumu ok; b) her cevapta son SONUÇ satırı okunabiliyor;
    c) birimler (eşdeğerlik: boş/birimsiz/-/1/boyutsuz) aynı; d) her değer çifti arasındaki göreli fark <= tolerans.
    Tahmin yok: koşul sağlanmazsa uzlasi=False. Dönen sözlük kayit.json'a yazılabilir (JSON uyumlu)."""
    adlar = list(tur0)
    kos: dict[str, dict] = {}
    kotu = [ad for ad in adlar if tur0[ad].get("durum") != "ok"]
    kos["a_durum_ok"] = {"saglandi": not kotu and len(adlar) == 3,
                         "ayrinti": ("üç çağrı ok" if not kotu and len(adlar) == 3 else
                                     f"ok olmayan çağrı: {', '.join(kotu)}" if kotu else f"koltuk sayısı {len(adlar)} (3 gerekli)")}
    degerler: dict[str, float] = {}
    birimler: dict[str, str] = {}
    okunmayan = {}
    satir_sayilari = {ad: sonuc_satir_sayisi(tur0[ad].get("metin", "")) for ad in adlar if tur0[ad].get("durum") == "ok"}
    for ad in adlar:
        if tur0[ad].get("durum") != "ok":
            okunmayan[ad] = "çağrı başarısız"
            continue
        d, b, neden = sonuc_oku(tur0[ad].get("metin", ""), sonuncu=True)
        if d is None:
            okunmayan[ad] = neden
        else:
            degerler[ad], birimler[ad] = d, b
    kos["b_sonuc_okunur"] = {"saglandi": not okunmayan and len(degerler) == len(adlar) and bool(adlar),
                             "ayrinti": "üç cevapta SONUÇ satırı okundu" if not okunmayan else
                             "; ".join(f"{ad}: {n}" for ad, n in okunmayan.items())}
    if kos["b_sonuc_okunur"]["saglandi"]:
        anahtarlar = {ad: birim_anahtari(b) for ad, b in birimler.items()}
        ayni = len(set(anahtarlar.values())) == 1
        kos["c_birim_ayni"] = {"saglandi": ayni, "ayrinti": "birimler aynı" if ayni else
                               "birimler farklı: " + ", ".join(f"{ad}='{b}'" for ad, b in birimler.items())}
        fark = max((goreli_fark(degerler[x], degerler[y]) for i, x in enumerate(adlar) for y in adlar[i + 1:]),
                   default=0.0)
        kos["d_tolerans_icinde"] = {"saglandi": fark <= tolerans, "en_buyuk_goreli_fark": fark,
                                    "ayrinti": f"en büyük göreli fark {fark:.4g} (tolerans {tolerans:g})"}
    else:
        kos["c_birim_ayni"] = {"saglandi": False, "ayrinti": "değerlendirilmedi (b sağlanmadı)"}
        kos["d_tolerans_icinde"] = {"saglandi": False, "ayrinti": "değerlendirilmedi (b sağlanmadı)"}
    uzlasi = all(k["saglandi"] for k in kos.values())
    birim_gosterim = ""
    if uzlasi:
        ilk = birimler[adlar[0]].strip().strip("*_`.,;").strip()
        birim_gosterim = "birimsiz" if birim_anahtari(ilk) == "" else ilk
    return {"uzlasi": uzlasi, "tolerans": tolerans, "kosullar": kos,
            "saglanmayan": [k for k, v in kos.items() if not v["saglandi"]],
            "degerler": degerler, "sonuc_satir_sayisi": satir_sayilari,
            "ortanca": sorted(degerler.values())[1] if uzlasi else None,
            "birim": birim_gosterim if uzlasi else None}
