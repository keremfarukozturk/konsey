"""v1.0: NİCEL_İDDİA_ALINTIDA_YOK yalnızca birimli/yüzdeli ölçüm sayılarına bakar; TARİH_BUGÜN zayıflık sayılmaz; sentez ve sentez
düzeltmesi promptlarında okuyucu kuralı; Atıf denetimi raporda tek satır, ayrıntı ayrinti.md'de."""
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
import arastirma as R  # noqa: E402
import atif as AT  # noqa: E402
import konsey as K  # noqa: E402

nicel = R.nicel_iddia_alintida_yok


class NicelKurali(unittest.TestCase):
    def test_birimli_ve_yuzdeli_sayilar_denetlenir(self):
        for iddia, beklenen in (("Verim %98.", ["98"]), ("Verim 98%.", ["98"]), ("Giriş 48V, çıkış 12 V.", ["48", "12"]),
                                ("Akım 5 A.", ["5"]), ("Güç 3 kW ve 2 W.", ["3", "2"]), ("Frekans 300 kHz, 2 MHz, 50 Hz.", ["300", "2", "50"]),
                                ("5.130 W/in³ ve 12 W/cm³.", ["5.130", "12"]), ("Yük 40 nC.", ["40"]), ("Direnç 3 mΩ.", ["3"]),
                                ("Sıcaklık 98 °C.", ["98"]), ("Maliyet $5 ve 7 $.", ["5", "7"]), ("Pazar 12 GW.", ["12"]),
                                ("Boyut 17 mm.", ["17"])):
            self.assertEqual(nicel(iddia, "alıntıda hiçbiri yok"), beklenen, iddia)

    def test_alintida_olan_birimli_sayi_etiket_vermez(self):
        self.assertEqual(nicel("Verim %98 ve 48 V.", "It reaches 98% at 48 V."), [])

    def test_birimsiz_sayilar_sayilmaz(self):
        for iddia in ("LMG3100R017 ürünü.", "TIDA-050089 tasarımı.", "GaN 100 sınıfı", "4:1 oran ve 1/8 tuğla", "2024 ve 2026 yılları",
                      "12 model ve 3 firma", "Seri 7 ve 15 madde", "12 mmHg ve 5 Aboneler"):
            self.assertEqual(nicel(iddia, "hiçbir sayı yok"), [], iddia)

    def test_soru_metnindeki_sayilar_sayilmaz(self):
        self.assertEqual(nicel("48 V'tan 12 V'a ve %98 verim.", "alıntı", soru="48 V'tan 12 V'a dönüşüm?"), ["98"])
        self.assertEqual(nicel("48 V'tan 12 V'a", "alıntı"), ["48", "12"])        # soru verilmezse sayılır

    def test_etiketleme_soruyu_kullanir(self):
        m = {"iddia": "48 V girişli", "alinti": "x", "url": "https://a.org/1", "tarih": "2020", "guven": "orta"}
        R.etiketle_maddeler([m], "2026-11-22", soru="48 V soru")
        self.assertNotIn("NİCEL_İDDİA_ALINTIDA_YOK", m["etiketler"])
        m2 = dict(m)
        R.etiketle_maddeler([m2], "2026-11-22")
        self.assertIn("NİCEL_İDDİA_ALINTIDA_YOK", m2["etiketler"])


class ZayifTanimi(unittest.TestCase):
    def test_tarih_bugun_zayif_degil_digerleri_zayif(self):
        def mad(**kw):
            return {"kimlik": "K1", "tur": "paket", "etiketler": kw.get("e", []), "kaynak_turu": kw.get("t", "DİĞER")}
        self.assertEqual(AT.zayiflik(mad(e=["TARİH_BUGÜN"])), [])
        self.assertEqual(AT.zayiflik(mad(e=["TARİH_BUGÜN", "GELECEK_TARİH", "TEKRAR_KAYNAK"])), [])
        for e in ("YÖNLENDİRME_ADRESİ", "BAŞLIK_ALINTISI", "NİCEL_İDDİA_ALINTIDA_YOK"):
            self.assertEqual(AT.zayiflik(mad(e=[e])), [e])
        self.assertEqual(AT.zayiflik(mad(t="VİDEO_SOSYAL")), ["KAYNAK_TÜRÜ=VİDEO_SOSYAL"])
        self.assertEqual(AT.zayiflik(mad(e=["TARİH_BUGÜN", "YÖNLENDİRME_ADRESİ"])), ["YÖNLENDİRME_ADRESİ"])


class OkuyucuKurali(unittest.TestCase):
    def test_sentez_ve_sentez_duzeltmesi_kuralı_icerir(self):
        for p in (K.p_sentez("S", None, ["a", "b"]), K.p_sentez_duzeltme("S", None, "M", ["i"])):
            for parca in ("ÖZET ve CEVAP'ta konseyin iç işleyişinden söz etme ('bir cevapta', 'üyeler', 'konseyin onayına').",
                          "Okuyucu paketi görmez: 'pakette/paketteki' yerine 'kaynaklarda' de; kaynağa yalnızca [K#] ile atıf yap.",
                          "Görüş ayrılıkları yalnızca KALAN ANLAŞMAZLIKLAR'da."):
                self.assertIn(parca, p)
            self.assertIn(K.OKUYUCU_KURALI, p)

    def test_bayrak_kapaliyken_ve_diger_promptlarda_yok(self):
        self.assertNotIn(K.OKUYUCU_KURALI, K.p_sentez("S", None, ["a"], None, None, {}))
        self.assertNotIn(K.OKUYUCU_KURALI, K.p_sentez_duzeltme("S", None, "M", ["i"], None, None, {}))
        for p in (K.p_tur0("S", None), K.p_duzeltme("S", None, "c", ["e"]), K.p_onay("S", None, "M", "abc", "k"),
                  K.p_elestiri("S", None, [("A", "x")])):
            self.assertNotIn("kaynaklarda", p.replace("Kaynak", ""))
            self.assertNotIn(K.OKUYUCU_KURALI, p)


class AtifBolumuOzet(unittest.TestCase):
    def test_rapor_tek_satir_ayrinti_detay(self):
        t = [{"kimlik": f"K{i}", "tur": "paket", "etiketler": [], "kaynak_turu": "DİĞER"} for i in range(1, 6)]
        t[1]["etiketler"] = ["YÖNLENDİRME_ADRESİ"]
        d = AT.denetim_hesapla({"tur0": {"claude": "a [K2] [K9]"}}, "n [K1] [K2] [K9]", t)
        sat = AT.denetim_bolumu(d)
        govde = [x for x in sat if x.startswith("Toplam atıf")]
        self.assertEqual(len(govde), 1)
        self.assertIn("Toplam atıf: 2 (nihai metinde 3); uydurma atıf: K9; nihai metinde zayıf dayanaklı kimlikler: K2 (1).", govde[0])
        self.assertFalse(any("tur0 /" in x or "nihai metin:" in x for x in sat))     # ayrıntı raporda yok
        ay = "\n".join(AT.ayrinti_tablosu(d))
        self.assertIn("  - tur0 / claude: K9", ay)
        self.assertIn("  - nihai metin: K9", ay)
        self.assertIn("  - nihai metin: K2 (YÖNLENDİRME_ADRESİ)", ay)


if __name__ == "__main__":
    unittest.main()
