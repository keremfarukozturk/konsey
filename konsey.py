#!/usr/bin/env python3
"""
Konsey: bir soruyu Claude, GPT ve Gemini'ye sorar; cevapları kimliksiz olarak birbirlerine
değerlendirtir, ortak bir metin çıkarır ve bu metni üç modele ayrı ayrı onaylatır.
Oyları program sayar. Protokol: PROJE.md Bölüm 7.

Kullanım:
    python konsey.py "sorum"
    python konsey.py -f soru.txt --kanit kanit.txt
    python konsey.py --duman          # her modele tek küçük soru; kurulum kontrolü

Sürüm 0.1 notları (PROJE.md ile uyumlu geçici kararlar):
- Tur 0 erken çıkışı yalnızca üç Tur 0 cevabının SONUÇ satırları uyuşuyorsa olur (karar 34).
- Karar 50 (v0.21, GEÇİCİ): Tur 0'dan sonra en fazla --tur (1-3, varsayılan 2) eleştiri-düzeltme turu; her model diğer
  modellerin cevaplarını eleştirir (kendi cevabını görmez), sonra kendi cevabını düzeltir; kritik madde kalmadıysa
  kodla durulur (v0.22, karar 55; önemli maddeler durmayı engellemez). Sentez üç son cevabı birleştirir (kelime sınırı yok); onayda her model kendi son cevabını da görür.
- Rapor: ekranda ve rapor.md'de %80 cevap / %20 not; geri kalan her şey ayrinti.md'de (--ayrinti ekrana da basar).
- Modellerin web erişimi ve araçları kapalı; kanıt paketi verilmezse olgusal iddialar
  "doğrulanmamış ortak kanaat" sayılır.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import adaptor as A
import arastirma as R
import atif as AT
import sayisal

SURUM = "0.1"
BURASI = Path(__file__).resolve().parent
GORUNEN_AD = {"claude": "Claude", "codex": "GPT", "gemini": "Gemini"}
ETIKETLER = ["A", "B", "C"]

DURUM_ACIKLAMA = {
    "OYBIRLIGI": "Üç model de aynı ortak metni kabul etti.",
    "COGUNLUK": "Üç model katıldı; en az ikisi kabul etti. Karşı görüş aşağıda.",
    "IKIDE_IKI_BIR_EKSIK": "Bir model katılamadı; katılan iki model kabul etti. Üçlü uzlaşı ilan edilmez.",
    "UZLASI_YOK": "Ortak metin yeterli onayı alamadı.",
    "YETERSIZ_KATILIM": "İkiden az model katılabildi; konsey karar veremedi.",
    "TUR0_UZLASI": "Üç modelin Tur 0 SONUÇ satırları birim ve tolerans bakımından uyuştu; Tur 1, sentez ve onay atlandı. "
                   "Ortak metin ve oylama yoktur; bu bir oybirliği değildir.",
}
ONAYLI_DURUMLAR = {"OYBIRLIGI", "COGUNLUK", "IKIDE_IKI_BIR_EKSIK"}
VARSAYILAN_TOLERANS = 0.01  # Tur 0 erken çıkışı: değer çiftleri arası göreli fark sınırı

ORTAK_KURALLAR = """Kurallar:
- Sorunun dilinde cevap ver.
- Emin olmadığın şeyi kesin bilgi gibi yazma; olgu, çıkarım ve tahmini ayır.
- Kaynak, rakam veya alıntı uydurma.
- Bu oturumda web erişimin ve araçların yok. Olgusal iddiaları yalnızca bilgine ve (varsa) kanıt paketine dayandırabilirsin."""

# v0.24 (karar 63): sentez ve sentez düzeltmesi genelleme yapmaz; kapsamı belirtir.
GENELLEME_KURALI = ("Genelleme yapma; her teknik iddianın geçerli olduğu koşulu ve kapsamı belirt. Bir cevaptan "
                    "aldığın iddiayı, cevaptakinden daha kesin hale getirme.")
# v0.24 (karar 63): onaydaki itirazların önem tanımları eleştiri turlarındakiyle aynıdır; aşırı genelleme ve kapsam
# hatası gerçek doğruluk hatası sayılır.
ONEM_TANIMI = ("Önem: kritik = sonucu ya da ana önerileri yanlış kılar; önemli = metni belirgin biçimde zayıflatır, "
               "önemli bir şeyi yanlış ya da eksik bırakır; bir kararı ya da tasarımı yanıltabilecek aşırı genelleme "
               "ve kapsam hatası da önemlidir; küçük = ifade ya da ayrıntı sorunu.")
ONEMLER = ("kritik", "önemli", "küçük")
GECERLI_ONEMLER = ("kritik", "önemli")
FARK_SINIRI = 20000

# v0.23 (karar 59): her prompt "Bugünün tarihi: YYYY-MM-DD" satırı taşır; tarih çalıştırma anında koddan alınır.
# Testler hash kararlılığı için TARIH_SABIT'i sabit bir değere çevirir.
TARIH_SABIT: str | None = None


def bugun_tarihi() -> str:
    return TARIH_SABIT or dt.date.today().isoformat()


def tarih_satiri() -> str:
    return f"Bugünün tarihi: {bugun_tarihi()}"


# Yalnızca Tur 0 prompt'unun kurallar bölümüne eklenir (Tur 1, sentez ve onay prompt'ları değişmez; karar 34).
TUR0_SAYISAL_KURAL = ("- Sorunun cevabı tek bir sayısal değerse, cevabının son satırını tam olarak şu biçimde yaz "
                      "(ondalık ayırıcı olarak nokta kullan): SONUÇ: <sayı> <birim>. Cevap tek bir sayı değilse "
                      "(açıklama, karşılaştırma, tasarım kararı ya da birden fazla değer) bu satırı yazma.")


# --------------------------------------------------------------------------- yardımcılar


def son_json_nesnesi(metin: str, anahtar: str | None = None) -> dict | None:
    """Metindeki JSON nesnelerinden, istenen anahtarı içeren ve en sonda biteni döndürür.
    İç içe nesnelerde dıştakini seçer; ```json çitleri ve öncesindeki/sonrasındaki metin sorun olmaz."""
    if not metin:
        return None
    coz = json.JSONDecoder()
    adaylar = []
    for i, ch in enumerate(metin):
        if ch != "{":
            continue
        try:
            nesne, son = coz.raw_decode(metin, i)
        except json.JSONDecodeError:
            continue
        if isinstance(nesne, dict) and (anahtar is None or anahtar in nesne):
            adaylar.append((son, -i, nesne))
    if not adaylar:
        return None
    adaylar.sort(key=lambda x: (x[0], x[1]))
    return adaylar[-1][2]


def kelime_sayisi(metin: str) -> int:
    return len((metin or "").split())



# --------------------------------------------------------------------------- v0.21: eleştiri-düzeltme ayrıştırıcıları (karar 50)

TUR_MIN, TUR_MAKS, VARSAYILAN_TUR = 1, 3, 1   # karar 69 (v0.30): varsayılan 1 tur
BAGLAM_MAKS_BAYT = 100_000
ONEM_ADLARI = ("kritik", "onemli", "kucuk")
ONERI = "oneri"  # v0.22: İYİLEŞTİRME ÖNERİLERİ maddeleri önem etiketi taşımaz (hata değil, öneri)
ELESTIRI_BOLUM_KALIBI = re.compile(r"^[#*\s]*===\s*CEVAP\s+([A-Z])\s+HAKKINDA\s*===[*\s]*$", re.M)
MADDE_KALIBI = re.compile(r"^(\s*(?:[-*•]\s*)?)\[(\d+)\](\s*\([^)\n]*\))?(.*)$")
# v0.22: başlıktan sonra yalnızca başlığın kendi KAPANIŞ işaretleri ve boşluk tüketilir. Önceki kalıp ("[*\s]*") cevap
# gövdesinin ilk "**" açılışını da yutuyordu (20 Kasım 2026 kaydı: "CEVAP:**", "...2030–2040.**").
GUNCEL_CEVAP_KALIBI = re.compile(r"^(?P<on>[#*\s]*)GÜNCEL\s+CEVAP(?P<ic>[*\s]*):", re.M | re.I)
# Gövdenin başında Tur 0 biçiminden kalan "CEVAP:" etiketi (yalnızca etiketin kendi kalın işaretleriyle birlikte).
CEVAP_ETIKETI_KALIBI = re.compile(r"^[#\s]*(?:\*\*CEVAP:\*\*|\*\*CEVAP\*\*:|CEVAP:)[ \t]*")
DEGISIKLIK_KAYDI_KALIBI = re.compile(r"^[#*\s]*DEĞİŞİKLİK\s+KAYDI[*\s]*:", re.M | re.I)
# v0.27: kalın/eğik/kod işaretli kimlik ("**E1-3** KABUL", "`E1-3` KABUL"), numaralı liste ("1. E1-3 KABUL") ve tire çeşitleri
# ("E1-3 – RED") da okunur; kararı yazılmış hiçbir madde sessizce "kararı eksik" sayılmaz.
KARAR_SATIRI_KALIBI = re.compile(
    r"^[\s\-*•\[`]*(?:\d+[.)]\s*)?[\s*_`\[]*(E\d+-\d+)[\]\s:.)\-–—*_`]*\s*"
    r"(K[Iıİi]SMEN\s+KABUL|KABUL|RED|RET|[ÇçCc][ÖöOo][Zz][ÜüUu][Ll][Ee][Mm][Ee][Dd][İIıi])\b", re.I)
# v0.29b (madde 4): "DAYANAK: <...>" alanı; satırdaki diğer alanlardan önce çıkarılır, DAYANAK değişen/kabul edilmeyen'den önce
# ya da sonra yazılmış olabilir. Boş ya da yer tutucu dayanak "dayanaksız" sayılır.
DAYANAK_KALIBI = re.compile(
    r"(?<![\wçğıöşüÇĞİÖŞÜ])DAYANAK\s*:\s*(?P<d>.*?)\s*(?=[;.]?\s*(?:de[ğĞ][iİıI][şŞ]en|kabul edilmeyen)\s*:|$)",
    re.I | re.S)
DAYANAK_BOS_DEGERLERI = ("", "-", "yok", "bos", "n/a", "—", "–", "belirtilmedi")
ELESTIRI_ALT_BASLIKLARI = ("HATALAR", "EKSİK NOKTALAR", "KANITSIZ İDDİALAR", "İYİLEŞTİRME ÖNERİLERİ")
ASIRI_GENELLEME_BASLIGI = "AŞIRI GENELLEME / KAPSAM HATASI"   # v0.29b: yeni kategori (yalnızca v029 promptunda istenir)
ASIRI_ALT = "asiri genelleme / kapsam hatasi"
ALT_BASLIK_KALIBI = re.compile(
    r"^[#*\s]*(HATALAR|EKSİK NOKTALAR|KANITSIZ İDDİALAR|AŞIRI GENELLEME\s*/\s*KAPSAM HATASI|İYİLEŞTİRME ÖNERİLERİ)"
    r"[*\s]*:?[*\s]*$", re.I)
# v0.29: yeni kurallar VARSAYILAN olarak açıktır (Konsey, p_elestiri, p_duzeltme ve
# tuzak aracı); v0.28 davranışı ve promptları yalnızca açıkça istenirse (v029={} / None) çalışır.
#   filtre : eleştiri promptu (boş liste geçerli, AŞIRI GENELLEME kategorisi) ve düzeltmeye
#            gidecek maddelerin süzülmesi (HATALAR, EKSİK NOKTALAR, KANITSIZ İDDİALAR, AŞIRI GENELLEME: kritik ve önemli
#            gider; v0.30a karar 70: EKSİK için "sonucu değiştirir" koşulu kalktı; "öneri" ve "küçük" gitmez); maddesi olmayan model düzeltmeye girmez.
#   dayanak: düzeltme kararlarına DAYANAK + ÇÖZÜLEMEDİ, doğrulama cümlesi; ÇÖZÜLEMEDİ maddeleri sentezde BELİRSİZLİKLER'e.
#   gecerlilik (v0.30b, karar 71): Tur 0 promptunda GEÇERLİLİK SINIRLARI alanı; sentez promptunda "koşulunu yaz" kuralı;
#            ilk oylamada "Kapsam kontrolü" maddesi.
#   atif (v0.31, karar 74): kanıt paketi / --kanit varken maddelere K# kimliği ve [K#] atıf kuralı (Tur 0, düzeltme, sentez,
#         ilk oylamada atıf kontrolü); kanıt yokken promptlar değişmez.
#   okuyucu (v1.0): sentez ve sentez düzeltmesi promptlarına "okuyucu kuralı" (konseyin iç işleyişinden söz etme, paketi
#           görmeyen okuyucu için "kaynaklarda" de, kaynağa yalnızca [K#] ile atıf yap, görüş ayrılıkları yalnızca KALAN ANLAŞMAZLIKLAR'da).
V029_OZELLIKLERI = {"filtre": True, "dayanak": True, "gecerlilik": True, "atif": True, "okuyucu": True}

SENTEZ_BASLIKLARI = ("ÖZET", "CEVAP", "KALAN ANLAŞMAZLIKLAR", "BELİRSİZLİKLER")
ZORUNLU_SENTEZ_BASLIKLARI = ("ÖZET", "CEVAP", "BELİRSİZLİKLER")
LATEX_KALIBI = re.compile(r"\$|\\\(|\\\[|\\(frac|cdot|text|approx|times|left|right|mathrm|sqrt)\b|_\{|\^\{")
_ASCII = str.maketrans("öüçışğÖÜÇİŞĞ", "oucisgOUCISG")


def _ascii(s: str) -> str:
    return (s or "").translate(_ASCII).lower()


def _onem_coz(etiket: str) -> str:
    """'kritik'/'önemli'/'küçük' (ASCII'siz de olur) -> kritik|onemli|kucuk; tanınmayan -> belirsiz."""
    e = _ascii(etiket).strip()
    return {"kritik": "kritik", "onemli": "onemli", "kucuk": "kucuk"}.get(e, "belirsiz")


def _alt_baslik(satir: str) -> str | None:
    m = ALT_BASLIK_KALIBI.match(satir)
    return re.sub(r"\s*/\s*", " / ", _ascii(m.group(1))) if m else None


def _madde_eslesmesi(satir: str, alt: str | None):
    """Satır bir eleştiri maddesiyse eşleşmeyi döndürür. Parantezli etiket yoksa yalnızca İYİLEŞTİRME ÖNERİLERİ altında
    madde sayılır (öneri satırı etiketsiz yazılmış olabilir)."""
    m = MADDE_KALIBI.match(satir)
    if not m:
        return None
    if not m.group(3) and alt != _ascii("İYİLEŞTİRME ÖNERİLERİ"):
        return None
    return m


def madde_satirlari(metin: str) -> list[dict]:
    """Metindeki '- [n] (önem: x; güven: y) ...' satırlarını okur. Önem etiketi okunamayan madde 'belirsiz' sayılır.
    v0.22: İYİLEŞTİRME ÖNERİLERİ altındaki madde (ya da '(öneri)' etiketli madde) önem taşımaz: onem == 'oneri'.
    Bölüm işareti ('=== CEVAP X HAKKINDA ===') alt başlığı sıfırlar."""
    maddeler = []
    alt = None
    for satir in (metin or "").splitlines():
        if ELESTIRI_BOLUM_KALIBI.match(satir):
            alt = None
            continue
        ab = _alt_baslik(satir)
        if ab:
            alt = ab
            continue
        m = _madde_eslesmesi(satir, alt)
        if not m:
            continue
        etiketler = m.group(3) or ""
        om = re.search(r"önem\s*:\s*([^;)\s]+)", etiketler, re.I) or re.search(r"onem\s*:\s*([^;)\s]+)", etiketler, re.I)
        gm = re.search(r"güven\s*:\s*([^;)\s]+)", etiketler, re.I) or re.search(r"guven\s*:\s*([^;)\s]+)", etiketler, re.I)
        oneri_alti = alt == _ascii("İYİLEŞTİRME ÖNERİLERİ")
        oneri_etiketi = bool(re.search(r"\(\s*[öo]neri\b", etiketler, re.I)) and not om
        if oneri_alti or oneri_etiketi:
            onem = ONERI
        else:
            onem = _onem_coz(om.group(1)) if om else "belirsiz"
        maddeler.append({"no": int(m.group(2)), "onem": onem, "etiketli_oneri": bool(oneri_alti and om),
                         "alt_baslik": alt, "guven": _ascii(gm.group(1)) if gm else "", "metin": m.group(4).strip(),
                         "satir": satir})
    return maddeler


def _sayilar_oku(j, etiketler: list[str]) -> dict | None:
    if not isinstance(j, dict):
        return None
    sonuc = {}
    for e in etiketler:
        d = j.get(e)
        if not isinstance(d, dict):
            return None
        sayim = {}
        for k in ONEM_ADLARI:
            v = d.get(k)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or v < 0:
                return None
            sayim[k] = int(v)
        sonuc[e] = sayim
    return sonuc


def elestiri_coz(metin: str, etiketler: list[str]) -> dict:
    """Eleştiri çıktısını çözer. etiketler: okuyucunun gördüğü cevap etiketleri (1 ya da 2).
    Döndürür: bolum_ok (her etiket için bölüm işareti okundu mu), bolumler, maddeler (bölüm başına), sayilar
    (JSON; okunamazsa None), daha_iyi (yalnızca 2 cevapta ve geçerliyse), agir_madde_metinde (bütün metinde
    kritik/önemli/belirsiz madde sayısı), tutarsiz (JSON 0 kritik+önemli diyor ama metinde var)."""
    metin = metin or ""
    j = son_json_nesnesi(metin, etiketler[0])
    sayilar = _sayilar_oku(j, etiketler)
    daha_iyi = None
    if sayilar is not None and len(etiketler) == 2:
        d = str(j.get("daha_iyi", "")).strip().upper()
        daha_iyi = d if d in etiketler else None
    json_basi = [m.start() for m in re.finditer(r'\{\s*"%s"\s*:' % re.escape(etiketler[0]), metin)]
    kesim = json_basi[-1] if json_basi else len(metin)
    isaretler = [(m.start(), m.end(), m.group(1)) for m in ELESTIRI_BOLUM_KALIBI.finditer(metin)]
    bolumler: dict[str, str] = {}
    for i, (bas, son, etiket) in enumerate(isaretler):
        if etiket in bolumler or etiket not in etiketler:
            continue
        bitis = isaretler[i + 1][0] if i + 1 < len(isaretler) else len(metin)
        if son < kesim <= bitis:
            bitis = kesim
        govde = re.sub(r"\n[ \t]*```(?:json)?[ \t]*\s*$", "", metin[son:bitis].rstrip()).strip()
        bolumler[etiket] = govde
    bolum_ok = all(e in bolumler for e in etiketler)
    maddeler = {e: madde_satirlari(bolumler[e]) for e in bolumler}
    tum = madde_satirlari(metin)
    agir_metinde = sum(1 for m in tum if m["onem"] not in ("kucuk", ONERI))
    # v0.22 (karar 55): erken durma yalnızca kritik maddeye bakar. Önemi okunamayan (belirsiz) madde kritik olabilir:
    # temkinli sayılır, JSON 0 kritik derken metinde kritik/belirsiz varsa eleştiri tutarsızdır.
    kritik_metinde = sum(1 for m in tum if m["onem"] in ("kritik", "belirsiz"))
    json_kritik = sum(s["kritik"] for s in sayilar.values()) if sayilar else None
    return {"bolum_ok": bolum_ok, "bolumler": bolumler, "maddeler": maddeler, "sayilar": sayilar,
            "daha_iyi": daha_iyi, "agir_madde_metinde": agir_metinde, "kritik_madde_metinde": kritik_metinde,
            "tutarsiz": bool(sayilar is not None and json_kritik == 0 and kritik_metinde > 0), "ham": metin}


def erken_durma_karari(cozumler: dict[str, dict]) -> tuple[bool, str]:
    """Bir turun eleştirilerinden (v0.22, karar 55 [GEÇİCİ]): hiçbir cevap için KRİTİK madde bildirilmediyse (True, neden);
    önemli maddeler artık durmayı engellemez. Başarısız çağrı karara girmez; başarılı ama JSON'u okunamayan ya da
    JSON/metin tutarsız (JSON 0 kritik, metinde kritik ya da önemi okunamayan madde) eleştiri durmayı engeller."""
    if not cozumler:
        return False, "okunabilir eleştiri yok"
    kritik = onemli = 0
    for ad, c in cozumler.items():
        if c["sayilar"] is None:
            return False, f"{GORUNEN_AD[ad]} eleştirisinin JSON'u okunamadı; erken durma uygulanmadı"
        if c["tutarsiz"]:
            return False, (f"{GORUNEN_AD[ad]} eleştirisinde JSON ile madde satırları tutarsız; erken durma uygulanmadı")
        kritik += sum(s["kritik"] for s in c["sayilar"].values())
        onemli += sum(s["onemli"] for s in c["sayilar"].values())
    ozet = f"{kritik} kritik, {onemli} önemli madde bildirildi"
    if kritik:
        return False, ozet
    return True, ozet + "; kritik madde yok"


def madde_yok(c: dict, etiket: str) -> bool:
    """Bu eleştiride etiketlenen cevap için hiç madde (küçük dahil) yok mu? Emin değilsek False (düzeltme çalışır)."""
    if not c["bolum_ok"] or c["sayilar"] is None or etiket not in c["sayilar"]:
        return False
    return sum(c["sayilar"][etiket].values()) == 0 and not c["maddeler"].get(etiket)


SONRAKI_TUR_ALT_BASLIKLARI = ("hatalar", "kanitsiz iddialar")  # v0.23 (karar 60): 2. ve sonraki turlarda gönderilenler


def elestiri_metni_hazirla_ayrintili(k: int, c: dict, etiket: str, yalniz_hata: bool = False
                                     ) -> tuple[str, list[str] | None, list[dict]]:
    """Düzeltme prompt'una girecek eleştiri metni, madde kimlikleri ve GÖNDERİLMEYEN maddeler. Bölüm okunabiliyorsa
    yalnızca o cevabın bölümü; maddeler modelin yazdığı numaradan bağımsız olarak kodun kendi sırasıyla [E<k>-<sıra>]
    kimliği alır (v0.22). Okunamıyorsa eleştirinin tamamı, kimlik listesi None ve gönderilmeyen boş.
    v0.23 (karar 60 [GEÇİCİ]): yalniz_hata=True (2. ve sonraki turlar) iken yalnızca HATALAR ve KANITSIZ İDDİALAR
    altındaki maddeler (ve o alt başlıkların kendisi) gönderilir; EKSİK NOKTALAR ve İYİLEŞTİRME ÖNERİLERİ maddeleri
    gönderilmez, gonderilmeyen listesine [{alt_baslik, metin}] olarak yazılır (ayrinti.md'ye gider). Kimlikler yalnızca
    gönderilen maddelere verilir. Bölüm okunamadığı için süzülemeyen eleştiri bütün olarak gider (ham)."""
    if not c["bolum_ok"]:
        govde = c["ham"].strip()
        return govde, None, []
    kimlikler = []
    satirlar = []
    gonderilmeyen = []
    alt = None
    for satir in c["bolumler"][etiket].splitlines():
        ab = _alt_baslik(satir)
        if ab:
            alt = ab
        m = None if ab else _madde_eslesmesi(satir, alt)
        if yalniz_hata and alt is not None and alt not in SONRAKI_TUR_ALT_BASLIKLARI:
            if m:
                gonderilmeyen.append({"alt_baslik": alt, "metin": satir.strip()})
            continue
        if m:
            kimlik = f"E{k}-{len(kimlikler) + 1}"
            kimlikler.append(kimlik)
            satir = f"{m.group(1)}[{kimlik}]{m.group(3) or ''}{m.group(4)}"
        satirlar.append(satir)
    return "\n".join(satirlar).strip(), kimlikler, gonderilmeyen


SUZ_GONDERILEN_BASLIKLAR = ("hatalar", "kanitsiz iddialar", ASIRI_ALT)


