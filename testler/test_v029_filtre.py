"""v0.29b (Aşama 3, maddeler 1–3): boş liste geçerli, süzgeç, atlanan düzeltme. Bayrak: V029_OZELLIKLERI["filtre"]."""
import os
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import konsey as K  # noqa: E402
from test_v023_tarih_ve_kurallar import V023Tabani  # noqa: E402

SAHTE_V029 = str(Path(__file__).resolve().parent / "sahte_v029_cli.py")
FILTRE = {"filtre": True}

UZUN = """=== CEVAP A HAKKINDA ===
HATALAR
- [1] (önem: kritik; güven: yüksek) hata-bir
- [2] (önem: küçük; güven: orta) hata-kucuk
EKSİK NOKTALAR
- [3] (önem: önemli; güven: orta; sonucu değiştirir: sayıyı iki katına çıkarır) eksik-sonuclu
- [4] (önem: önemli; güven: orta) eksik-sonucsuz
- [5] (önem: önemli; güven: orta; sonucu değiştirir: hayır) eksik-hayir
- [6] (önem: önemli; güven: orta; sonucu değiştirir: ) eksik-bos
- [12] (önem: küçük; güven: orta) eksik-kucuk
- [13] (önem: kritik; güven: orta) eksik-kritik
KANITSIZ İDDİALAR
- [7] (önem: önemli; güven: düşük) kanitsiz
- [8] (önem: belirsizx; güven: düşük) kanitsiz-belirsiz-onem
AŞIRI GENELLEME / KAPSAM HATASI
- [9] (önem: önemli; güven: orta) asiri
  devam satiri asiri
- [10] (önem: küçük; güven: orta) asiri-kucuk
  devam satiri kucuk
İYİLEŞTİRME ÖNERİLERİ
- [11] (öneri) oneri
```json
{"A": {"kritik": 1, "onemli": 6, "kucuk": 3}}
```"""


