"""
Eleştiri-düzeltme protokolü testleri (v0.21, karar 50 [GEÇİCİ]): ayrıştırıcılar, erken durma, hata durumları, nötr hakem,
rapor yerleşimi ve uyarıların ana raporda görünmesi, --baglam, kota görüntüsü, kayıt dosyaları.
Gerçek CLI yerine sahte_cli.py kullanılır; gerçek kotaya dokunulmaz.

Çalıştırma (konsey klasöründe):  python -m unittest discover -s testler -v
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import konsey as K  # noqa: E402

SAHTE = str(Path(__file__).resolve().parent / "sahte_cli.py")


def madde(n=1, onem="önemli", guven="yüksek", metin="bir madde"):
    return f"- [{n}] (önem: {onem}; güven: {guven}) {metin}"


def elestiri_metni(bolumler: dict, json_nesnesi: dict | None, fence=True) -> str:
    parca = []
    for e, maddeler in bolumler.items():
        parca.append(f"=== CEVAP {e} HAKKINDA ===\nHATALAR\n" + ("\n".join(maddeler) if maddeler else "Sorun yok.")
                     + "\nEKSİK NOKTALAR\nSorun yok.\n")
    if json_nesnesi is not None:
        j = json.dumps(json_nesnesi)
        parca.append(f"```json\n{j}\n```" if fence else j)
    return "\n".join(parca)


SIFIR = {"kritik": 0, "onemli": 0, "kucuk": 0}


def MODELLER_SAHTE() -> dict:
    return {"claude": {"komut": [sys.executable, SAHTE, "claude"], "model": "opus"},
            "codex": {"komut": [sys.executable, SAHTE, "codex"], "model": "gpt-6.2-astra"},
            "gemini": {"komut": [sys.executable, SAHTE, "gemini"], "model": "gemini-4-neon-high"}}


class AyristirmaTesti(unittest.TestCase):
    def test_gecerli_iki_cevap(self):
        m = elestiri_metni({"A": [madde(1, "kritik"), madde(2, "küçük", "orta")], "B": []},
                           {"A": {"kritik": 1, "onemli": 0, "kucuk": 1}, "B": SIFIR, "daha_iyi": "B"})
        c = K.elestiri_coz(m, ["A", "B"])
        self.assertTrue(c["bolum_ok"])
        self.assertEqual(c["sayilar"]["A"], {"kritik": 1, "onemli": 0, "kucuk": 1})
        self.assertEqual(c["daha_iyi"], "B")
        self.assertEqual([x["onem"] for x in c["maddeler"]["A"]], ["kritik", "kucuk"])
        self.assertEqual(c["maddeler"]["B"], [])
        self.assertFalse(c["tutarsiz"])
        self.assertNotIn("```", c["bolumler"]["B"])
        self.assertNotIn('"daha_iyi"', c["bolumler"]["B"])

    def test_ascii_onem_etiketleri(self):
        m = elestiri_metni({"A": ["- [1] (onem: onemli; guven: yuksek) x", "- [2] (önem: KÜÇÜK; güven: düşük) y"]},
                           {"A": {"kritik": 0, "onemli": 1, "kucuk": 1}})
        c = K.elestiri_coz(m, ["A"])
        self.assertEqual([x["onem"] for x in c["maddeler"]["A"]], ["onemli", "kucuk"])

    def test_tek_cevap_daha_iyi_yok(self):
        c = K.elestiri_coz(elestiri_metni({"A": []}, {"A": SIFIR, "daha_iyi": "A"}), ["A"])
        self.assertIsNone(c["daha_iyi"])
        self.assertEqual(c["sayilar"]["A"], SIFIR)

    def test_bolum_isareti_yoksa(self):
        c = K.elestiri_coz("Düz metin " + json.dumps({"A": SIFIR, "B": SIFIR, "daha_iyi": "A"}), ["A", "B"])
        self.assertFalse(c["bolum_ok"])
        self.assertEqual(c["daha_iyi"], "A")

    def test_eksik_bolum(self):
        m = elestiri_metni({"A": []}, {"A": SIFIR, "B": SIFIR, "daha_iyi": "A"})
        self.assertFalse(K.elestiri_coz(m, ["A", "B"])["bolum_ok"])

    def test_json_okunamaz(self):
        self.assertIsNone(K.elestiri_coz(elestiri_metni({"A": [], "B": []}, None), ["A", "B"])["sayilar"])
        for kotu in ({"A": SIFIR}, {"A": {"kritik": -1, "onemli": 0, "kucuk": 0}, "B": SIFIR},
                     {"A": {"kritik": "0", "onemli": 0, "kucuk": 0}, "B": SIFIR},
                     {"A": {"kritik": 0.5, "onemli": 0, "kucuk": 0}, "B": SIFIR}, {"A": {"kritik": True, "onemli": 0, "kucuk": 0}, "B": SIFIR}):
            c = K.elestiri_coz(elestiri_metni({"A": [], "B": []}, dict(kotu, daha_iyi="A")), ["A", "B"])
            self.assertIsNone(c["sayilar"], kotu)

    def test_gecersiz_daha_iyi(self):
        c = K.elestiri_coz(elestiri_metni({"A": [], "B": []}, {"A": SIFIR, "B": SIFIR, "daha_iyi": "C"}), ["A", "B"])
        self.assertIsNone(c["daha_iyi"])
        self.assertIsNotNone(c["sayilar"])

    def test_json_sifir_ama_metinde_agir_madde_tutarsiz(self):
        m = elestiri_metni({"A": [madde(1, "kritik")], "B": []}, {"A": SIFIR, "B": SIFIR, "daha_iyi": "A"})
        self.assertTrue(K.elestiri_coz(m, ["A", "B"])["tutarsiz"])
        m = elestiri_metni({"A": [madde(1, "önemli")], "B": []}, {"A": SIFIR, "B": SIFIR, "daha_iyi": "A"})
        self.assertFalse(K.elestiri_coz(m, ["A", "B"])["tutarsiz"])  # v0.22: önemli madde artık tutarsızlık sayılmaz
        m = elestiri_metni({"A": [madde(1, "küçük")], "B": []}, {"A": SIFIR, "B": SIFIR, "daha_iyi": "A"})
        self.assertFalse(K.elestiri_coz(m, ["A", "B"])["tutarsiz"])  # küçük madde durmayı engellemez

    def test_belirsiz_onem_agir_sayilir(self):
        m = elestiri_metni({"A": ["- [1] (önem: ???; güven: yüksek) x"]}, {"A": SIFIR})
        c = K.elestiri_coz(m, ["A"])
        self.assertEqual(c["maddeler"]["A"][0]["onem"], "belirsiz")
        self.assertTrue(c["tutarsiz"])

    def test_madde_yok(self):
        temiz = K.elestiri_coz(elestiri_metni({"A": [], "B": [madde()]},
                                              {"A": SIFIR, "B": {"kritik": 0, "onemli": 1, "kucuk": 0}, "daha_iyi": "A"}),
                               ["A", "B"])
        self.assertTrue(K.madde_yok(temiz, "A"))
        self.assertFalse(K.madde_yok(temiz, "B"))
        self.assertFalse(K.madde_yok(K.elestiri_coz("Düz metin", ["A"]), "A"))  # emin değilsek düzeltme çalışır
        # JSON "0" diyor ama bölümde madde satırı var: madde var sayılır
        c = K.elestiri_coz(elestiri_metni({"A": [madde(1, "küçük")]}, {"A": SIFIR}), ["A"])
        self.assertFalse(K.madde_yok(c, "A"))

    def test_elestiri_metni_hazirla_kimlik_verir(self):
        c = K.elestiri_coz(elestiri_metni({"A": [madde(1), madde(2, "küçük")], "B": [madde(1)]},
                                          {"A": {"kritik": 0, "onemli": 1, "kucuk": 1},
                                           "B": {"kritik": 0, "onemli": 1, "kucuk": 0}, "daha_iyi": "A"}), ["A", "B"])
        metin, idler = K.elestiri_metni_hazirla(2, c, "A")
        self.assertEqual(idler, ["E2-1", "E2-2"])
        self.assertIn("[E2-1]", metin)
        self.assertNotIn("CEVAP B", metin)
        ham, idler = K.elestiri_metni_hazirla(1, K.elestiri_coz("Düz metin", ["A"]), "A")
        self.assertIsNone(idler)
        self.assertIn("Düz metin", ham)

    def test_duzeltme_coz(self):
        d = K.duzeltme_coz("DEĞİŞİKLİK KAYDI:\n- E1-1 KABUL: ekledim\n- E1-2 RED: haksız\n* E2-1 ret: x\n"
                           "GÜNCEL CEVAP:\nCEVAP: yeni\nGEREKÇE: g")
        self.assertTrue(d["gecerli"])
        self.assertEqual(d["kararlar"], {"E1-1": "KABUL", "E1-2": "RED", "E2-1": "RED"})
        self.assertEqual(d["cevap"], "yeni\nGEREKÇE: g")  # v0.22: gövde başındaki tekrarlı "CEVAP:" etiketi atılır
        self.assertNotIn("KABUL", d["cevap"])

    def test_duzeltme_gecersizler(self):
        self.assertFalse(K.duzeltme_coz("DEĞİŞİKLİK KAYDI:\n- E1-1 KABUL: x\nCevabı yazmadım")["gecerli"])
        self.assertFalse(K.duzeltme_coz("GÜNCEL CEVAP:\n  ")["gecerli"])
        self.assertFalse(K.duzeltme_coz("")["gecerli"])
        self.assertFalse(K.duzeltme_coz(None)["gecerli"])

    def test_duzeltme_ilk_karar_gecerli(self):
        d = K.duzeltme_coz("- E1-1 KABUL: a\n- E1-1 RED: b\nGÜNCEL CEVAP:\nyeni cevap metni")
        self.assertEqual(d["kararlar"]["E1-1"], "KABUL")

    def test_degisiklik_sayimi(self):
        s = K.degisiklik_sayimi(["E1-1", "E1-2", "E2-1"], {"E1-1": "KABUL", "E2-1": "RED", "E9-9": "KABUL"})
        self.assertEqual((s["madde"], s["kabul"], s["red"], s["yanitsiz"], s["taninmayan"]), (3, 1, 1, 1, 1))
        s = K.degisiklik_sayimi(None, {"E1-1": "KABUL", "E1-2": "RED", "E1-3": "RED"})
        self.assertEqual((s["kimlikli"], s["madde"], s["kabul"], s["red"], s["yanitsiz"]), (False, None, 1, 2, None))
        self.assertEqual(K.degisiklik_sayimi([], {})["madde"], 0)


class ErkenDurmaTesti(unittest.TestCase):
    def c(self, a=SIFIR, b=SIFIR, **ek):
        m = elestiri_metni({"A": [], "B": []}, {"A": a, "B": b, "daha_iyi": "A"})
        return dict(K.elestiri_coz(m, ["A", "B"]), **ek)

    def test_hepsi_sifir_durur(self):
        self.assertTrue(K.erken_durma_karari({"claude": self.c(), "codex": self.c()})[0])

    def test_kucuk_madde_durmayi_engellemez(self):
        k = {"A": {"kritik": 0, "onemli": 0, "kucuk": 3}}
        self.assertTrue(K.erken_durma_karari({"claude": self.c(a=k["A"])})[0])

    def test_yalniz_kritik_devam_ettirir(self):
        # v0.22 (karar 55): önemli maddeler artık durmayı engellemez; yalnızca kritik engeller
        self.assertTrue(K.erken_durma_karari({"claude": self.c(), "codex": self.c(b={"kritik": 0, "onemli": 1, "kucuk": 0})})[0])
        self.assertFalse(K.erken_durma_karari({"claude": self.c(a={"kritik": 1, "onemli": 0, "kucuk": 0})})[0])

    def test_json_okunamazsa_durmaz(self):
        bozuk = K.elestiri_coz("json yok", ["A", "B"])
        d, neden = K.erken_durma_karari({"claude": self.c(), "codex": bozuk})
        self.assertFalse(d)
        self.assertIn("JSON", neden)

    def test_tutarsizsa_durmaz(self):
        self.assertFalse(K.erken_durma_karari({"claude": self.c(tutarsiz=True)})[0])

    def test_eleştiri_yoksa_durmaz(self):
        self.assertFalse(K.erken_durma_karari({})[0])


class NotrHakemTesti(unittest.TestCase):
    def k(self, hakem, kazanan, kaybeden):
        return {"hakem": hakem, "kazanan": kazanan, "kaybeden": kaybeden}

    def test_galip(self):
        a = K.notr_hakem_analizi(["claude", "codex", "gemini"],
                                 [self.k("gemini", "claude", "codex"), self.k("codex", "claude", "gemini"),
                                  self.k("claude", "codex", "gemini")])
        self.assertEqual((a["notr_hakem_durumu"], a["notr_hakem_galibi"]), ("galip", "claude"))
        self.assertEqual({c["hakem"] for c in a["karsilastirmalar"]}, {"claude", "codex", "gemini"})

    def test_dongu(self):
        a = K.notr_hakem_analizi(["claude", "codex", "gemini"],
                                 [self.k("gemini", "claude", "codex"), self.k("claude", "codex", "gemini"),
                                  self.k("codex", "gemini", "claude")])
        self.assertEqual(a["notr_hakem_durumu"], "net_galip_yok")

    def test_eksik_cift_belirlenemedi(self):
        a = K.notr_hakem_analizi(["claude", "codex", "gemini"], [self.k("gemini", "claude", "codex")])
        self.assertEqual(a["notr_hakem_durumu"], "belirlenemedi")
        self.assertEqual(sum(1 for c in a["karsilastirmalar"] if c["kazanan"] is None), 2)

    def test_eksik_cift_galibi_bozmaz(self):
        a = K.notr_hakem_analizi(["claude", "codex", "gemini"],
                                 [self.k("gemini", "claude", "codex"), self.k("codex", "claude", "gemini")])
        self.assertEqual((a["notr_hakem_durumu"], a["notr_hakem_galibi"]), ("galip", "claude"))

    def test_iki_cevapta_olculmez(self):
        a = K.notr_hakem_analizi(["claude", "codex"], [])
        self.assertEqual(a["notr_hakem_durumu"], "olculmedi")


class AkisTabani(unittest.TestCase):
    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        kok = Path(self.gecici.name)
        self.kok = kok
        self.ayar = {
            "calisma_klasoru": str(kok / "oturum"),
            "kayit_klasoru": str(kok / "kayitlar"),
            "cagri_zaman_asimi_sn": 30,
            "saglayicilar": {
                "claude": {"komut": [sys.executable, SAHTE, "claude"], "model": "opus"},
                "codex": {"komut": [sys.executable, SAHTE, "codex"], "model": "gpt-6.2-astra"},
                "gemini": {"komut": [sys.executable, SAHTE, "gemini"], "model": "gemini-4-neon-high"},
            },
        }
        self.eski_ortam = dict(os.environ)
        for k in list(os.environ):
            if k.startswith("SAHTE_"):
                del os.environ[k]

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.eski_ortam)
        self.gecici.cleanup()

    def calistir(self, **kw) -> dict:
        kw.setdefault("v029", {})   # v0.29 varsayılan açık oldu; bu testler v0.28 davranışını açıkça ister
        return asyncio.run(K.Konsey(self.ayar, tohum=42, **kw).calistir("Test sorusu?"))

    def ham(self, s, ad_dosya):
        return json.loads((Path(s["kayit_klasoru"]) / ad_dosya).read_text("utf-8"))

    def prompt(self, s, ad_dosya, ipucu):
        return next(x for x in self.ham(s, ad_dosya)["komut"] if ipucu in x)


class AkisTesti(AkisTabani):
    def test_maddesiz_eleştiri_bir_turda_durur_ve_duzeltme_atlanir(self):
        s = self.calistir(tur=2)   # v0.30 (karar 69): varsayılan tur 1 oldu; 'erken durdu' için sınır 2 verilir
        self.assertEqual(s["durum"], "OYBIRLIGI")
        self.assertEqual(s["cagri_sayisi"], 10)  # 3 + 3 eleştiri + 0 düzeltme + 1 sentez + 3 onay
        self.assertEqual(s["tur_sayisi"], 1)
        t = s["turlar"][0]
        self.assertTrue(t["erken_durma"])
        self.assertTrue(all(d["durum"] == "atlandı" for d in t["duzeltmeler"].values()))
        self.assertIn("erken durdu", s["durma_nedeni"])
        self.assertFalse((Path(s["kayit_klasoru"]) / "tur1_duzeltme_claude.json").exists())

    def test_madde_varsa_duzeltme_calisir_ve_ikinci_turda_durur(self):
        os.environ["SAHTE_ELESTIRI"] = "madde"
        s = self.calistir()
        # v0.22 (karar 55): önemli madde (kritik yok) 1. turdan sonra durdurur; düzeltme yine çalışır.
        # tur0 3 + tur1 (3 eleştiri + 3 düzeltme) + sentez 1 + onay 3
        self.assertEqual(s["cagri_sayisi"], 13)
        self.assertEqual(s["tur_sayisi"], 1)
        self.assertTrue(s["turlar"][0]["erken_durma"])
        self.assertIn("1. turda", s["durma_nedeni"])
        for ad in ("claude", "codex", "gemini"):  # sahte düzeltme maddelerin yarısını KABUL, yarısını RED sayar
            sayim = s["turlar"][0]["duzeltmeler"][ad]["sayim"]
            self.assertTrue(sayim["kimlikli"])
            self.assertEqual(sayim["madde"], 2)  # iki eleştirmenden birer önemli madde
            self.assertEqual((sayim["kabul"], sayim["red"], sayim["yanitsiz"]), (1, 1, 0))

    def test_tur_siniri_birde_durur(self):
        os.environ["SAHTE_ELESTIRI"] = "madde"
        s = self.calistir(tur=1)
        self.assertEqual(s["cagri_sayisi"], 13)  # 3 + 6 + 1 + 3
        self.assertEqual(s["tur_sayisi"], 1)
        self.assertIn("1. turda kritik madde bildirilmedi", s["durma_nedeni"])  # v0.22: önemli madde durmayı engellemez

    def test_tur_siniri_ucte_madde_surerse(self):
        # v0.22: önemli madde tura devam ettirmez; kritik madde sürerse 3 tur: test_v022_duzeltmeler.py
        os.environ["SAHTE_ELESTIRI"] = "madde"
        os.environ["SAHTE_DUZELTME"] = "bozuk"
        s = self.calistir(tur=3)
        self.assertEqual(s["tur_sayisi"], 1)

    def test_gecersiz_tur_degeri(self):
        for t in (0, 4):
            with self.assertRaises(ValueError):
                K.Konsey(self.ayar, tur=t)

    def test_elestiri_kendi_cevabini_ve_saglayici_adini_gormez(self):
        s = self.calistir()
        for ad, kendi in (("claude", "claude cevabı"), ("codex", "codex cevabı"), ("gemini", "gemini cevabı")):
            p = self.prompt(s, f"tur1_elestiri_{ad}.json", "=== CEVAP A ===")
            self.assertNotIn(kendi, p)
            for baska in ({"claude", "codex", "gemini"} - {ad}):
                self.assertIn(f"{baska} cevabı", p)  # diğer iki cevabın metni (sahte cevap yazar adını içerir)
            self.assertEqual(p.count("=== CEVAP "), 2 + p.count("HAKKINDA"))  # yalnızca iki cevap bloğu

    def test_duzeltme_yalniz_kendi_cevabi_ve_kimlikli_maddeler(self):
        os.environ["SAHTE_ELESTIRI"] = "madde"
        s = self.calistir(tur=1)
        p = self.prompt(s, "tur1_duzeltme_codex.json", "SENİN GÜNCEL CEVABIN")
        self.assertIn("codex cevabı", p)
        self.assertNotIn("claude cevabı", p)
        self.assertNotIn("gemini cevabı", p)
        self.assertIn("[E1-1]", p)
        self.assertIn("[E2-1]", p)
        self.assertEqual(p.count("=== DEĞERLENDİRİCİ"), 2)
        self.assertNotIn(K.DUZELTME_HAM_NOTU, p)

    def test_sentez_uc_son_cevabi_ve_onay_kendi_cevabini_alir(self):
        os.environ["SAHTE_ELESTIRI"] = "madde"
        s = self.calistir(tur=1)
        yazar = s["sentez"]["yazar"]
        p = self.prompt(s, f"sentez_{yazar}.json", "sentez yazarısın")
        self.assertEqual(p.count("DÜZELTİLDİ"), 3)  # üç son cevap (düzeltilmiş), Tur 1 değerlendirmeleri değil
        self.assertNotIn("HAKKINDA", p)
        for ad in ("claude", "codex", "gemini"):
            o = self.prompt(s, f"onay_{ad}.json", "ÖNERİLEN ORTAK METİN")
            self.assertIn(f"{ad} cevabı DÜZELTİLDİ", o)
            for baska in ({"claude", "codex", "gemini"} - {ad}):
                self.assertNotIn(f"{baska} cevabı DÜZELTİLDİ", o)

    def test_tur_dosyalari_ve_sayimlar(self):
        os.environ["SAHTE_ELESTIRI"] = "madde"
        s = self.calistir(tur=1)
        k = Path(s["kayit_klasoru"])
        for ad in ("claude", "codex", "gemini"):
            for on in ("elestiri", "degisiklik", "cevap"):
                self.assertTrue((k / "tur1" / f"{on}_{ad}.md").is_file(), (on, ad))
            self.assertTrue((k / f"tur1_elestiri_{ad}.json").is_file())
            self.assertTrue((k / f"tur1_duzeltme_{ad}.json").is_file())
        self.assertIn("DÜZELTİLDİ", (k / "tur1" / "cevap_claude.md").read_text("utf-8"))
        m = json.loads((k / "tur1" / "madde_sayilari.json").read_text("utf-8"))
        self.assertEqual(m["degisiklik_sayimi"]["claude"]["madde"], 2)
        self.assertEqual(set(m["elestiri_sayilari"]), {"claude", "codex", "gemini"})
        for d in ("rapor.md", "ayrinti.md", "kayit.json", "taslak.md"):
            self.assertTrue((k / d).is_file(), d)

    def test_bolum_isareti_okunamazsa_tam_elestiri_gonderilir_ve_not_dusulur(self):
        os.environ["SAHTE_ELESTIRI"] = "bolumsuz"
        s = self.calistir(tur=1)
        self.assertEqual(sorted(s["turlar"][0]["ham_elestiri_gonderilen"]), ["claude", "codex", "gemini"])
        p = self.prompt(s, "tur1_duzeltme_claude.json", "SENİN GÜNCEL CEVABIN")
        self.assertIn(K.DUZELTME_HAM_NOTU, p)
        self.assertIn("bölüm işaretleri okunamadı", s["ayrinti"])
        sayim = s["turlar"][0]["duzeltmeler"]["claude"]["sayim"]
        self.assertFalse(sayim["kimlikli"])

    def test_json_okunamazsa_erken_durma_uygulanmaz(self):
        os.environ["SAHTE_ELESTIRI"] = "bozuk_json"
        s = self.calistir(tur=1)
        self.assertFalse(s["turlar"][0]["erken_durma"])
        self.assertIn("JSON", s["turlar"][0]["erken_durma_nedeni"])
        self.assertIn("sayılar okunamadı", s["ayrinti"])

    def test_json_metin_tutarsizsa_erken_durma_uygulanmaz(self):
        os.environ["SAHTE_ELESTIRI"] = "tutarsiz"
        # v0.22: sahte "tutarsiz" biçimi önemli madde + JSON 0 üretir; artık tutarsızlık değil, durma sebebi (kritik yok).
        # Kritikli tutarsızlık: test_v022_duzeltmeler.py
        s = self.calistir(tur=1)
        self.assertTrue(s["turlar"][0]["erken_durma"])

    def test_basarisiz_elestiri_tek_elestiriyle_devam(self):
        os.environ["SAHTE_ELESTIRI"] = "madde"
        os.environ["SAHTE_GEMINI"] = "kota_elestiri"
        s = self.calistir(tur=1)
        self.assertEqual(s["turlar"][0]["elestiri_basarisiz"], ["gemini"])
        self.assertIn("gemini", s["eksik_katilim"]["tur1_elestiri"])
        p = self.prompt(s, "tur1_duzeltme_claude.json", "SENİN GÜNCEL CEVABIN")
        self.assertEqual(p.count("=== DEĞERLENDİRİCİ"), 1)  # yalnızca GPT'nin eleştirisi
        self.assertEqual(s["turlar"][0]["duzeltmeler"]["claude"]["sayim"]["madde"], 1)
        self.assertEqual(s["durum"], "OYBIRLIGI")

    def test_basarisiz_duzeltmede_onceki_cevap_gecerli_kalir(self):
        os.environ["SAHTE_ELESTIRI"] = "madde"
        os.environ["SAHTE_CODEX"] = "kota_duzeltme"
        s = self.calistir(tur=1)
        d = s["turlar"][0]["duzeltmeler"]["codex"]
        self.assertEqual(d["durum"], "başarısız")
        self.assertIn("codex", s["eksik_katilim"]["tur1_duzeltme"])
        self.assertEqual(s["son_cevaplar"]["codex"], "CEVAP: codex cevabı\nGEREKÇE: test\nGÜVEN: 70")  # Tur 0 cevabı
        self.assertIn("DÜZELTİLDİ", s["son_cevaplar"]["claude"])

    def test_gecersiz_duzeltme_cikti_onceki_cevap_kalir(self):
        os.environ["SAHTE_ELESTIRI"] = "madde"
        os.environ["SAHTE_DUZELTME"] = "bozuk"
        s = self.calistir(tur=1)
        self.assertTrue(all(d["durum"] == "geçersiz" for d in s["turlar"][0]["duzeltmeler"].values()))
        self.assertIn("geçersiz düzeltme çıktısı", s["eksik_katilim"]["tur1_duzeltme"]["claude"])
        self.assertNotIn("DÜZELTİLDİ", s["son_cevaplar"]["claude"])

    def test_notr_hakem_birinci_tur_kayitta(self):
        os.environ["SAHTE_SIRA_CLAUDE"] = "codex,gemini,claude"
        os.environ["SAHTE_SIRA_CODEX"] = "codex,gemini,claude"
        os.environ["SAHTE_SIRA_GEMINI"] = "codex,gemini,claude"
        s = self.calistir()
        a = s["notr_hakem"]["birinci_tur"]
        self.assertEqual((a["notr_hakem_durumu"], a["notr_hakem_galibi"]), ("galip", "codex"))
        self.assertEqual(len(s["notr_hakem"]["turlar"]), 1)
        self.assertIn("GPT>Gemini (hakem: Claude)", s["ayrinti"])
        self.assertIn("Nötr hakem galibi: GPT", s["ayrinti"])
        self.assertNotIn("Nötr hakem", s["ozet_rapor"])  # yalnızca ayrıntıda
        self.assertNotIn("1. sıraya", s["ayrinti"])  # eski "kendini 1. sıraya koyma" mekanizması yok

    def test_iki_cevapta_tek_cevap_gorulur(self):
        os.environ["SAHTE_GEMINI"] = "kota"
        s = self.calistir()
        self.assertEqual(s["durum"], "IKIDE_IKI_BIR_EKSIK")
        p = self.prompt(s, "tur1_elestiri_claude.json", "=== CEVAP A ===")
        self.assertNotIn("=== CEVAP B ===", p)
        self.assertEqual(s["notr_hakem"]["birinci_tur"]["notr_hakem_durumu"], "olculmedi")
        self.assertIn("ölçülmedi (2 cevap)", s["ayrinti"])

    def test_yetersiz_katilim(self):
        os.environ["SAHTE_GEMINI"] = "kota"
        os.environ["SAHTE_CODEX"] = "kota"
        self.assertEqual(self.calistir()["durum"], "YETERSIZ_KATILIM")

    def test_ret_oyu_ve_onay_sayimi_degismedi(self):
        os.environ["SAHTE_CLAUDE"] = "ret"
        s = self.calistir()
        self.assertEqual(s["durum"], "COGUNLUK")


class BaglamTesti(AkisTabani):
    def test_baglam_tum_turlarda_ve_kanit_notunu_etkilemez(self):
        os.environ["SAHTE_ELESTIRI"] = "madde"
        s = self.calistir(tur=1, baglam="BAGLAM-METNI-XYZ")
        self.assertTrue(s["baglam_var"])
        yazar = s["sentez"]["yazar"]
        for dosya, ipucu in (("tur0_claude.json", "bağımsız üyesisin"), ("tur1_elestiri_claude.json", "=== CEVAP A ==="),
                             ("tur1_duzeltme_claude.json", "SENİN GÜNCEL CEVABIN"),
                             (f"sentez_{yazar}.json", "sentez yazarısın"), ("onay_gemini.json", "ÖNERİLEN ORTAK METİN")):
            p = self.prompt(s, dosya, ipucu)
            self.assertIn("SORAN KİŞİ HAKKINDA (kullanıcının verdiği bilgi):", p, dosya)
            self.assertIn("BAGLAM-METNI-XYZ", p, dosya)
            self.assertNotIn("KANIT PAKETİ", p, dosya)
        e = self.prompt(s, "tur1_elestiri_claude.json", "=== CEVAP A ===")
        self.assertIn(K.BAGLAM_ELESTIRI_CUMLESI, e)
        self.assertIn("kullanıcı beyanıdır, doğrulama notunu etkilemedi", s["ayrinti"])
        self.assertIn("kanıt paketi verilmedi", s["ozet_rapor"])  # doğrulama notu baglamdan etkilenmez
        self.assertNotIn("BAGLAM-METNI-XYZ", s["ozet_rapor"])

    def test_baglamsiz_promptlarda_baslik_yok(self):
        s = self.calistir(tur=1)
        self.assertFalse(s["baglam_var"])
        for dosya, ipucu in (("tur0_claude.json", "bağımsız üyesisin"), ("tur1_elestiri_claude.json", "=== CEVAP A ===")):
            p = self.prompt(s, dosya, ipucu)
            self.assertNotIn("SORAN KİŞİ HAKKINDA", p)
            self.assertNotIn(K.BAGLAM_ELESTIRI_CUMLESI, p)

    def test_kanit_ve_baglam_birlikte_ayri_bloklar(self):
        s = self.calistir(tur=1, baglam="BAG", kanit="KANITMETNI")
        p = self.prompt(s, "tur0_codex.json", "bağımsız üyesisin")
        self.assertIn("KANIT PAKETİ", p)
        self.assertIn("SORAN KİŞİ HAKKINDA", p)
        self.assertIn("Doğrulama: kanıt paketi verildi", s["ozet_rapor"])


def kayit_tabani(**ek) -> dict:
    k = {"durum": "OYBIRLIGI", "soru": "S", "onaylanan_metin": "ÖZET: a b.\nCEVAP: c d e\nBELİRSİZLİKLER: Yok",
         "taslak_metin": "ÖZET: a b.\nCEVAP: c d e\nBELİRSİZLİKLER: Yok", "kanit_var": False, "baglam_var": False,
         "eksik_katilim": {}, "istenen_modeller": {"claude": "opus", "codex": "gpt", "gemini": "gem"},
         "gercek_modeller": {}, "on_kontrol": {"surumler": {}}, "cagri_sayisi": 10, "sure_sn": 130.0, "tohum": 1,
         "not": None, "tur_sayisi": 2, "tur_siniri": 2, "durma_nedeni": "2. turda kritik/önemli madde bildirilmedi; erken durdu",
         "kayit_yolu": "/tmp/kayit/xyz", "arac_denetimi": {}, "turlar": [], "kota": {}}
    k.update(ek)
    return k


def oylar(kabul="KABUL", **ek):
    p = {ad: {"oy": kabul, "gecerli": True, "not": "", "gerekce": "gerekçe", "itirazlar": []}
         for ad in ("claude", "codex", "gemini")}
    for ad, v in ek.items():
        p[ad] = dict(p[ad], **v)
    return p


class RaporYerlesimiTesti(unittest.TestCase):
    def ozet(self, k=None, p=None):
        k = k or kayit_tabani()
        p = oylar() if p is None else p
        return K.ozet_rapor_olustur(k, p, "claude", "abc")

    def test_sira_baslik_uyari_cevap_not(self):
        r = self.ozet(kayit_tabani(eksik_katilim={"tur1_elestiri": {"gemini": "zaman aşımı: x"}}))
        satirlar = [x for x in r.splitlines() if x.strip()]
        self.assertTrue(satirlar[0].startswith("# Konsey: OYBIRLIGI · 3 KABUL / 0 RET / 0 ÇEKİMSER · 2 tur · 2,2 dk"), satirlar[0])
        self.assertIn("⚠", satirlar[1])
        i_cevap = r.index("ÖZET: a b.")
        self.assertLess(r.index("⚠"), i_cevap)
        self.assertLess(i_cevap, r.index("## Konsey notu"))
        self.assertTrue(r.rstrip().splitlines()[-1].startswith("- Kayıt: /tmp/kayit/xyz"))

    def test_uyarisiz_rapor_cevap_disi_150_kelimeyi_gecmez(self):
        r = self.ozet()
        self.assertNotIn("⚠", r)
        cevap = "ÖZET: a b.\nCEVAP: c d e\nBELİRSİZLİKLER: Yok"
        self.assertEqual(r.count(cevap), 1)
        digeri = r.replace(cevap, "")
        self.assertLessEqual(len(digeri.split()), 150, digeri)

    def test_ret_gerekceli_rapor_da_150_kelimeyi_gecmez(self):
        uzun = " ".join(["itiraz"] * 80)
        p = oylar(gemini={"oy": "RET", "itirazlar": [uzun]})
        k = kayit_tabani(durum="COGUNLUK")
        r = self.ozet(k, p)
        self.assertIn("Gemini RET (", r)
        self.assertIn("…", r)  # 30 kelimeye kısaltıldı
        self.assertLessEqual(len(r.replace(k["onaylanan_metin"], "").split()), 150)
        self.assertIn("1 RET", r.splitlines()[0])

    def test_uzun_cevap_cevap_disini_sisirmez(self):
        uzun = "ÖZET: a b.\nCEVAP: " + " ".join(["kelime"] * 5000) + "\nBELİRSİZLİKLER: Yok"
        r = self.ozet(kayit_tabani(onaylanan_metin=uzun, taslak_metin=uzun))
        self.assertLessEqual(len(r.replace(uzun, "").split()), 150)
        self.assertNotIn("⚠", r)

    def test_ayrinti_ana_rapora_girmez(self):
        k = kayit_tabani(soru="ÖZGÜN-SORU-METNİ", model_dogrulama={"claude": "sunucu"})
        r = self.ozet(k)
        for yok in ("ÖZGÜN-SORU-METNİ", "model doğrulama", "Araç denetimi", "Çalışma bilgisi", "Nötr hakem", "Tur 0 erken"):
            self.assertNotIn(yok, r)
        a = K.ayrinti_olustur(k, oylar(), "claude", "abc")
        self.assertIn("ÖZGÜN-SORU-METNİ", a)
        self.assertIn("## Çalışma bilgisi", a)

    def test_kota_once_sonra_ayrintida(self):
        k = kayit_tabani(kota_once={"claude": {"durum": "ok", "metin": "Current session: 10% used"}},
                         kota_sonra={"claude": {"durum": "ok", "metin": "Current session: 14% used"},
                                     "gemini": {"durum": "atlandı", "metin": "komut `agy` değil"}})
        a = K.ayrinti_olustur(k, oylar(), "claude", "abc")
        self.assertIn("## Kota: çalıştırmadan önce ve sonra", a)
        self.assertIn("Claude (önce, ok):", a)
        self.assertIn("Current session: 10% used", a)
        self.assertIn("Claude (sonra, ok):", a)
        self.assertIn("Current session: 14% used", a)
        self.assertIn("Gemini (önce): okunmadı", a)
        self.assertIn("Gemini (sonra, atlandı):", a)

    def test_uzlasi_yok_taslagi_etiketle_gosterir(self):
        p = oylar("RET", gemini={"oy": "KABUL"})
        p["claude"]["itirazlar"] = ["Önemli bir noktayı yanlış aktarıyor"]
        p["codex"]["gerekce"], p["codex"]["itirazlar"] = "Kendi noktam atıldı", []
        k = kayit_tabani(durum="UZLASI_YOK", onaylanan_metin=None)
        r = self.ozet(k, p)
        satirlar = [x for x in r.splitlines() if x.strip()]
        i = next(i for i, x in enumerate(satirlar) if "ONAYLANMADI — konsey bu metinde uzlaşamadı." in x)
        self.assertLess(i, 4)
        self.assertIn("RET itirazı (Claude): Önemli bir noktayı yanlış aktarıyor", satirlar[i + 1])
        self.assertIn("RET itirazı (GPT): Kendi noktam atıldı", satirlar[i + 2])
        self.assertLess(r.index("ONAYLANMADI"), r.index("ÖZET: a b."))
        self.assertIn("2 RET", satirlar[0])

    def test_tur0_uzlasi_gerekce_cevabi_ve_etiket(self):
        e = {"karar": "erken_cikis", "degerler": {"claude": 5.0, "codex": 5.0, "gemini": 5.0}, "ortanca": 5.0, "birim": "V",
             "tolerans": 0.01, "gerekce_modeli": "codex",
             "kosullar": {"d_tolerans_icinde": {"en_buyuk_goreli_fark": 0}}}
        k = kayit_tabani(durum="TUR0_UZLASI", onaylanan_metin=None, taslak_metin=None, erken_cikis=e, tur_sayisi=0,
                         durma_nedeni=None, tur0={"codex": {"metin": "CEVAP: 5 V\nGEREKÇE: codex gerekçesi"},
                                                  "claude": {"metin": "CLAUDE-GEREKÇESİ"}})
        r = K.ozet_rapor_olustur(k, {}, None, None)
        self.assertIn("TUR0_UZLASI (oybirliği değildir) · oy yok · 0 tur", r.splitlines()[0])
        self.assertIn("Claude 5 V · GPT 5 V · Gemini 5 V", r)
        self.assertIn("Ortanca: **5 V**", r)
        self.assertIn("Gerekçe: bir üyenin Tur 0 cevabı; diğer ikisi aynı sonucu buldu; metin onaylanmadı.", r)
        self.assertIn("codex gerekçesi", r)
        self.assertNotIn("CLAUDE-GEREKÇESİ", r)
        self.assertNotIn("GPT:", r.split("Gerekçe:")[1])  # gerekçe cevabı üyeyi adlandırmaz

    def test_tur0_gerekce_modeli_ortancaya_en_yakin_esitlikte_tohum(self):
        kon = K.Konsey(self.ayar_bos(), tohum=3)
        self.assertEqual(kon._tur0_gerekce_modeli({"degerler": {"claude": 1.0, "codex": 2.0, "gemini": 3.0}, "ortanca": 2.0}),
                         "codex")
        bir = kon._tur0_gerekce_modeli({"degerler": {"claude": 5.0, "codex": 5.0, "gemini": 5.0}, "ortanca": 5.0})
        self.assertEqual(bir, K.Konsey(self.ayar_bos(), tohum=3)._tur0_gerekce_modeli(
            {"degerler": {"claude": 5.0, "codex": 5.0, "gemini": 5.0}, "ortanca": 5.0}))
        secilenler = {K.Konsey(self.ayar_bos(), tohum=t)._tur0_gerekce_modeli(
            {"degerler": {"claude": 5.0, "codex": 5.0, "gemini": 5.0}, "ortanca": 5.0}) for t in range(40)}
        self.assertGreater(len(secilenler), 1)

    def ayar_bos(self):
        return {"calisma_klasoru": "/tmp/x", "kayit_klasoru": "/tmp/y", "saglayicilar": {}}


class UyariGorunurluguTesti(unittest.TestCase):
    """Her ihlal türü ⚠ satırıyla ozet_rapor'da görünür; hiçbir uyarı yalnızca ayrıntıda kalmaz."""

    def uyarilar(self, k, p=None):
        r = K.ozet_rapor_olustur(k, oylar() if p is None else p, "claude", "abc")
        return [x for x in r.splitlines() if "⚠" in x], r

    def test_model_uyusmazligi(self):
        u, r = self.uyarilar(kayit_tabani(eksik_katilim={"tur0": {"gemini": "cevap veren model istenen model değil; cevap kullanılmadı: x"}}))
        self.assertEqual(len(u), 1)
        self.assertIn("Model uyuşmazlığı", u[0])
        self.assertIn("Gemini", u[0])

    def test_arac_ihlali_cagri_hatasindan(self):
        u, _ = self.uyarilar(kayit_tabani(eksik_katilim={"tur1_elestiri": {"codex": "araç çalıştırdı (salt okunurluk ihlali); cevap kullanılmadı: x"}}))
        self.assertTrue(any("Araç ihlali" in x and "GPT" in x for x in u), u)

    def test_arac_ihlali_denetim_sayaclarindan(self):
        base = {"ihlal": 0, "codex_web_aramasi": 0, "codex_arac_cagrisi": 0, "codex_komutlar": [],
                "codex_bilinmeyen_olaylar": {}, "bos_cevap_arac_denemesi": 0}
        for degisen in ({"ihlal": 1}, {"codex_web_aramasi": 2}, {"codex_arac_cagrisi": 1},
                        {"codex_komutlar": [{"komut": "date", "cikis": 0}]}, {"codex_bilinmeyen_olaylar": {"x": 1}},
                        {"bos_cevap_arac_denemesi": 1}):
            u, _ = self.uyarilar(kayit_tabani(arac_denetimi={"gemini": dict(base, **degisen)}))
            self.assertTrue(any("Araç ihlali — Gemini" in x for x in u), (degisen, u))
        u, _ = self.uyarilar(kayit_tabani(arac_denetimi={"gemini": dict(base)}))
        self.assertEqual(u, [])

    def test_eksik_katilim(self):
        u, _ = self.uyarilar(kayit_tabani(durum="IKIDE_IKI_BIR_EKSIK",
                                          eksik_katilim={"onay": {"gemini": "kota doldu: RESOURCE_EXHAUSTED"}}))
        self.assertEqual(len(u), 1)
        self.assertIn("Eksik katılım — Gemini (onay): kota doldu", u[0])

    def test_basarisiz_tur_cagrilari_da_eksik_katilim_uyarisi(self):
        u, _ = self.uyarilar(kayit_tabani(eksik_katilim={"tur1_duzeltme": {"codex": "geçersiz düzeltme çıktısı (x); önceki cevap geçerli kaldı"},
                                                         "tur2_elestiri": {"claude": "zaman aşımı: x"}}))
        self.assertEqual(len(u), 2)

    def test_bicim_sorunu(self):
        metin = "CEVAP: formül $x$\nBELİRSİZLİKLER: Yok"  # ÖZET yok + LaTeX
        u, _ = self.uyarilar(kayit_tabani(onaylanan_metin=metin, taslak_metin=metin))
        self.assertEqual(len(u), 2)
        self.assertTrue(all("Biçim sorunu" in x for x in u))

    def test_gecersiz_pusula(self):
        p = oylar(gemini={"oy": "CEKIMSER", "gecerli": False, "not": "Oy pusulası (JSON) bulunamadı"})
        u, _ = self.uyarilar(kayit_tabani(durum="IKIDE_IKI_BIR_EKSIK"), p)
        self.assertTrue(any("Geçersiz oy pusulası" in x and "Gemini" in x for x in u))

    def test_uyarilar_basliktan_hemen_sonra_cevaptan_once(self):
        k = kayit_tabani(eksik_katilim={"onay": {"gemini": "kota doldu: x"}},
                         arac_denetimi={"claude": {"ihlal": 1}})
        r = K.ozet_rapor_olustur(k, oylar(), "claude", "abc")
        satirlar = [x for x in r.splitlines() if x.strip()]
        self.assertTrue(satirlar[1].startswith("> ⚠"))
        self.assertTrue(satirlar[2].startswith("> ⚠"))
        self.assertTrue(satirlar[3].startswith("ÖZET:"))

    def test_uc_uca_eksik_katilim_ozet_raporda(self):
        gecici = tempfile.TemporaryDirectory()
        self.addCleanup(gecici.cleanup)
        kok = Path(gecici.name)
        ayar = {"calisma_klasoru": str(kok / "o"), "kayit_klasoru": str(kok / "k"), "cagri_zaman_asimi_sn": 30,
                "saglayicilar": MODELLER_SAHTE()}
        eski = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(eski)))
        os.environ["SAHTE_GEMINI"] = "kota_onay"
        s = asyncio.run(K.Konsey(ayar, tohum=42).calistir("S?"))
        self.assertEqual(s["durum"], "IKIDE_IKI_BIR_EKSIK")
        self.assertIn("⚠", s["ozet_rapor"])
        self.assertIn("Eksik katılım — Gemini (onay)", s["ozet_rapor"])
        self.assertEqual(s["rapor"], s["ozet_rapor"] + "\n---\n\n" + s["ayrinti"])
        self.assertEqual((Path(s["kayit_klasoru"]) / "rapor.md").read_text("utf-8"), s["ozet_rapor"])
        self.assertEqual((Path(s["kayit_klasoru"]) / "ayrinti.md").read_text("utf-8"), s["ayrinti"])