def madde_v029_karari(satir_eslesmesi, alt: str | None) -> tuple[bool, str]:
    """v0.29b süzgeci: (düzeltmeye gitsin mi, gitmeme nedeni). v0.30c (karar 73): HATALAR / KANITSIZ İDDİALAR /
    AŞIRI GENELLEME (ve başlıksız madde) önem derecesinden bağımsız, küçük dahil, gider. EKSİK NOKTALAR: kritik ve önemli
    gider (önemi okunamayan 'belirsiz' temkinli olarak gider), küçük gitmez. İYİLEŞTİRME ÖNERİLERİ ve '(öneri)' etiketi gitmez
    (yalnızca kayda). v0.30a'daki 'EKSİK için sonucu değiştirir koşulu kalktı' (karar 70) aynen geçerli."""
    etiketler = satir_eslesmesi.group(3) or ""
    om = re.search(r"[öo]nem\s*:\s*([^;)\s]+)", etiketler, re.I)
    if alt == _ascii("İYİLEŞTİRME ÖNERİLERİ") or (re.search(r"\(\s*[öo]neri\b", etiketler, re.I) and not om):
        return False, "öneri"
    onem = _onem_coz(om.group(1)) if om else "belirsiz"
    if onem == "kucuk" and alt == "eksik noktalar":
        return False, "küçük (eksik nokta)"
    # v0.30a (karar 70): EKSİK NOKTALAR'da "kritik" ve "önemli" maddeler "sonucu değiştirir" işareti aranmadan gider.
    # v0.30c (karar 73): diğer kategorilerde küçük maddeler de gider; yalnızca EKSİK'in küçükleri ve öneriler kayda gider.
    return True, ""


def elestiri_metni_suz_v029(k: int, c: dict, etiket: str) -> tuple[str, list[str] | None, list[dict]]:
    """v0.29b: düzeltme prompt'una girecek eleştiri metni (yalnızca madde_v029_karari'nin gönderdikleri; maddesi
    kalmayan başlık yazılmaz), kimlikler ve gönderilmeyenler [{alt_baslik, metin, neden}]. Bölüm okunamıyorsa eleştirinin
    tamamı gider (kimlik None). Bir maddenin devam satırları maddeyle birlikte gider ya da düşer."""
    if not c["bolum_ok"]:
        return c["ham"].strip(), None, []
    kimlikler: list[str] = []
    cikti: list[str] = []
    gonderilmeyen: list[dict] = []
    alt = None
    baslik_satiri = None
    baslik_yazildi = False
    son_gider = None   # son maddenin devam satırları için karar (None: devam satırı düşer)
    for satir in c["bolumler"][etiket].splitlines():
        ab = _alt_baslik(satir)
        if ab:
            alt, baslik_satiri, baslik_yazildi, son_gider = ab, satir, False, None
            continue
        m = _madde_eslesmesi(satir, alt)
        if m:
            gider, neden = madde_v029_karari(m, alt)
            son_gider = gider
            if not gider:
                gonderilmeyen.append({"alt_baslik": alt or "basliksiz", "metin": satir.strip(), "neden": neden})
                continue
            if baslik_satiri is not None and not baslik_yazildi:
                cikti.append(baslik_satiri)
                baslik_yazildi = True
            kimlik = f"E{k}-{len(kimlikler) + 1}"
            kimlikler.append(kimlik)
            cikti.append(f"{m.group(1)}[{kimlik}]{m.group(3) or ''}{m.group(4)}")
        elif son_gider and satir.strip():
            cikti.append(satir)
    return "\n".join(cikti).strip(), kimlikler, gonderilmeyen


def elestiri_metni_hazirla(k: int, c: dict, etiket: str) -> tuple[str, list[str] | None]:
    """Eski imza (1. tur davranışı: bütün maddeler). Bkz. elestiri_metni_hazirla_ayrintili."""
    metin, kimlikler, _ = elestiri_metni_hazirla_ayrintili(k, c, etiket, False)
    return metin, kimlikler


def cevap_etiketini_sok(cevap: str) -> str:
    """Cevap gövdesinin başındaki, Tur 0 biçiminden kalan 'CEVAP:' etiketini (kendi kalın işaretleriyle) atar."""
    return CEVAP_ETIKETI_KALIBI.sub("", cevap, count=1).lstrip()


GEREKCE_KALIBI = re.compile(r"[çÇ][üÜ]nk[üÜ][\s,:]*(?P<g>.*?)\s*[;.]?\s*de[ğĞ][iİıI][şŞ]en\s*:\s*(?P<d>.*)$", re.I | re.S)
DEGISEN_KALIBI = re.compile(r"de[ğĞ][iİıI][şŞ]en\s*:\s*(?P<d>.*)$", re.I | re.S)
MIN_GEREKCE_HARF = 8  # bundan kısa "gerekçe" ("x", "doğru") gerekçe sayılmaz


def karar_kayitlarini_oku(kayit_metni: str, kimlik_kalibi: re.Pattern | None = None) -> dict[str, dict]:
    """DEĞİŞİKLİK KAYDI satırlarını okur (ilk satır geçerli). Döndürür {kimlik: {karar: KABUL|KISMEN|RED, gerekce, degisen,
    metin}}. v0.23 (karar 61): KABUL/KISMEN KABUL satırı "doğru, çünkü <...>; değişen: <...>" biçimindeyse gerekce ve
    degisen ayrı okunur; eski biçim ("KABUL: <ne değişti>") da okunur (gerekce None, degisen = satırın tamamı).
    RED satırında gerekce = yazılan neden."""
    kalip = kimlik_kalibi or KARAR_SATIRI_KALIBI
    kayitlar: dict[str, dict] = {}
    for satir in (kayit_metni or "").splitlines():
        satir = satir.strip()
        mm = kalip.match(satir)
        if not mm or mm.group(1).upper() in kayitlar:
            continue
        tur = re.sub(r"\s+", " ", mm.group(2).upper())
        cozulemedi = _ascii(tur).startswith("cozul")
        karar = ("COZULEMEDI" if cozulemedi else "KABUL" if tur == "KABUL" else "RED" if tur in ("RED", "RET")
                 else "KISMEN")
        kalan = satir[mm.end():].lstrip(" \t:.-–—*").strip()
        gerekce = degisen = None
        dayanak = None
        dm = DAYANAK_KALIBI.search(kalan)
        if dm:
            dayanak = dm.group("d").strip()
            kalan = (kalan[:dm.start()].rstrip(" ;.") + ("; " + kalan[dm.end():].lstrip(" ;.")
                                                       if kalan[dm.end():].strip(" ;.") else "")).strip()
        if karar in ("RED", "COZULEMEDI"):
            gerekce = kalan or None
        else:
            g = GEREKCE_KALIBI.search(kalan)
            if g:
                gerekce, degisen = g.group("g").strip() or None, g.group("d").strip() or None
            else:
                d = DEGISEN_KALIBI.search(kalan)
                degisen = (d.group("d").strip() if d else kalan) or None
        kayitlar[mm.group(1).upper()] = {"karar": karar, "gerekce": gerekce, "degisen": degisen, "metin": kalan,
                                         "dayanak": dayanak}
    return kayitlar


def dayanak_bos_mu(dayanak: str | None) -> bool:
    return _ascii(dayanak or "").strip(" .") in DAYANAK_BOS_DEGERLERI


def dayanak_sayimi(kayitlar: dict[str, dict], madde_kimlikleri: list[str] | None = None) -> dict:
    """v0.29b (madde 4): KABUL/KISMEN KABUL satırlarından kaçının dayanağı boş (kod işaretler) ve kaç madde ÇÖZÜLEMEDİ.
    Kimlikler biliniyorsa yalnızca onlar sayılır. Ölçümdür; düzeltmeyi engellemez."""
    secili = {i: d for i, d in kayitlar.items() if madde_kimlikleri is None or i in madde_kimlikleri}
    kabuller = {i: d for i, d in secili.items() if d["karar"] in ("KABUL", "KISMEN")}
    bos = sorted(i for i, d in kabuller.items() if dayanak_bos_mu(d.get("dayanak")))
    return {"kabul_kismen": len(kabuller), "dayanaksiz": len(bos), "dayanaksiz_kimlikler": bos,
            "cozulemedi": sum(1 for d in secili.values() if d["karar"] == "COZULEMEDI")}


def gerekce_sayimi(kayitlar: dict[str, dict], madde_kimlikleri: list[str] | None = None) -> dict:
    """KABUL ve KISMEN KABUL satırlarından kaçında eleştirinin neden doğru olduğu yazılmış ("çünkü ..."). Kimlikler
    biliniyorsa yalnızca onlar sayılır. Ölçümdür; düzeltmeyi etkilemez."""
    secili = [d for i, d in kayitlar.items() if madde_kimlikleri is None or i in madde_kimlikleri]
    kabuller = [d for d in secili if d["karar"] in ("KABUL", "KISMEN")]
    gerekceli = sum(1 for d in kabuller if d["gerekce"] and len(d["gerekce"]) >= MIN_GEREKCE_HARF)
    return {"kabul_kismen": len(kabuller), "gerekceli": gerekceli}


def duzeltme_coz(metin: str) -> dict:
    """Düzeltme çıktısı: DEĞİŞİKLİK KAYDI + GÜNCEL CEVAP. 'GÜNCEL CEVAP:' başlığı ya da gövdesi yoksa gecerli=False
    (önceki cevap geçerli kalır). kararlar: {madde kimliği: KABUL|KISMEN|RED} (ilk satır geçerli).
    v0.22: başlıktan sonra yalnızca başlığın kendi kapanış '**' işareti ve boşluk tüketilir (gövdenin açılış '**'
    işareti korunur); gövde başındaki tekrarlı 'CEVAP:' etiketi atılır."""
    metin = metin or ""
    m = GUNCEL_CEVAP_KALIBI.search(metin)
    if not m:
        return {"gecerli": False, "neden": "GÜNCEL CEVAP: başlığı yok", "cevap": None, "kararlar": {}, "kayit_metni": ""}
    bas = m.end()
    if "*" in m.group("on"):  # başlık kalın açıldıysa, aynı satırdaki hemen sonraki '**' kapanıştır
        kapanis = re.match(r"[ \t]*\*+", metin[bas:])
        if kapanis:
            bas += kapanis.end()
    cevap = cevap_etiketini_sok(metin[bas:].strip())
    onceki = metin[:m.start()]
    k = DEGISIKLIK_KAYDI_KALIBI.search(onceki)
    kayit_metni = (onceki[k.end():] if k else onceki).strip()
    kayitlar = karar_kayitlarini_oku(kayit_metni)
    kararlar = {kimlik: d["karar"] for kimlik, d in kayitlar.items()}
    if len(cevap) < 3:
        return {"gecerli": False, "neden": "GÜNCEL CEVAP gövdesi boş", "cevap": None, "kararlar": kararlar,
                "kayitlar": kayitlar, "kayit_metni": kayit_metni}
    return {"gecerli": True, "neden": "", "cevap": cevap, "kararlar": kararlar, "kayitlar": kayitlar,
            "kayit_metni": kayit_metni}


SENTEZ_DUZELTME_KALIBI = re.compile(r"^(?P<on>[#*\s]*)D[ÜU]ZELT[İI]LM[İI][ŞS]\s+MET[İI]N(?P<ic>[*\s]*):", re.M | re.I)
ITIRAZ_KARAR_KALIBI = re.compile(
    r"^[\s\-*•\[`]*(?:\d+[.)]\s*)?[\s*_`\[]*(R\d+)[\]\s:.)\-–—*_`]*\s*(K[Iıİi]SMEN\s+KABUL|KABUL|RED|RET)\b", re.I)


def sentez_duzeltme_coz(metin: str) -> dict:
    """Sentez yazarının itirazlara verdiği cevap (v0.23, karar 62): İTİRAZ KAYDI (R1, R2... için KABUL/KISMEN KABUL/RED) +
    DÜZELTİLMİŞ METİN. Başlık ya da gövde yoksa gecerli=False (ilk oylamanın sonucu geçerli kalır)."""
    metin = metin or ""
    m = SENTEZ_DUZELTME_KALIBI.search(metin)
    if not m:
        return {"gecerli": False, "neden": "DÜZELTİLMİŞ METİN: başlığı yok", "metin": None, "kararlar": {}, "kayitlar": {}}
    bas = m.end()
    if "*" in m.group("on"):
        kapanis = re.match(r"[ \t]*\*+", metin[bas:])
        if kapanis:
            bas += kapanis.end()
    govde = metin[bas:].strip()
    kayitlar = karar_kayitlarini_oku(metin[:m.start()], ITIRAZ_KARAR_KALIBI)
    kararlar = {k: d["karar"] for k, d in kayitlar.items()}
    if len(govde) < 20:
        return {"gecerli": False, "neden": "DÜZELTİLMİŞ METİN gövdesi boş ya da çok kısa", "metin": None,
                "kararlar": kararlar, "kayitlar": kayitlar}
    return {"gecerli": True, "neden": "", "metin": govde, "kararlar": kararlar, "kayitlar": kayitlar}


def somut_itirazlar(pusulalar: dict) -> list[tuple[str, str]]:
    """RET oyu veren üyelerin RET'i geçerli kılan (kritik/önemli) somut itirazları: [(sağlayıcı, itiraz)]. Gerekçesiz,
    itirazsız ya da yalnızca küçük itirazlı RET sentez düzeltmesini tetiklemez (karar 62, 63)."""
    sonuc = []
    for ad, p in (pusulalar or {}).items():
        if p["oy"] != "RET" or not p["gecerli"]:
            continue
        ayr = p.get("itiraz_ayrintilari")
        if ayr is None:   # eski biçimli pusula: önem bilinmiyor, temkinli olarak önemli
            ayr = [{"metin": str(i), "onem": "önemli"} for i in p["itirazlar"] if str(i).strip()]
        sonuc += [(ad, a["metin"]) for a in ayr if a["onem"] in GECERLI_ONEMLER]
    return sonuc


def itiraz_onemi(pusulalar: dict, ad: str, metin: str) -> str:
    for a in ((pusulalar or {}).get(ad) or {}).get("itiraz_ayrintilari") or []:
        if a["metin"] == metin:
            return a["onem"]
    return "önemli"


def ek_not_sayisi(pusulalar: dict) -> int:
    return sum(len(p.get("ek_notlar") or []) for p in (pusulalar or {}).values())


def degisiklik_sayimi(madde_kimlikleri: list[str] | None, kararlar: dict[str, str]) -> dict:
    """Tur başına ölçüm: kaç eleştiri maddesi KABUL / KISMEN KABUL / RED / yanıtsız. Kimlikler bilinmiyorsa (eleştiri
    bölümlenemedi) yalnızca kayıttaki satırlar sayılır ve madde/yanıtsız None kalır."""
    if madde_kimlikleri is None:
        return {"kimlikli": False, "madde": None, "kabul": sum(1 for v in kararlar.values() if v == "KABUL"),
                "kismen": sum(1 for v in kararlar.values() if v == "KISMEN"),
                "red": sum(1 for v in kararlar.values() if v == "RED"), "yanitsiz": None, "taninmayan": 0}
    kabul = sum(1 for i in madde_kimlikleri if kararlar.get(i) == "KABUL")
    kismen = sum(1 for i in madde_kimlikleri if kararlar.get(i) == "KISMEN")
    red = sum(1 for i in madde_kimlikleri if kararlar.get(i) == "RED")
    return {"kimlikli": True, "madde": len(madde_kimlikleri), "kabul": kabul, "kismen": kismen, "red": red,
            "yanitsiz": len(madde_kimlikleri) - kabul - kismen - red,
            "taninmayan": sum(1 for i in kararlar if i not in madde_kimlikleri)}


def degisiklik_sayimi_v029(madde_kimlikleri: list[str] | None, kararlar: dict[str, str]) -> dict:
    """degisiklik_sayimi + ÇÖZÜLEMEDİ sayısı (yanıtsız sayılmaz; sessiz kayıp yok)."""
    s = degisiklik_sayimi(madde_kimlikleri, kararlar)
    if madde_kimlikleri is None:
        s["cozulemedi"] = sum(1 for v in kararlar.values() if v == "COZULEMEDI")
    else:
        s["cozulemedi"] = sum(1 for i in madde_kimlikleri if kararlar.get(i) == "COZULEMEDI")
        s["yanitsiz"] -= s["cozulemedi"]
    return s


MADDE_METNI_KALIBI = re.compile(r"^\s*(?:[-*•]\s*)?\[(E\d+-\d+)\]\s*(?:\([^)\n]*\))?\s*(.*)$")


def madde_metinleri_oku(metin: str) -> dict[str, str]:
    """Düzeltme prompt'una giden eleştiri metnindeki "[E1-2] (…) metin" satırlarından {kimlik: madde metni}."""
    sonuc = {}
    for satir in (metin or "").splitlines():
        m = MADDE_METNI_KALIBI.match(satir)
        if m:
            sonuc[m.group(1)] = m.group(2).strip()
    return sonuc


def belirsizlik_bolumu_dolu_mu(metin: str) -> bool:
    """Sentez metninde BELİRSİZLİKLER bölümü var ve boş ya da yalnızca "Yok" değil mi?"""
    m = re.search(r"^[#*\s]*BELİRSİZLİKLER[*\s]*:?[*\s]*(?P<g>.*?)(?=^[#*\s]*(?:ÖZET|CEVAP|KALAN ANLAŞMAZLIKLAR)[*\s]*(?::|$)|\Z)",
                  metin or "", re.M | re.S)
    if not m:
        return False
    return _ascii(m.group("g")).strip(" .\n\t*-") not in ("", "yok")


def notr_hakem_analizi(yazarlar: list[str], karsilastirmalar: list[dict]) -> dict:
    """Nötr hakem (karar 50): her çift, çiftte yer almayan okuyucunun eleştiri JSON'undaki 'daha_iyi' alanıdır.
    karsilastirmalar: [{hakem, kazanan, kaybeden}] (yalnızca okunabilenler). Yalnızca 3 cevapta ölçülür."""
    uc = len(yazarlar) == 3
    if not uc:
        return {"cevap_sayisi": len(yazarlar), "karsilastirmalar": [], "notr_hakem_galibi": None,
                "notr_hakem_durumu": "olculmedi"}
    yz = sorted(yazarlar)
    ciftler = {frozenset(c): None for c in ((yz[0], yz[1]), (yz[0], yz[2]), (yz[1], yz[2]))}
    for k in karsilastirmalar:
        c = frozenset((k["kazanan"], k["kaybeden"]))
        if c in ciftler:
            ciftler[c] = k
    galip, durum = None, "belirlenemedi"
    for y in yz:
        ikisi = [k for c, k in ciftler.items() if y in c]
        if len(ikisi) == 2 and all(k and k["kazanan"] == y for k in ikisi):
            galip, durum = y, "galip"
            break
    else:
        if all(ciftler.values()):
            durum = "net_galip_yok"
    return {"cevap_sayisi": 3,
            "karsilastirmalar": [{"cift": sorted(c), **(k or {"kazanan": None, "kaybeden": None, "hakem": None})}
                                 for c, k in sorted(ciftler.items(), key=lambda x: sorted(x[0]))],
            "notr_hakem_galibi": galip, "notr_hakem_durumu": durum}


def sentez_baslik_var_mi(metin: str, baslik: str) -> bool:
    # v0.22: "ÖZET:", "**ÖZET:**", "## ÖZET", "**ÖZET**" tanınır; başlık satırda tek başına (iki nokta olmadan) da olabilir.
    return bool(re.search(r"^[#*\s]*{}[*\s]*(?::|$)".format(re.escape(baslik)), metin or "", re.M))


def bicim_uyarilari(metin: str) -> list[str]:
    """Ortak metnin biçim kurallarına uyup uymadığı. Uyarıdır; oylamayı etkilemez (ilke 4); rapor bunları görünür kılar."""
    uyarilar = [f"Ortak metinde {b}: başlığı bulunamadı." for b in ZORUNLU_SENTEZ_BASLIKLARI
                if not sentez_baslik_var_mi(metin, b)]
    latex = len(LATEX_KALIBI.findall(metin or ""))
    if latex:
        uyarilar.append(f"Ortak metinde {latex} LaTeX işareti var; Terminal'de okunmayabilir.")
    return uyarilar



def metin_ozeti(metin: str) -> str:
    return hashlib.sha256(metin.encode("utf-8")).hexdigest()[:12]


def oy_normalize(oy) -> str:
    o = str(oy or "").strip().upper().replace("Ç", "C").replace("İ", "I")
    return {"RED": "RET", "REDDET": "RET", "KABUL EDIYORUM": "KABUL"}.get(o, o)


def onem_oku(x) -> tuple[str, bool]:
    """İtirazın önemi (kritik/önemli/küçük) ve açıkça belirtilip belirtilmediği. Belirtilmemiş ya da tanınmayan değer
    temkinli olarak 'önemli' sayılır (v0.24, karar 63): eski biçim (düz metin itiraz) davranışı değiştirmez."""
    e = _onem_coz(str(x or ""))
    return {"kritik": ("kritik", True), "onemli": ("önemli", True), "kucuk": ("küçük", True)}.get(e, ("önemli", False))


def itiraz_coz(x, ikinci_oylama: bool = False) -> dict | None:
    """Pusuladaki bir itiraz: düz metin ya da {'onem','kaynak','metin'}. Boşsa None."""
    if isinstance(x, dict):
        metin = str(x.get("metin") or x.get("itiraz") or "").strip()
        onem, belirtildi = onem_oku(x.get("onem"))
        kaynak = _ascii(str(x.get("kaynak") or "")).strip()
    else:
        metin, onem, belirtildi, kaynak = str(x or "").strip(), "önemli", False, ""
    if not metin:
        return None
    if ikinci_oylama:
        kaynak_belirtildi = kaynak in ("ilk", "yeni", "degismeyen")
        if not kaynak_belirtildi:
            kaynak = "belirtilmedi"   # temkinli: RET sebebi sayılır (biçim ihlali ayrıntıda işaretlenir)
    else:
        kaynak_belirtildi, kaynak = True, ""
    return {"metin": metin, "onem": onem, "onem_belirtildi": belirtildi, "kaynak": kaynak,
            "kaynak_belirtildi": kaynak_belirtildi}


def ret_gecerli_itirazlar(ayrintilar: list[dict], ikinci_oylama: bool = False) -> list[dict]:
    """RET'i geçerli kılan itirazlar. İlk oylamada: kritik/önemli. İkinci oylamada: kritik/önemli VE kaynağı 'ilk'
    (ilk itiraz karşılanmadı) ya da 'yeni' (düzeltme yeni sorun getirdi)."""
    return [a for a in ayrintilar if a["onem"] in GECERLI_ONEMLER
            and (not ikinci_oylama or a["kaynak"] in ("ilk", "yeni", "belirtilmedi"))]


def pusula_coz(metin: str, beklenen_ozet: str, ikinci_oylama: bool = False) -> dict:
    """Onay pusulasını çözer. Geçersiz pusula çekimser sayılır (PROJE.md 7.6, ölçüt 5).
    v0.24 (karar 63): itirazların önemi okunur; RET ancak geçerli (kritik/önemli; ikinci oylamada ayrıca kaynağı ilk/yeni)
    bir itiraz içeriyorsa RET kalır, yalnızca geçersiz itirazı olan RET kodla KABUL sayılır ve itirazlar ek not olur."""
    j = son_json_nesnesi(metin, "oy")
    if not j:
        return {"oy": "CEKIMSER", "gecerli": False, "not": "Oy pusulası (JSON) bulunamadı", "gerekce": "", "itirazlar": [],
                "itiraz_ayrintilari": [], "ek_notlar": []}
    oy = oy_normalize(j.get("oy"))
    ham = j.get("itirazlar") or []
    if not isinstance(ham, list):
        ham = [ham]
    ayrintilar = [a for a in (itiraz_coz(x, ikinci_oylama) for x in ham) if a]
    sonuc = {"oy": oy, "gecerli": True, "not": "", "gerekce": str(j.get("gerekce", "")),
             "itirazlar": [a["metin"] for a in ayrintilar], "itiraz_ayrintilari": ayrintilar, "ek_notlar": []}
    if str(j.get("metin_surumu", "")).strip() != beklenen_ozet:
        sonuc["oy"], sonuc["gecerli"] = "CEKIMSER", False
        sonuc["not"] = f"Pusuladaki metin sürümü ({j.get('metin_surumu')}) önerilen metinle uyuşmuyor"
    elif oy not in ("KABUL", "RET", "CEKIMSER"):
        sonuc["oy"], sonuc["gecerli"] = "CEKIMSER", False
        sonuc["not"] = f"Geçersiz oy değeri: {j.get('oy')}"
    elif oy == "RET" and ayrintilar:
        gecerli = ret_gecerli_itirazlar(ayrintilar, ikinci_oylama)
        sonuc["ek_notlar"] = [a for a in ayrintilar if a not in gecerli]
        if not gecerli:
            sonuc["oy"], sonuc["orijinal_oy"] = "KABUL", "RET"
            sonuc["not"] = ("RET yalnızca küçük itirazlar içerdiği için kodla KABUL sayıldı" if not ikinci_oylama else
                            "RET, ilk oylamadaki kritik/önemli bir itirazın karşılanmaması ya da düzeltmenin yeni kritik/"
                            "önemli sorun getirmesi dışında olduğu için kodla KABUL sayıldı")
    return sonuc


