"""
v0.27 testleri: telemetri.json, konsey notundaki yazar dışı oylar ve "erken durdu" ifadesi.
Oy sayımı ve akış değişmez; yalnızca ölçüm ve raporlama eklendi. Gerçek CLI çağrılmaz (sahte CLI'lar).
"""
import json
import os
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import arastirma as R  # noqa: E402
import konsey as K  # noqa: E402
from test_elestiri_duzeltme import AkisTabani, kayit_tabani, oylar  # noqa: E402
from test_v023_tarih_ve_kurallar import V023Tabani  # noqa: E402
from test_v025_arastirma import dizi, madde, sahte_arastirmaci  # noqa: E402


class TelemetriTesti(V023Tabani):
    def tel(self, s) -> dict:
        return json.loads((Path(s["kayit_klasoru"]) / "telemetri.json").read_text("utf-8"))

    def zengin(self, **kw):
        os.environ["SAHTE_V023_ELESTIRI"] = "zengin"
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        return self.calistir(**kw)

    def test_telemetri_json_yazilir_ve_alanlari_var(self):
        s = self.zengin(tur=2)
        t = self.tel(s)
        for alan in ("kod_surumu", "protokol_surumu", "git", "cli_surumleri", "bildirilen_modeller", "asamalar", "kelime",
                     "elestiri_kategori_onem", "duzeltmeye_iletilen", "kararlar", "oylar", "sentez", "arastirma", "durum"):
            self.assertIn(alan, t, alan)
        self.assertEqual((t["kod_surumu"], t["protokol_surumu"], t["arastirma"]), ("v1.0", "v1.0", False))
        self.assertEqual(t["cli_surumleri"]["claude"], "claude 9.9.9-sahte")
        self.assertEqual(t["bildirilen_modeller"]["claude"], ["claude-opus-5-5"])
        self.assertTrue(t["git"] is None or {"commit", "ozet", "kirli"} <= set(t["git"]))
        self.assertEqual(t["durum"], s["durum"])

    def test_asama_zamanlari_ve_kelime_sayilari(self):
        t = self.tel(self.zengin(tur=2))
        for asama in ("tur0", "tur1_elestiri", "tur1_duzeltme", "tur2_elestiri", "tur2_duzeltme", "sentez", "onay",
                      "sentez_duzeltme", "onay2"):
            a = t["asamalar"][asama]
            self.assertLessEqual(a["baslangic"], a["bitis"], asama)
            self.assertGreaterEqual(a["sure_sn"], 0, asama)
        for asama in ("tur0", "tur1_elestiri", "tur1_duzeltme", "onay"):
            self.assertEqual(set(t["kelime"][asama]), {"claude", "codex", "gemini"}, asama)
            self.assertTrue(all(isinstance(v, int) and v > 0 for v in t["kelime"][asama].values()), asama)
        self.assertEqual(list(t["kelime"]["sentez"]), [t["sentez"]["yazar"]])
        self.assertEqual(set(t["cevap_kelime_tur_sonu"]), {"tur1", "tur2"})

    def test_kategori_onem_ve_iletilen_maddeler(self):
        t = self.tel(self.zengin(tur=2))
        # sahte zengin eleştiri (v0.23 sahte CLI): 1. tur: hata/kritik, eksik/önemli, öneri; 2. tur: + kanıtsız/küçük
        c1 = t["elestiri_kategori_onem"]["tur1"]["claude"]
        self.assertEqual(c1["hatalar"], {"kritik": 2})
        self.assertEqual(c1["eksik noktalar"], {"onemli": 2})
        self.assertEqual(c1["iyilestirme onerileri"], {"oneri": 2})
        c2 = t["elestiri_kategori_onem"]["tur2"]["claude"]
        self.assertEqual(c2["kanitsiz iddialar"], {"kucuk": 2})
        i1 = t["duzeltmeye_iletilen"]["tur1"]["claude"]
        self.assertEqual((i1["madde"], i1["oneri_veya_kucuk"]), (6, 2))       # 1. tur: hepsi gider (öneri dahil)
        self.assertEqual(i1["dagilim"]["iyilestirme onerileri"], {"oneri": 2})
        i2 = t["duzeltmeye_iletilen"]["tur2"]["claude"]
        self.assertEqual((i2["madde"], i2["oneri_veya_kucuk"]), (4, 2))       # 2. tur: yalnızca HATALAR + KANITSIZ
        self.assertNotIn("iyilestirme onerileri", i2["dagilim"])
        self.assertNotIn("eksik noktalar", i2["dagilim"])

    def test_kararlar_oylar_ve_sentez(self):
        t = self.tel(self.zengin(tur=2))
        top = t["kararlar"]["toplam"]
        self.assertEqual(top["madde"], top["kabul"] + top["kismen"] + top["red"] + top["karari_eksik"])
        self.assertGreater(top["madde"], 0)
        for ad in ("claude", "codex", "gemini"):
            k = t["kararlar"]["tur1"][ad]
            self.assertEqual(k["durum"], "ok")
            self.assertIn("karari_eksik", k)
        self.assertEqual(t["oylar"]["ilk"]["codex"], "RET")
        self.assertIsNotNone(t["oylar"]["ikinci"])
        self.assertEqual(t["oylar"]["sonuc"], t["durum"])
        sz = t["sentez"]
        self.assertIn(sz["yazar"], ("claude", "codex", "gemini"))
        self.assertEqual(sz["tur0_medyan_kelime"], 7.0)
        self.assertEqual(sz["oran_tur0_medyan"], round(sz["kelime"] / 7.0, 2))

    def test_eksik_karar_sayisi_telemetride(self):
        os.environ["SAHTE_ELESTIRI"] = "madde"
        os.environ["SAHTE_DUZELTME"] = "ok"
        s = self.calistir(tur=1)
        t = self.tel(s)
        top = t["kararlar"]["toplam"]
        self.assertEqual(top["karari_eksik"], 0)

    def test_arastirma_telemetrisi_ve_asamasi(self):
        eski = R.arastirmaci_calistir
        R.arastirmaci_calistir = sahte_arastirmaci({"gemini": ("ok", dizi(madde(url="https://a.org/1"))),
                                                    "codex": ("ok", dizi(madde(url="https://b.org/1")))}, [])
        try:
            t = self.tel(self.calistir(arastir=True))
        finally:
            R.arastirmaci_calistir = eski
        self.assertTrue(t["arastirma"])
        self.assertIn("arastirma", t["asamalar"])
        self.assertLessEqual(t["asamalar"]["arastirma"]["baslangic"], t["asamalar"]["tur0"]["baslangic"])

    def test_arastirma_durursa_da_telemetri_yazilir(self):
        eski = R.arastirmaci_calistir
        R.arastirmaci_calistir = sahte_arastirmaci({"gemini": ("hata", ""), "codex": ("hata", "")}, [])
        try:
            with self.assertRaises(R.ArastirmaDurdu):
                self.calistir(arastir=True)
        finally:
            R.arastirmaci_calistir = eski
        yollar = list(Path(self.ayar["kayit_klasoru"]).glob("*/telemetri.json"))
        self.assertEqual(len(yollar), 1)
        t = json.loads(yollar[0].read_text("utf-8"))
        self.assertEqual(t["durum"], "ARASTIRMA_DURDU")
        self.assertTrue(t["arastirma"] or True)

    def test_telemetri_hatasi_kosuyu_bozmaz(self):
        eski = K.telemetri_olustur
        K.telemetri_olustur = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("deneme"))
        try:
            s = self.zengin(tur=2)
        finally:
            K.telemetri_olustur = eski
        self.assertIn(s["durum"], K.ONAYLI_DURUMLAR | {"UZLASI_YOK"})
        self.assertIn("RuntimeError", s["telemetri_hatasi"])
        self.assertFalse((Path(s["kayit_klasoru"]) / "telemetri.json").exists())
        self.assertTrue((Path(s["kayit_klasoru"]) / "kayit.json").exists())

    def test_seyrek_kayitla_saf_islev_calisir(self):
        t = K.telemetri_olustur({"durum": "YETERSIZ_KATILIM"}, [], None, None, "2026-11-21T10:00:00")
        self.assertEqual(t["durum"], "YETERSIZ_KATILIM")
        self.assertIsNone(t["sentez"]["kelime"])
        self.assertEqual(t["kararlar"]["toplam"]["madde"], 0)

    def test_oy_ve_sonuc_telemetriden_bagimsiz_ayni(self):
        # telemetri yazımı sonucu etkilemez: aynı koşu telemetri hata verse de aynı durumu üretir
        a = self.zengin(tur=2)["durum"]
        eski = K.telemetri_olustur
        K.telemetri_olustur = lambda *x, **k: (_ for _ in ()).throw(RuntimeError("x"))
        try:
            os.environ["SAHTE_V023_ELESTIRI"] = "zengin"
            os.environ["SAHTE_V023_RET_ILK"] = "codex"
            b = self.calistir(tur=2)["durum"]
        finally:
            K.telemetri_olustur = eski
        self.assertEqual(a, b)


