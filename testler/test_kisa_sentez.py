"""
Prompt ve biçim testleri (v0.21, karar 50). Dosya adı eski kısa sentez kararından kalma; içerik artık yeni protokolün
prompt'larını (eleştiri, düzeltme, sentez, onay), Tur 0 hash korumasını, sentez biçim uyarılarını ve komut satırı
seçeneklerini sınar. Eski testler (GEREKÇE sınırı, --uzun, Tur 1 hash'i) kalktı: Tur 1 ve kısa sentez karar 50 ile
değişti. Tur 0 prompt'u DEĞİŞMEDİ (hash aynı).
Gerçek CLI yerine sahte_cli.py kullanılır; gerçek kotaya dokunulmaz.

Çalıştırma (konsey klasöründe):  python -m unittest discover -s testler -v
"""
import hashlib
import re
import subprocess
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import konsey as K  # noqa: E402

# Tur 0 (19 Kasım 2026, karar 34): v0.21'de DEĞİŞMEDİ; baglam verilmediğinde prompt bayt bayt aynı olmalı.
# v0.23 (karar 59): bütün prompt'lara "Bugünün tarihi" satırı eklendi; bu yüzden TÜM özetler bilinçli olarak güncellendi.
# Tarih satırı testte K.TARIH_SABIT ile sabitlenir; satır çıkarılınca Tur 0 prompt'u eski (karar 34) özetle aynıdır
# (bkz. test_v023_tarih_ve_kurallar.py).
TUR0_OZETLERI = ("b943d8153e138fdc868c57d1666c91f9de91dbfe96fabc01ccb7280c8a7f4311",
                 "3e06552b1971f9b74ba41deddde470635cfd155da7b75e548eba564090a6b9f7")
# v0.22 (20 Kasım 2026, karar 55–58): eleştiri ve düzeltme özetleri güncellendi (sentez/onay v0.21'dekiyle aynı).
# v0.21 (20 Kasım 2026, karar 50): yeni prompt'ların özetleri (bağlamsız ve bağlamlı/kanıtlı birer örnek).
# Bu testler kırılırsa değişiklik bilinçli olmalı.
# v0.24 (karar 63): SENTEZ_OZETLERI ve ONAY_OZETLERI genelleme kuralı / önem dereceli itiraz için güncellendi.
ELESTIRI_OZETLERI = ("648b5602c1192671264d03eb69fb2df7a640ea13afc9e270d186d61035a372da",
                     "d63e95dc02fe7eb4ce6d02eba82dc953ecd2ef098d7296f6abdd8345564cd6eb")
DUZELTME_OZETLERI = ("2d0ab566c45df2efb7d6d66a81431d8058c7f7a1f072e95c34bdc6ed282795fa",
                     "9bf2080eef4bad67baa3313edee19fd386edefc7612dbb4aa9616a3a7b55727a")
SENTEZ_OZETLERI = ("db5f85f1a1d20b24ea145ff8b00e29439939e4d1f0b6d3b39645966efd373d30",
                   "7fe8336217748a3e80c9aebd7cace075372462997cb566b8eb5f2ca14f0bda18")
ONAY_OZETLERI = ("3970d7d836cbd41948915e4335a732172422434949ab6a726b36a6aa0b31d53b",
                 "9c7f2cd7be2790e2595906f3308acb588179b69beae3120dbbeeed2aed5a743f")


def ozet(metin: str) -> str:
    return hashlib.sha256(metin.encode()).hexdigest()