def sonucu_belirle(oylar: dict[str, str]) -> str:
    """Oyları sayar (PROJE.md 7.3). oylar: {sağlayıcı: KABUL|RET|CEKIMSER}, yalnızca pusula gönderebilenler."""
    katilan = len(oylar)
    kabul = sum(1 for o in oylar.values() if o == "KABUL")
    if katilan < 2:
        return "YETERSIZ_KATILIM"
    if katilan >= 3:
        if kabul == katilan:
            return "OYBIRLIGI"
        return "COGUNLUK" if kabul >= 2 else "UZLASI_YOK"
    return "IKIDE_IKI_BIR_EKSIK" if kabul == 2 else "UZLASI_YOK"


# v0.27: yalnızca --arastir açıkken (kanıt metni ArastirmaliKanit ise) her kanıt bloğunun ardına bu cümle eklenir.
# Araştırma kapalıyken prompt'lar v0.26 ile birebir aynıdır (testler/test_v027_promptlar_ayni.py).
ARASTIRMA_CUMLESI = "Etiketli maddelere dayanan iddiaları kesin olgu gibi yazma; dayanağın zayıf olduğunu belirt."


class ArastirmaliKanit(str):
    """Araştırma paketi içeren kanıt metni (sıradan str gibi davranır; yalnızca kanit_blogu'nun cümleyi eklemesini sağlar)."""


def kanit_blogu(kanit: str | None) -> str:
    if not kanit:
        return ""
    blok = f"\n\nKANIT PAKETİ (tüm konsey üyelerine aynı paket verildi):\n<<<\n{kanit}\n>>>"
    if isinstance(kanit, ArastirmaliKanit):
        blok += f"\n{ARASTIRMA_CUMLESI}"
    return blok


def eksik_ipucu(s: A.CagriSonucu) -> str:
    if s.durum == "rate_limited":
        return "kota doldu"
    if s.durum == "auth_error":
        komut = {"claude": "claude auth login", "codex": "codex (Sign in with ChatGPT)", "gemini": "agy"}[s.saglayici]
        return f"giriş sorunu; yeniden giriş: {komut}"
    if s.durum == "timeout":
        return "zaman aşımı"
    if s.hata.startswith(A.MODEL_UYUSMAZLIGI):
        return "cevap veren model istenen model değil; cevap kullanılmadı"
    if s.hata.startswith(A.ARAC_IHLALI):
        return "araç çalıştırdı (salt okunurluk ihlali); cevap kullanılmadı"
    if s.hata.startswith(A.ARAC_DENEMESI_BOS):
        return "araç denemesi nedeniyle boş cevap"
    if s.hata.startswith(A.KANCA_HATASI):
        return "salt okunur kancası hazırlanamadı; çağrı yapılmadı"
    if "model" in s.hata.lower():
        return "model adı geçersiz olabilir; modeller.json'u ve model listesini kontrol et"
    return "teknik hata"


def dogrulama_ozeti(duzeyler: list[str]) -> str:
    """Bir koltuğun başarılı çağrılarındaki doğrulama düzeylerini tek ifadeye indirir."""
    if not duzeyler:
        return "başarılı çağrı yok"
    sayim = {d: duzeyler.count(d) for d in dict.fromkeys(duzeyler)}
    if len(sayim) == 1:
        return duzeyler[0]
    return "karışık: " + ", ".join(f"{d} ×{n}" for d, n in sayim.items())


KOTA_ESKI_DAKIKA = 30  # Codex kayıt olayı bu süreden eskiyse okuma "güncel değil" sayılır


def _yerel_zaman(iso: str) -> dt.datetime | None:
    """Codex kaydındaki UTC zaman damgası ('...Z') -> yerel saatte, saat dilimsiz datetime."""
    try:
        return dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def kota_eskilik(kota: dict, simdi: dt.datetime | None = None) -> list[str]:
    """Codex kota okumasının güncel olmadığını gösteren nedenler (boşsa güncel sayılır). (1) Bir pencerenin sıfırlanma
    zamanı geçmişse değer eski pencereye aittir; (2) kayıttaki son olay KOTA_ESKI_DAKIKA'dan eskiyse, o andan sonraki
    kullanım görünmüyor olabilir."""
    simdi = simdi or dt.datetime.now()
    nedenler = []
    for anahtar, ad in (("5_saat", "5 saatlik"), ("haftalik", "haftalık")):
        k = kota.get(anahtar)
        if isinstance(k, dict) and k.get("sifirlanma"):
            try:
                if dt.datetime.strptime(k["sifirlanma"], "%Y-%m-%d %H:%M") <= simdi:
                    nedenler.append(f"{ad} pencerenin sıfırlanma zamanı ({k['sifirlanma']}) geçmiş; değer eski pencereye ait")
            except ValueError:
                pass
    olay = _yerel_zaman(kota["olay_zamani"]) if kota.get("olay_zamani") else None
    if olay is not None and (simdi - olay) > dt.timedelta(minutes=KOTA_ESKI_DAKIKA):
        nedenler.append(f"kayıttaki son olay {int((simdi - olay).total_seconds() // 60)} dakika önce")
    return nedenler


def kota_metni(kota: dict, simdi: dt.datetime | None = None) -> str:
    if not kota:
        return "okunamadı"
    parcalar = []
    for anahtar, ad in (("5_saat", "5 saatlik"), ("haftalik", "haftalık")):
        k = kota.get(anahtar)
        if k:
            parcalar.append(f"{ad} %{k['kullanilan_yuzde']:g} kullanıldı"
                            + (f" (sıfırlanma {k['sifirlanma']})" if k.get("sifirlanma") else ""))
    for anahtar, k in kota.items():  # bilinmeyen pencere uzunlukları da gösterilsin
        if isinstance(k, dict) and anahtar not in ("5_saat", "haftalik"):
            parcalar.append(f"{anahtar} %{k['kullanilan_yuzde']:g} kullanıldı")
    if kota.get("sinira_ulasildi"):
        parcalar.append(f"SINIRA ULAŞILDI: {kota['sinira_ulasildi']}")
    metin = "; ".join(parcalar) or "okunamadı"
    if kota.get("sinir_sonrasi_bos_kayit"):
        metin += (f" [son okunabilir değer; sonrasında kota sınırına çarpıldı, yeni kayıtta rate_limits boş "
                  f"({kota['sinir_sonrasi_bos_kayit']})]")
    if kota.get("olay_zamani") or kota.get("kayit_dosyasi"):
        olay = _yerel_zaman(kota["olay_zamani"]) if kota.get("olay_zamani") else None
        kaynak = f"kayıt: {kota.get('kayit_dosyasi') or '?'}, olay: " + (olay.strftime("%Y-%m-%d %H:%M:%S") if olay else "?")
        metin += f" [{kaynak}]"
        nedenler = kota_eskilik(kota, simdi)
        if nedenler:
            metin += " — GÜNCEL DEĞİL: " + "; ".join(nedenler)
    return metin


def arac_toplami(sonuclar: list[A.CagriSonucu]) -> dict:
    """Bir koltuğun bütün çağrılarındaki araç denetimini toplar (rapor ve kayit.json için)."""
    t = {"cagri": len(sonuclar), "duzeyler": {}, "bos_cevap_arac_denemesi": 0, "ihlal": 0,
         "denenen_arac": 0, "reddedilen_arac": 0, "codex_arac_cagrisi": 0, "codex_komutlar": [], "codex_web_aramasi": 0,
         "codex_bilinmeyen_olaylar": {}}
    for s in sonuclar:
        d = s.arac_denetimi or "denetlenmedi"
        t["duzeyler"][d] = t["duzeyler"].get(d, 0) + 1
        o = s.arac_ozeti or {}
        if s.hata.startswith(A.ARAC_DENEMESI_BOS):
            t["bos_cevap_arac_denemesi"] += 1
        if s.arac_denetimi == A.DENETIM_IHLAL:
            t["ihlal"] += 1
        t["denenen_arac"] += len(o.get("denenen", []))
        t["reddedilen_arac"] += int(o.get("reddedilen", 0) or 0)
        t["codex_arac_cagrisi"] += len(o.get("arac_cagrisi", []))
        t["codex_komutlar"] += o.get("komutlar", [])
        t["codex_web_aramasi"] += len(o.get("web_aramalari", []))
        for ad, n in (o.get("bilinmeyen_olaylar") or {}).items():
            t["codex_bilinmeyen_olaylar"][ad] = t["codex_bilinmeyen_olaylar"].get(ad, 0) + n
    return t


def arac_toplami_metni(ad: str, t: dict) -> str:
    duzeyler = ", ".join(f"{d} ×{n}" for d, n in t["duzeyler"].items())
    if ad == "codex":
        km = t["codex_komutlar"]
        liste = "; ".join(f"`{x['komut']}` (çıkış {x['cikis']})" for x in km[:5]) + (" …" if len(km) > 5 else "")
        web = t.get("codex_web_aramasi", 0)
        uyari = (f" **Codex web erişimi tespit edildi: {web} web arama olayı; bu çağrılar hata sayıldı, "
                 "cevapları kullanılmadı.**" if web else f" Web arama olayı: 0.")
        bil = t.get("codex_bilinmeyen_olaylar") or {}
        if bil:
            uyari += (" **Bilinmeyen olay türü (izin listesinde yok; araç kullanımı sayıldı, çağrılar hata): "
                      + ", ".join(f"`{a}` ×{n}" for a, n in sorted(bil.items())) + ".**")
        return (f"{t['cagri']} çağrı ({duzeyler}); {t['codex_arac_cagrisi']} araç çağrısı, {len(km)} kayıtlı komut"
                + (f": {liste}" if liste else "") + ". Komut ve araç kullanımı hata sayılır (karar 41); sandbox yazmayı ayrıca engeller."
                + uyari)
    if ad == "gemini":
        return (f"{t['cagri']} çağrı ({duzeyler}); denenen araç {t['denenen_arac']}, reddedilen "
                f"{t['reddedilen_arac']}; araç ihlali {t['ihlal']}; "
                f"araç denemesi nedeniyle boş cevap: {t['bos_cevap_arac_denemesi']}")
    return f"{t['cagri']} çağrı ({duzeyler}); araç yüzeyi ihlali {t['ihlal']}"