class KotaGoruntusuTesti(unittest.TestCase):
    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        self.addCleanup(self.gecici.cleanup)
        self.kok = Path(self.gecici.name)
        (self.kok / "o").mkdir()
        self.eski = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self.eski)))
        for k in list(os.environ):
            if k.startswith("SAHTE_"):
                del os.environ[k]

    def ayar(self, **ek):
        sag = {ad: dict(v, **ek.get(ad, {})) for ad, v in MODELLER_SAHTE().items()}
        return {"calisma_klasoru": str(self.kok / "o"), "kayit_klasoru": str(self.kok / "k"), "cagri_zaman_asimi_sn": 30,
                "saglayicilar": sag}

    def test_sahte_komutlarda_atlanir(self):
        r = asyncio.run(K.kota_goruntusu(self.ayar(), str(self.kok / "o")))
        self.assertEqual(r["claude"]["durum"], "atlandı")
        self.assertEqual(r["gemini"]["durum"], "atlandı")
        self.assertEqual(r["codex"]["durum"], "atlandı")  # sahte komut ve kayit_dizini yok: gerçek ~/.codex okunmaz

    def test_kota_oku_acikken_okur(self):
        ayar = self.ayar(claude={"kota_oku": True}, gemini={"kota_oku": True})
        r = asyncio.run(K.kota_goruntusu(ayar, str(self.kok / "o")))
        self.assertEqual((r["claude"]["durum"], r["claude"]["metin"]), ("ok", "Current session: 10% used"))
        self.assertEqual(r["gemini"]["durum"], "ok")
        self.assertIn("Five Hour Limit Remaining", r["gemini"]["metin"])

    def test_okuma_hatasi_cokertmez(self):
        os.environ["SAHTE_CLAUDE"] = "bozuk_cikti"
        ayar = self.ayar(claude={"kota_oku": True}, gemini={"kota_oku": True})
        ayar["saglayicilar"]["gemini"]["komut"] = [str(self.kok / "yok-program")]
        r = asyncio.run(K.kota_goruntusu(ayar, str(self.kok / "o")))
        self.assertEqual(r["claude"]["durum"], "okunamadı")
        self.assertEqual(r["gemini"]["durum"], "okunamadı")

    def test_agy_yalitimi_eksikse_agy_calistirilmaz(self):
        ayar = self.ayar(gemini={"kota_oku": True, "home": str(self.kok / "yalitimsiz-home")})
        r = asyncio.run(K.kota_goruntusu(ayar, str(self.kok / "o")))
        self.assertEqual(r["gemini"]["durum"], "atlandı")
        self.assertIn("yalıtım", r["gemini"]["metin"])

    def test_codex_son_oturum_kaydindan(self):
        klasor = self.kok / "codex" / "2026" / "11" / "20"
        klasor.mkdir(parents=True)
        olay = {"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
            "primary": {"used_percent": 12.0, "window_minutes": 300, "resets_at": 1790000000},
            "secondary": {"used_percent": 33.0, "window_minutes": 10080, "resets_at": 1790500000}}}}
        (klasor / "rollout-2026-11-20T10-00-00-abc.jsonl").write_text("bozuk satır\n" + json.dumps(olay) + "\n", "utf-8")
        r = asyncio.run(K.kota_goruntusu(self.ayar(codex={"kayit_dizini": str(self.kok / "codex")}), str(self.kok / "o")))
        self.assertEqual(r["codex"]["durum"], "ok")
        self.assertIn("5 saatlik %12", r["codex"]["metin"])
        self.assertIn("haftalık %33", r["codex"]["metin"])

    def test_konsey_kayda_once_ve_sonra_yazar_ve_cagri_saymaz(self):
        ayar = self.ayar(claude={"kota_oku": True})
        s = asyncio.run(K.Konsey(ayar, tohum=42).calistir("S?"))
        self.assertEqual(s["cagri_sayisi"], 10)  # kota okumaları çağrı sayılmaz
        self.assertEqual(s["kota_once"]["claude"]["durum"], "ok")
        self.assertEqual(s["kota_sonra"]["claude"]["durum"], "ok")
        self.assertIn("Claude (önce, ok):", s["ayrinti"])
        self.assertIn("Claude (sonra, ok):", s["ayrinti"])


