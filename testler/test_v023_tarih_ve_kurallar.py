"""
v0.23 testleri (karar 59–62, 20 Kasım 2026: v0.22 doğrulama koşusunda 43 eleştiri maddesinin hiçbiri RED edilmedi):
  59  bütün prompt'larda "Bugünün tarihi" satırı (çalıştırma anında koddan; hash testleri sabit tarihle)
  60  2. ve sonraki turlarda düzeltmeye yalnızca HATALAR ve KANITSIZ İDDİALAR maddeleri; gönderilmeyenler ayrinti.md'de
  61  KABUL/KISMEN KABUL satırında "doğru, çünkü ...; değişen: ..." gerekçesi (eski biçim de okunur)
  62  RET'ten sonra tek seferlik sentez düzeltmesi ve yeniden oylama (açık soru 24)
Gerçek CLI yerine sahte_v023_cli.py (sahte_cli.py'yi saran) kullanılır; gerçek kotaya dokunulmaz.

Çalıştırma (konsey klasöründe):  python -m unittest discover -s testler -v
"""
import datetime as dt
import json
import os
import re
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import konsey as K  # noqa: E402
from test_elestiri_duzeltme import AkisTabani, elestiri_metni, madde  # noqa: E402

SAHTE_V023 = str(Path(__file__).resolve().parent / "sahte_v023_cli.py")
BUGUN = dt.date.today().isoformat()


class V023Tabani(AkisTabani):
    def setUp(self):
        super().setUp()
        for ad in ("claude", "codex", "gemini"):
            self.ayar["saglayicilar"][ad]["komut"] = [sys.executable, SAHTE_V023, ad]

    def tum_promptlar(self, s) -> dict:
        """Kayıt klasöründeki her çağrının prompt'u (komut satırındaki en uzun argüman): {dosya_adı: prompt}."""
        sonuc = {}
        for f in Path(s["kayit_klasoru"]).glob("*.json"):
            if f.name == "kayit.json":
                continue
            d = json.loads(f.read_text("utf-8"))
            if isinstance(d, dict) and d.get("komut"):
                sonuc[f.name] = max(d["komut"], key=len)
        return sonuc

    def ayrinti(self, s) -> str:
        return (Path(s["kayit_klasoru"]) / "ayrinti.md").read_text("utf-8")


# --------------------------------------------------------------------------- karar 59: tarih