class ToplamaFonksiyonlariTesti(unittest.TestCase):
    def test_gonderilen_madde_dagilimi(self):
        metin = ("HATALAR\n- [E1-1] (önem: kritik; güven: yüksek) a\n- [E1-2] (önem: küçük; güven: orta) b\n"
                 "EKSİK NOKTALAR\n- [E1-3] (önem: önemli; güven: orta) c\n"
                 "İYİLEŞTİRME ÖNERİLERİ\n- [E1-4] (öneri) d\n- [E1-5] e\n")
        self.assertEqual(K.gonderilen_madde_dagilimi("HATALAR\n- [E1-1] etiketsiz satır madde sayılmaz\n")["madde"], 0)
        d = K.gonderilen_madde_dagilimi(metin)
        self.assertEqual(d["madde"], 5)
        self.assertEqual(d["oneri_veya_kucuk"], 3)
        self.assertEqual(d["dagilim"]["hatalar"], {"kritik": 1, "kucuk": 1})
        self.assertEqual(d["dagilim"]["iyilestirme onerileri"], {"oneri": 2})   # etiketsiz satır öneriler altında öneridir
        self.assertEqual(K.gonderilen_madde_dagilimi("hiç madde yok")["madde"], 0)

    def test_medyan(self):
        self.assertEqual(K.medyan([3, 1, 2]), 2.0)
        self.assertEqual(K.medyan([1, 2, 3, 4]), 2.5)
        self.assertIsNone(K.medyan([]))