class AyarVeKomutSatiriTesti(unittest.TestCase):
    def test_modeller_json_zaman_asimi_600(self):
        self.assertEqual(json.loads((KOK / "modeller.json").read_text("utf-8"))["cagri_zaman_asimi_sn"], 600)

    def cli(self, *arg, ortam=None):
        gecici = tempfile.TemporaryDirectory()
        self.addCleanup(gecici.cleanup)
        kok = Path(gecici.name)
        ayar = kok / "ayar.json"
        ayar.write_text(json.dumps({
            "calisma_klasoru": str(kok / "o"), "kayit_klasoru": str(kok / "k"), "cagri_zaman_asimi_sn": 30,
            "saglayicilar": MODELLER_SAHTE()}),
            encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("SAHTE_")}
        env.update(ortam or {})
        return subprocess.run([sys.executable, str(KOK / "konsey.py"), "--ayar", str(ayar), "--tohum", "5", *arg],
                              capture_output=True, text=True, env=env, timeout=300), kok

    def test_varsayilan_cikti_ozet_rapor_ayrinti_yok(self):
        r, _ = self.cli("Soru?")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("# Konsey: OYBIRLIGI"))
        self.assertNotIn("# Konsey ayrıntısı", r.stdout)
        self.assertIn("Kayıtlar: ", r.stdout)

    def test_ayrinti_secenegi_ekrana_basar(self):
        r, kok = self.cli("--ayrinti", "Soru?")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("# Konsey ayrıntısı: OYBIRLIGI", r.stdout)
        self.assertIn("## Çalışma bilgisi", r.stdout)
        klasor = Path(r.stdout.strip().splitlines()[-1].split("Kayıtlar: ", 1)[1])
        self.assertIn((klasor / "ayrinti.md").read_text("utf-8").strip(), r.stdout)

    def test_tur_secenegi(self):
        r, _ = self.cli("--tur", "1", "Soru?", ortam={"SAHTE_ELESTIRI": "madde"})
        self.assertIn("· 1 tur ·", r.stdout.splitlines()[0])
        self.assertIn("1. turda kritik madde bildirilmedi", r.stdout)

    def test_baglam_dosyasi(self):
        gecici = tempfile.TemporaryDirectory()
        self.addCleanup(gecici.cleanup)
        d = Path(gecici.name)
        (d / "b.md").write_text("Ben bir mühendisim.", "utf-8")
        r, _ = self.cli("--baglam", str(d / "b.md"), "Soru?")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (d / "bos.md").write_text("  \n", "utf-8")
        (d / "buyuk.md").write_bytes(b"x" * (K.BAGLAM_MAKS_BAYT + 1))
        for dosya in ("bos.md", "buyuk.md", "yok.md"):
            r, _ = self.cli("--baglam", str(d / dosya), "Soru?")
            self.assertEqual(r.returncode, 2, dosya)
            self.assertIn("--baglam", r.stdout)


if __name__ == "__main__":
    unittest.main()
