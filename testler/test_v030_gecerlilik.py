"""v0.30b (karar 71): GEÇERLİLİK SINIRLARI alanı (Tur 0), sentezde kapsam kuralı, ilk oylamada kapsam kontrolü.
SONUÇ satırı ve TUR0_UZLASI ayrıştırması alandan etkilenmemeli."""
import re
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import konsey as K  # noqa: E402
import sayisal  # noqa: E402
from test_elestiri_duzeltme import AkisTabani  # noqa: E402

ACIK = K.V029_OZELLIKLERI


def cevap(sonuc="12.5 V", sinir="DCM'de geçersiz; ESR ihmal edilemezse geçersiz"):
    return (f"CEVAP: Görev oranı bulunur.\nGEREKÇE: hesap\nVARSAYIMLAR: ideal\nBELİRSİZLİKLER: yok\nGÜVEN: 80\n"
            f"GEÇERLİLİK SINIRLARI: {sinir}\nSONUÇ: {sonuc}")


class Promptlar(unittest.TestCase):
    def test_tur0_alani_varsayilan_acik_ve_sonucu_etkilemez(self):
        p = K.p_tur0("S", None)
        self.assertIn("GEÇERLİLİK SINIRLARI: (Bu cevabın geçersiz olacağı en önemli 1–3 koşul; yoksa YOK)", p)
        self.assertIn("SONUÇ satırı yine cevabın son satırı olsun", p)
        self.assertGreater(p.index("GEÇERLİLİK SINIRLARI"), p.index("GÜVEN: (0-100)"))   # sona eklendi
        self.assertIn(K.TUR0_SAYISAL_KURAL, p)                                            # SONUÇ talimatı duruyor
        self.assertIsNone(re.search(r"karşı görüş|savun", p.lower()))                      # belirli görüş savunması istenmez
        self.assertNotIn("GEÇERLİLİK", K.p_tur0("S", None, None, {}))                      # açıkça v0.28

    def test_sentez_kapsam_kurali(self):
        p = K.p_sentez("S", None, ["a", "b"])
        self.assertIn(K.SENTEZ_KAPSAM_MADDESI, p)
        for s in ("Her genel kuralın hangi koşulda geçerli olduğunu yaz.", "'her zaman', 'hiçbir zaman', 'tüm', 'kesinlikle'",
                  "yalnızca dayanağın varsa kullan", "GEÇERLİLİK SINIRLARI alanlarını kapsam bilgisi olarak kullan"):
            self.assertIn(s, p)
        self.assertNotIn(K.SENTEZ_KAPSAM_MADDESI, K.p_sentez("S", None, ["a", "b"], None, None, {}))

    def test_onay_kapsam_kontrolu_yalniz_ilk_oylamada(self):
        ilk = K.p_onay("S", None, "M", "abc", "k")
        self.assertIn("Kapsam kontrolü: Metinde koşulu belirtilmemiş genel bir iddia var mı? Varsa itiraz olarak yaz "
                      "(önem derecesiyle).", ilk)
        ikinci = K.p_onay("S", None, "M", "abc", "k", None, {"itirazlar": []})
        self.assertNotIn("Kapsam kontrolü", ikinci)
        self.assertNotIn("Kapsam kontrolü", K.p_onay("S", None, "M", "abc", "k", None, None, {}))

    def test_uzunluk_sinirina_dokunulmadi(self):
        for p in (K.p_tur0("S", None), K.p_sentez("S", None, ["a"])):
            self.assertIsNone(re.search(r"\ben fazla \d+ kelime|\bmaksimum \d+ kelime|kelime sınırı", p.lower()))


class Ayristirma(unittest.TestCase):
    def test_sonuc_satiri_alandan_etkilenmez(self):
        d, birim, neden = sayisal.sonuc_oku(cevap())
        self.assertEqual((d, birim), (12.5, "V"))
        d, birim, _ = sayisal.sonuc_oku(cevap(sinir="YOK"))
        self.assertEqual(d, 12.5)
        # alan metninde sayı ve 'SONUÇ' benzeri sözcük olsa da son SONUÇ satırı okunur
        d, _, _ = sayisal.sonuc_oku(cevap(sinir="Vin < 5 V ya da sonuç 3 V altına düşerse geçersiz"))
        self.assertEqual(d, 12.5)

    def test_tur0_uzlasi_alandan_etkilenmez(self):
        t0 = {a: {"durum": "ok", "metin": cevap(sinir=s)} for a, s in
              (("claude", "DCM"), ("codex", "YOK"), ("gemini", "ESR büyükse; Vin düşükse"))}
        k = sayisal.tur0_uzlasi(t0, 0.01)
        self.assertTrue(k["uzlasi"], k)
        t0["gemini"] = {"durum": "ok", "metin": cevap("13.9 V")}
        self.assertFalse(sayisal.tur0_uzlasi(t0, 0.01)["uzlasi"])


class Akis(AkisTabani):
    def test_akis_tur0_sentez_ve_onay_promptlarinda_yeni_metin_var(self):
        s = self.calistir(v029=ACIK)
        import json
        pr = {}
        for f in Path(s["kayit_klasoru"]).glob("*.json"):
            d = json.loads(f.read_text("utf-8"))
            if isinstance(d, dict) and d.get("komut"):
                pr[f.name] = max(d["komut"], key=len)
        self.assertTrue(all("GEÇERLİLİK SINIRLARI" in p for a, p in pr.items() if a.startswith("tur0_")))
        self.assertTrue(any("Kapsam kontrolü" in p for a, p in pr.items() if a.startswith("onay_")))
        self.assertTrue(all("Kapsam kontrolü" not in p for a, p in pr.items() if a.startswith("onay2_")))


if __name__ == "__main__":
    unittest.main()