class YeniBaslikVeSuzgec(unittest.TestCase):
    def test_asiri_genelleme_basligi_taninir(self):
        for b in ("AŞIRI GENELLEME / KAPSAM HATASI", "**AŞIRI GENELLEME / KAPSAM HATASI**",
                  "## AŞIRI GENELLEME/KAPSAM HATASI:", "AŞIRI GENELLEME  /  KAPSAM HATASI"):
            self.assertEqual(K._alt_baslik(b), K.ASIRI_ALT, b)
        m = K.madde_satirlari("AŞIRI GENELLEME / KAPSAM HATASI\n- [1] (önem: önemli; güven: orta) x")
        self.assertEqual((m[0]["alt_baslik"], m[0]["onem"]), (K.ASIRI_ALT, "onemli"))

    def test_suzgec_kararlari(self):
        c = K.elestiri_coz(UZUN, ["A"])
        metin, idler, gonderilmeyen = K.elestiri_metni_suz_v029(1, c, "A")
        # v0.30a (karar 70): EKSİK'te kritik/önemli "sonucu değiştirir" aranmadan gider.
        # v0.30c (karar 73): HATALAR / KANITSIZ / AŞIRI GENELLEME maddeleri küçük dahil gider; yalnızca EKSİK'in küçükleri ve öneriler gitmez
        gider = ["hata-bir", "hata-kucuk", "eksik-sonuclu", "eksik-sonucsuz", "eksik-hayir", "eksik-bos", "eksik-kritik",
                 "kanitsiz", "kanitsiz-belirsiz-onem", "asiri", "asiri-kucuk"]
        for x in gider:
            self.assertIn(x, metin, x)
        self.assertEqual(idler, [f"E1-{i}" for i in range(1, 12)])
        for x in ("eksik-kucuk", "oneri"):
            self.assertNotIn(x, metin, x)
        self.assertIn("devam satiri asiri", metin)
        self.assertIn("devam satiri kucuk", metin)     # küçük AŞIRI GENELLEME maddesinin devam satırı da gider
        neden = {g["metin"].split(") ", 1)[-1]: g["neden"] for g in gonderilmeyen}
        self.assertEqual(neden["eksik-kucuk"], "küçük (eksik nokta)")
        self.assertEqual(neden["oneri"], "öneri")
        self.assertEqual(len(gonderilmeyen), 2)
        # kategori başına küçük madde
        for kat, onem_etiketi in (("HATALAR", "hata-kucuk"), ("KANITSIZ İDDİALAR", "kk"), ("AŞIRI GENELLEME / KAPSAM HATASI", "ak")):
            c2 = K.elestiri_coz(f"=== CEVAP A HAKKINDA ===\n{kat}\n- [1] (önem: küçük; güven: yüksek) {onem_etiketi}-x\n```json\n"
                                '{"A": {"kritik": 0, "onemli": 0, "kucuk": 1}}\n```', ["A"])
            m2, i2, g2 = K.elestiri_metni_suz_v029(1, c2, "A")
            self.assertEqual((i2, g2), (["E1-1"], []), kat)
            self.assertIn(f"{onem_etiketi}-x", m2)

    def test_bos_baslik_yazilmaz(self):
        c = K.elestiri_coz("=== CEVAP A HAKKINDA ===\nEKSİK NOKTALAR\n- [1] (önem: küçük; güven: orta) k\n"
                           "İYİLEŞTİRME ÖNERİLERİ\n- [2] (öneri) o\n```json\n"
                           '{"A": {"kritik": 0, "onemli": 0, "kucuk": 1}}\n```', ["A"])
        metin, idler, gonderilmeyen = K.elestiri_metni_suz_v029(1, c, "A")
        self.assertEqual((metin, idler, len(gonderilmeyen)), ("", [], 2))

    def test_bolum_okunamazsa_ham_gider(self):
        metin, idler, g = K.elestiri_metni_suz_v029(1, K.elestiri_coz("Düz metin", ["A"]), "A")
        self.assertIsNone(idler)
        self.assertIn("Düz metin", metin)
        self.assertEqual(g, [])

    def test_bos_liste_gecerli_eleştiridir(self):
        c = K.elestiri_coz("=== CEVAP A HAKKINDA ===\nBu cevapta düzeltilmesi gereken bir şey yok.\n```json\n"
                           '{"A": {"kritik": 0, "onemli": 0, "kucuk": 0}}\n```', ["A"])
        self.assertTrue(c["bolum_ok"])
        self.assertTrue(K.madde_yok(c, "A"))
        self.assertTrue(K.erken_durma_karari({"claude": c})[0])

    def test_prompt_v029_biçimi(self):
        p = K.p_elestiri("S", None, [("A", "x")], None, FILTRE)
        for s in ("Bu cevapta düzeltilmesi gereken bir şey yok.", "AŞIRI GENELLEME / KAPSAM HATASI",
                  "hiçbiri zorunlu değil", "Bugünün tarihi: ", "HATALAR, EKSİK NOKTALAR, KANITSIZ İDDİALAR ve"):
            self.assertIn(s, p)
        self.assertNotIn("sonucu değiştirir", p)   # v0.30a: alan kalktı
        self.assertNotIn("şu dört alt başlık olsun", p)
        self.assertEqual(p.count("Bugünün tarihi: "), 1)
        for s in ("test", "tuzak"):
            self.assertNotIn(s, p.replace("sonucu", "").lower().split("=== cevap a ===")[0])

    def test_bayraksiz_prompt_degismez(self):
        eski = K.p_elestiri("S", None, [("A", "x")], None, {})
        self.assertEqual(K.p_elestiri("S", None, [("A", "x")], None, None), eski)
        self.assertEqual(K.p_elestiri("S", None, [("A", "x")], None, {}), eski)
        self.assertNotIn("AŞIRI GENELLEME", eski)
        self.assertIn("şu dört alt başlık olsun", eski)

    def test_v029_ozellikleri_bayraklari(self):
        self.assertEqual(K.V029_OZELLIKLERI, {"filtre": True, "dayanak": True, "gecerlilik": True, "atif": True, "okuyucu": True})   # v0.30b: gecerlilik, v0.31: atif, v1.0: okuyucu eklendi