class PromptTesti(unittest.TestCase):
    def setUp(self):  # v0.23: tarih satırı sabit değerle; hash'ler çalıştırma gününe bağlı olmasın
        self.eski_tarih = K.TARIH_SABIT
        K.TARIH_SABIT = "2026-01-01"

    def tearDown(self):
        K.TARIH_SABIT = self.eski_tarih

    def test_tur0_promptu_degismedi(self):
        self.assertEqual((ozet(K.p_tur0("SORU", None, None, {})), ozet(K.p_tur0("SORU", "KANIT", None, {}))), TUR0_OZETLERI)

    def test_tur0_promptunda_uzunluk_siniri_yok(self):
        p = K.p_tur0("SORU", None).lower()
        self.assertIsNone(re.search(r"\ben fazla\b|\bkelime\b|\bsınır", p))

    def test_yeni_promptlarin_ozetleri(self):
        self.assertEqual((ozet(K.p_elestiri("SORU", None, [("A", "x"), ("B", "y")], None, {})),
                          ozet(K.p_elestiri("SORU", "KANIT", [("A", "x")], "BAGLAM", {}))), ELESTIRI_OZETLERI)
        self.assertEqual((ozet(K.p_duzeltme("SORU", None, "k", ["e1", "e2"], None, False, {})),
                          ozet(K.p_duzeltme("SORU", "KANIT", "k", ["e1"], "BAGLAM", True, {}))), DUZELTME_OZETLERI)
        self.assertEqual((ozet(K.p_sentez("SORU", None, ["a", "b", "c"], None, None, {})),
                          ozet(K.p_sentez("SORU", "KANIT", ["a"], "BAGLAM", None, {}))), SENTEZ_OZETLERI)
        self.assertEqual((ozet(K.p_onay("SORU", None, "METIN", "abc", "KENDI", None, None, {})),
                          ozet(K.p_onay("SORU", "KANIT", "METIN", "abc", "KENDI", "BAGLAM", None, {}))), ONAY_OZETLERI)

    def test_elestiri_kendi_cevabini_gostermez_ve_bolum_ister(self):
        p = K.p_elestiri("SORU", None, [("A", "cevap-a"), ("B", "cevap-b")])
        self.assertIn("kendi cevabını görmüyorsun", p)
        self.assertIn("=== CEVAP A HAKKINDA ===", p)
        for alan in ("HATALAR", "EKSİK NOKTALAR", "KANITSIZ İDDİALAR", "İYİLEŞTİRME ÖNERİLERİ"):
            self.assertIn(alan, p)
        for s in ("kritik", "önemli", "küçük", "yüksek", "orta", "düşük", "Övgü yazma", "daha_iyi"):
            self.assertIn(s, p)
        for ad in ("Claude", "GPT", "Gemini", "claude", "codex", "gemini"):
            self.assertNotIn(ad, p)

    def test_baglam_cumlesi_yalniz_baglam_varken(self):
        self.assertNotIn(K.BAGLAM_ELESTIRI_CUMLESI, K.p_elestiri("S", None, [("A", "x")]))
        self.assertIn(K.BAGLAM_ELESTIRI_CUMLESI, K.p_elestiri("S", None, [("A", "x")], "ben"))
        self.assertIn("Bağlam verildiyse, cevabın soran kişinin durumuna uygunluğunu da değerlendir.",
                      K.p_elestiri("S", None, [("A", "x")], "ben"))

    def test_baglam_ayri_baslikla_ve_kanittan_ayri(self):
        p = K.p_tur0("S", "KANITMETNI", "BAGLAMMETNI")
        self.assertIn("SORAN KİŞİ HAKKINDA (kullanıcının verdiği bilgi):", p)
        self.assertIn("kanıt paketi değildir", p)
        self.assertLess(p.index("BAGLAMMETNI"), p.index("KANIT PAKETİ"))
        self.assertNotIn("SORAN KİŞİ HAKKINDA", K.p_tur0("S", "KANITMETNI"))
        self.assertNotIn("SORAN KİŞİ HAKKINDA", K.p_tur0("S", None))

    def test_duzeltme_kurali_ve_kayit_bicimi(self):
        p = K.p_duzeltme("S", None, "kendi", ["e1", "e2"])
        self.assertIn("Eleştiriyi yalnızca ikna olduysan kabul et; sırf eleştirildin diye görüş değiştirme.", p)
        self.assertIn("DEĞİŞİKLİK KAYDI:", p)
        self.assertIn("GÜNCEL CEVAP:", p)
        self.assertIn("E1-1 KABUL", p)
        self.assertIn("E1-3 RED", p)
        self.assertIn("TAM ve güncel", p)
        self.assertNotIn(K.DUZELTME_HAM_NOTU, p)
        self.assertIn(K.DUZELTME_HAM_NOTU, K.p_duzeltme("S", None, "kendi", ["e1"], None, True))

    def test_sentez_basliklari_ve_kurallari_ve_kelime_siniri_yok(self):
        p = K.p_sentez("SORU", None, ["c1", "c2", "c3"])
        for baslik in ("ÖZET:", "CEVAP:", "KALAN ANLAŞMAZLIKLAR:", "BELİRSİZLİKLER:"):
            self.assertIn(baslik, p)
        for eski in ("KISA CEVAP", "GEREKÇE:", "TAHMİNLER:", "En fazla", "kelime"):
            self.assertNotIn(eski, p.replace("Yalnızca bir cevapta", ""))
        self.assertIn("LaTeX kullanma", p)
        self.assertIn("2-4 cümle", p)
        self.assertIn("Gerçek bir anlaşmazlık yoksa hiçbir öneriyi anlaşmazlık bölümüne itme", p)
        self.assertIn("Uzunluk sorunun gerektirdiği kadar olsun", p)
        self.assertIn("Soru kendi çıktı biçimini istiyorsa", p)
        self.assertIn("=== CEVAP 3 ===", p)

    def test_onay_olcutu_kendi_cevabi_ve_uzunluk(self):
        p = K.p_onay("SORU", None, "METIN", "abc", "KENDI-SON-CEVAP")
        self.assertIn("KENDI-SON-CEVAP", p)
        self.assertIn("senin cevabındaki doğru ve önemli bir nokta haksız yere atılmış", p)
        self.assertIn("Metnin uzunluğu, üslup farkları ve küçük ifade farkları tek başına ret sebebi değildir", p)
        self.assertIn('"metin_surumu": "abc"', p)