def ilerleme(mesaj: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {mesaj}", file=sys.stderr, flush=True)



# --------------------------------------------------------------------------- prompt'lar


BAGLAM_ELESTIRI_CUMLESI = "Bağlam verildiyse, cevabın soran kişinin durumuna uygunluğunu da değerlendir."


def baglam_blogu(baglam: str | None) -> str:
    """--baglam: kullanıcının kendisi hakkında verdiği bilgi. Kanıt paketi değildir; ayrı başlıkla ve açık notla verilir."""
    if not baglam:
        return ""
    return ("\n\nSORAN KİŞİ HAKKINDA (kullanıcının verdiği bilgi):\n<<<\n" + baglam +
            "\n>>>\n(Bu, kullanıcının kendi beyanıdır; kanıt paketi değildir ve doğrulanmış sayılmaz.)")


ATIF_KURALI = ("Paketteki bir maddeye dayanan her olgusal iddianın sonuna o maddenin kimliğini köşeli parantezle yaz, ör. [K3] "
               "ya da [K3, K7]. Paket dışındaki genel bilgine ya da kendi hesabına dayanan cümlelere etiket koyma. Pakette olmayan "
               "bir kimlik yazma. Bir iddiayı yalnızca etiketli (zayıf) bir maddeye dayandırıyorsan bunu cümlede belirt.")
OKUYUCU_KURALI = ("ÖZET ve CEVAP'ta konseyin iç işleyişinden söz etme ('bir cevapta', 'üyeler', 'konseyin onayına'). Okuyucu "
                  "paketi görmez: 'pakette/paketteki' yerine 'kaynaklarda' de; kaynağa yalnızca [K#] ile atıf yap. Görüş "
                  "ayrılıkları yalnızca KALAN ANLAŞMAZLIKLAR'da.")
SENTEZ_ATIF_MADDESI = "Üyelerin [K#] atıflarını koru; birleştirdiğin iddialarda hangi maddeye dayandığını kaybetme."
ONAY_ATIF_KONTROLU = ("Atıflı iddiaların atıf yapılan maddeyle uyuşup uyuşmadığına bak; uyuşmayanı itiraz olarak yaz.")


def atif_acik(kanit, v029) -> bool:
    return bool(kanit) and bool(v029) and bool(v029.get("atif"))


def atif_blogu(kanit, v029) -> str:
    """Kanıt (paket ya da --kanit) varken ve bayrak açıkken atıf kuralı paragrafı; aksi halde boş (prompt değişmez)."""
    return f"\n{ATIF_KURALI}" if atif_acik(kanit, v029) else ""


GECERLILIK_SATIRI = "GEÇERLİLİK SINIRLARI: (Bu cevabın geçersiz olacağı en önemli 1–3 koşul; yoksa YOK)"
SENTEZ_KAPSAM_MADDESI = ("Her genel kuralın hangi koşulda geçerli olduğunu yaz. 'her zaman', 'hiçbir zaman', 'tüm', "
                         "'kesinlikle' gibi mutlak ifadeleri yalnızca dayanağın varsa kullan. Üyelerin GEÇERLİLİK SINIRLARI "
                         "alanlarını kapsam bilgisi olarak kullan.")
ONAY_KAPSAM_KONTROLU = ("Kapsam kontrolü: Metinde koşulu belirtilmemiş genel bir iddia var mı? Varsa itiraz olarak yaz "
                        "(önem derecesiyle).\n")


def p_tur0(soru, kanit, baglam=None, v029: dict | None = V029_OZELLIKLERI):
    if v029 and v029.get("gecerlilik"):
        return _p_tur0_gecerlilik(soru, kanit, baglam, v029)
    atif = atif_blogu(kanit, v029)
    return f"""Bir karar konseyinin bağımsız üyesisin. Diğer üyelerin cevaplarını görmüyorsun.
{tarih_satiri()}

SORU:
<<<
{soru}
>>>{baglam_blogu(baglam)}{kanit_blogu(kanit)}

{ORTAK_KURALLAR}
{TUR0_SAYISAL_KURAL}{atif}

Cevabını şu başlıklarla yaz:
CEVAP: (önce net sonuç)
GEREKÇE:
VARSAYIMLAR:
BELİRSİZLİKLER:
GÜVEN: (0-100)"""


def _p_tur0_gecerlilik(soru, kanit, baglam=None, v029=None):
    atif = atif_blogu(kanit, v029)
    return f"""Bir karar konseyinin bağımsız üyesisin. Diğer üyelerin cevaplarını görmüyorsun.
{tarih_satiri()}

SORU:
<<<
{soru}
>>>{baglam_blogu(baglam)}{kanit_blogu(kanit)}

{ORTAK_KURALLAR}
{TUR0_SAYISAL_KURAL}{atif}

Cevabını şu başlıklarla yaz:
CEVAP: (önce net sonuç)
GEREKÇE:
VARSAYIMLAR:
BELİRSİZLİKLER:
GÜVEN: (0-100)
{GECERLILIK_SATIRI}
Bu alanı cevabının sonuna, varsa SONUÇ satırından önce yaz; SONUÇ satırı yine cevabın son satırı olsun."""


def _json_sablonu(etiketler: list[str]) -> str:
    sayilar = '{"kritik": <sayı>, "onemli": <sayı>, "kucuk": <sayı>}'
    parcalar = [f'"{e}": {sayilar}' for e in etiketler]
    if len(etiketler) == 2:
        parcalar.append('"daha_iyi": "<A|B>"')
    return "{" + ", ".join(parcalar) + "}"


def p_elestiri(soru, kanit, etiketli_cevaplar: list[tuple[str, str]], baglam=None, v029: dict | None = V029_OZELLIKLERI):
    """Eleştiri: okuyucu yalnızca diğer üyelerin güncel cevaplarını görür (kendi cevabı yok), kimliksiz.
    v029 {"filtre": True}: v0.29b biçimi (boş liste geçerli, AŞIRI GENELLEME kategorisi)."""
    if v029 and v029.get("filtre"):
        return _p_elestiri_v029(soru, kanit, etiketli_cevaplar, baglam)
    etiketler = [e for e, _ in etiketli_cevaplar]
    bloklar = "\n\n".join(f"=== CEVAP {e} ===\n{c}" for e, c in etiketli_cevaplar)
    cok = len(etiketler) > 1
    gorev = "Görevin: Her cevabı ayrı ayrı ve eleştirel biçimde incele." if cok else "Görevin: Cevabı eleştirel biçimde incele."
    if baglam:
        gorev += " " + BAGLAM_ELESTIRI_CUMLESI
    bolum = ('Her cevap için ayrı bir bölüm aç. Bölüm başlığı satır başında, tam olarak şu biçimde olsun: '
             '"=== CEVAP A HAKKINDA ===" (B için "=== CEVAP B HAKKINDA ==="). Bir bölümde yalnızca o cevabı ele al; '
             'iki cevabı karşılaştırmayı bölümlere değil, sondaki JSON\'a bırak.') if cok else (
        'Bölüm başlığı satır başında, tam olarak şu biçimde olsun: "=== CEVAP A HAKKINDA ===".')
    ilk = ("Aynı soruya diğer konsey üyeleri cevap verdi. Aşağıda yalnızca onların güncel cevapları var; kendi cevabını "
           "görmüyorsun. Cevaplar kimliksiz ve rastgele sırada; kimin yazdığı belirtilmiyor.") if cok else (
        "Aynı soruya bir başka konsey üyesi cevap verdi. Aşağıda yalnızca onun güncel cevabı var; kendi cevabını "
        "görmüyorsun. Cevap kimliksiz; kimin yazdığı belirtilmiyor.")
    json_notu = ('Sayılar, bölümlerde önem etiketi verdiğin maddelerin (HATALAR, EKSİK NOKTALAR, KANITSIZ İDDİALAR) '
                 'sayılarıyla tutarlı olmalı; öneri maddeleri sayılmaz. "daha_iyi": doğruluk, gerekçenin '
                 'sağlamlığı ve soruyu karşılaması bakımından hangi cevap daha iyi; uzunluk, üslup ve biçim ölçüt '
                 'değildir; beraberlik yok.') if cok else (
        'Sayılar, bölümde önem etiketi verdiğin maddelerin (HATALAR, EKSİK NOKTALAR, KANITSIZ İDDİALAR) sayılarıyla '
        'tutarlı olmalı; öneri maddeleri sayılmaz.')
    return f"""Bir karar konseyinin üyesisin. {ilk}
{tarih_satiri()}

SORU:
<<<
{soru}
>>>{baglam_blogu(baglam)}{kanit_blogu(kanit)}

{bloklar}

{ORTAK_KURALLAR}

{gorev}

{bolum} Her bölümde şu dört alt başlık olsun: HATALAR, EKSİK NOKTALAR, KANITSIZ İDDİALAR, İYİLEŞTİRME ÖNERİLERİ.

HATALAR, EKSİK NOKTALAR ve KANITSIZ İDDİALAR altındaki her madde tek satır olsun ve şu biçimde yazılsın:
- [1] (önem: kritik|önemli|küçük; güven: yüksek|orta|düşük) <madde>
İYİLEŞTİRME ÖNERİLERİ altındaki her madde de tek satır olsun, ama önem etiketi taşımasın (bunlar hata değil, öneridir) ve şu biçimde yazılsın:
- [5] (öneri) <öneri>
Madde numarası her cevap bölümünde 1'den başlar. Numara bölüm boyunca sürekli olsun; alt başlıklarda sıfırlanmasın. Aynı sorunu bir kez yaz; başka bir alt başlıkta tekrar etme. Önem: kritik = sonucu ya da ana önerileri yanlış kılar; önemli = cevabı belirgin biçimde zayıflatır ya da önemli bir şeyi eksik bırakır; küçük = ifade ya da ayrıntı sorunu. Güven: maddenin doğru olduğundan ne kadar emin olduğun. Doğrulayamadığın bir olgusal itirazı düşük güvenle yaz.

Övgü yazma, dolgu madde ekleme, madde uydurma. Bir alt başlıkta sorun bulamadıysan "Sorun yok." yaz. Bir cevapta hiç sorun bulamadıysan bunu açıkça belirt.

En sonda, başka metin eklemeden, şu JSON nesnesini yaz:
{_json_sablonu(etiketler)}
{json_notu}"""


def _p_elestiri_v029(soru, kanit, etiketli_cevaplar: list[tuple[str, str]], baglam=None):
    etiketler = [e for e, _ in etiketli_cevaplar]
    bloklar = "\n\n".join(f"=== CEVAP {e} ===\n{c}" for e, c in etiketli_cevaplar)
    cok = len(etiketler) > 1
    gorev = "Görevin: Her cevabı ayrı ayrı ve eleştirel biçimde incele." if cok else "Görevin: Cevabı eleştirel biçimde incele."
    if baglam:
        gorev += " " + BAGLAM_ELESTIRI_CUMLESI
    bolum = ('Her cevap için ayrı bir bölüm aç. Bölüm başlığı satır başında, tam olarak şu biçimde olsun: '
             '"=== CEVAP A HAKKINDA ===" (B için "=== CEVAP B HAKKINDA ==="). Bir bölümde yalnızca o cevabı ele al; '
             'iki cevabı karşılaştırmayı bölümlere değil, sondaki JSON\'a bırak.') if cok else (
        'Bölüm başlığı satır başında, tam olarak şu biçimde olsun: "=== CEVAP A HAKKINDA ===".')
    ilk = ("Aynı soruya diğer konsey üyeleri cevap verdi. Aşağıda yalnızca onların güncel cevapları var; kendi cevabını "
           "görmüyorsun. Cevaplar kimliksiz ve rastgele sırada; kimin yazdığı belirtilmiyor.") if cok else (
        "Aynı soruya bir başka konsey üyesi cevap verdi. Aşağıda yalnızca onun güncel cevabı var; kendi cevabını "
        "görmüyorsun. Cevap kimliksiz; kimin yazdığı belirtilmiyor.")
    json_notu = ('Sayılar, bölümlerde önem etiketi verdiğin maddelerin (HATALAR, EKSİK NOKTALAR, KANITSIZ İDDİALAR, '
                 'AŞIRI GENELLEME / KAPSAM HATASI) sayılarıyla tutarlı olmalı; öneri maddeleri sayılmaz. Hiç madde yazmadıysan '
                 'sayıların hepsi 0 olur. "daha_iyi": doğruluk, gerekçenin sağlamlığı ve soruyu karşılaması bakımından hangi '
                 'cevap daha iyi; uzunluk, üslup ve biçim ölçüt değildir; beraberlik yok.') if cok else (
        'Sayılar, bölümde önem etiketi verdiğin maddelerin (HATALAR, EKSİK NOKTALAR, KANITSIZ İDDİALAR, '
        'AŞIRI GENELLEME / KAPSAM HATASI) sayılarıyla tutarlı olmalı; öneri maddeleri sayılmaz. Hiç madde yazmadıysan '
        'sayıların hepsi 0 olur.')
    return f"""Bir karar konseyinin üyesisin. {ilk}
{tarih_satiri()}

SORU:
<<<
{soru}
>>>{baglam_blogu(baglam)}{kanit_blogu(kanit)}

{bloklar}

{ORTAK_KURALLAR}

{gorev}

{bolum} Bölümde yalnızca sorun bulduğun alt başlıkları yaz; şu alt başlıklar kullanılabilir (hiçbiri zorunlu değil): HATALAR, EKSİK NOKTALAR, KANITSIZ İDDİALAR, {ASIRI_GENELLEME_BASLIGI}, İYİLEŞTİRME ÖNERİLERİ. Bir cevapta düzeltilmesi gereken bir şey bulamadıysan bölüme yalnızca "Bu cevapta düzeltilmesi gereken bir şey yok." yaz; bu geçerli ve tam bir eleştiridir, madde uydurma.

HATALAR, EKSİK NOKTALAR, KANITSIZ İDDİALAR ve {ASIRI_GENELLEME_BASLIGI} altındaki her madde tek satır olsun ve şu biçimde yazılsın:
- [1] (önem: kritik|önemli|küçük; güven: yüksek|orta|düşük) <madde>
İYİLEŞTİRME ÖNERİLERİ altındaki her madde de tek satır olsun, ama önem etiketi taşımasın (bunlar hata değil, öneridir) ve şu biçimde yazılsın:
- [5] (öneri) <öneri>
Madde numarası her cevap bölümünde 1'den başlar ve bölüm boyunca sürekli olsun; alt başlıklarda sıfırlanmasın. Aynı sorunu bir kez yaz; başka bir alt başlıkta tekrar etme. {ASIRI_GENELLEME_BASLIGI}: cevabın geçerli olduğu koşulu ya da kapsamı aşan, gereğinden daha genel ya da kesin söylenmiş iddia. Önem: kritik = sonucu ya da ana önerileri yanlış kılar; önemli = cevabı belirgin biçimde zayıflatır ya da önemli bir şeyi eksik bırakır; küçük = ifade ya da ayrıntı sorunu. Güven: maddenin doğru olduğundan ne kadar emin olduğun. Doğrulayamadığın bir olgusal itirazı düşük güvenle yaz.

Övgü yazma, dolgu madde ekleme, madde uydurma.

En sonda, başka metin eklemeden, şu JSON nesnesini yaz:
{_json_sablonu(etiketler)}
{json_notu}"""


DUZELTME_HAM_NOTU = ('Bu eleştiriler iki cevabı birden kapsıyor; hangisinin senin cevabın olduğunu içeriğinden ayırt et, '
                     'yalnızca onunla ilgili maddeleri değerlendir. Madde kimliği yoksa "E1-<sıra>" biçiminde kendin '
                     'numarala.')


DAYANAK_DOGRULAMA_CUMLESI = ("Eleştiriyi kabul etmeden önce iddiasını kendin doğrula; doğrulayamıyorsan ÇÖZÜLEMEDİ yaz, "
                             "doğrulanabilir biçimde yanlışsa RED yaz.")


def p_duzeltme(soru, kanit, kendi_cevabi: str, elestiriler: list[str], baglam=None, ham_elestiri: bool = False,
               v029: dict | None = V029_OZELLIKLERI):
    """Düzeltme: kendi güncel cevabı + ona gelen eleştiriler (kimliksiz değerlendiriciler).
    v029 {"dayanak": True}: v0.29b kararları (KABUL / KISMEN KABUL / RED / ÇÖZÜLEMEDİ), DAYANAK alanı ve doğrulama cümlesi."""
    if v029 and v029.get("dayanak"):
        return _p_duzeltme_dayanak(soru, kanit, kendi_cevabi, elestiriler, baglam, ham_elestiri, v029)
    atif = atif_blogu(kanit, v029)
    bloklar = "\n".join(f"=== DEĞERLENDİRİCİ {i} ELEŞTİRİSİ ===\n{e}" for i, e in enumerate(elestiriler, 1))
    ham = ("\n" + DUZELTME_HAM_NOTU + "\n") if ham_elestiri else ""
    return f"""Bir karar konseyinin üyesisin. Aşağıda soruya verdiğin güncel cevap ve onun hakkında yazılmış eleştiriler var. Eleştirenler kimliksiz.
{tarih_satiri()}

SORU:
<<<
{soru}
>>>{baglam_blogu(baglam)}{kanit_blogu(kanit)}

=== SENİN GÜNCEL CEVABIN ===
{kendi_cevabi}
{bloklar}

{ORTAK_KURALLAR}{atif}

Kural: Eleştiriyi yalnızca ikna olduysan kabul et; sırf eleştirildin diye görüş değiştirme. Haklı bulduğun maddeyi kabul et, haksız ya da kanıtsız bulduğunu gerekçesiyle reddet. Eleştirenlerin sayısı bu kuralı değiştirmez.
Bir eleştiri olgusal olarak yanlışsa, soruyla ilgisizse ya da önemi abartılmışsa RED et. RED etmek bir başarısızlık değildir.
Kabul ettiğin düzeltmeleri mevcut metne işle; yeni paragraflar yığma, tekrar yaratma. Gereksiz hale gelen kısımları çıkar.
{ham}
Çıktın iki bölümden oluşsun, bu sırayla:
DEĞİŞİKLİK KAYDI:
Her eleştiri maddesi için bir satır; madde kimliğini aynen kullan:
- E1-1 KABUL: doğru, çünkü <eleştirinin neden doğru olduğu>; değişen: <cevapta ne değişti>
- E1-2 KISMEN KABUL: kısmen doğru, çünkü <hangi kısmının neden doğru olduğu>; değişen: <ne değişti>; kabul edilmeyen: <hangi kısım ve neden>
- E1-3 RED: <neden>
KABUL ve KISMEN KABUL satırlarında yalnızca neyi değiştirdiğini değil, eleştirinin neden doğru olduğunu da yaz ("çünkü" kısmı zorunlu).
Aynı noktayı iki eleştiri yapmışsa ikisine de ayrı satır yaz.
GÜNCEL CEVAP:
Bu başlıktan sonra cevabının TAM ve güncel halini yaz; yalnızca değişen kısımları değil. Kabul ettiğin düzeltmeler girsin, reddettiklerinde eski halini koru. Uzunluk ve biçim kısıtı yok; soru kendi çıktı biçimini istiyorsa ona uy. Bu başlıktan sonra değişiklik kaydı, açıklama ya da yorum yazma."""


def _p_duzeltme_dayanak(soru, kanit, kendi_cevabi: str, elestiriler: list[str], baglam=None, ham_elestiri: bool = False,
                        v029=None):
    atif = atif_blogu(kanit, v029)
    bloklar = "\n".join(f"=== DEĞERLENDİRİCİ {i} ELEŞTİRİSİ ===\n{e}" for i, e in enumerate(elestiriler, 1))
    ham = ("\n" + DUZELTME_HAM_NOTU + "\n") if ham_elestiri else ""
    return f"""Bir karar konseyinin üyesisin. Aşağıda soruya verdiğin güncel cevap ve onun hakkında yazılmış eleştiriler var. Eleştirenler kimliksiz.
{tarih_satiri()}

SORU:
<<<
{soru}
>>>{baglam_blogu(baglam)}{kanit_blogu(kanit)}

=== SENİN GÜNCEL CEVABIN ===
{kendi_cevabi}
{bloklar}

{ORTAK_KURALLAR}{atif}

Kural: Eleştiriyi yalnızca ikna olduysan kabul et; sırf eleştirildin diye görüş değiştirme. Haklı bulduğun maddeyi kabul et, haksız ya da kanıtsız bulduğunu gerekçesiyle reddet. Eleştirenlerin sayısı bu kuralı değiştirmez.
{DAYANAK_DOGRULAMA_CUMLESI}
Bir eleştiri olgusal olarak yanlışsa, soruyla ilgisizse ya da önemi abartılmışsa RED et. RED etmek bir başarısızlık değildir.
Kabul ettiğin düzeltmeleri mevcut metne işle; yeni paragraflar yığma, tekrar yaratma. Gereksiz hale gelen kısımları çıkar.
{ham}
Çıktın iki bölümden oluşsun, bu sırayla:
DEĞİŞİKLİK KAYDI:
Her eleştiri maddesi için bir satır; madde kimliğini aynen kullan:
- E1-1 KABUL: doğru, çünkü <eleştirinin neden doğru olduğu>; değişen: <cevapta ne değişti>; DAYANAK: <dayanağın>
- E1-2 KISMEN KABUL: kısmen doğru, çünkü <hangi kısmının neden doğru olduğu>; değişen: <ne değişti>; kabul edilmeyen: <hangi kısım ve neden>; DAYANAK: <dayanağın>
- E1-3 RED: <neden>; DAYANAK: <dayanağın>
- E1-4 ÇÖZÜLEMEDİ: <iddia neden doğrulanamadı>; DAYANAK: yok
KABUL ve KISMEN KABUL satırlarında yalnızca neyi değiştirdiğini değil, eleştirinin neden doğru olduğunu da yaz ("çünkü" kısmı zorunlu).
Her karar satırı bir DAYANAK taşısın; DAYANAK şunlardan biridir: yaptığın hesap, kanıt paketindeki bir madde [K#], bir karşı örnek, sorunun kendi şartı ya da bilinen bir olgu. KABUL ve KISMEN KABUL satırında DAYANAK boş bırakılamaz.
ÇÖZÜLEMEDİ yazdığın maddeyi cevaba işleme; cevabında o noktayı olduğu gibi bırak.
Aynı noktayı iki eleştiri yapmışsa ikisine de ayrı satır yaz.
GÜNCEL CEVAP:
Bu başlıktan sonra cevabının TAM ve güncel halini yaz; yalnızca değişen kısımları değil. Kabul ettiğin düzeltmeler girsin, reddettiklerinde eski halini koru. Uzunluk ve biçim kısıtı yok; soru kendi çıktı biçimini istiyorsa ona uy. Bu başlıktan sonra değişiklik kaydı, açıklama ya da yorum yazma."""


def p_sentez(soru, kanit, cevaplar: list[str], baglam=None, cozulemedi: list[str] | None = None,
             v029: dict | None = V029_OZELLIKLERI):
    bloklar = "\n\n".join(f"=== CEVAP {i} ===\n{c}" for i, c in enumerate(cevaplar, 1))
    cz = ""
    if cozulemedi:   # v0.29b (madde 4): düzeltme turlarında doğrulanamayan eleştiriler BELİRSİZLİKLER'e taşınır
        cz = ("\n\nDüzeltme turlarında üyelerin DOĞRULAYAMADIĞI eleştiri iddiaları (ÇÖZÜLEMEDİ; doğru da olabilir, yanlış da). "
              "Bunları ÖZET ya da CEVAP'ta kesin olgu gibi kullanma; her birini BELİRSİZLİKLER bölümüne madde olarak yaz:\n"
              + "\n".join(f"- {x}" for x in cozulemedi))
    kapsam = f"\n- {SENTEZ_KAPSAM_MADDESI}" if (v029 and v029.get("gecerlilik")) else ""
    if atif_acik(kanit, v029):
        kapsam += f"\n- {ATIF_KURALI}\n- {SENTEZ_ATIF_MADDESI}"
    if v029 and v029.get("okuyucu"):
        kapsam += f"\n- {OKUYUCU_KURALI}"
    return f"""Bir karar konseyinin sentez yazarısın. Karar yetkin yok; yazacağın metin bütün üyelere ayrıca onaya sunulacak.
{tarih_satiri()}

SORU:
<<<
{soru}
>>>{baglam_blogu(baglam)}{kanit_blogu(kanit)}

Üyelerin eleştiri-düzeltme turlarından sonraki son cevapları (kimliksiz, rastgele sırada):

{bloklar}{cz}

{ORTAK_KURALLAR}

Görevin: Cevapları tek bir ortak cevapta birleştir. Cevaplara sadık kal; kendi görüşünü öne çıkarma.
- Cevaplardaki doğru ve önemli her noktayı koru; yalnızca tekrarı çıkar. Yalnızca bir cevapta geçen ama doğru ve önemli olan nokta da kalır.
- Uzunluk sorunun gerektirdiği kadar olsun; dolgu ekleme, ama içeriği kısaltmak için de atma.
- Gerçek bir anlaşmazlık yoksa hiçbir öneriyi anlaşmazlık bölümüne itme. Birbirini dışlamayan öneriler CEVAP içinde birleşir.
- Cevaplar gerçekten bağdaşmayan görüşler içeriyorsa KALAN ANLAŞMAZLIKLAR'da her görüşü adil ve ayrı ayrı yaz.
- {GENELLEME_KURALI}{kapsam}

Metin şu başlıklarla yazılsın:
ÖZET: 2-4 cümle. Yalnızca bunu okuyan cevabı almış olmalı.
CEVAP: Gerekçeleriyle birlikte tam cevap. Alt başlıklar serbest.
KALAN ANLAŞMAZLIKLAR: Yalnızca gerçek anlaşmazlık varsa; yoksa bu başlığı hiç yazma.
BELİRSİZLİKLER: Doğrulanamayan iddialar, tahminler, varsayımlar. Kanıt paketi verildiyse paketle doğrulanmayan olgusal iddiaları da yaz. Yoksa "Yok".

Biçim: LaTeX kullanma; formülleri düz metinle yaz. Soru kendi çıktı biçimini istiyorsa CEVAP bölümünde ona uy; başlıklar yine de kalsın.
Yalnızca bu metni yaz; başına veya sonuna açıklama ekleme."""


def p_sentez_duzeltme(soru, kanit, metin: str, itirazlar: list[str], baglam=None, onemler: list[str] | None = None,
                      v029: dict | None = V029_OZELLIKLERI):
    """RET sonrası tek seferlik düzeltme (v0.23, karar 62): sentezi yazan model kendi metnini ve itirazları alır."""
    bloklar = "\n".join(f"[R{i}] {t}" + (f" (önem: {onemler[i - 1]})" if onemler else "")
                        for i, t in enumerate(itirazlar, 1))
    okuyucu = f"\n- {OKUYUCU_KURALI}" if (v029 and v029.get("okuyucu")) else ""
    return f"""Bir karar konseyinin sentez yazarısın. Yazdığın ortak metin oylandı; en az bir üye RET oyu verdi ve somut itiraz yazdı. Karar yetkin yok; düzelttiğin metin üyelere bir kez daha oylatılacak.
{tarih_satiri()}

SORU:
<<<
{soru}
>>>{baglam_blogu(baglam)}{kanit_blogu(kanit)}

=== SENİN YAZDIĞIN ORTAK METİN ===
{metin}
=== METİN SONU ===

=== İTİRAZLAR (kimliksiz) ===
{bloklar}
=== İTİRAZLAR SONU ===

{ORTAK_KURALLAR}

Görevin: Her itirazı ayrı ayrı değerlendir ve metni gerekiyorsa düzelt.
- İtirazı yalnızca ikna olduysan kabul et; sırf itiraz edildi diye metni değiştirme. Olgusal olarak yanlış, soruyla ilgisiz ya da abartılmış itirazı RED et; RED bir başarısızlık değildir.
- Kabul ettiklerini mevcut metne işle; paragraf yığma, tekrar yaratma. Gereksiz hale gelen kısmı çıkar. Metne sadık kal; kendi görüşünü öne çıkarma.
- {GENELLEME_KURALI}{okuyucu}
- Biçim: LaTeX kullanma. Metin ÖZET, CEVAP, KALAN ANLAŞMAZLIKLAR (yalnızca gerçek anlaşmazlık varsa), BELİRSİZLİKLER başlıklarını korusun.

Çıktın iki bölümden oluşsun, bu sırayla:
İTİRAZ KAYDI:
Her itiraz için bir satır; kimliği aynen kullan:
- R1 KABUL: doğru, çünkü <itirazın neden doğru olduğu>; değişen: <metinde ne değişti>
- R2 KISMEN KABUL: kısmen doğru, çünkü <...>; değişen: <...>; kabul edilmeyen: <hangi kısım ve neden>
- R3 RED: <neden>
DÜZELTİLMİŞ METİN:
Bu başlıktan sonra ortak metnin TAM ve düzeltilmiş halini yaz; yalnızca değişen kısımları değil. Hepsini reddettiysen metni olduğu gibi yaz. Bu başlıktan sonra kayıt, açıklama ya da yorum yazma."""


def sentez_farki(eski: str, yeni: str, sinir: int = FARK_SINIRI) -> str:
    """Düzeltme öncesi ve sonrası metnin satır farkı (v0.24, karar 63); çok uzunsa kesilir."""
    import difflib
    d = "\n".join(difflib.unified_diff((eski or "").splitlines(), (yeni or "").splitlines(),
                                        "DÜZELTMEDEN ÖNCE", "DÜZELTMEDEN SONRA", lineterm="", n=0))
    return d if len(d) <= sinir else d[:sinir] + "\n[... fark kesildi ...]"


def ikinci_oylama_bloku(ikinci: dict) -> str:
    """İkinci oylama prompt'una eklenen blok: ilk itirazlar + ele alınışları + metin farkı (v0.24, karar 63)."""
    sat = []
    for it in ikinci.get("itirazlar") or []:
        sat.append(f"[{it['kimlik']}] (önem: {it.get('onem', 'önemli')}) {it['metin']}")
        if it.get("karar"):
            sat.append(f"    Sentez yazarının kararı: {it['karar']}"
                       + (f" — gerekçe: {it['gerekce']}" if it.get("gerekce") else "")
                       + (f"; değişen: {it['degisen']}" if it.get("degisen") else ""))
    return f"""
=== BU İKİNCİ OYLAMA: İLK OYLAMADAKİ İTİRAZLAR VE ELE ALINIŞLARI (kimliksiz) ===
{chr(10).join(sat) if sat else "(yok)"}
=== İTİRAZLAR SONU ===

=== DÜZELTMEDEN ÖNCEKİ VE SONRAKİ METNİN FARKI ===
{ikinci.get("fark", "")}
=== FARK SONU ===

İkinci oylamada RET yalnızca şu iki durumda geçerlidir: (a) yukarıdaki kritik/önemli itirazlardan biri düzeltmeyle gerçekten karşılanmadı ("kaynak": "ilk"); (b) düzeltme yeni bir kritik/önemli sorun getirdi ("kaynak": "yeni"). Değişmeyen metne yönelik yeni itirazlar RET sebebi değildir; yine de yaz ve "kaynak": "degismeyen" işaretle, ek not olarak kaydedilir.
"""


def p_onay(soru, kanit, metin, ozet, kendi_cevabi: str, baglam=None, ikinci: dict | None = None,
           v029: dict | None = V029_OZELLIKLERI):
    if ikinci is None:
        eksiksiz = ("Bütün itirazlarını bu oylamada eksiksiz yaz; sonradan eklenen itirazlar düzeltilemez.\n")
        if v029 and v029.get("gecerlilik"):
            eksiksiz += (ONAY_KAPSAM_KONTROLU.rstrip("\n") + " " + ONAY_ATIF_KONTROLU + "\n") if atif_acik(kanit, v029) \
                else ONAY_KAPSAM_KONTROLU
        ikinci_blok = ""
        itiraz_sablonu = '[{"onem": "<kritik|önemli|küçük>", "metin": "<itiraz>"}]'
    else:
        eksiksiz = ""
        ikinci_blok = ikinci_oylama_bloku(ikinci)
        itiraz_sablonu = ('[{"onem": "<kritik|önemli|küçük>", "kaynak": "<ilk|yeni|degismeyen>", '
                          '"metin": "<itiraz>"}]')
    return f"""Bir karar konseyinin üyesisin. Aşağıdaki ortak cevap metni konseyin son cevaplarından derlendi ve onayına sunuluyor.
{tarih_satiri()}

SORU:
<<<
{soru}
>>>{baglam_blogu(baglam)}{kanit_blogu(kanit)}

METİN SÜRÜMÜ: {ozet}
=== ÖNERİLEN ORTAK METİN ===
{metin}
=== METİN SONU ===

=== SENİN SON CEVABIN (eleştiri-düzeltme turlarından sonraki hali) ===
{kendi_cevabi}
=== SENİN SON CEVABIN SONU ===
{ikinci_blok}
{ORTAK_KURALLAR}

Bu metni değerlendir:
- KABUL: Metin doğru; senin cevabındaki doğru ve önemli noktalar korunmuş; hiçbir görüş çarpıtılmamış.
- RET: Metinde kritik ya da önemli bir hata var YA DA senin cevabındaki doğru ve önemli bir nokta haksız yere atılmış ya da çarpıtılmış. Hatayı ya da atılan noktayı "itirazlar" alanında somut yaz.
- CEKIMSER: Karar vermek için yeterli bilgin yok.
Metnin uzunluğu, üslup farkları ve küçük ifade farkları tek başına ret sebebi değildir. Bir noktayı, doğru olmadığına ya da önemsiz olduğuna gerçekten inanıyorsan atılmış sayma; yalnızca kendi cevabında olduğu için önemli sayma.
Her itirazın önemini belirt. {ONEM_TANIMI} Yalnızca küçük itirazı olan bir RET kodla KABUL sayılır; itirazlar not olarak kaydedilir.
{eksiksiz}
Kısa bir değerlendirme yazabilirsin. En sonda şu JSON nesnesini yaz (metin_surumu değerini aynen kopyala):
{{"metin_surumu": "{ozet}", "oy": "<KABUL|RET|CEKIMSER>", "gerekce": "<kısa gerekçe>", "itirazlar": {itiraz_sablonu}}}"""


def _terminalden_onay() -> bool:
    """--arastir-onay: paketi gösterdikten sonra onay ister. Etkileşimli terminal yoksa onay VERİLMEMİŞ sayılır."""
    if not sys.stdin.isatty():
        raise R.ArastirmaDurdu("--arastir-onay için etkileşimli terminal gerekli (stdin terminal değil); onay alınamadı")
    return input("Bu paket konseye verilsin mi? [e/H]: ").strip().lower() in ("e", "evet", "y", "yes")


# --------------------------------------------------------------------------- kota görüntüsü (karar 50 ek; ayrinti.md)

KOTA_OKUMA_ZAMAN_ASIMI_SN = 30


def _komut_adi(s: dict) -> str:
    try:
        return Path(os.path.expanduser(str(s["komut"][0]))).name
    except Exception:
        return ""


def _son_codex_kotasi(s: dict) -> dict:
    """Codex'in en son oturum kaydındaki rate_limits (yeni çağrı yapmaz; kayıt eskiyse değer eski olabilir).
    v0.22: sonuca olay zamanı (UTC) ve kayıt dosyasının adı da eklenir (kota_metni eskiliği buna bakar).
    v0.30: kota sınırına çarpılınca Codex'in kayıtlarında rate_limits boş gelir (primary/secondary None); bu durumda en yeni
    OKUNABİLİR değer (son 20 kayıt dosyasında) ve zamanı gösterilir, sonuca `sinir_sonrasi_bos_kayit` (boş kaydın olay zamanı)
    eklenir ve kota_metni bunu yazar."""
    try:
        kok = Path(s.get("kayit_dizini") or A.varsayilan_kayit_dizini("codex", s)).expanduser()
        bos_zaman = None   # okunabilir değerden DAHA YENİ, ama rate_limits'i boş olan en yeni kaydın olay zamanı
        for yol in sorted(kok.glob("*/*/*/rollout-*.jsonl"), reverse=True)[:20]:
            son, zaman, bos_son = None, None, None
            with open(yol, encoding="utf-8", errors="replace") as f:
                for satir in f:
                    try:
                        d = json.loads(satir)
                    except json.JSONDecodeError:
                        continue
                    yuk = d.get("payload") if isinstance(d, dict) and isinstance(d.get("payload"), dict) else {}
                    if yuk.get("type") == "token_count" and isinstance(yuk.get("rate_limits"), dict):
                        z = d.get("timestamp") if isinstance(d.get("timestamp"), str) else None
                        if A.kota_ozeti(yuk["rate_limits"]):
                            son, zaman, bos_son = yuk["rate_limits"], z, None
                        else:
                            bos_son = z or "zaman bilinmiyor"
            if bos_son and bos_zaman is None:
                bos_zaman = bos_son
            if son:
                ozet = A.kota_ozeti(son)
                if ozet:
                    ozet["kayit_dosyasi"] = yol.name
                    if zaman:
                        ozet["olay_zamani"] = zaman
                    if bos_zaman:
                        ozet["sinir_sonrasi_bos_kayit"] = bos_zaman
                    return ozet
    except Exception:
        pass
    return {}


async def _komutla_kota(s: dict, ad: str, calisma: str, argumanlar: list[str], alan: str) -> dict:
    try:
        rc, out, err, zaman_doldu = await A.surec_calistir(list(s["komut"]) + argumanlar, calisma,
                                                           KOTA_OKUMA_ZAMAN_ASIMI_SN, A.saglayici_ortami(ad, s))
    except Exception as e:  # kota okuma hiçbir zaman konseyi çökertmez
        return {"durum": "okunamadı", "metin": f"çalıştırılamadı: {e}"}
    if zaman_doldu:
        return {"durum": "okunamadı", "metin": f"{KOTA_OKUMA_ZAMAN_ASIMI_SN} saniyede cevap gelmedi"}
    try:
        d = json.loads(out)
        metin = str(d.get(alan) or "").strip()
    except (json.JSONDecodeError, AttributeError):
        metin = ""
    if rc != 0 or not metin:
        return {"durum": "okunamadı", "metin": f"çıkış kodu {rc}: {(err or out).strip()[:300]}"}
    return {"durum": "ok", "metin": metin[:1500]}


async def kota_goruntusu(ayar: dict, calisma: str) -> dict:
    """Her koltuğun kotasını harcamadan okur: Claude `claude -p "/usage"`, Gemini yalıtılmış HOME'la `agy -p "/usage"`
    (ikisi de yerel komut: model çağrısı yok, num_turns 0, token 0; 20 Kasım 2026 deneyi), GPT mevcut Codex oturum
    kaydından. Hata ya da sahte komut durumunda 'okunamadı'/'atlandı' yazar; asla istisna fırlatmaz."""
    sag = ayar["saglayicilar"]
    gorevler: dict[str, object] = {}

    async def atla(neden):
        return {"durum": "atlandı", "metin": neden}

    if "claude" in sag:
        s = sag["claude"]
        if _komut_adi(s) == "claude" or s.get("kota_oku"):
            gorevler["claude"] = _komutla_kota(s, "claude", calisma,
                                                ["-p", "/usage", "--output-format", "json", "--strict-mcp-config",
                                                 "--setting-sources", ""], "result")
        else:
            gorevler["claude"] = atla("komut `claude` değil")
    if "gemini" in sag:
        s = sag["gemini"]
        if A.agy_gercek_mi(s) or s.get("kota_oku"):
            problemler = A.agy_yalitimini_dogrula(s, calisma) if s.get("home") else []
            if problemler:  # yalıtım yoksa agy gerçek HOME'la çalıştırılmaz
                gorevler["gemini"] = atla("agy yalıtımı eksik: " + "; ".join(problemler)[:200])
            else:
                gorevler["gemini"] = _komutla_kota(s, "gemini", calisma, ["-p", "/usage", "--output-format", "json"],
                                                    "response")
        else:
            gorevler["gemini"] = atla("komut `agy` değil")
    adlar = list(gorevler)
    sonuclar = await asyncio.gather(*gorevler.values(), return_exceptions=True)
    cikti = {ad: (r if isinstance(r, dict) else {"durum": "okunamadı", "metin": f"hata: {r}"})
             for ad, r in zip(adlar, sonuclar)}
    if "codex" in sag:
        s = sag["codex"]
        if _komut_adi(s) == "codex" or s.get("kayit_dizini") or s.get("kota_oku"):
            k = _son_codex_kotasi(s)
            cikti["codex"] = {"durum": "ok" if k else "okunamadı", "metin": kota_metni(k) + " (son Codex oturum kaydından)"}
        else:
            cikti["codex"] = {"durum": "atlandı", "metin": "komut `codex` değil"}
    return cikti


# --------------------------------------------------------------------------- konsey


# --------------------------------------------------------------------------- v0.27: ölçüm (telemetri.json)
# Bu bölüm prompt'ları ve akışı değiştirmez; yalnızca kayıt klasörüne telemetri.json yazmak için veri toplar.

KOD_SURUMU = "v1.0"
TELEMETRI_SURUMU = 1
TELEMETRI_ONEMLERI = ("kritik", "onemli", "kucuk", "oneri", "belirsiz")
GONDERILEN_MADDE_KALIBI = re.compile(r"^(\s*(?:[-*•]\s*)?)\[(E\d+-\d+)\](\s*\([^)\n]*\))?(.*)$")


def kategori_onem_sayimi(maddeler: list[dict]) -> dict:
    """madde_satirlari çıktısından {alt başlık: {önem: sayı}} (alt başlık yoksa "basliksiz")."""
    sonuc: dict[str, dict[str, int]] = {}
    for m in maddeler:
        kat = m.get("alt_baslik") or "basliksiz"
        sonuc.setdefault(kat, {})
        sonuc[kat][m["onem"]] = sonuc[kat].get(m["onem"], 0) + 1
    return sonuc


def gonderilen_madde_dagilimi(metin: str) -> dict:
    """Düzeltme prompt'una giden eleştiri metnindeki "[E1-3] (önem: ...)" maddelerinin kategori × önem dağılımı.
    Dönüş: {"madde": toplam, "oneri_veya_kucuk": n, "dagilim": {alt başlık: {önem: sayı}}}."""
    dagilim: dict[str, dict[str, int]] = {}
    alt = None
    toplam = oneri_kucuk = 0
    for satir in (metin or "").splitlines():
        ab = _alt_baslik(satir)
        if ab:
            alt = ab
            continue
        m = GONDERILEN_MADDE_KALIBI.match(satir)
        if not m:
            continue
        if not m.group(3) and alt != _ascii("İYİLEŞTİRME ÖNERİLERİ"):
            continue   # _madde_eslesmesi ile aynı kural: etiketsiz satır yalnızca öneriler altında madde sayılır
        etiketler = m.group(3) or ""
        om = re.search(r"[öo]nem\s*:\s*([^;)\s]+)", etiketler, re.I)
        if alt == _ascii("İYİLEŞTİRME ÖNERİLERİ") or (re.search(r"\(\s*[öo]neri\b", etiketler, re.I) and not om):
            onem = ONERI
        else:
            onem = _onem_coz(om.group(1)) if om else "belirsiz"
        kat = alt or "basliksiz"
        dagilim.setdefault(kat, {})
        dagilim[kat][onem] = dagilim[kat].get(onem, 0) + 1
        toplam += 1
        oneri_kucuk += onem in (ONERI, "kucuk")
    return {"madde": toplam, "oneri_veya_kucuk": oneri_kucuk, "dagilim": dagilim}


def git_bilgisi() -> dict | None:
    """Depodaki git kısa özeti (yalnızca okuma; hata olursa None, koşuyu asla bozmaz)."""
    def git(*a):
        r = subprocess.run(["git", "--no-optional-locks", "-C", str(BURASI), *a], capture_output=True, text=True,
                           timeout=10, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip())
        return r.stdout.strip()
    try:
        return {"commit": git("rev-parse", "--short", "HEAD"), "ozet": git("log", "-1", "--format=%s"),
                "kirli": bool(git("status", "--porcelain"))}
    except Exception:  # noqa: BLE001 — telemetri için en iyi çaba
        return None


def medyan(degerler: list[float]) -> float | None:
    d = sorted(degerler)
    if not d:
        return None
    o = len(d) // 2
    return float(d[o]) if len(d) % 2 else (d[o - 1] + d[o]) / 2


def telemetri_olustur(k: dict, cagrilar: list[dict], asama_ek: dict | None = None, git: dict | None = None,
                      bitis: str | None = None) -> dict:
    """kayit sözlüğü ve çağrı kayıtlarından telemetri.json içeriği. Saf işlev (dosya/ağ/git erişimi yok; git dışarıdan
    verilir). Eksik alanlar (örn. Tur 0 uzlaşısında turlar yok) boş sözlük/None olur."""
    asamalar: dict[str, dict] = {}
    kelime: dict[str, dict] = {}
    modeller: dict[str, list[str]] = {}
    for c in cagrilar:
        a = asamalar.setdefault(c["adim"], {"baslangic": c["baslangic"], "bitis": c["bitis"]})
        a["baslangic"], a["bitis"] = min(a["baslangic"], c["baslangic"]), max(a["bitis"], c["bitis"])
        if c.get("kelime") is not None:
            kelime.setdefault(c["adim"], {})[c["ad"]] = c["kelime"]
        if c.get("gercek_model") and c["gercek_model"] not in modeller.setdefault(c["ad"], []):
            modeller[c["ad"]].append(c["gercek_model"])
    for ad, a in (asama_ek or {}).items():
        asamalar[ad] = dict(a)
    for a in asamalar.values():
        a["sure_sn"] = round((dt.datetime.fromisoformat(a["bitis"]) - dt.datetime.fromisoformat(a["baslangic"])).total_seconds(), 1)
    turlar = k.get("turlar") or []
    elestiri_ko = {f"tur{t['tur']}": t.get("elestiri_kategori_onem") or {} for t in turlar}
    iletilen = {f"tur{t['tur']}": t.get("duzeltmeye_iletilen") or {} for t in turlar}
    cevap_kelime = {f"tur{t['tur']}": t.get("cevap_kelime") or {} for t in turlar}
    kararlar: dict[str, dict] = {}
    toplam = {"madde": 0, "kabul": 0, "kismen": 0, "red": 0, "karari_eksik": 0, "kimliksiz_duzeltme": 0}
    for t in turlar:
        kararlar[f"tur{t['tur']}"] = {}
        for ad, d in (t.get("duzeltmeler") or {}).items():
            if d.get("durum") != "ok":
                kararlar[f"tur{t['tur']}"][ad] = {"durum": d.get("durum")}
                continue
            sy = d["sayim"]
            kararlar[f"tur{t['tur']}"][ad] = {"durum": "ok", "madde": sy["madde"], "kabul": sy["kabul"],
                                              "kismen": sy.get("kismen", 0), "red": sy["red"],
                                              "karari_eksik": sy["yanitsiz"], "taninmayan": sy.get("taninmayan", 0)}
            if d.get("dayanak"):   # v0.29b: yalnızca dayanak bayrağıyla yazılan alanlar
                kararlar[f"tur{t['tur']}"][ad].update(
                    {"cozulemedi": sy.get("cozulemedi", 0), "dayanaksiz_kabul": d["dayanak"]["dayanaksiz"],
                     "kabul_kismen": d["dayanak"]["kabul_kismen"]})
                for a in ("cozulemedi", "dayanaksiz_kabul", "kabul_kismen"):
                    toplam[a] = toplam.get(a, 0) + kararlar[f"tur{t['tur']}"][ad][a]
            if sy["madde"] is None:
                toplam["kimliksiz_duzeltme"] += 1
                continue
            for a, b in (("madde", "madde"), ("kabul", "kabul"), ("kismen", "kismen"), ("red", "red"),
                         ("karari_eksik", "yanitsiz")):
                toplam[a] += sy.get(b, 0) or 0
    kararlar["toplam"] = toplam
    tur0_kelime = [c["kelime"] for c in cagrilar if c["adim"] == "tur0" and c.get("kelime") is not None]
    tur0_med = medyan(tur0_kelime)
    sentez = k.get("sentez") or {}
    sentez_kelime = kelime_sayisi(sentez.get("metin", "")) if sentez else None
    sd = k.get("sentez_duzeltme") or {}
    ad_ = k.get("atif_denetimi")
    atif_tel = None
    if ad_:
        atif_tel = {"madde_sayisi": ad_["madde_sayisi"], "paket_madde_sayisi": ad_["paket_madde_sayisi"],
                    "kullanici_madde_sayisi": ad_["kullanici_madde_sayisi"],
                    "nihai_kullanilan": len(ad_["nihai_kullanilan_gecerli"]), "kullanilmayan": ad_["kullanilmayan_sayisi"],
                    "uydurma_toplam": ad_["uydurma_toplam"], "zayif_toplam": ad_["zayif_toplam"],
                    "asamalar": {a: {m: {"atif": d["atif"], "uydurma": len(d["uydurma"]), "zayif": len(d["zayif"])}
                                     for m, d in ms.items()} for a, ms in ad_["asamalar"].items()},
                    "nihai": {"atif": ad_["nihai"]["atif"], "uydurma": len(ad_["nihai"]["uydurma"]),
                              "zayif": len(ad_["nihai"]["zayif"])}}
    return {
        **({"atif": atif_tel} if atif_tel else {}),
        "telemetri_surumu": TELEMETRI_SURUMU, "kod_surumu": KOD_SURUMU, "protokol_surumu": k.get("protokol"),
        "git": git, "cli_surumleri": (k.get("on_kontrol") or {}).get("surumler"),
        "istenen_modeller": k.get("istenen_modeller"), "bildirilen_modeller": modeller,
        "durum": k.get("durum"), "arastirma": bool(k.get("arastirma")), "tur_siniri": k.get("tur_siniri"),
        "tur_sayisi": k.get("tur_sayisi"), "durma_nedeni": k.get("durma_nedeni"),
        "baslangic": k.get("baslangic"), "bitis": bitis, "sure_sn": k.get("sure_sn"), "cagri_sayisi": k.get("cagri_sayisi"),
        "asamalar": asamalar, "kelime": kelime, "cevap_kelime_tur_sonu": cevap_kelime,
        "elestiri_kategori_onem": elestiri_ko, "duzeltmeye_iletilen": iletilen, "kararlar": kararlar,
        "oylar": {"ilk": (k.get("ilk_oylama") or {}).get("oylar"), "ilk_durum": (k.get("ilk_oylama") or {}).get("durum"),
                  "ikinci": (sd.get("ikinci_oylama") or {}).get("oylar") if sd.get("durum") == "yapildi" else None,
                  "sonuc": k.get("durum")},
        "sentez": {"yazar": sentez.get("yazar"), "kelime": sentez_kelime,
                   "son_kelime": kelime_sayisi(k.get("taslak_metin") or "") if sentez else None,
                   "tur0_medyan_kelime": tur0_med,
                   "oran_tur0_medyan": round(sentez_kelime / tur0_med, 2) if sentez_kelime and tur0_med else None},
    }


class Konsey:
    def __init__(self, ayar: dict, zaman_asimi: int | None = None, kanit: str | None = None,
                 tohum: int | None = None, erken_cikis: bool = True,
                 tolerans: float = VARSAYILAN_TOLERANS, tur: int = VARSAYILAN_TUR, baglam: str | None = None,
                 arastir: bool = False, arastir_onay: bool = False, onay_fn=None, v029: dict | None = V029_OZELLIKLERI):
        if not TUR_MIN <= tur <= TUR_MAKS:
            raise ValueError(f"tur {TUR_MIN} ile {TUR_MAKS} arasında olmalı")
        self.ayar = ayar
        self.cozulemedi: list[dict] = []   # v0.29b: düzeltmede ÇÖZÜLEMEDİ yazılan maddeler (sentezde BELİRSİZLİKLER'e gider)
        self.v029 = dict(v029) if v029 else {}   # Aşama 3 bayrakları; varsayılan V029_OZELLIKLERI (açık); eski davranış yalnızca v029={} ile istenir
        self.erken_cikis = erken_cikis  # False: --erken-cikis-yok (yalnızca kontrol amaçlı)
        self.tolerans = tolerans
        self.tur = tur  # en fazla eleştiri-düzeltme turu (--tur)
        self.baglam = baglam or None  # --baglam: tüm turlarda "SORAN KİŞİ HAKKINDA" bloğu (kanıt paketi değil)
        self.zaman_asimi = zaman_asimi or int(ayar.get("cagri_zaman_asimi_sn", 600))
        self.kanit = kanit
        self.kanit_ham = kanit               # kullanıcının --kanit içeriği (araştırma paketi eklenmeden önce)
        # v0.31 (karar 74): --kanit maddelere bölünür ve K kimliği alır (araştırma paketi varsa kimlikleri ondan ÖNCE gelir)
        self.kullanici_maddeleri: list[dict] = []
        self.kaynak_maddeleri: list[dict] = []   # atıf denetiminin tablosu (kullanıcı kanıtı + araştırma paketi)
        self.atif_metinleri: dict[str, dict[str, str]] = {}   # aşama -> {model: metin} (kod denetimi için)
        if kanit and self.v029.get("atif"):
            self.kanit, self.kullanici_maddeleri = AT.kanit_kimlikle(kanit)
            self.kanit_ham = self.kanit
            self.kaynak_maddeleri = list(self.kullanici_maddeleri)
        self.arastir = arastir or arastir_onay  # v0.25 (karar 64): --arastir / --arastir-onay
        self.arastir_onay = arastir_onay
        self.onay_fn = onay_fn               # testler için; None ise terminalden sorulur
        self.arastirma: dict | None = None
        self.tohum = tohum if tohum is not None else random.SystemRandom().randrange(1_000_000)
        self.rng = random.Random(self.tohum)
        self.calisma = ayar["calisma_klasoru"]
        self.cagri_sayisi = 0
        zaman = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.kayit = Path(ayar["kayit_klasoru"]) / f"{zaman}_{self.tohum}"
        self.eksik: dict[str, dict[str, str]] = {}  # tur -> {sağlayıcı: açıklama}
        self.gercek_modeller: dict[str, str] = {}
        self.dogrulamalar: dict[str, list[str]] = {}  # sağlayıcı -> başarılı çağrıların doğrulama düzeyleri
        self.kota: dict[str, dict] = {}  # sağlayıcı -> en son okunan kota (şimdilik yalnızca codex)
        self.arac_sonuclari: dict[str, list[A.CagriSonucu]] = {}  # sağlayıcı -> tüm çağrılar (araç denetimi için)
        self.cagri_kayitlari: list[dict] = []  # v0.27 telemetri: {adim, ad, baslangic, bitis, kelime, gercek_model}
        self.asama_ek: dict[str, dict] = {}    # v0.27 telemetri: çağrı olmayan aşamalar (araştırma)

    def _calisma_klasorunu_hazirla(self):
        cal = Path(self.calisma).resolve()
        if cal == BURASI or BURASI in cal.parents:
            raise A.AyarHatasi(
                "Çalışma klasörü proje klasörünün içinde olamaz; yoksa CLI'lar CLAUDE.md/AGENTS.md'yi "
                "her konsey çağrısında okur (PROJE.md 6.3).")
        cal.mkdir(parents=True, exist_ok=True)

    async def _cagir(self, ad: str, prompt: str, adim: str) -> A.CagriSonucu:
        self.cagri_sayisi += 1
        bas = dt.datetime.now()
        s = await A.cagir(ad, self.ayar["saglayicilar"][ad], prompt, self.zaman_asimi, self.calisma,
                          self.kayit / f"{adim}_{ad}.json")
        self.cagri_kayitlari.append({"adim": adim, "ad": ad, "baslangic": bas.isoformat(timespec="milliseconds"),
                                     "bitis": dt.datetime.now().isoformat(timespec="milliseconds"),
                                     "kelime": kelime_sayisi(s.metin) if s.basarili else None,
                                     "gercek_model": s.gercek_model if s.basarili else None})
        if s.basarili and s.gercek_model:
            self.gercek_modeller[ad] = s.gercek_model
        if s.basarili:
            self.dogrulamalar.setdefault(ad, []).append(s.model_dogrulama or A.DOGRULAMA_YOK)
        if s.kota:
            self.kota[ad] = s.kota
        self.arac_sonuclari.setdefault(ad, []).append(s)
        return s

    async def _paralel(self, istekler: dict[str, str], tur: str) -> dict[str, A.CagriSonucu]:
        adlar = list(istekler)
        sonuclar = await asyncio.gather(*(self._cagir(ad, istekler[ad], tur) for ad in adlar))
        cikti = dict(zip(adlar, sonuclar))
        for ad, s in cikti.items():
            if not s.basarili:
                self.eksik.setdefault(tur, {})[ad] = f"{eksik_ipucu(s)}: {s.hata[:300]}"
        return cikti

    async def on_kontrol(self) -> dict:
        self._calisma_klasorunu_hazirla()
        bilgi = {"surumler": {}, "giris": ""}
        surumler = await asyncio.gather(*(A.surum_al(s, self.calisma, ad) for ad, s in self.ayar["saglayicilar"].items()))
        bilgi["surumler"] = dict(zip(self.ayar["saglayicilar"], surumler))
        if "claude" in self.ayar["saglayicilar"]:
            tamam, mesaj = await A.claude_giris_kontrol(self.ayar["saglayicilar"]["claude"], self.calisma)
            if not tamam:
                raise A.AyarHatasi(mesaj)
            bilgi["giris"] = mesaj
        return bilgi

    def _tur0_gerekce_modeli(self, karar: dict) -> str | None:
        """TUR0_UZLASI'da gerekçe olarak gösterilecek Tur 0 cevabının sahibi: değeri ortancaya en yakın model;
        eşitlikte tohumla belirlenir (ana rastgelelik akışına dokunmaz)."""
        degerler = karar.get("degerler") or {}
        if not degerler:
            return None
        ort = karar["ortanca"]
        fark = {ad: abs(d - ort) for ad, d in degerler.items()}
        en_az = min(fark.values())
        adaylar = sorted(ad for ad, f in fark.items() if f == en_az)
        return random.Random(f"{self.tohum}-gerekce").choice(adaylar)

    def _tur_dosyalari_yaz(self, n: int, elestiri_ham: dict, duzeltme_ham: dict, guncel: dict, sayimlar: dict,
                           elestiri_sayilari: dict) -> None:
        klasor = self.kayit / f"tur{n}"
        klasor.mkdir(parents=True, exist_ok=True)
        for ad, metin in elestiri_ham.items():
            (klasor / f"elestiri_{ad}.md").write_text(metin, encoding="utf-8")
        for ad, metin in duzeltme_ham.items():
            (klasor / f"degisiklik_{ad}.md").write_text(metin, encoding="utf-8")
        for ad, metin in guncel.items():
            (klasor / f"cevap_{ad}.md").write_text(metin, encoding="utf-8")
        with open(klasor / "madde_sayilari.json", "w", encoding="utf-8") as f:
            json.dump({"elestiri_sayilari": elestiri_sayilari, "degisiklik_sayimi": sayimlar}, f,
                      ensure_ascii=False, indent=2)

    async def _tur(self, n: int, soru: str, aktif: list[str], guncel: dict[str, str]) -> dict:
        """Bir eleştiri-düzeltme turu (karar 50). Dönen: guncel (yeni cevaplar), durdur, kayit."""
        # --- eleştiri: her model diğer modellerin güncel cevaplarını kimliksiz görür; kendi cevabı yok
        ilerleme(f"Tur {n}/{self.tur}: {len(aktif)} model diğerlerinin cevaplarını eleştiriyor...")
        haritalar: dict[str, dict[str, str]] = {}
        istekler = {}
        for okuyucu in aktif:
            digerleri = [a for a in aktif if a != okuyucu]
            self.rng.shuffle(digerleri)
            harita = {ETIKETLER[i]: yazar for i, yazar in enumerate(digerleri)}
            haritalar[okuyucu] = harita
            istekler[okuyucu] = p_elestiri(soru, self.kanit, [(e, guncel[y]) for e, y in harita.items()], self.baglam,
                                           self.v029)
        r_e = await self._paralel(istekler, f"tur{n}_elestiri")
        cozumler = {ad: elestiri_coz(s.metin, list(haritalar[ad])) for ad, s in r_e.items() if s.basarili}
        karsilastirmalar = []
        for okuyucu, c in cozumler.items():
            if c["daha_iyi"]:
                harita = haritalar[okuyucu]
                kaz = harita[c["daha_iyi"]]
                kay = next(y for e, y in harita.items() if e != c["daha_iyi"])
                karsilastirmalar.append({"hakem": okuyucu, "kazanan": kaz, "kaybeden": kay})
        durdur, durdur_nedeni = erken_durma_karari(cozumler)

        # --- düzeltme: her model kendi cevabını ve ona gelen eleştirileri alır
        alinan: dict[str, list[tuple[str, str, dict]]] = {}
        for okuyucu, c in cozumler.items():
            for etiket, yazar in haritalar[okuyucu].items():
                alinan.setdefault(yazar, []).append((okuyucu, etiket, c))
        istekler, atlanan, kimlikler, ham_gonderilen = {}, {}, {}, []
        gonderilmeyen_maddeler: dict[str, list[dict]] = {}
        madde_metinleri: dict[str, dict[str, str]] = {}   # v0.29b: {yazar: {kimlik: madde metni}}
        iletilen: dict[str, dict] = {}  # v0.27 telemetri: düzeltmeye giden maddelerin kategori × önem dağılımı
        yalniz_hata = n >= 2  # karar 60: 2. ve sonraki turlarda yalnızca HATALAR ve KANITSIZ İDDİALAR gönderilir
        v029_filtre = bool(self.v029.get("filtre"))
        if v029_filtre:
            yalniz_hata = False   # v0.29b süzgeci her turda aynıdır; karar 60'ın tur ayrımı yerine geçer
        for yazar in aktif:
            liste = alinan.get(yazar, [])
            if not liste:
                atlanan[yazar] = "eleştiri alınamadı"
                continue
            if all(madde_yok(c, e) for _, e, c in liste):
                atlanan[yazar] = "madde yok" if v029_filtre else "eleştirilerde madde yok"
                continue
            self.rng.shuffle(liste)
            parcalar, idler, ham = [], [], False
            for k, (_okuyucu, etiket, c) in enumerate(liste, 1):
                if v029_filtre:
                    metin, i, gonderilmeyen = elestiri_metni_suz_v029(k, c, etiket)
                else:
                    metin, i, gonderilmeyen = elestiri_metni_hazirla_ayrintili(k, c, etiket, yalniz_hata)
                parcalar.append(metin)
                if gonderilmeyen:
                    gonderilmeyen_maddeler.setdefault(yazar, []).extend(
                        {"degerlendirici": k, **g} for g in gonderilmeyen)
                if i is None:
                    ham = True
                else:
                    idler += i
            if v029_filtre and not ham and not idler:
                atlanan[yazar] = "madde yok"   # rapor: "düzeltme atlandı (madde yok)"; cevap aynen taşınır
                continue
            if yalniz_hata and not ham and not idler:
                atlanan[yazar] = "gönderilecek HATALAR/KANITSIZ İDDİALAR maddesi yok (2. tur ve sonrası yalnızca bunları alır)"
                continue
            if ham:
                ham_gonderilen.append(yazar)
            kimlikler[yazar] = None if ham else idler
            istekler[yazar] = p_duzeltme(soru, self.kanit, guncel[yazar], parcalar, self.baglam, ham, self.v029)
            madde_metinleri[yazar] = madde_metinleri_oku("\n".join(parcalar))
            iletilen[yazar] = ({"madde": None, "ham": True} if ham else gonderilen_madde_dagilimi("\n".join(parcalar)))
        if istekler:
            ilerleme(f"Tur {n}/{self.tur}: {len(istekler)} model cevabını düzeltiyor...")
            r_d = await self._paralel(istekler, f"tur{n}_duzeltme")
        else:
            r_d = {}
        yeni = dict(guncel)
        duzeltmeler: dict[str, dict] = {}
        duzeltme_ham: dict[str, str] = {}
        sayimlar: dict[str, dict] = {}
        for yazar in aktif:
            if yazar in atlanan:
                duzeltmeler[yazar] = {"durum": "atlandı", "neden": atlanan[yazar]}
                continue
            s = r_d[yazar]
            if not s.basarili:
                duzeltmeler[yazar] = {"durum": "başarısız", "neden": "çağrı hata verdi; önceki cevap geçerli"}
                continue
            d = duzeltme_coz(s.metin)
            duzeltme_ham[yazar] = s.metin
            if not d["gecerli"]:
                self.eksik.setdefault(f"tur{n}_duzeltme", {})[yazar] = (
                    f"geçersiz düzeltme çıktısı ({d['neden']}); önceki cevap geçerli kaldı")
                duzeltmeler[yazar] = {"durum": "geçersiz", "neden": d["neden"]}
                continue
            yeni[yazar] = d["cevap"]
            dayanakli = bool(self.v029.get("dayanak"))
            sayimlar[yazar] = (degisiklik_sayimi_v029 if dayanakli else degisiklik_sayimi)(kimlikler[yazar], d["kararlar"])
            duzeltmeler[yazar] = {"durum": "ok", "sayim": sayimlar[yazar],
                                  "gerekce": gerekce_sayimi(d["kayitlar"], kimlikler[yazar])}
            if dayanakli:
                duzeltmeler[yazar]["dayanak"] = dayanak_sayimi(d["kayitlar"], kimlikler[yazar])
                for kimlik, kd in d["kayitlar"].items():
                    if kd["karar"] == "COZULEMEDI" and (kimlikler[yazar] is None or kimlik in kimlikler[yazar]):
                        self.cozulemedi.append({
                            "tur": n, "kimlik": kimlik, "yazar": yazar,
                            "madde": (madde_metinleri.get(yazar) or {}).get(kimlik, "(madde metni okunamadı)"),
                            "neden": kd.get("gerekce") or kd.get("metin") or ""})

        elestiri_sayilari = {ad: c["sayilar"] for ad, c in cozumler.items()}
        self._tur_dosyalari_yaz(n, {ad: s.metin for ad, s in r_e.items() if s.basarili}, duzeltme_ham, yeni, sayimlar,
                                elestiri_sayilari)
        analiz = notr_hakem_analizi(aktif, karsilastirmalar)
        kayit = {
            "tur": n, "etiket_haritalari": haritalar,
            "elestiriler": {ad: {"bolum_ok": c["bolum_ok"], "sayilar": c["sayilar"], "daha_iyi": c["daha_iyi"],
                                 "tutarsiz": c["tutarsiz"], "agir_madde_metinde": c["agir_madde_metinde"],
                                 "kritik_madde_metinde": c["kritik_madde_metinde"],
                                 "maddeler": {e: len(m) for e, m in c["maddeler"].items()}}
                            for ad, c in cozumler.items()},
            "elestiri_basarisiz": [ad for ad, s in r_e.items() if not s.basarili],
            "ham_elestiri_gonderilen": ham_gonderilen,
            "yalniz_hata_kurali": yalniz_hata, "v029_filtre": v029_filtre,
            "gonderilmeyen_maddeler": gonderilmeyen_maddeler,
            "duzeltmeler": duzeltmeler, "notr_hakem": analiz,
            "erken_durma": durdur, "erken_durma_nedeni": durdur_nedeni,
            # v0.27 ölçüm alanları (telemetri.json kaynağı; akışı etkilemez)
            "elestiri_kategori_onem": {ad: kategori_onem_sayimi(madde_satirlari(c["ham"])) for ad, c in cozumler.items()},
            "duzeltmeye_iletilen": iletilen,
            "onceki_cevap_kelime": {ad: kelime_sayisi(guncel[ad]) for ad in aktif},
            "cevap_kelime": {ad: kelime_sayisi(yeni[ad]) for ad in aktif},
        }
        return {"guncel": yeni, "durdur": durdur, "kayit": kayit}

    async def _arastir(self, soru: str, kayit: dict) -> None:
        """v0.25 (karar 64): iki ayrı araştırmacı yalnızca soru + tarih ile kaynak toplar; paket kodla birleştirilir ve
        mevcut kanıt mekanizmasıyla (güvenilmeyen veri notuyla) koltuklara verilir. `--arastir-onay` paketi önce ekranda
        gösterip onay bekler. Araştırma tümden başarısızsa ya da onaylanmazsa ArastirmaDurdu (konsey çalışmaz)."""
        self.kayit.mkdir(parents=True, exist_ok=True)
        ilerleme("Araştırma: Gemini ve GPT araştırmacıları yalnızca soruyla web'de kaynak topluyor...")
        bas = dt.datetime.now()
        atif = bool(self.v029.get("atif"))
        a = await R.arastir(self.ayar, soru, kayit_klasoru=self.kayit,
                            kimlik_baslangic=len(self.kullanici_maddeleri) if atif else None)
        self.asama_ek["arastirma"] = {"baslangic": bas.isoformat(timespec="milliseconds"),
                                      "bitis": dt.datetime.now().isoformat(timespec="milliseconds")}
        self.arastirma = a
        kayit["arastirma"] = a
        (self.kayit / "arastirma_paketi.md").write_text(a["paket_metni"], encoding="utf-8")
        if a["durum"] == "basarisiz":
            hatalar = "; ".join(f"{r['etiket']}: {r['hata'][:200]}" for r in a["arastirmacilar"].values())
            raise R.ArastirmaDurdu(f"iki araştırmacı da başarısız ({hatalar}); konsey çalıştırılmadı. "
                                   f"Kayıtlar: {self.kayit}")
        if self.arastir_onay:
            print("\n=== ARAŞTIRMA PAKETİ (konseyden önce; güvenilmeyen veri) ===")
            print(R.kaynak_satiri(a))
            if a.get("gelecek_atilan"):
                print(R.gelecek_atilan_satiri(a))
            if a.get("etiket_sayimlari"):
                print(R.etiket_sayim_satiri({"etiketler": a["etiket_sayimlari"], "kaynak_turleri": a["kaynak_turleri"]}))
            print(a["paket_metni"])
            print("=== PAKET SONU ===")
            onay = self.onay_fn(a) if self.onay_fn else _terminalden_onay()
            kayit["arastirma"]["onay"] = bool(onay)
            if not onay:
                raise R.ArastirmaDurdu(f"paket onaylanmadı; konsey çalıştırılmadı. Kayıtlar: {self.kayit}")
        self.kanit = ArastirmaliKanit("\n\n".join(x for x in (self.kanit_ham, a["paket_metni"].strip()) if x))
        if atif:
            self.kaynak_maddeleri = list(self.kullanici_maddeleri) + AT.paket_maddeleri(a)
        kayit["kanit_var"] = True

    async def calistir(self, soru: str) -> dict:
        t0 = time.monotonic()
        on = await self.on_kontrol()
        kota_once = await kota_goruntusu(self.ayar, self.calisma)
        uyeler = list(self.ayar["saglayicilar"])
        kayit = {"surum": SURUM, "protokol": KOD_SURUMU, "soru": soru, "kanit_var": bool(self.kanit),
                 "baglam_var": bool(self.baglam), "tohum": self.tohum, "tur_siniri": self.tur,
                 "baslangic": dt.datetime.now().isoformat(timespec="seconds"), "on_kontrol": on,
                 "istenen_modeller": {ad: s["model"] for ad, s in self.ayar["saglayicilar"].items()},
                 "kota_once": kota_once}

        if self.arastir:
            try:
                await self._arastir(soru, kayit)
            except R.ArastirmaDurdu as e:
                kayit.update({"durum": "ARASTIRMA_DURDU", "not": str(e)[:300],
                              "sure_sn": round(time.monotonic() - t0, 1), "cagri_sayisi": self.cagri_sayisi})
                self._telemetri_yaz(kayit)
                raise

        # Tur 0: bağımsız cevaplar
        ilerleme(f"Tur 0: {len(uyeler)} model bağımsız cevap veriyor...")
        r0 = await self._paralel({ad: p_tur0(soru, self.kanit, self.baglam, self.v029) for ad in uyeler}, "tur0")
        aktif = [ad for ad in uyeler if r0[ad].basarili]
        kayit["tur0"] = {ad: s.sozluk() for ad, s in r0.items()}
        self.atif_metinleri["tur0"] = {ad: r0[ad].metin for ad in uyeler if r0[ad].basarili}
        karar = sayisal.tur0_uzlasi({ad: {"durum": s.durum, "metin": s.metin} for ad, s in r0.items()}, self.tolerans)
        kayit["erken_cikis"] = {"acik": self.erken_cikis, "karar": "erken_cikis" if karar["uzlasi"] and self.erken_cikis
                                else "tam_konsey", **karar}
        if self.erken_cikis and karar["uzlasi"]:
            kayit["erken_cikis"]["gerekce_modeli"] = self._tur0_gerekce_modeli(karar)
            ilerleme("Tur 0 uzlaşısı: SONUÇ değerleri uyuştu; eleştiri turları, sentez ve onay atlanıyor.")
            return await self._bitir(kayit, "TUR0_UZLASI", None, {}, t0,
                                     not_="Eleştiri turları, sentez ve onay atlandı.", ayar_kota=True)
        if len(aktif) < 2:
            return await self._bitir(kayit, "YETERSIZ_KATILIM", None, {}, t0,
                                     not_="Tur 0'da ikiden az model cevap verdi.")

        # Eleştiri-düzeltme turları
        guncel = {ad: r0[ad].metin.strip() for ad in aktif}
        turlar, durma = [], None
        for n in range(1, self.tur + 1):
            t = await self._tur(n, soru, aktif, guncel)
            guncel = t["guncel"]
            self.atif_metinleri[f"tur{n}_duzeltme"] = {ad: guncel[ad] for ad in aktif}
            turlar.append(t["kayit"])
            if t["durdur"]:
                # v0.27: "erken durdu" yalnızca tur sınırından önce durulduysa yazılır. Karar eleştiriden sonra,
                # düzeltmeden önce verilir (_tur: erken_durma_karari), ama o turun düzeltmesi yine çalışır; döngü
                # turu bitirdikten sonra çıkar.
                if n < self.tur:
                    durma = f"{n}. turda kritik madde bildirilmedi; erken durdu"
                else:
                    durma = f"tur sınırına ({self.tur}) ulaşıldı; {n}. turda kritik madde bildirilmedi"
                break
            if n == self.tur:
                durma = f"tur sınırına ({self.tur}) ulaşıldı; son tur: {t['kayit']['erken_durma_nedeni']}"
        kayit["turlar"] = turlar
        kayit["tur_sayisi"] = len(turlar)
        kayit["durma_nedeni"] = durma
        kayit["notr_hakem"] = {"birinci_tur": turlar[0]["notr_hakem"], "turlar": [t["notr_hakem"] for t in turlar]}
        kayit["son_cevaplar"] = guncel

        # Sentez: rastgele seçilen bir üye üç son cevabı birleştirir; karar yetkisi yok
        cevaplar = [guncel[ad] for ad in aktif]
        self.rng.shuffle(cevaplar)
        sira = aktif[:]
        self.rng.shuffle(sira)
        metin, sentezci = None, None
        for aday in sira:
            ilerleme(f"Sentez: ortak metni {GORUNEN_AD[aday]} yazıyor...")
            cz_metinler = [f"{c['madde']} (düzeltmede doğrulanamadı: {c['neden']})" for c in self.cozulemedi] or None
            s = await self._cagir(aday, p_sentez(soru, self.kanit, cevaplar, self.baglam, cz_metinler, self.v029), "sentez")
            if s.basarili:
                metin, sentezci = s.metin.strip(), aday
                break
            self.eksik.setdefault("sentez", {})[aday] = f"{eksik_ipucu(s)}: {s.hata[:300]}"
        if metin is None:
            return await self._bitir(kayit, "YETERSIZ_KATILIM", None, {}, t0, not_="Ortak metni yazabilecek model kalmadı.")
        ozet = metin_ozeti(metin)
        kayit["sentez"] = {"yazar": sentezci, "metin": metin, "metin_surumu": ozet}
        self.atif_metinleri["sentez"] = {sentezci: metin}
        if self.cozulemedi:   # sessiz kayıp olmasın: kod, BELİRSİZLİKLER'in doldurulup doldurulmadığını denetler
            kayit["cozulemedi"] = {"maddeler": self.cozulemedi,
                                   "belirsizlikte": belirsizlik_bolumu_dolu_mu(metin)}

        # Onay: her model sentezi ve KENDİ son cevabını görür; aynı metin sürümüne ayrı oturumlarda oy
        ilerleme(f"Onay: {len(aktif)} model ortak metni oyluyor...")
        r2 = await self._paralel({ad: p_onay(soru, self.kanit, metin, ozet, guncel[ad], self.baglam, None, self.v029) for ad in aktif},
                                 "onay")
        pusulalar = {ad: pusula_coz(s.metin, ozet) for ad, s in r2.items() if s.basarili}
        kayit["onay"] = {"pusulalar": pusulalar, "sonuclar": {ad: s.sozluk() for ad, s in r2.items()}}
        durum = sonucu_belirle({ad: p["oy"] for ad, p in pusulalar.items()})
        kayit["ilk_oylama"] = {"durum": durum, "metin_surumu": ozet,
                               "oylar": {ad: p["oy"] for ad, p in pusulalar.items()}}

        # RET sonrası tek seferlik sentez düzeltmesi (karar 62, açık soru 24)
        itirazlar = somut_itirazlar(pusulalar)
        if itirazlar:
            sd = await self._sentez_duzelt(soru, metin, ozet, sentezci, itirazlar, guncel, aktif, kayit, durum)
            if sd:
                metin, ozet, pusulalar, durum = sd
        return await self._bitir(kayit, durum, metin, pusulalar, t0, sentezci=sentezci, ozet=ozet)

    async def _sentez_duzelt(self, soru, metin, ozet, sentezci, itirazlar, guncel, aktif, kayit, ilk_durum):
        """RET'te somut itiraz varsa sentezi yazan model itirazları değerlendirir ve metni bir kez düzeltir; yeni metin yeni
        sürüm özetiyle yeniden oylanır. Yalnızca bir kez yapılır. Düzeltme çağrısı başarısız/geçersizse, metin değişmediyse
        ya da ikinci oylamada en az iki geçerli katılım yoksa ilk oylamanın sonucu geçerli kalır; None döner.
        Başarıda (yeni_metin, yeni_ozet, ikinci_pusulalar, ikinci_durum) döner."""
        self.rng.shuffle(itirazlar)
        sd = {"denendi": True, "sentezci": sentezci, "ilk_ozet": ozet, "ilk_oylama_ozeti": dict(kayit["ilk_oylama"]),
              "itirazlar": [{"kimlik": f"R{i}", "oy_veren": ad, "metin": t,
                           "onem": itiraz_onemi(kayit["onay"]["pusulalar"], ad, t)}
                          for i, (ad, t) in enumerate(itirazlar, 1)]}
        kayit["sentez_duzeltme"] = sd
        ilerleme(f"Sentez düzeltmesi: {len(itirazlar)} somut itiraz var; {GORUNEN_AD[sentezci]} metni bir kez düzeltiyor...")
        s = await self._cagir(sentezci, p_sentez_duzeltme(soru, self.kanit, metin, [t for _, t in itirazlar], self.baglam,
                                                 [x["onem"] for x in sd["itirazlar"]], self.v029),
                              "sentez_duzeltme")
        if not s.basarili:
            sd["durum"] = "cagri_basarisiz"
            sd["neden"] = f"{eksik_ipucu(s)}: {s.hata[:300]}"
            self.eksik.setdefault("sentez_duzeltme", {})[sentezci] = sd["neden"]
            return None
        d = sentez_duzeltme_coz(s.metin)
        sd["kararlar"], sd["kayitlar"] = d["kararlar"], d["kayitlar"]
        sd["ham_cikti"] = s.metin
        if not d["gecerli"]:
            sd["durum"] = "gecersiz_cikti"
            sd["neden"] = d["neden"]
            self.eksik.setdefault("sentez_duzeltme", {})[sentezci] = (
                f"geçersiz düzeltme çıktısı ({d['neden']}); ilk oylamanın sonucu geçerli kaldı")
            return None
        yeni = d["metin"].strip()
        yeni_ozet = metin_ozeti(yeni)
        sd["yeni_ozet"] = yeni_ozet
        sd["yeni_metin"] = yeni
        if yeni_ozet == ozet:
            sd["durum"] = "degismedi"
            sd["neden"] = "metin değişmedi (itirazların hepsi RED); yeniden oylama yapılmadı, ilk oylama geçerli"
            return None
        ilerleme(f"Sentez düzeltmesi: yeni metin ({yeni_ozet}) yeniden oylanıyor...")
        # v0.24 (karar 63): ikinci oylama düzeltme farkını, ilk itirazları ve ele alınışlarını görür
        ikinci = {"fark": sentez_farki(metin, yeni),
                  "itirazlar": [{"kimlik": x["kimlik"], "onem": x["onem"], "metin": x["metin"],
                                 **{a: (d["kayitlar"].get(x["kimlik"]) or {}).get(a, "")
                                    for a in ("karar", "gerekce", "degisen")}} for x in sd["itirazlar"]]}
        sd["ikinci_oylama_baglami"] = {"fark_uzunlugu": len(ikinci["fark"])}
        r3 = await self._paralel({ad: p_onay(soru, self.kanit, yeni, yeni_ozet, guncel[ad], self.baglam, ikinci)
                                  for ad in aktif}, "onay2")
        pus2 = {ad: pusula_coz(x.metin, yeni_ozet, ikinci_oylama=True) for ad, x in r3.items() if x.basarili}
        kayit["onay2"] = {"pusulalar": pus2, "sonuclar": {ad: x.sozluk() for ad, x in r3.items()}}
        durum2 = sonucu_belirle({ad: p["oy"] for ad, p in pus2.items()})
        sd["ikinci_oylama"] = {"durum": durum2, "metin_surumu": yeni_ozet, "oylar": {ad: p["oy"] for ad, p in pus2.items()}}
        if durum2 == "YETERSIZ_KATILIM":
            sd["durum"] = "ikinci_oylama_yapilamadi"
            sd["neden"] = "ikinci oylamada ikiden az model katıldı; ilk oylamanın sonucu geçerli"
            return None
        sd["durum"] = "yapildi"
        sd["ilk_durum"] = ilk_durum
        return yeni, yeni_ozet, pus2, durum2

    def _telemetri_yaz(self, kayit: dict) -> None:
        """v0.27: kayit klasörüne telemetri.json. En iyi çaba: hata koşuyu ve sonucu asla bozmaz."""
        try:
            tel = telemetri_olustur(kayit, self.cagri_kayitlari, self.asama_ek, git_bilgisi(),
                                    dt.datetime.now().isoformat(timespec="milliseconds"))
            self.kayit.mkdir(parents=True, exist_ok=True)
            with open(self.kayit / "telemetri.json", "w", encoding="utf-8") as f:
                json.dump(tel, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            kayit["telemetri_hatasi"] = f"{type(e).__name__}: {e}"
            ilerleme(f"Uyarı: telemetri.json yazılamadı ({type(e).__name__}: {e})")

    async def _bitir(self, kayit, durum, metin, pusulalar, t0, sentezci=None, ozet=None, not_=None,
                     ayar_kota=False) -> dict:
        kayit["kota_sonra"] = await kota_goruntusu(self.ayar, self.calisma)
        if self.kaynak_maddeleri:   # v0.31: [K#] atıflarının KOD denetimi (kanıt paketi ya da --kanit varken)
            nihai = metin
            if durum == "TUR0_UZLASI":   # raporda gösterilen metin: gerekçe olarak seçilen Tur 0 cevabı
                gm = (kayit.get("erken_cikis") or {}).get("gerekce_modeli")
                nihai = (self.atif_metinleri.get("tur0") or {}).get(gm)
            kayit["kaynak_maddeleri"] = self.kaynak_maddeleri
            kayit["atif_denetimi"] = AT.denetim_hesapla(self.atif_metinleri, nihai, self.kaynak_maddeleri)
        kayit.update({
            "durum": durum,
            "onaylanan_metin": metin if durum in ONAYLI_DURUMLAR else None,
            "taslak_metin": metin,
            "eksik_katilim": self.eksik,
            "gercek_modeller": self.gercek_modeller,
            "model_dogrulama": {ad: dogrulama_ozeti(d) for ad, d in self.dogrulamalar.items()},
            "kota": self.kota,
            "arac_denetimi": {ad: arac_toplami(s) for ad, s in self.arac_sonuclari.items()},
            "cagri_sayisi": self.cagri_sayisi,
            "sure_sn": round(time.monotonic() - t0, 1),
            "not": not_,
        })
        self.kayit.mkdir(parents=True, exist_ok=True)
        with open(self.kayit / "kayit.json", "w", encoding="utf-8") as f:
            json.dump(kayit, f, ensure_ascii=False, indent=2)
        if metin:
            (self.kayit / "taslak.md").write_text(metin, encoding="utf-8")
        self._telemetri_yaz(kayit)
        kayit["kayit_yolu"] = str(self.kayit)
        ozet_rapor, ayrinti = rapor_olustur(kayit, pusulalar, sentezci, ozet)
        (self.kayit / "rapor.md").write_text(ozet_rapor, encoding="utf-8")
        (self.kayit / "ayrinti.md").write_text(ayrinti, encoding="utf-8")
        kayit["ozet_rapor"] = ozet_rapor
        kayit["ayrinti"] = ayrinti
        kayit["rapor"] = ozet_rapor + "\n---\n\n" + ayrinti  # tam metin (özet rapor + ayrıntı)
        kayit["kayit_klasoru"] = str(self.kayit)
        return kayit



# --------------------------------------------------------------------------- rapor (karar 50: %80 cevap / %20 geri kalan)

RET_KISA_KELIME = 30


def kisalt(metin: str, kelime: int = RET_KISA_KELIME) -> str:
    k = (metin or "").split()
    return " ".join(k[:kelime]) + (" …" if len(k) > kelime else "")


def uyari_satirlari(k: dict, pusulalar: dict) -> list[str]:
    """Her ihlal türü ana raporda görünür olmalı: model uyuşmazlığı, araç ihlali, eksik katılım, biçim sorunu
    (ayrıca geçersiz oy pusulası). Hiçbiri yalnızca ayrıntıda kalmaz."""
    u = []
    atif_u = AT.uyari_satiri(k.get("atif_denetimi"))
    if atif_u:
        u.append(atif_u)   # durum hesabı değişmez; yalnızca uyarı
    for tur, d in (k.get("eksik_katilim") or {}).items():
        for ad, aciklama in d.items():
            if "cevap veren model istenen model değil" in aciklama:
                tur_adi = "Model uyuşmazlığı"
            elif aciklama.startswith("araç çalıştırdı") or "araç denemesi nedeniyle" in aciklama:
                tur_adi = "Araç ihlali"
            else:
                tur_adi = "Eksik katılım"
            u.append(f"{tur_adi} — {GORUNEN_AD[ad]} ({tur}): {aciklama.split(': ', 1)[0] if tur_adi == 'Eksik katılım' else aciklama.splitlines()[0][:160]}")
    for ad, t in (k.get("arac_denetimi") or {}).items():
        ihlaller = []
        if t.get("ihlal"):
            ihlaller.append(f"{t['ihlal']} çağrıda araç ihlali")
        if t.get("codex_web_aramasi"):
            ihlaller.append(f"{t['codex_web_aramasi']} web arama olayı")
        if t.get("codex_arac_cagrisi") or t.get("codex_komutlar"):
            ihlaller.append("araç/komut çağrısı")
        if t.get("codex_bilinmeyen_olaylar"):
            ihlaller.append("bilinmeyen olay türü")
        if t.get("bos_cevap_arac_denemesi"):
            ihlaller.append(f"{t['bos_cevap_arac_denemesi']} çağrı araç denemesi nedeniyle boş")
        if ihlaller:
            u.append(f"Araç ihlali — {GORUNEN_AD[ad]}: " + "; ".join(ihlaller) + " (ayrıntı: ayrinti.md)")
    if k.get("taslak_metin"):
        for b in bicim_uyarilari(k["taslak_metin"]):
            u.append(f"Biçim sorunu — {b}")
    cz = k.get("cozulemedi")
    if cz and not cz.get("belirsizlikte"):
        u.append(f"Düzeltmede {len(cz['maddeler'])} eleştiri maddesi ÇÖZÜLEMEDİ olarak işaretlendi, ama ortak metnin "
                 "BELİRSİZLİKLER bölümü boş ya da 'Yok'; bu maddeler sentezde görünmüyor (ayrıntı: ayrinti.md)")
    ar = k.get("arastirma")
    if ar and ar["durum"] == "kismi":
        for ad, r in ar["arastirmacilar"].items():
            if r["durum"] != "ok":
                u.append(f"Araştırma — {r['etiket']} başarısız ({r['hata'][:120]}); diğerinin paketiyle devam edildi")
    for ad, p in (pusulalar or {}).items():
        if not p["gecerli"]:
            u.append(f"Geçersiz oy pusulası — {GORUNEN_AD[ad]}: {p['not']} (çekimser sayıldı)")
    return u


def oy_sayilari(pusulalar: dict) -> tuple[int, int, int]:
    oylar = [p["oy"] for p in (pusulalar or {}).values()]
    return oylar.count("KABUL"), oylar.count("RET"), oylar.count("CEKIMSER")


def oy_dagilimi(oylar: dict) -> str:
    v = list((oylar or {}).values())
    return f"{v.count('KABUL')} KABUL / {v.count('RET')} RET / {v.count('CEKIMSER')} ÇEKİMSER"


def sentez_duzeltme_notu(sd: dict) -> str | None:
    """Konsey notundaki tek satır (karar 62): düzeltme yapıldıysa iki oylamanın sonucu, yapılamadıysa nedeni."""
    if not sd:
        return None
    if sd.get("durum") == "yapildi":
        i, y = sd["ilk_oylama_ozeti"], sd["ikinci_oylama"]
        return (f"Sentez itirazlara göre bir kez düzeltildi. 1. oylama: {oy_dagilimi(i['oylar'])} ({i['durum']}); "
                f"2. oylama: {oy_dagilimi(y['oylar'])} ({y['durum']}); sonuç 2. oylamaya göre.")
    return (f"Sentez düzeltmesi denendi ama uygulanmadı ({sd.get('neden', sd.get('durum'))}); "
            "ilk oylamanın sonucu geçerli.")


def tum_oylamalar(k: dict) -> list[tuple[str, dict]]:
    """[(oylama adı, pusulalar)]: ilk oylama ve varsa ikinci oylama."""
    sonuc = []
    if (k.get("onay") or {}).get("pusulalar"):
        sonuc.append(("1. oylama" if k.get("onay2") else "Oylama", k["onay"]["pusulalar"]))
    if (k.get("onay2") or {}).get("pusulalar"):
        sonuc.append(("2. oylama", k["onay2"]["pusulalar"]))
    return sonuc


def yazar_disi_oylar_notu(k: dict) -> str | None:
    """v0.27: Konsey notunda sentez yazarı ve her oylamada yazar dışı oylar. Yazar dışı = sentezi yazan model dışındaki
    üyeler; yazar kendi metnine oy verdiği için yazar dışı oylar bağımsız onay işaretidir. Oy sayımını ve sonucu
    değiştirmez, yalnızca gösterir. Örnek: "Sentez yazarı: Gemini · Yazar dışı oylar: 1/2 KABUL (Claude KABUL, GPT RET)"."""
    yazar = (k.get("sentez") or {}).get("yazar")
    oylamalar = tum_oylamalar(k)
    if not yazar or not oylamalar:
        return None
    parcalar = []
    for ad, pusulalar in oylamalar:
        dis = {a: p for a, p in pusulalar.items() if a != yazar}
        if not dis:
            continue
        kabul = sum(1 for p in dis.values() if p["oy"] == "KABUL")
        ayrinti = ", ".join(f"{GORUNEN_AD[a]} {p['oy']}" for a, p in dis.items())
        parcalar.append((ad, f"{kabul}/{len(dis)} KABUL ({ayrinti})"))
    if not parcalar:
        return None
    if len(parcalar) == 1:
        govde = f"Yazar dışı oylar: {parcalar[0][1]}"
    else:
        govde = "Yazar dışı oylar — " + "; ".join(f"{ad}: {m}" for ad, m in parcalar)
    return f"Sentez yazarı: {GORUNEN_AD[yazar]} · {govde}"


def ek_not_notu(k: dict) -> str | None:
    """Konsey notundaki tek satır (karar 63): oy sonucunu değiştirmeyen itirazların sayısı."""
    ek = sum(ek_not_sayisi(p) for _, p in tum_oylamalar(k))
    donusen = sum(1 for _, p in tum_oylamalar(k) for x in p.values() if x.get("orijinal_oy") == "RET")
    if not ek and not donusen:
        return None
    return (f"Ek notlar: oy sonucunu değiştirmeyen {ek} itiraz (küçük ya da değişmeyen metne yönelik)"
            + (f"; {donusen} RET oyu yalnızca bu tür itiraz içerdiği için kodla KABUL sayıldı" if donusen else "")
            + " (tam metin: ayrinti.md).")


def sure_metni(sn: float) -> str:
    return f"{sn:.0f} sn" if sn < 60 else f"{sn / 60:.1f} dk".replace(".", ",")


def baslik_satiri(k: dict, pusulalar: dict) -> str:
    kabul, ret, cek = oy_sayilari(pusulalar)
    oy = f"{kabul} KABUL / {ret} RET / {cek} ÇEKİMSER" if pusulalar else "oy yok"
    ek = " (oybirliği değildir)" if k["durum"] == "TUR0_UZLASI" else ""
    return (f"# Konsey: {k['durum']}{ek} · {oy} · {k.get('tur_sayisi', 0)} tur · {sure_metni(k['sure_sn'])}")


def ret_itirazlari(pusulalar: dict, kelime: int = RET_KISA_KELIME) -> list[tuple[str, str]]:
    sonuc = []
    for ad, p in pusulalar.items():
        if p["oy"] == "RET":
            neden = (p["itirazlar"][0] if p["itirazlar"] else "") or p["gerekce"]
            sonuc.append((GORUNEN_AD[ad], kisalt(neden, kelime)))
    return sonuc


def dogrulama_notu(k: dict) -> str:
    if k.get("arastirma"):
        return ("Doğrulama: internetten toplanmış araştırma paketi verildi (güvenilmeyen veri; koltuklar çevrimdışı); "
                "paketle doğrulanmayan iddialar BELİRSİZLİKLER bölümünde.")
    if k["kanit_var"]:
        return "Doğrulama: kanıt paketi verildi; paketle doğrulanmayan iddialar BELİRSİZLİKLER bölümünde."
    return ("Doğrulama: kanıt paketi verilmedi, modellerin web ve araçları kapalıydı; olgusal iddialar doğrulanmamış "
            "ortak kanaattir.")


def ozet_rapor_olustur(k: dict, pusulalar: dict, sentezci, ozet) -> str:
    sat = [baslik_satiri(k, pusulalar), ""]
    for u in uyari_satirlari(k, pusulalar):
        sat.append(f"> ⚠ **UYARI:** {u}")
    if sat[-1] != "":
        sat.append("")
    durum = k["durum"]
    if durum in ONAYLI_DURUMLAR and k.get("onaylanan_metin"):
        sat += [k["onaylanan_metin"].strip(), ""]
    elif durum == "UZLASI_YOK" and k.get("taslak_metin"):
        sat += ["> **ONAYLANMADI — konsey bu metinde uzlaşamadı.**"]
        for ad, neden in ret_itirazlari(pusulalar):
            sat.append(f"> - RET itirazı ({ad}): {neden or 'gerekçe verilmedi'}")
        sat += ["", k["taslak_metin"].strip(), ""]
    elif durum == "TUR0_UZLASI":
        e = k["erken_cikis"]
        degerler = " · ".join(f"{GORUNEN_AD[ad]} {d:g} {e['birim']}".strip() for ad, d in e["degerler"].items())
        sat += [f"Tur 0 SONUÇ değerleri uyuştu: {degerler}. Ortanca: **{e['ortanca']:g} {e['birim']}**".rstrip() +
                f" (tolerans: göreli fark ≤ {e['tolerans']:g}).", ""]
        gm = e.get("gerekce_modeli")
        gerekce = (k["tur0"].get(gm) or {}).get("metin") if gm else None
        if gerekce:
            sat += ["> Gerekçe: bir üyenin Tur 0 cevabı; diğer ikisi aynı sonucu buldu; metin onaylanmadı.", "",
                    gerekce.strip(), ""]
    else:
        sat += [f"Ortak cevap üretilemedi. {k.get('not') or ''}".strip(), ""]
    if k.get("atif_denetimi"):   # v0.31: kodla üretilen bölümler (model yazmaz)
        sat += ["---", ""] + AT.kaynaklar_bolumu(k["atif_denetimi"], k.get("kaynak_maddeleri") or []) + \
            AT.denetim_bolumu(k["atif_denetimi"])
    sat += ["---", "", "## Konsey notu", ""]
    if pusulalar:
        parcalar = []
        for ad, p in pusulalar.items():
            oy = f"{GORUNEN_AD[ad]} {p['oy']}"
            if p["oy"] == "RET" and durum != "UZLASI_YOK":
                neden = (p["itirazlar"][0] if p["itirazlar"] else "") or p["gerekce"]
                oy += f" ({kisalt(neden)})" if neden else ""
            parcalar.append(oy)
        sat.append("- Oylar: " + " · ".join(parcalar))
    else:
        sat.append("- Oylar: yok" + (" (Tur 0 uzlaşısı; oylama yapılmadı)" if durum == "TUR0_UZLASI" else ""))
    if durum == "TUR0_UZLASI":
        sat.append("- Turlar: Tur 0 erken çıkışı; eleştiri turu yapılmadı.")
    else:
        sinir = k.get("tur_siniri")
        sat.append(f"- Turlar: {k.get('tur_sayisi', 0)}" + (f"/{sinir}" if sinir else "") + " eleştiri-düzeltme turu yapıldı"
                   + (f"; {k['durma_nedeni']}." if k.get("durma_nedeni") else "."))
    sdn = sentez_duzeltme_notu(k.get("sentez_duzeltme"))
    if sdn:
        sat.append(f"- {sdn}")
    ydn = yazar_disi_oylar_notu(k)
    if ydn:
        sat.append(f"- {ydn}")
    ekn = ek_not_notu(k)
    if ekn:
        sat.append(f"- {ekn}")
    if k.get("arastirma"):
        sat.append(f"- {R.kaynak_satiri(k['arastirma'])}")
    sat.append(f"- {dogrulama_notu(k)}")
    sat.append(f"- Kayıt: {k.get('kayit_yolu', '')} (ayrıntı: ayrinti.md)")
    return "\n".join(sat) + "\n"


def ayrinti_olustur(k: dict, pusulalar: dict, sentezci, ozet) -> str:
    sat = [f"# Konsey ayrıntısı: {k['durum']}", "", DURUM_ACIKLAMA[k["durum"]]]
    if k.get("not"):
        sat += ["", f"Not: {k['not']}"]
    sat += ["", "## Soru", "", k["soru"]]
    if k.get("baglam_var"):
        sat += ["", "Soran kişi bağlamı (`--baglam`) verildi; kullanıcı beyanıdır, doğrulama notunu etkilemedi."]
    if k.get("taslak_metin"):
        sat += ["", f"Ortak metin: sürüm {ozet}, yazan {GORUNEN_AD.get(sentezci, '?')}, "
                    f"{kelime_sayisi(k['taslak_metin'])} kelime."]
    for u in (bicim_uyarilari(k["taslak_metin"]) if k.get("taslak_metin") else []):
        sat.append(f"- Biçim uyarısı: {u} (Uyarıdır; oylamayı etkilemez.)")
    sat += AT.ayrinti_tablosu(k.get("atif_denetimi"))
    cz = k.get("cozulemedi")
    if cz:
        sat += ["", f"## ÇÖZÜLEMEDİ maddeler ({len(cz['maddeler'])}; sentezde BELİRSİZLİKLER'e taşınması istendi; "
                    f"ortak metnin BELİRSİZLİKLER bölümü {'dolu' if cz.get('belirsizlikte') else 'BOŞ ya da Yok'})", ""]
        for c in cz["maddeler"]:
            sat.append(f"- (tur {c['tur']}, {GORUNEN_AD.get(c['yazar'], c['yazar'])}, {c['kimlik']}) {c['madde']} — "
                       f"modelin notu: {c['neden']}")

    # Tur 0 erken çıkışı
    e = k.get("erken_cikis")
    if e:
        if e["karar"] == "erken_cikis":
            sat += ["", "## Tur 0 uzlaşısı", ""]
            for ad, d in e["degerler"].items():
                sat.append(f"- {GORUNEN_AD[ad]}: SONUÇ {d:g} {e['birim']}")
            sat += [f"- Ortanca: {e['ortanca']:g} {e['birim']}; tolerans ≤ {e['tolerans']:g} (en büyük fark "
                    f"{e['kosullar']['d_tolerans_icinde']['en_buyuk_goreli_fark']:.4g})",
                    f"- Gerekçe olarak gösterilen Tur 0 cevabı: {GORUNEN_AD.get(e.get('gerekce_modeli'), '?')} "
                    "(değeri ortancaya en yakın; eşitlikte tohum)"]
        elif not e.get("acik", True):
            sat += ["", "> Tur 0 erken çıkışı kapalıydı (--erken-cikis-yok)."]
        elif e.get("saglanmayan"):
            sat += ["", "> Tur 0 erken çıkışı yapılmadı; sağlanmayan koşul(lar): "
                    + "; ".join(f"{ad[0]}) {e['kosullar'][ad]['ayrinti']}" for ad in e["saglanmayan"]) + "."]

    # Eleştiri-düzeltme turları
    for t in k.get("turlar") or []:
        n = t["tur"]
        sat += ["", f"## Tur {n}: eleştiri ve düzeltme", ""]
        for okuyucu, h in t["etiket_haritalari"].items():
            c = t["elestiriler"].get(okuyucu)
            if c is None:
                sat.append(f"- {GORUNEN_AD[okuyucu]} eleştirisi: **alınamadı**")
                continue
            ayrinti = []
            for etiket, yazar in h.items():
                s = (c["sayilar"] or {}).get(etiket)
                ayrinti.append(f"{GORUNEN_AD[yazar]} cevabı: " + (f"kritik {s['kritik']}, önemli {s['onemli']}, küçük {s['kucuk']}"
                                                                    if s else "sayılar okunamadı"))
            notlar = []
            if not c["bolum_ok"]:
                notlar.append("bölüm işaretleri okunamadı (eleştirinin tamamı sahiplerine gönderildi)")
            if c["tutarsiz"]:
                notlar.append("JSON 0 kritik diyor ama metinde kritik ya da önemi okunamayan madde var (tutarsız)")
            sat.append(f"- {GORUNEN_AD[okuyucu]} eleştirisi → " + "; ".join(ayrinti)
                       + (f" [{'; '.join(notlar)}]" if notlar else ""))
        sat.append(f"- Erken durma: {'evet' if t['erken_durma'] else 'hayır'} ({t['erken_durma_nedeni']})")
        a = t["notr_hakem"]
        if a["notr_hakem_durumu"] == "olculmedi":
            sat.append("- Nötr hakem: ölçülmedi (2 cevap)")
        else:
            for c in a["karsilastirmalar"]:
                if c["kazanan"]:
                    sat.append(f"- {GORUNEN_AD[c['kazanan']]}>{GORUNEN_AD[c['kaybeden']]} (hakem: {GORUNEN_AD[c['hakem']]})")
                else:
                    sat.append(f"- {GORUNEN_AD[c['cift'][0]]}–{GORUNEN_AD[c['cift'][1]]}: eksik")
            d = a["notr_hakem_durumu"]
            sat.append("- Nötr hakem galibi: " + (GORUNEN_AD[a["notr_hakem_galibi"]] if d == "galip"
                                                   else "net galip yok" if d == "net_galip_yok" else "belirlenemedi"))
        for yazar, d in t["duzeltmeler"].items():
            if d["durum"] == "ok":
                s = d["sayim"]
                sat.append(f"- {GORUNEN_AD[yazar]} düzeltmesi: eleştiri maddesi "
                           + (f"{s['madde']}" if s["madde"] is not None else "?")
                           + f", KABUL {s['kabul']}, KISMEN KABUL {s.get('kismen', 0)}, RED {s['red']}"
                           + (f", yanıtsız {s['yanitsiz']}" if s["yanitsiz"] is not None else ", kimlik eşlemesi yapılamadı")
                           + (f", tanınmayan kimlik {s['taninmayan']}" if s.get("taninmayan") else "")
                           + (f"; RED oranı %{100 * s['red'] / s['madde']:.0f}" if s.get("madde") else "")
                           + (f"; gerekçe yazılan KABUL/KISMEN KABUL {d['gerekce']['gerekceli']}/{d['gerekce']['kabul_kismen']}"
                              if d.get("gerekce") else "")
                           + (f"; ÇÖZÜLEMEDİ {s.get('cozulemedi', 0)}; dayanaksız KABUL/KISMEN KABUL "
                              f"{d['dayanak']['dayanaksiz']}/{d['dayanak']['kabul_kismen']}"
                              + (f" ({', '.join(d['dayanak']['dayanaksiz_kimlikler'])})" if d['dayanak']['dayanaksiz'] else "")
                              if d.get("dayanak") else ""))
            else:
                sat.append(f"- {GORUNEN_AD[yazar]} düzeltmesi: {d['durum']} ({d['neden']}); önceki cevap geçerli")
        if t.get("yalniz_hata_kurali") or t.get("v029_filtre"):
            sat.append("- v0.29b: düzeltmeye HATALAR, KANITSIZ İDDİALAR ve AŞIRI GENELLEME / KAPSAM HATASI "
                       "altındaki bütün maddeler (küçük dahil) ve EKSİK NOKTALAR'ın kritik/önemli maddeleri gönderildi; "
                       "EKSİK'in küçük maddeleri ve öneriler gitmedi."
                       if t.get("v029_filtre") else
                       "- Karar 60: bu turda düzeltmeye yalnızca HATALAR ve KANITSIZ İDDİALAR maddeleri gönderildi.")
            for yazar, liste in (t.get("gonderilmeyen_maddeler") or {}).items():
                sat.append(f"- {GORUNEN_AD[yazar]} cevabına gelen, düzeltmeye GÖNDERİLMEYEN {len(liste)} madde:")
                for g in liste:
                    sat.append(f"  - (değerlendirici {g['degerlendirici']}, {g['alt_baslik']}"
                               + (f"; neden: {g['neden']}" if g.get("neden") else "") + f") {g['metin']}")
        sat.append(f"- Dosyalar: tur{n}/ (elestiri_*.md, degisiklik_*.md, cevap_*.md, madde_sayilari.json)")
    if k.get("tur_sayisi") is not None and k.get("durma_nedeni"):
        sat += ["", f"Turlar: {k['tur_sayisi']} (sınır {k.get('tur_siniri')}); {k['durma_nedeni']}."]
    nh = k.get("notr_hakem")
    if nh:
        a = nh["birinci_tur"]
        d = a["notr_hakem_durumu"]
        sat += ["", "## Nötr hakem (1. tur; bilgi amaçlı, oyu ve sonucu etkilemez)", "",
                "Her çift, çiftte yer almayan üyenin eleştirisindeki 'daha_iyi' alanıdır. Bu tur, cevaplar henüz "
                "birbirinin eleştirisinden etkilenmeden yapıldığı için ana ölçüdür; sonraki turlar yukarıda.",
                "- Sonuç: " + (GORUNEN_AD[a["notr_hakem_galibi"]] if d == "galip" else
                               "ölçülmedi (2 cevap)" if d == "olculmedi" else
                               "net galip yok" if d == "net_galip_yok" else "belirlenemedi")]

    sd = k.get("sentez_duzeltme")
    if sd:
        sat += ["", "## Sentez düzeltmesi (RET sonrası, tek seferlik; karar 62)", "",
                f"- Sentezi yazan: {GORUNEN_AD.get(sd.get('sentezci'), '?')}; itiraz sayısı: {len(sd.get('itirazlar') or [])}; "
                f"durum: {sd.get('durum')}" + (f" ({sd['neden']})" if sd.get("neden") else "")]
        io = k.get("ilk_oylama") or {}
        sat.append(f"- 1. oylama (sürüm {io.get('metin_surumu')}): {oy_dagilimi(io.get('oylar'))} → {io.get('durum')}")
        if sd.get("ikinci_oylama"):
            y = sd["ikinci_oylama"]
            sat.append(f"- 2. oylama (sürüm {y['metin_surumu']}): {oy_dagilimi(y['oylar'])} → {y['durum']}")
        for it in sd.get("itirazlar") or []:
            kk = (sd.get("kayitlar") or {}).get(it["kimlik"]) or {}
            sat.append(f"- {it['kimlik']} ({GORUNEN_AD.get(it['oy_veren'], '?')} itirazı): {it['metin']}")
            if kk:
                sat.append(f"  - Sentez yazarının kararı: {kk['karar']}"
                           + (f" — gerekçe: {kk['gerekce']}" if kk.get("gerekce") else "")
                           + (f"; değişen: {kk['degisen']}" if kk.get("degisen") else ""))
        if sd.get("kayitlar"):
            sat.append(f"- Karar sayısı: KABUL {sum(1 for v in sd['kararlar'].values() if v == 'KABUL')}, "
                       f"KISMEN KABUL {sum(1 for v in sd['kararlar'].values() if v == 'KISMEN')}, "
                       f"RED {sum(1 for v in sd['kararlar'].values() if v == 'RED')}")
        sat.append("- Dosyalar: sentez_duzeltme_<model>.json, onay2_*.json (ham çıktılar); kayit.json → sentez_duzeltme")

    if pusulalar:
        sat += ["", "## Oylar (sonuca esas olan oylama)" if sd and sd.get("durum") == "yapildi" else "## Oylar", ""]
        for ad, p in pusulalar.items():
            satir = f"- **{GORUNEN_AD[ad]}:** {p['oy']}"
            if not p["gecerli"]:
                satir += f" (geçersiz pusula: {p['not']})"
            if p["gerekce"]:
                satir += f" — {p['gerekce']}"
            sat.append(satir)
            if p.get("orijinal_oy"):
                sat.append(f"  - Not: {p['not']} (orijinal oy: {p['orijinal_oy']})")
            for a_ in p.get("itiraz_ayrintilari") or [{"metin": x, "onem": None} for x in p["itirazlar"]]:
                sat.append(f"  - İtiraz" + (f" (önem: {a_['onem']}" + (f", kaynak: {a_['kaynak']}" if a_.get("kaynak") else "")
                                          + ("" if a_.get("onem_belirtildi", True) else "; önem belirtilmedi, önemli sayıldı")
                                          + ")" if a_.get("onem") else "") + f": {a_['metin']}")

    ek_sat = []
    for oylama, pus in tum_oylamalar(k):
        for ad, p in pus.items():
            for a_ in p.get("ek_notlar") or []:
                ek_sat.append(f"- {oylama}, {GORUNEN_AD[ad]} (önem: {a_['onem']}"
                              + (f", kaynak: {a_['kaynak']}" + ("" if a_.get("kaynak_belirtildi", True) else " [belirtilmedi]")
                                 if a_.get("kaynak") else "") + f"): {a_['metin']}")
    if ek_sat:
        sat += ["", "## Ek notlar (oy sonucunu değiştirmeyen itirazlar; karar 63)", "",
                "Yalnızca küçük itirazlar ya da (ikinci oylamada) değişmeyen metne yönelik itirazlar. "
                "Sentez düzeltmesi bunlara uygulanmaz."] + ek_sat

    if k.get("arastirma"):
        sat += R.ayrinti_bolumu(k["arastirma"])

    if k.get("eksik_katilim"):
        sat += ["", "## Eksik katılım", ""]
        for tur, d in k["eksik_katilim"].items():
            for ad, aciklama in d.items():
                sat.append(f"- {tur}: **{GORUNEN_AD[ad]}** — {aciklama}")

    if k.get("arac_denetimi"):
        sat += ["", "## Araç denetimi (salt okunurluk)", ""]
        for ad, t in k["arac_denetimi"].items():
            sat.append(f"- **{GORUNEN_AD[ad]}:** {arac_toplami_metni(ad, t)}")

    sat += ["", "## Çalışma bilgisi", ""]
    for ad, model in k["istenen_modeller"].items():
        gercek = k["gercek_modeller"].get(ad, "CLI bildirmedi")
        surum = k["on_kontrol"]["surumler"].get(ad, "?")
        dogrulama = k.get("model_dogrulama", {}).get(ad, "başarılı çağrı yok")
        sat.append(f"- {GORUNEN_AD[ad]}: istenen model `{model}`, cevap veren `{gercek}`, "
                   f"model doğrulama: {dogrulama}, CLI {surum}")
    if "codex" in k["istenen_modeller"]:
        sat.append(f"- GPT kotası (Codex oturum kaydından): {kota_metni(k.get('kota', {}).get('codex', {}))}")
    sat.append("- Model doğrulama düzeyleri: sunucu = sunucunun bildirdiği model okundu; "
               "istemci = yalnızca CLI'ın gönderdiği model okundu; doğrulanamadı = model bilgisi okunamadı.")
    sat.append(f"- Çağrı sayısı: {k['cagri_sayisi']}, süre: {k['sure_sn']} sn, tohum: {k['tohum']}")

    once, sonra = k.get("kota_once") or {}, k.get("kota_sonra") or {}
    if once or sonra:
        sat += ["", "## Kota: çalıştırmadan önce ve sonra", "",
                "Okumalar kota harcamaz (Claude/Gemini `/usage` yerel komuttur, model çağrısı yok; GPT son Codex oturum "
                "kaydından okunur ve kayıt eskiyse güncel olmayabilir). Metin kaynaktan olduğu gibi alınmıştır."]
        for ad in k["istenen_modeller"]:
            for etiket, d in (("önce", once.get(ad)), ("sonra", sonra.get(ad))):
                if not d:
                    sat.append(f"- {GORUNEN_AD[ad]} ({etiket}): okunmadı")
                    continue
                govde = (d["metin"] or "").strip().replace("\t", "  ")
                sat.append(f"- {GORUNEN_AD[ad]} ({etiket}, {d['durum']}):")
                sat += ["    " + x for x in govde.splitlines()] or ["    -"]
    return "\n".join(sat) + "\n"


def rapor_olustur(k: dict, pusulalar: dict, sentezci, ozet) -> tuple[str, str]:
    """(ozet_rapor, ayrinti). Ana rapor: tek satır başlık, uyarılar, ortak cevap, kısa Konsey notu; geri kalan ayrıntıda."""
    return ozet_rapor_olustur(k, pusulalar, sentezci, ozet), ayrinti_olustur(k, pusulalar, sentezci, ozet)



# --------------------------------------------------------------------------- duman testi


async def duman_testi(ayar: dict, zaman_asimi: int) -> int:
    konsey = Konsey(ayar, zaman_asimi=zaman_asimi)
    gemini = ayar["saglayicilar"].get("gemini")
    yalitim = bool(gemini and gemini.get("home"))
    if yalitim:  # agy'ye dokunan her şeyden ÖNCE: gerçek ~/.gemini ve yalıtılmış HOME'un özeti (karar 45)
        gercek_once = A.dizin_ozeti(A.gercek_gemini_dizini(gemini))
        iz_once = A.dizin_ozeti(gemini["home"])
    try:
        on = await konsey.on_kontrol()
        print(f"Giriş: {on['giris']}")
    except A.AyarHatasi as e:
        print(f"ÖN KONTROL BAŞARISIZ: {e}")
        return 2
    print("CLI sürümleri: " + ", ".join(f"{GORUNEN_AD[a]} {v}" for a, v in on["surumler"].items()))
    prompt = "Bu bir bağlantı testidir. 2+2 kaç? Yalnızca sayıyı yaz."
    sonuclar = await konsey._paralel({ad: prompt for ad in ayar["saglayicilar"]}, "duman")
    hepsi_tamam = True
    for ad, s in sonuclar.items():
        if s.basarili:
            print(f"✓ {GORUNEN_AD[ad]}: \"{s.metin.strip()[:60]}\" — istenen `{s.istenen_model}`, "
                  f"cevap veren `{s.gercek_model or 'CLI bildirmedi'}`, {s.sure_sn} sn")
            print(f"    model doğrulama: {s.model_dogrulama or A.DOGRULAMA_YOK}"
                  + (f" ({s.dogrulama_notu})" if s.dogrulama_notu else ""))
        else:
            hepsi_tamam = False
            print(f"✗ {GORUNEN_AD[ad]}: {s.durum} — {eksik_ipucu(s)}\n    {s.hata[:500]}")
        print(f"    araç denetimi: {A.arac_ozeti_metni(s)}")
    if "codex" in sonuclar:
        print(f"GPT kotası: {kota_metni(sonuclar['codex'].kota)}")
    for ad in ayar["saglayicilar"]:
        silinen = A.silinen_ortam_degiskenleri(ad)
        if silinen:
            print(f"Ortam temizliği ({GORUNEN_AD[ad]}): {len(silinen)} yönlendirme/anahtar değişkeni alt süreçten silindi: "
                  + ", ".join(silinen))
    # v0.25 (karar 64): araştırmacı kanaryaları a, b, d, e. agy yalıtım kontrollerinden ÖNCE çalışır; böylece koltuğun
    # kancası, yapılandırması ve gerçek ~/.gemini'nin araştırmacıdan etkilenmediği aynı kontrolle doğrulanır.
    kanca_yolu = Path(konsey.calisma) / ".agents" / "hooks.json"
    kanca_once = hashlib.sha256(kanca_yolu.read_bytes()).hexdigest() if kanca_yolu.is_file() else None
    ar_once = A.dizin_ozeti(gemini["home"]) if yalitim else None
    print("Araştırmacı kanaryaları (a: yerel dosya, b: 127.0.0.1, d: izin listesi, e: bağlam sızıntısı):")
    if not await R.kanaryalari_calistir(ayar, zaman_asimi, konsey.kayit, gercek=R.gercek_komutlar_mi(ayar)):
        hepsi_tamam = False
    kanca_sonra = hashlib.sha256(kanca_yolu.read_bytes()).hexdigest() if kanca_yolu.is_file() else None
    ar_sonra = A.dizin_ozeti(gemini["home"]) if yalitim else None
    koltuk_ok = koltuk_kontrolu_raporla(kanca_once, kanca_sonra, ar_once, ar_sonra, konsey.kayit)
    if not koltuk_ok:
        hepsi_tamam = False
    if gemini:
        if not await _agy_yuzey_kontrolu(gemini, konsey.calisma):
            hepsi_tamam = False
        if yalitim:
            if not _agy_yalitim_kontrolu(gemini, konsey.calisma, gercek_once, iz_once):
                hepsi_tamam = False
        else:
            print("agy yalıtım kontrolü: atlandı (`home` ayarı yok; agy kullanıcının genel ayarlarıyla çalışır)")
    print(f"Ham çıktılar: {konsey.kayit}")
    return 0 if hepsi_tamam else 1


# Karar 67: koltuk HOME karşılaştırmasından YALNIZCA bu iki yol, tam eşleşmeyle hariç
# tutulur (agy'nin kendi güncelleme durum dosyaları). Klasör ya da desen hariç tutulmaz; aynı klasördeki başka bir
# dosya değişirse kontrol bozulur. Hariç tutulan dosya değişirse rapora bilgi satırı olarak yazılır.
KOLTUK_HARIC_YOLLAR = frozenset({
    ".gemini/antigravity-cli/updater/update_status.json",
    ".gemini/antigravity-cli/updater/last_check.timestamp",
})


def koltuk_karsilastir(kanca_once, kanca_sonra, ozet_once, ozet_sonra) -> dict:
    """Koltuk kontrolü karşılaştırması (saf işlev). Geçti/kaldı kararı: kanca hash'i aynı VE (HOME özeti yoksa ya da aynı).
    Dönen: {tamam, kanca_ayni, home_ayni (None: HOME bakılmadı), home_fark: {yeni, silinen, degisen: [{yol, neden}]}}."""
    kanca_ayni = kanca_once == kanca_sonra
    home_ayni, home_fark = None, {"yeni": [], "silinen": [], "degisen": []}
    haric_bilgi: list[dict] = []
    if ozet_once is not None:
        tam_f = A.ozet_farki(ozet_once, ozet_sonra or {})
        for tur in ("yeni", "silinen", "degisen"):
            for yol in tam_f[tur]:
                if yol in KOLTUK_HARIC_YOLLAR:
                    haric_bilgi.append({"yol": yol, "tur": tur})
        ozet_once = {k: v for k, v in ozet_once.items() if k not in KOLTUK_HARIC_YOLLAR}
        ozet_sonra = {k: v for k, v in (ozet_sonra or {}).items() if k not in KOLTUK_HARIC_YOLLAR}
        home_ayni = ozet_sonra == ozet_once
        f = A.ozet_farki(ozet_once, ozet_sonra)
        home_fark["yeni"], home_fark["silinen"] = f["yeni"], f["silinen"]
        for yol in f["degisen"]:
            (m1, b1, h1), (m2, b2, h2) = ozet_once[yol], ozet_sonra[yol]
            neden = [n for n, d in (("mtime", m1 != m2), ("boyut", b1 != b2), ("hash", h1 != h2)) if d]
            home_fark["degisen"].append({"yol": yol, "neden": neden,
                                         "once": {"mtime_ns": m1, "boyut": b1}, "sonra": {"mtime_ns": m2, "boyut": b2}})
    return {"tamam": bool(kanca_ayni and (home_ayni is None or home_ayni)), "kanca_ayni": kanca_ayni,
            "kanca_once": kanca_once, "kanca_sonra": kanca_sonra, "home_ayni": home_ayni, "home_fark": home_fark,
            "haric_tutulan_degisen": haric_bilgi}


def koltuk_kontrolu_raporla(kanca_once, kanca_sonra, ozet_once, ozet_sonra, kayit_klasoru) -> bool:
    """Duman testi: karşılaştırmayı yapar, sonucu ekrana yazar ve önce/sonra özetini `koltuk_kontrol.json`'a kaydeder
    (yazma hatası kontrolü etkilemez). Karar karşılaştırmanın kararıdır; yalnızca rapor ayrıntılıdır."""
    r = koltuk_karsilastir(kanca_once, kanca_sonra, ozet_once, ozet_sonra)
    try:
        Path(kayit_klasoru).mkdir(parents=True, exist_ok=True)
        with open(Path(kayit_klasoru) / "koltuk_kontrol.json", "w", encoding="utf-8") as f:
            json.dump({"sonuc": r, "home_ozeti_once": ozet_once, "home_ozeti_sonra": ozet_sonra}, f,
                      ensure_ascii=False, indent=1, default=list)
    except OSError as e:
        print(f"UYARI: koltuk_kontrol.json yazılamadı: {e}")
    for h in r["haric_tutulan_degisen"]:
        print(f"    bilgi: hariç tutulan dosya değişti ({h['tur']}): {h['yol']}")
    if r["tamam"]:
        print(f"✓ Koltuk yapılandırması araştırmacıdan etkilenmedi (koltuk kancası aynı"
              + ("; koltuk HOME'u aynı" if r["home_ayni"] else "") + ")")
        return True
    print(f"✗ Koltuk yapılandırması araştırmacıdan etkilenmedi (koltuk kancası "
          f"{'aynı' if r['kanca_ayni'] else 'DEĞİŞTİ'}"
          + ("" if r["home_ayni"] is None else f"; koltuk HOME'u {'aynı' if r['home_ayni'] else 'DEĞİŞTİ'}") + ")")
    print(f"    bozulan parça: " + ", ".join(
        x for x, kotu in (("kanca hash'i", not r["kanca_ayni"]), ("HOME özeti", r["home_ayni"] is False)) if kotu))
    if not r["kanca_ayni"]:
        print(f"    kanca hash'i önce {r['kanca_once']} → sonra {r['kanca_sonra']}")
    hf = r["home_fark"]
    for etiket, anahtar in (("eklendi", "yeni"), ("silindi", "silinen")):
        for yol in hf[anahtar]:
            print(f"    {etiket}: {yol}")
    for d in hf["degisen"]:
        print(f"    değişti ({'+'.join(d['neden'])}): {d['yol']} — boyut {d['once']['boyut']}→{d['sonra']['boyut']}")
    print(f"    ayrıntı: {Path(kayit_klasoru) / 'koltuk_kontrol.json'}")
    return False


async def _duman_web(ayar: dict, zaman_asimi: int) -> int:
    """--duman-web: araştırmacı kanaryası c (web çalışıyor). Araştırmacı çağrısı yapar; kota harcar."""
    try:
        ayarlar = R.arastirma_ayari(ayar)
    except A.AyarHatasi as e:
        print(f"Araştırmacı ayarı: {e}")
        return 2
    konsey = Konsey(ayar, zaman_asimi=zaman_asimi)
    konsey.kayit.mkdir(parents=True, exist_ok=True)
    tamam = await R._web_kanaryasi(ayarlar, R.bugun(), zaman_asimi, konsey.kayit, print)
    print(f"Ham çıktılar: {konsey.kayit}")
    return 0 if tamam else 1


def _agy_yalitim_kontrolu(s: dict, calisma: str, gercek_once: dict, iz_once: dict) -> bool:
    """Duman testi (karar 45), agy çağrılarından SONRA: (1) gerçek ~/.gemini'de hiçbir dosya değişmemiş, (2) yalıtılmış
    HOME'da log ve konuşma dosyası oluşmuş, (3) çalışma alanı katmanı temiz. Ayrıca yalıtılmış HOME'da dosyaya yazılmış
    kimlik bilgisi izlenimi veren dosya varsa UYARI (başarısızlık değil). Doğruysa True."""
    gercek_sonra = A.dizin_ozeti(A.gercek_gemini_dizini(s))
    iz_sonra = A.dizin_ozeti(s["home"])
    sorunlar = A.agy_yalitim_sorunlari(A.ozet_farki(gercek_once, gercek_sonra), A.ozet_farki(iz_once, iz_sonra))
    sorunlar += [f"çalışma alanı: {x}" for x in A.calisma_alani_sorunlari(calisma)]
    if sorunlar:
        print("✗ agy yalıtım kontrolü BAŞARISIZ:")
        for x in sorunlar:
            print(f"    - {x}")
        print("    (bkz. belgeler/guvenlik.md 9.6; kullanıcı agy'yi aynı anda kullanıyorsa gerçek ~/.gemini değişikliği "
              "yanlış alarm olabilir)")
    else:
        print(f"✓ agy yalıtım kontrolü: gerçek ~/.gemini değişmedi; log ve konuşma dosyaları {s['home']} altında; "
              "çalışma alanı katmanı temiz")
    kimlik = A.agy_kimlik_dosyalari(s["home"])
    if kimlik:
        print(f"UYARI: {s['home']} içinde kimlik bilgisi dosyası olabilir (giriş Keychain yerine dosyaya yazılmış): "
              + ", ".join(kimlik[:5]))
    return not sorunlar


async def _agy_yuzey_kontrolu(s: dict, calisma: str) -> bool:
    """Duman testi: agy'de kurulu MCP sunucusu ya da eklenti olmamalı (karar 43). Doğruysa True."""
    if not A.agy_gercek_mi(s):
        print("agy yüzey kontrolü: atlandı (komut `agy` değil)")
        return True
    tamam = True
    for k in await A.agy_yuzeyini_yokla(s, calisma):
        if k["durum"] == A.YUZEY_BOS:
            print(f"✓ {k['komut']}: boş")
        else:
            tamam = False
            ne = ("BOŞ DEĞİL, bulunan" if k["durum"] == A.YUZEY_DOLU else "YOKLANAMADI")
            print(f"✗ {k['komut']}: {ne}:\n    " + k["cikti"].replace("\n", "\n    "))
    if not tamam:
        print("agy yüzey kontrolü BAŞARISIZ: kurulu MCP sunucusu/eklenti konsey kancasıyla denenmedi "
              "(bkz. belgeler/guvenlik.md 9.5); kaldırın ya da kullanıp kullanmayacağınıza kendiniz karar verin.")
    return tamam



# --------------------------------------------------------------------------- giriş noktası


def main() -> int:
    ap = argparse.ArgumentParser(description="Claude, GPT ve Gemini ile karar konseyi")
    ap.add_argument("soru", nargs="?", help="Konseye sorulacak soru")
    ap.add_argument("-f", "--soru-dosyasi", help="Soruyu bir dosyadan oku")
    ap.add_argument("--kanit", help="Üç modele aynen verilecek kanıt paketi dosyası")
    ap.add_argument("--duman", action="store_true", help="Her modele tek küçük soru sor (kurulum kontrolü)")
    ap.add_argument("--zaman-asimi", type=int, help="Çağrı başına süre sınırı (saniye)")
    ap.add_argument("--ayar", default=str(BURASI / "modeller.json"), help="Ayar dosyası")
    ap.add_argument("--tohum", type=int, help="Rastgele sıralama tohumu (tekrarlanabilirlik için)")
    ap.add_argument("--tur", type=int, default=VARSAYILAN_TUR,
                    help=f"En fazla eleştiri-düzeltme turu ({TUR_MIN}-{TUR_MAKS}; varsayılan {VARSAYILAN_TUR})")
    ap.add_argument("--baglam", help="Soran kişi hakkında bilgi içeren dosya; tüm turlarda "
                                     "'SORAN KİŞİ HAKKINDA' başlığıyla verilir (kanıt paketi değildir)")
    ap.add_argument("--arastir", action="store_true",
                    help="Yalnızca bu soru için: iki araştırmacı (Gemini, Codex) yalnızca soru metniyle web'de kaynak "
                         "toplar; paket konsey kanıtına eklenir. --baglam/--kanit araştırmacılara verilmez")
    ap.add_argument("--arastir-onay", action="store_true",
                    help="--arastir ve paketi konseyden önce ekranda gösterip onay bekler")
    ap.add_argument("--duman-web", action="store_true",
                    help="Araştırmacı web kanaryası (c): herkese açık sabit sayfadan doğru bilgiyi getiriyor mu")
    ap.add_argument("--ayrinti", action="store_true", help="ayrinti.md içeriğini ekrana da bas")
    ap.add_argument("--tolerans", type=float, default=VARSAYILAN_TOLERANS,
                    help="Tur 0 erken çıkışı: üç SONUÇ değeri arasındaki en büyük göreli fark (varsayılan 0.01)")
    ap.add_argument("--erken-cikis-yok", action="store_true",
                    help="Tur 0 erken çıkışını kapat; her soru tam konseyden geçer (yalnızca kontrol amaçlı)")
    a = ap.parse_args()
    if not a.tolerans >= 0:
        print("--tolerans negatif ya da sayı değil.")
        return 2
    if not TUR_MIN <= a.tur <= TUR_MAKS:
        print(f"--tur {TUR_MIN} ile {TUR_MAKS} arasında olmalı.")
        return 2

    try:
        ayar = A.ayarlari_yukle(a.ayar)
    except (A.AyarHatasi, OSError, json.JSONDecodeError, KeyError) as e:
        print(f"Ayar dosyası hatası: {e}")
        return 2

    if a.duman:
        return asyncio.run(duman_testi(ayar, a.zaman_asimi or 120))
    if a.duman_web:
        return asyncio.run(_duman_web(ayar, a.zaman_asimi or 300))

    if a.soru_dosyasi:
        soru = Path(a.soru_dosyasi).read_text(encoding="utf-8").strip()
    else:
        soru = a.soru or input("Soru: ").strip()
    if not soru:
        print("Soru boş.")
        return 2
    kanit = Path(a.kanit).read_text(encoding="utf-8").strip() if a.kanit else None
    baglam = None
    if a.baglam:
        try:
            ham = Path(a.baglam).read_bytes()
        except OSError as e:
            print(f"--baglam dosyası okunamadı: {e}")
            return 2
        if len(ham) > BAGLAM_MAKS_BAYT:
            print(f"--baglam dosyası çok büyük ({len(ham)} bayt; sınır {BAGLAM_MAKS_BAYT}).")
            return 2
        baglam = ham.decode("utf-8", "replace").strip()
        if not baglam:
            print("--baglam dosyası boş.")
            return 2

    konsey = Konsey(ayar, zaman_asimi=a.zaman_asimi, kanit=kanit, tohum=a.tohum,
                     erken_cikis=not a.erken_cikis_yok, tolerans=a.tolerans, tur=a.tur, baglam=baglam,
                     arastir=a.arastir, arastir_onay=a.arastir_onay, v029=V029_OZELLIKLERI)
    try:
        sonuc = asyncio.run(konsey.calistir(soru))
    except R.ArastirmaDurdu as e:
        print(f"ARAŞTIRMA DURDU: {e}")
        return 2
    except A.AyarHatasi as e:
        print(f"ÖN KONTROL BAŞARISIZ: {e}")
        return 2
    print(sonuc["ozet_rapor"])
    if a.ayrinti:
        print("\n" + sonuc["ayrinti"])
    print(f"Kayıtlar: {sonuc['kayit_klasoru']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())