class TarihTesti(V023Tabani):
    def test_tarih_satiri_koddan_ve_sabitlenebilir(self):
        self.assertEqual(K.tarih_satiri(), f"Bugünün tarihi: {BUGUN}")
        eski = K.TARIH_SABIT
        try:
            K.TARIH_SABIT = "2030-05-05"
            self.assertEqual(K.tarih_satiri(), "Bugünün tarihi: 2030-05-05")
            self.assertIn("Bugünün tarihi: 2030-05-05", K.p_tur0("S", None))
        finally:
            K.TARIH_SABIT = eski

    def test_bes_promptun_hepsinde_tarih_var(self):
        t = "Bugünün tarihi: "
        for p in (K.p_tur0("S", None), K.p_elestiri("S", None, [("A", "x")]), K.p_duzeltme("S", None, "k", ["e"]),
                  K.p_sentez("S", None, ["a"]), K.p_onay("S", None, "M", "abc", "k"),
                  K.p_sentez_duzeltme("S", None, "M", ["i"])):
            self.assertEqual(p.count(t), 1)
            self.assertRegex(p, re.escape(t) + r"\d{4}-\d{2}-\d{2}\n")

    def test_tur0_yalniz_tarih_satiri_kadar_degisti(self):
        # Eski (karar 34) Tur 0 özeti: tarih satırı çıkarılınca bayt bayt aynı olmalı.
        import hashlib
        eski = K.TARIH_SABIT
        try:
            K.TARIH_SABIT = "2026-01-01"
            p = K.p_tur0("SORU", None, None, {}).replace("Bugünün tarihi: 2026-01-01\n", "")   # v0.30: v0.28 Tur 0 açıkça istenir
        finally:
            K.TARIH_SABIT = eski
        self.assertEqual(hashlib.sha256(p.encode()).hexdigest(),
                         "339f2ce9ffa2a0be390eb7c839d76bae994e105f938f437144e1bd1c94d4ba91")

    def test_akistaki_her_cagri_tarih_satirini_icerir(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        s = self.calistir()
        promptlar = self.tum_promptlar(s)
        self.assertTrue(any(a.startswith("tur0_") for a in promptlar))
        for turu in ("tur0_", "tur1_elestiri_", "sentez_", "onay_", "sentez_duzeltme_", "onay2_"):
            ornekler = [p for a, p in promptlar.items() if a.startswith(turu)]
            self.assertTrue(ornekler, turu)
            for p in ornekler:
                self.assertIn(f"Bugünün tarihi: {BUGUN}", p, turu)

    def test_duzeltme_promptunda_tarih_var(self):
        os.environ["SAHTE_ELESTIRI"] = "madde"
        s = self.calistir(tur=1)
        ornekler = [p for a, p in self.tum_promptlar(s).items() if a.startswith("tur1_duzeltme_")]
        self.assertEqual(len(ornekler), 3)
        for p in ornekler:
            self.assertIn(f"Bugünün tarihi: {BUGUN}", p)


# --------------------------------------------------------------------------- karar 60: sonraki turlarda yalnızca hata


class SonrakiTurSuzmeTesti(V023Tabani):
    def elestiri(self):
        m = elestiri_metni({"A": []}, None).replace("EKSİK NOKTALAR\nSorun yok.\n", "")
        govde = ("=== CEVAP A HAKKINDA ===\n"
                 "HATALAR\n- [1] (önem: önemli; güven: yüksek) hata bir\n- [2] (önem: küçük; güven: orta) hata iki\n"
                 "EKSİK NOKTALAR\n- [3] (önem: önemli; güven: orta) eksik bir\n"
                 "KANITSIZ İDDİALAR\n- [4] (önem: önemli; güven: düşük) kanıtsız bir\n"
                 "İYİLEŞTİRME ÖNERİLERİ\n- [5] (öneri) öneri bir\n")
        j = {"A": {"kritik": 0, "onemli": 3, "kucuk": 1}}
        return K.elestiri_coz(govde + "```json\n" + json.dumps(j) + "\n```", ["A"])

    def test_birinci_tur_davranisi_ayni(self):
        metin, idler, gonderilmeyen = K.elestiri_metni_hazirla_ayrintili(1, self.elestiri(), "A", False)
        self.assertEqual(idler, ["E1-1", "E1-2", "E1-3", "E1-4", "E1-5"])
        self.assertEqual(gonderilmeyen, [])
        for s in ("hata bir", "eksik bir", "kanıtsız bir", "öneri bir", "EKSİK NOKTALAR", "İYİLEŞTİRME ÖNERİLERİ"):
            self.assertIn(s, metin)
        self.assertEqual(K.elestiri_metni_hazirla(1, self.elestiri(), "A"), (metin, idler))  # eski imza

    def test_sonraki_tur_yalniz_hata_ve_kanitsiz(self):
        metin, idler, gonderilmeyen = K.elestiri_metni_hazirla_ayrintili(2, self.elestiri(), "A", True)
        self.assertEqual(idler, ["E2-1", "E2-2", "E2-3"])  # kimlikler yalnızca gönderilenlere, sürekli
        for s in ("hata bir", "hata iki", "kanıtsız bir", "HATALAR", "KANITSIZ İDDİALAR"):
            self.assertIn(s, metin)
        for s in ("eksik bir", "öneri bir", "EKSİK NOKTALAR", "İYİLEŞTİRME ÖNERİLERİ"):
            self.assertNotIn(s, metin)
        self.assertEqual([g["metin"].split(") ", 1)[-1] for g in gonderilmeyen], ["eksik bir", "öneri bir"])
        self.assertEqual([g["alt_baslik"] for g in gonderilmeyen], ["eksik noktalar", "iyilestirme onerileri"])

    def test_bolum_okunamazsa_suzulemez_ham_gider(self):
        c = K.elestiri_coz("Düz metin, bölüm işareti yok", ["A"])
        metin, idler, gonderilmeyen = K.elestiri_metni_hazirla_ayrintili(2, c, "A", True)
        self.assertIsNone(idler)
        self.assertEqual(gonderilmeyen, [])
        self.assertIn("Düz metin", metin)

    def test_akis_ikinci_turda_yalniz_hata_gider_birinci_turda_hepsi(self):
        os.environ["SAHTE_V023_ELESTIRI"] = "zengin"
        s = self.calistir(tur=2)
        self.assertEqual(s["tur_sayisi"], 2)
        p1 = next(p for a, p in self.tum_promptlar(s).items() if a == "tur1_duzeltme_claude.json")
        for m in ("HATA1-MADDESI", "EKSIK1-MADDESI", "ONERI1-MADDESI"):
            self.assertIn(m, p1)
        self.assertFalse(s["turlar"][0]["yalniz_hata_kurali"])
        self.assertTrue(s["turlar"][1]["yalniz_hata_kurali"])
        for ad in ("claude", "codex", "gemini"):
            p2 = next(p for a, p in self.tum_promptlar(s).items() if a == f"tur2_duzeltme_{ad}.json")
            self.assertIn("HATA2-MADDESI", p2)
            self.assertIn("KANITSIZ2-MADDESI", p2)
            self.assertNotIn("EKSIK2-MADDESI", p2)
            self.assertNotIn("ONERI2-MADDESI", p2)
            self.assertNotIn("EKSİK NOKTALAR", p2.split("SENİN GÜNCEL CEVABIN")[1])
            self.assertEqual(p2.count("=== DEĞERLENDİRİCİ"), 2)
            self.assertEqual(s["turlar"][1]["duzeltmeler"][ad]["sayim"]["madde"], 4)  # 2 eleştirmen x (hata + kanıtsız)

    def test_gonderilmeyenler_ayrinti_ve_kayitta(self):
        os.environ["SAHTE_V023_ELESTIRI"] = "zengin"
        s = self.calistir(tur=2)
        liste = s["turlar"][1]["gonderilmeyen_maddeler"]["claude"]
        self.assertEqual(len(liste), 4)  # 2 eleştirmen x (eksik + öneri)
        a = self.ayrinti(s)
        self.assertIn("GÖNDERİLMEYEN 4 madde", a)
        self.assertIn("EKSIK2-MADDESI", a)
        self.assertIn("ONERI2-MADDESI", a)
        self.assertEqual(s["turlar"][0]["gonderilmeyen_maddeler"], {})

    def test_ikinci_turda_gonderilecek_hata_yoksa_duzeltme_atlanir(self):
        # 2. turda yalnızca EKSİK/ÖNERİ maddesi varsa düzeltme çağrısı yapılmaz; maddeler ayrinti'ya yazılır.
        c = K.elestiri_coz(
            "=== CEVAP A HAKKINDA ===\nHATALAR\nSorun yok.\nEKSİK NOKTALAR\n- [1] (önem: önemli; güven: orta) eksik\n"
            "KANITSIZ İDDİALAR\nSorun yok.\nİYİLEŞTİRME ÖNERİLERİ\n- [2] (öneri) öneri\n"
            '```json\n{"A": {"kritik": 0, "onemli": 1, "kucuk": 0}}\n```', ["A"])
        metin, idler, gonderilmeyen = K.elestiri_metni_hazirla_ayrintili(2, c, "A", True)
        self.assertEqual(idler, [])
        self.assertEqual(len(gonderilmeyen), 2)


# --------------------------------------------------------------------------- karar 61: KABUL gerekçesi


class KabulGerekcesiTesti(V023Tabani):
    def test_yeni_bicim_okunur(self):
        d = K.duzeltme_coz(
            "DEĞİŞİKLİK KAYDI:\n"
            "- E1-1 KABUL: doğru, çünkü kaynak 2024 tarihli ve süreç eskimiş; değişen: tarih 2026 yapıldı\n"
            "- E1-2 KISMEN KABUL: kısmen doğru, çünkü sayı yuvarlanmış; değişen: aralık verildi; "
            "kabul edilmeyen: ikinci iddia, çünkü kanıt yok\n"
            "- E1-3 RED: eleştiri olgusal olarak yanlış\n"
            "GÜNCEL CEVAP:\nyeni metin burada")
        self.assertTrue(d["gecerli"])
        self.assertEqual(d["kararlar"], {"E1-1": "KABUL", "E1-2": "KISMEN", "E1-3": "RED"})
        k1, k2, k3 = (d["kayitlar"][i] for i in ("E1-1", "E1-2", "E1-3"))
        self.assertEqual(k1["gerekce"], "kaynak 2024 tarihli ve süreç eskimiş")
        self.assertEqual(k1["degisen"], "tarih 2026 yapıldı")
        self.assertEqual(k2["gerekce"], "sayı yuvarlanmış")
        self.assertTrue(k2["degisen"].startswith("aralık verildi"))
        self.assertIsNone(k3["degisen"])
        self.assertEqual(k3["gerekce"], "eleştiri olgusal olarak yanlış")

    def test_eski_bicim_okunabilir_kalir(self):
        d = K.duzeltme_coz("DEĞİŞİKLİK KAYDI:\n- E1-1 KABUL: cevaba örnek eklendi\n- E1-2 RED: haksız\n"
                           "GÜNCEL CEVAP:\nyeni cevap")
        self.assertEqual(d["kararlar"], {"E1-1": "KABUL", "E1-2": "RED"})
        self.assertIsNone(d["kayitlar"]["E1-1"]["gerekce"])
        self.assertEqual(d["kayitlar"]["E1-1"]["degisen"], "cevaba örnek eklendi")

    def test_sadece_degisen_etiketi_varsa(self):
        k = K.karar_kayitlarini_oku("- E1-1 KABUL: değişen: bölüm eklendi")["E1-1"]
        self.assertIsNone(k["gerekce"])
        self.assertEqual(k["degisen"], "bölüm eklendi")

    def test_buyuk_harf_ve_madde_isareti_degisimleri(self):
        k = K.karar_kayitlarini_oku("* [E2-1] kabul: DOĞRU, ÇÜNKÜ gerekçe burada yazılı; DEĞİŞEN: x yapıldı")["E2-1"]
        self.assertEqual((k["karar"], k["gerekce"], k["degisen"]), ("KABUL", "gerekçe burada yazılı", "x yapıldı"))

    def test_ilk_satir_gecerli(self):
        k = K.karar_kayitlarini_oku("- E1-1 KABUL: a\n- E1-1 RED: b")
        self.assertEqual(k["E1-1"]["karar"], "KABUL")

    def test_gerekce_sayimi(self):
        kayitlar = K.karar_kayitlarini_oku(
            "- E1-1 KABUL: doğru, çünkü yeterince uzun bir gerekçe; değişen: a\n"
            "- E1-2 KABUL: doğru, çünkü x; değişen: b\n"      # çok kısa gerekçe sayılmaz
            "- E1-3 KABUL: sadece ne değişti\n"
            "- E1-4 RED: neden\n")
        self.assertEqual(K.gerekce_sayimi(kayitlar), {"kabul_kismen": 3, "gerekceli": 1})
        self.assertEqual(K.gerekce_sayimi(kayitlar, ["E1-1", "E1-4"]), {"kabul_kismen": 1, "gerekceli": 1})

    def test_duzeltme_promptu_yeni_bicimi_ister(self):
        p = K.p_duzeltme("S", None, "kendi", ["e1"])
        self.assertIn("E1-1 KABUL: doğru, çünkü <eleştirinin neden doğru olduğu>; değişen: <cevapta ne değişti>", p)
        self.assertIn("KISMEN KABUL: kısmen doğru, çünkü", p)
        self.assertIn("E1-3 RED: <neden>", p)
        self.assertIn("\"çünkü\" kısmı zorunlu", p)

    def test_akis_gerekce_sayilir_ve_red_orani_gosterilir(self):
        os.environ["SAHTE_ELESTIRI"] = "madde"
        s = self.calistir(tur=1)
        for ad in ("claude", "codex", "gemini"):
            g = s["turlar"][0]["duzeltmeler"][ad]["gerekce"]
            self.assertEqual(g["kabul_kismen"], 1)
            self.assertEqual(g["gerekceli"], 1)
        a = self.ayrinti(s)
        self.assertIn("RED oranı %50", a)
        self.assertIn("gerekçe yazılan KABUL/KISMEN KABUL 1/1", a)

    def test_akis_eski_bicim_gerekcesiz_sayilir_ama_okunur(self):
        os.environ["SAHTE_ELESTIRI"] = "madde"
        os.environ["SAHTE_V023_ESKI_BICIM"] = "1"
        s = self.calistir(tur=1)
        d = s["turlar"][0]["duzeltmeler"]["claude"]
        self.assertEqual(d["sayim"]["kabul"], 1)
        self.assertEqual(d["gerekce"], {"kabul_kismen": 1, "gerekceli": 0})


# --------------------------------------------------------------------------- karar 62: sentez düzeltmesi


class SentezDuzeltmeBirimTesti(unittest.TestCase):
    def test_somut_itirazlar(self):
        pus = {"claude": {"oy": "RET", "gecerli": True, "itirazlar": ["a", " ", "b"]},
               "codex": {"oy": "RET", "gecerli": True, "itirazlar": []},           # itirazsız RET tetiklemez
               "gemini": {"oy": "KABUL", "gecerli": True, "itirazlar": ["c"]}}     # KABUL'ün itirazı sayılmaz
        self.assertEqual(K.somut_itirazlar(pus), [("claude", "a"), ("claude", "b")])
        self.assertEqual(K.somut_itirazlar({}), [])
        self.assertEqual(K.somut_itirazlar({"x": {"oy": "RET", "gecerli": False, "itirazlar": ["z"]}}), [])

    def test_cozucu_gecerli(self):
        d = K.sentez_duzeltme_coz(
            "İTİRAZ KAYDI:\n- R1 KABUL: doğru, çünkü sayı yanlıştı; değişen: sayı düzeltildi\n- R2 RED: haksız\n"
            "DÜZELTİLMİŞ METİN:\nÖZET: yeni özet burada yazıldı.\nCEVAP: x\nBELİRSİZLİKLER: Yok")
        self.assertTrue(d["gecerli"])
        self.assertEqual(d["kararlar"], {"R1": "KABUL", "R2": "RED"})
        self.assertTrue(d["metin"].startswith("ÖZET: yeni özet"))
        self.assertEqual(d["kayitlar"]["R1"]["gerekce"], "sayı yanlıştı")

    def test_cozucu_kalin_baslik(self):
        d = K.sentez_duzeltme_coz("- R1 RED: x\n**DÜZELTİLMİŞ METİN:** \n**ÖZET:** yeni özet burada yazıldı.\nCEVAP: x")
        self.assertTrue(d["gecerli"])
        self.assertTrue(d["metin"].startswith("**ÖZET:**"))

    def test_cozucu_gecersizler(self):
        for t in ("- R1 KABUL: x\nmetin yok", "DÜZELTİLMİŞ METİN:\nçok kısa", "", None):
            self.assertFalse(K.sentez_duzeltme_coz(t)["gecerli"], t)

    def test_prompt_icerigi(self):
        p = K.p_sentez_duzeltme("SORU", "KANIT", "MEVCUT-METIN", ["itiraz bir", "itiraz iki"], "BAGLAM")
        for s in ("MEVCUT-METIN", "[R1] itiraz bir", "[R2] itiraz iki", "KANIT", "BAGLAM", "İTİRAZ KAYDI:",
                  "DÜZELTİLMİŞ METİN:", "RED bir başarısızlık değildir", "sırf itiraz edildi diye",
                  "R1 KABUL: doğru, çünkü", "TAM ve düzeltilmiş"):
            self.assertIn(s, p)
        for ad in ("Claude", "GPT", "Gemini", "claude", "codex", "gemini"):
            self.assertNotIn(ad, p)

    def test_oy_dagilimi(self):
        self.assertEqual(K.oy_dagilimi({"a": "KABUL", "b": "RET", "c": "KABUL"}), "2 KABUL / 1 RET / 0 ÇEKİMSER")


class SentezDuzeltmeAkisTesti(V023Tabani):
    def kayit(self, s):
        return self.ham(s, "kayit.json")

    def test_ret_sonrasi_duzeltme_ve_ikinci_oylama_oybirligi(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        s = self.calistir()
        # tur0 3 + eleştiri 3 + (düzeltme 0) + sentez 1 + onay 3 + sentez düzeltmesi 1 + onay2 3
        self.assertEqual(s["cagri_sayisi"], 14)
        sd = s["sentez_duzeltme"]
        self.assertEqual(sd["durum"], "yapildi")
        self.assertEqual(s["ilk_oylama"]["durum"], "COGUNLUK")
        self.assertEqual(sd["ikinci_oylama"]["durum"], "OYBIRLIGI")
        self.assertEqual(s["durum"], "OYBIRLIGI")  # sonuç ikinci oylamaya göre
        self.assertIn("DÜZELTİLDİ-SENTEZ", s["onaylanan_metin"])
        self.assertNotEqual(sd["yeni_ozet"], sd["ilk_ozet"])
        self.assertEqual(sd["yeni_ozet"], K.metin_ozeti(s["onaylanan_metin"]))
        self.assertEqual(s["onay"]["pusulalar"]["codex"]["oy"], "RET")  # ilk oylama kayıtta korunur
        self.assertEqual({p["oy"] for p in s["onay2"]["pusulalar"].values()}, {"KABUL"})
        self.assertEqual(sd["kararlar"]["R1"], "KABUL")
        self.assertEqual(self.kayit(s)["sentez_duzeltme"]["durum"], "yapildi")

    def test_duzeltme_promptu_itiraz_ve_kendi_sentezini_icerir(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        s = self.calistir()
        yazar = s["sentez"]["yazar"]
        p = self.tum_promptlar(s)[f"sentez_duzeltme_{yazar}.json"]
        self.assertIn("[R1] önemli hata", p)
        self.assertIn(s["sentez"]["metin"], p)
        self.assertNotIn("codex", p.lower())  # itiraz sahibi kimliksiz
        self.assertEqual(sum(1 for a in self.tum_promptlar(s) if a.startswith("sentez_duzeltme_")), 1)

    def test_ikinci_oylama_yeni_surume_baglidir(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        s = self.calistir()
        yeni = s["sentez_duzeltme"]["yeni_ozet"]
        for ad in ("claude", "codex", "gemini"):
            p = self.tum_promptlar(s)[f"onay2_{ad}.json"]
            self.assertIn(f"METİN SÜRÜMÜ: {yeni}", p)
            self.assertIn("DÜZELTİLDİ-SENTEZ", p)
            self.assertIn(f"{ad} cevabı", p)  # her üye ikinci oylamada da kendi son cevabını görür
            self.assertNotIn(f"METİN SÜRÜMÜ: {s['sentez_duzeltme']['ilk_ozet']}", p)

    def test_ikinci_oylamada_da_ret_varsa_bir_kez_yapilir(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        os.environ["SAHTE_V023_RET_IKINCI"] = "codex"
        s = self.calistir()
        self.assertEqual(s["cagri_sayisi"], 14)  # ikinci bir düzeltme yok
        self.assertEqual(s["durum"], "COGUNLUK")
        self.assertEqual(s["sentez_duzeltme"]["ikinci_oylama"]["durum"], "COGUNLUK")
        self.assertEqual(sum(1 for a in self.tum_promptlar(s) if a.startswith(("sentez_duzeltme_", "onay3_"))), 1)

    def test_ikinci_oylama_daha_kotuyse_sonuc_ikinciye_gore(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        os.environ["SAHTE_V023_RET_IKINCI"] = "codex,gemini"
        s = self.calistir()
        self.assertEqual(s["ilk_oylama"]["durum"], "COGUNLUK")
        self.assertEqual(s["durum"], "UZLASI_YOK")
        self.assertIsNone(s["onaylanan_metin"])
        self.assertIn("DÜZELTİLDİ-SENTEZ", s["taslak_metin"])

    def test_cagri_basarisizsa_ilk_oylama_gecerli(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        os.environ["SAHTE_V023_SENTEZ_DUZ"] = "hata"
        s = self.calistir()
        self.assertEqual(s["durum"], "COGUNLUK")
        self.assertEqual(s["sentez_duzeltme"]["durum"], "cagri_basarisiz")
        self.assertEqual(s["cagri_sayisi"], 11)  # onay2 yok
        self.assertNotIn("onay2", s)
        self.assertNotIn("DÜZELTİLDİ-SENTEZ", s["onaylanan_metin"])
        self.assertIn("sentez_duzeltme", s["eksik_katilim"])

    def test_gecersiz_cikti_ilk_oylama_gecerli(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        os.environ["SAHTE_V023_SENTEZ_DUZ"] = "bozuk"
        s = self.calistir()
        self.assertEqual((s["durum"], s["sentez_duzeltme"]["durum"], s["cagri_sayisi"]), ("COGUNLUK", "gecersiz_cikti", 11))
        self.assertIn("sentez_duzeltme", s["eksik_katilim"])

    def test_metin_degismediyse_yeniden_oylama_yok(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        os.environ["SAHTE_V023_SENTEZ_DUZ"] = "ayni"
        s = self.calistir()
        self.assertEqual((s["durum"], s["sentez_duzeltme"]["durum"], s["cagri_sayisi"]), ("COGUNLUK", "degismedi", 11))
        self.assertNotIn("onay2", s)

    def test_itirazsiz_ret_duzeltmeyi_tetiklemez(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        os.environ["SAHTE_V023_ITIRAZSIZ"] = "1"
        s = self.calistir()
        self.assertEqual((s["durum"], s["cagri_sayisi"]), ("COGUNLUK", 10))
        self.assertNotIn("sentez_duzeltme", s)

    def test_ret_yoksa_tetiklenmez(self):
        s = self.calistir()
        self.assertEqual((s["durum"], s["cagri_sayisi"]), ("OYBIRLIGI", 10))
        self.assertNotIn("sentez_duzeltme", s)
        self.assertNotIn("Sentez itirazlara göre", s["rapor"])

    def test_rapor_notu_ve_ayrinti(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        s = self.calistir()
        rapor = s["ozet_rapor"]
        self.assertIn("Sentez itirazlara göre bir kez düzeltildi.", rapor)
        self.assertIn("1. oylama: 2 KABUL / 1 RET / 0 ÇEKİMSER (COGUNLUK)", rapor)
        self.assertIn("2. oylama: 3 KABUL / 0 RET / 0 ÇEKİMSER (OYBIRLIGI)", rapor)
        self.assertTrue(rapor.startswith("# Konsey: OYBIRLIGI"))
        a = self.ayrinti(s)
        self.assertIn("## Sentez düzeltmesi", a)
        self.assertIn("R1 (GPT itirazı): önemli hata", a)
        self.assertIn("Sentez yazarının kararı: KABUL — gerekçe: itiraz metindeki sayıyı yanlış bulduğunu gösteriyor", a)
        self.assertIn("Karar sayısı: KABUL 1, KISMEN KABUL 0, RED 0", a)
        self.assertIn("sentez_duzeltme_", a)
        self.assertTrue((Path(s["kayit_klasoru"]) / f"sentez_duzeltme_{s['sentez']['yazar']}.json").exists())

    def test_rapor_notu_basarisiz_duzeltmede(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        os.environ["SAHTE_V023_SENTEZ_DUZ"] = "hata"
        s = self.calistir()
        self.assertIn("Sentez düzeltmesi denendi ama uygulanmadı", s["ozet_rapor"])
        self.assertIn("ilk oylamanın sonucu geçerli", s["ozet_rapor"])
        self.assertNotIn("Sentez itirazlara göre bir kez düzeltildi", s["ozet_rapor"])


class SurumTesti(V023Tabani):
    def test_protokol_v023(self):
        s = self.calistir()
        self.assertEqual(self.ham(s, "kayit.json")["protokol"], K.KOD_SURUMU)


if __name__ == "__main__":
    unittest.main()