class AkisTesti(V023Tabani):
    def setUp(self):
        super().setUp()
        for ad in ("claude", "codex", "gemini"):
            self.ayar["saglayicilar"][ad]["komut"] = [sys.executable, SAHTE_V029, ad]

    def duzeltme_promptlari(self, s, tur="tur1"):
        return {a: p for a, p in self.tum_promptlar(s).items() if a.startswith(f"{tur}_duzeltme_")}

    def test_uzun_eleştiri_suzulur_ve_kayda_yazilir(self):
        os.environ["SAHTE_V029_ELESTIRI"] = "uzun"
        s = self.calistir(tur=2, v029=FILTRE)
        ps = self.duzeltme_promptlari(s)
        self.assertEqual(len(ps), 3)
        for p in ps.values():
            kisim = p.split("SENİN GÜNCEL CEVABIN")[1]
            for m in ("HATA-V029", "EKSIKSONUC-V029", "EKSIKSONUCSUZ-V029", "KANITSIZ-V029", "ASIRI-V029"):
                self.assertIn(m, kisim)   # v0.30a: önemli EKSİK maddeleri "sonucu değiştirir" aranmadan gider
            self.assertIn("HATAKUCUK-V029", kisim)     # v0.30c: küçük HATALAR maddesi de gider
            for m in ("EKSIKKUCUK-V029", "ONERI-V029"):
                self.assertNotIn(m, kisim)
            self.assertEqual(kisim.count("=== DEĞERLENDİRİCİ"), 2)
        t = s["turlar"][0]
        self.assertTrue(t["v029_filtre"])
        self.assertFalse(t["yalniz_hata_kurali"])
        self.assertEqual(len(t["gonderilmeyen_maddeler"]["claude"]), 4)  # 2 eleştirmen x (küçük EKSİK, öneri)
        a = self.ayrinti(s)
        self.assertIn("GÖNDERİLMEYEN 4 madde", a)
        self.assertIn("neden: küçük (eksik nokta)", a)
        self.assertIn("neden: öneri", a)

    def test_yalniz_eksik_kucuk_ve_oneri_varsa_duzeltme_atlanir_cevap_aynen_tasinir(self):
        os.environ["SAHTE_V029_ELESTIRI"] = "yalniz_oneri"
        s = self.calistir(tur=2, v029=FILTRE)
        t = s["turlar"][0]
        for ad in ("claude", "codex", "gemini"):
            self.assertEqual(t["duzeltmeler"][ad], {"durum": "atlandı", "neden": "madde yok"})
            self.assertFalse((Path(s["kayit_klasoru"]) / f"tur1_duzeltme_{ad}.json").exists())
        self.assertEqual(s["son_cevaplar"]["claude"], self.ham(s, "kayit.json")["tur0"]["claude"]["metin"].strip())
        self.assertIn("atlandı (madde yok)", self.ayrinti(s))

    def test_bos_liste_duzeltmeyi_atlar(self):
        os.environ["SAHTE_V029_ELESTIRI"] = "bos"
        s = self.calistir(tur=2, v029=FILTRE)
        self.assertEqual(s["tur_sayisi"], 1)
        self.assertTrue(all(d == {"durum": "atlandı", "neden": "madde yok"} for d in s["turlar"][0]["duzeltmeler"].values()))
        self.assertEqual(s["cagri_sayisi"], 10)  # 3 + 3 eleştiri + 0 düzeltme + 1 sentez + 3 onay

    def test_bayraksiz_konsey_v028_promptunu_kullanir(self):
        os.environ["SAHTE_V029_ELESTIRI"] = "bos"
        s = self.calistir(tur=1)
        for p in self.tum_promptlar(s).values():
            self.assertNotIn("AŞIRI GENELLEME", p)


if __name__ == "__main__":
    unittest.main()