class BicimUyarisiTesti(unittest.TestCase):
    TEMIZ = "ÖZET: Kısa özet.\nCEVAP: Ayrıntı. D = 3,3 / 12 = 0,275\nBELİRSİZLİKLER: Yok"

    def test_temiz_metinde_uyari_yok(self):
        self.assertEqual(K.bicim_uyarilari(self.TEMIZ), [])

    def test_kalan_anlasmazliklar_istege_bagli(self):
        self.assertEqual(K.bicim_uyarilari(self.TEMIZ + "\nKALAN ANLAŞMAZLIKLAR: x"), [])

    def test_uzun_cevapta_kelime_siniri_uyarisi_yok(self):
        self.assertEqual(K.bicim_uyarilari("ÖZET: a\nCEVAP: " + " ".join(["kelime"] * 3000) + "\nBELİRSİZLİKLER: Yok"), [])

    def test_latex_uyarir(self):
        for latex in (r" $D$", r" \(x\)", r" \frac{a}{b}", " V_{out}"):
            u = K.bicim_uyarilari(self.TEMIZ + latex)
            self.assertTrue(any("LaTeX" in x for x in u), latex)

    def test_duz_metin_formul_latex_sayilmaz(self):
        self.assertFalse(any("LaTeX" in x for x in K.bicim_uyarilari(self.TEMIZ + "\nD = Vout / Vin")))

    def test_eksik_baslik_uyarir(self):
        u = K.bicim_uyarilari("CEVAP: x\nBELİRSİZLİKLER: Yok")
        self.assertEqual(len(u), 1)
        self.assertIn("ÖZET", u[0])
        self.assertEqual(len(K.bicim_uyarilari("düz metin")), 3)

    def test_markdown_isaretli_baslik_taninir(self):
        self.assertEqual(K.bicim_uyarilari("**ÖZET:** a\n## CEVAP: b\n**BELİRSİZLİKLER:** Yok"), [])


class KomutSatiriTesti(unittest.TestCase):
    def calistir(self, *arg):
        return subprocess.run([sys.executable, str(KOK / "konsey.py"), *arg], capture_output=True, text=True, timeout=60)

    def test_uzun_secenegi_kalkti(self):
        self.assertNotEqual(self.calistir("--uzun", "x").returncode, 0)

    def test_tur_siniri(self):
        for gecersiz in ("0", "4", "-1"):
            r = self.calistir("--tur", gecersiz, "x")
            self.assertEqual(r.returncode, 2, gecersiz)
            self.assertIn("--tur", r.stdout)

    def test_yeni_secenekler_yardimda(self):
        yardim = self.calistir("--help").stdout
        for s in ("--tur", "--baglam", "--ayrinti"):
            self.assertIn(s, yardim)


if __name__ == "__main__":
    unittest.main()