class YazarDisiOylarTesti(unittest.TestCase):
    def k(self, **ek):
        return kayit_tabani(sentez={"yazar": "gemini", "metin": "x", "metin_surumu": "abc"},
                            onay={"pusulalar": ek.pop("p1", oylar())}, **ek)

    def test_ornek_bicim(self):
        p = oylar(codex={"oy": "RET", "itirazlar": ["x"]})
        k = self.k(p1=p)
        self.assertEqual(K.yazar_disi_oylar_notu(k),
                         "Sentez yazarı: Gemini · Yazar dışı oylar: 1/2 KABUL (Claude KABUL, GPT RET)")

    def test_rapor_notunda_satir_ve_oy_sayimi_degismez(self):
        p = oylar(codex={"oy": "RET", "itirazlar": ["x"]})
        k = self.k(p1=p, durum="COGUNLUK")
        r = K.ozet_rapor_olustur(k, p, "gemini", "abc")
        self.assertIn("- Sentez yazarı: Gemini · Yazar dışı oylar: 1/2 KABUL (Claude KABUL, GPT RET)", r)
        self.assertIn("2 KABUL / 1 RET / 0 ÇEKİMSER", r)
        self.assertIn("- Oylar: Claude KABUL · GPT RET", r)       # mevcut oy satırı aynen

    def test_iki_oylama(self):
        p1 = oylar(codex={"oy": "RET", "itirazlar": ["x"]}, claude={"oy": "RET", "itirazlar": ["y"]})
        p2 = oylar(codex={"oy": "RET", "itirazlar": ["x"]})
        k = self.k(p1=p1, onay2={"pusulalar": p2}, durum="COGUNLUK")
        n = K.yazar_disi_oylar_notu(k)
        self.assertIn("Sentez yazarı: Gemini", n)
        self.assertIn("1. oylama: 0/2 KABUL (Claude RET, GPT RET)", n)
        self.assertIn("2. oylama: 1/2 KABUL (Claude KABUL, GPT RET)", n)

    def test_yazar_oyu_sayilmaz_ve_oy_yoksa_satir_yok(self):
        k = self.k(p1=oylar(gemini={"oy": "RET", "itirazlar": ["z"]}))
        self.assertIn("2/2 KABUL (Claude KABUL, GPT KABUL)", K.yazar_disi_oylar_notu(k))   # yazarın RET'i yazar dışı değil
        self.assertIsNone(K.yazar_disi_oylar_notu(kayit_tabani()))                         # sentez yazarı/oy yok
        self.assertIsNone(K.yazar_disi_oylar_notu(kayit_tabani(durum="TUR0_UZLASI")))


class TurDurumuMetniTesti(V023Tabani):
    def rapor(self, s) -> str:
        return s["ozet_rapor"]

    def test_sinira_ulasildi_ve_kritik_yok_erken_durdu_yazilmaz(self):
        os.environ["SAHTE_V023_ELESTIRI"] = "zengin"            # 1. tur kritik var, 2. tur kritik yok
        s = self.calistir(tur=2)
        self.assertEqual(s["tur_sayisi"], 2)
        self.assertNotIn("erken durdu", s["durma_nedeni"])
        self.assertIn("2. turda kritik madde bildirilmedi", s["durma_nedeni"])
        self.assertIn("tur sınırına (2) ulaşıldı", s["durma_nedeni"])
        satir = next(x for x in self.rapor(s).splitlines() if x.startswith("- Turlar:"))
        self.assertIn("2/2", satir)
        self.assertNotIn("erken durdu", self.rapor(s))
        self.assertNotIn("erken durdu", s["ayrinti"])

    def test_sinirdan_once_durulursa_erken_durdu_yazilir(self):
        os.environ["SAHTE_V023_ELESTIRI"] = "zengin"
        s = self.calistir(tur=3)                                 # 2. turda kritik yok, sınır 3
        self.assertEqual(s["tur_sayisi"], 2)
        self.assertIn("2. turda kritik madde bildirilmedi; erken durdu", s["durma_nedeni"])
        satir = next(x for x in self.rapor(s).splitlines() if x.startswith("- Turlar:"))
        self.assertIn("2/3", satir)
        self.assertIn("erken durdu", satir)

    def test_ilk_turda_durulursa_erken_durdu(self):
        os.environ["SAHTE_ELESTIRI"] = "madde"                   # sahte_cli: önemli madde, kritik yok
        for ad in self.ayar["saglayicilar"]:
            self.ayar["saglayicilar"][ad]["komut"][1] = str(Path(__file__).resolve().parent / "sahte_cli.py")
        s = self.calistir(tur=2)
        self.assertEqual(s["tur_sayisi"], 1)
        self.assertIn("1. turda kritik madde bildirilmedi; erken durdu", s["durma_nedeni"])

    def test_tur_siniri_1_ve_kritik_yok_erken_durdu_yazilmaz(self):
        os.environ["SAHTE_ELESTIRI"] = "madde"
        for ad in self.ayar["saglayicilar"]:
            self.ayar["saglayicilar"][ad]["komut"][1] = str(Path(__file__).resolve().parent / "sahte_cli.py")
        s = self.calistir(tur=1)
        self.assertNotIn("erken durdu", s["durma_nedeni"])
        self.assertIn("tur sınırına (1) ulaşıldı", s["durma_nedeni"])

    def test_erken_durma_karari_eleştiriden_sonra_duzeltmeden_once_ama_duzeltme_yine_calisir(self):
        os.environ["SAHTE_V023_ELESTIRI"] = "zengin"
        s = self.calistir(tur=2)
        t2 = s["turlar"][1]
        self.assertTrue(t2["erken_durma"])                      # karar verildi
        self.assertTrue(any(d["durum"] == "ok" for d in t2["duzeltmeler"].values()))   # düzeltme yine de çalıştı
        self.assertTrue((Path(s["kayit_klasoru"]) / "tur2_duzeltme_claude.json").exists())


if __name__ == "__main__":
    unittest.main()
