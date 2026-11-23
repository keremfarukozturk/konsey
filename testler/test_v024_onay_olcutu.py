"""
v0.24 testleri (karar 63, 20 Kasım 2026: GPT üç koşuda da tek RET veren model; son koşuda dört itiraz kabul edildi,
ikinci oylamada değişmeyen metne yönelik üç yeni itirazla yine RET verdi):
  - sentez ve sentez düzeltme prompt'larında genelleme kuralı
  - onaydaki itirazlara önem derecesi; yalnızca küçük itirazlı RET kodla KABUL, itirazlar ek not
  - ilk oylama prompt'unda "bütün itirazlarını yaz"
  - ikinci oylama: metin farkı + ilk itirazlar ve ele alınışları; RET yalnızca ilk itirazın karşılanmaması ya da
    düzeltmenin yeni kritik/önemli sorun getirmesi; değişmeyen metne yönelik itirazlar ek not
Gerçek CLI yerine sahte_v024_cli.py kullanılır.
"""
import json
import os
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import konsey as K  # noqa: E402
from test_v023_tarih_ve_kurallar import V023Tabani  # noqa: E402

SAHTE_V024 = str(Path(__file__).resolve().parent / "sahte_v024_cli.py")


def pusula(oy="RET", itirazlar=(), ozet="abc"):
    return json.dumps({"metin_surumu": ozet, "oy": oy, "gerekce": "g", "itirazlar": list(itirazlar)}, ensure_ascii=False)


class PromptKurallariTesti(unittest.TestCase):
    def test_sentez_ve_sentez_duzeltme_genelleme_kurali(self):
        for p in (K.p_sentez("S", None, ["a"]), K.p_sentez_duzeltme("S", None, "M", ["i"])):
            self.assertIn("Genelleme yapma; her teknik iddianın geçerli olduğu koşulu ve kapsamı belirt.", p)
            self.assertIn("Bir cevaptan aldığın iddiayı, cevaptakinden daha kesin hale getirme.", p)

    def test_ilk_oylama_promptu_eksiksiz_itiraz_ister_ve_onem_ister(self):
        p = K.p_onay("S", None, "M", "abc", "k")
        self.assertIn("Bütün itirazlarını bu oylamada eksiksiz yaz; sonradan eklenen itirazlar düzeltilemez.", p)
        self.assertIn('"onem": "<kritik|önemli|küçük>"', p)
        self.assertNotIn("İKİNCİ OYLAMA", p)
        self.assertNotIn('"kaynak"', p)
        self.assertNotIn("{{", p)   # JSON şablonu süslü parantezleri çiftlenmemeli
        self.assertTrue(p.rstrip().endswith('"metin": "<itiraz>"}]}'))

    def test_onem_tanimi_elestiri_turlariyla_ayni_olcuyu_kullanir(self):
        e = K.p_elestiri("S", None, [("A", "x")])
        o = K.p_onay("S", None, "M", "abc", "k")
        for parca in ("kritik = sonucu ya da ana önerileri yanlış kılar", "küçük = ifade ya da ayrıntı sorunu"):
            self.assertIn(parca, e)
            self.assertIn(parca, o)
        self.assertIn("aşırı genelleme ve kapsam hatası da önemlidir", o)  # uyarıya düşürülmez

    def test_ikinci_oylama_promptu_fark_ve_itirazlari_icerir(self):
        fark = K.sentez_farki("satır bir\nsatır iki", "satır bir\nsatır ÜÇ")
        ik = {"fark": fark, "itirazlar": [{"kimlik": "R1", "onem": "önemli", "metin": "bootstrap yanlış",
                                           "karar": "KABUL", "gerekce": "doğru", "degisen": "bölüm 3"}]}
        p = K.p_onay("S", None, "M", "abc", "k", None, ik)
        self.assertIn("satır ÜÇ", p)
        self.assertIn("[R1] (önem: önemli) bootstrap yanlış", p)
        self.assertIn("Sentez yazarının kararı: KABUL — gerekçe: doğru; değişen: bölüm 3", p)
        self.assertIn('"kaynak": "<ilk|yeni|degismeyen>"', p)
        self.assertIn("Değişmeyen metne yönelik yeni itirazlar RET sebebi değildir", p)
        self.assertNotIn("sonradan eklenen itirazlar düzeltilemez", p)
        self.assertNotIn("{{", p)
        self.assertTrue(p.rstrip().endswith('"metin": "<itiraz>"}]}'))

    def test_sentez_farki_degisen_satiri_gosterir_ve_sinirlanir(self):
        self.assertEqual(K.sentez_farki("a\nb", "a\nb"), "")
        uzun = K.sentez_farki("x", "y" * 50000, sinir=100)
        self.assertLessEqual(len(uzun), 140)
        self.assertIn("kesildi", uzun)

    def test_sentez_duzeltme_prompt_onemi_gosterir(self):
        p = K.p_sentez_duzeltme("S", None, "M", ["a", "b"], None, ["kritik", "önemli"])
        self.assertIn("[R1] a (önem: kritik)", p)
        self.assertIn("[R2] b (önem: önemli)", p)


class PusulaOnemTesti(unittest.TestCase):
    def test_yalniz_kucuk_itirazli_ret_kabul_sayilir(self):
        p = K.pusula_coz(pusula(itirazlar=[{"onem": "küçük", "metin": "ifade"}]), "abc")
        self.assertEqual((p["oy"], p["orijinal_oy"], p["gecerli"]), ("KABUL", "RET", True))
        self.assertEqual([a["metin"] for a in p["ek_notlar"]], ["ifade"])
        self.assertIn("kodla KABUL", p["not"])

    def test_onemli_ya_da_kritik_itirazli_ret_kalir(self):
        for onem in ("önemli", "kritik", "ONEMLI"):
            p = K.pusula_coz(pusula(itirazlar=[{"onem": onem, "metin": "x"}]), "abc")
            self.assertEqual(p["oy"], "RET", onem)
            self.assertNotIn("orijinal_oy", p)

    def test_karisik_itiraz_ret_kalir_kucuk_ek_not_olur(self):
        p = K.pusula_coz(pusula(itirazlar=[{"onem": "küçük", "metin": "k"}, {"onem": "önemli", "metin": "o"}]), "abc")
        self.assertEqual(p["oy"], "RET")
        self.assertEqual([a["metin"] for a in p["ek_notlar"]], ["k"])
        self.assertEqual(p["itirazlar"], ["k", "o"])

    def test_onemi_belirtilmeyen_ve_duz_metin_itiraz_onemli_sayilir(self):
        for itiraz in ("düz metin", {"metin": "nesne ama önemsiz"}, {"onem": "acil", "metin": "x"}):
            p = K.pusula_coz(pusula(itirazlar=[itiraz]), "abc")
            self.assertEqual(p["oy"], "RET")
            self.assertFalse(p["itiraz_ayrintilari"][0]["onem_belirtildi"])
            self.assertEqual(p["itiraz_ayrintilari"][0]["onem"], "önemli")

    def test_itirazsiz_ret_degismez(self):
        p = K.pusula_coz(pusula(itirazlar=[]), "abc")
        self.assertEqual(p["oy"], "RET")

    def test_kabul_ve_surum_uyusmazligi_etkilenmez(self):
        self.assertEqual(K.pusula_coz(pusula("KABUL"), "abc")["oy"], "KABUL")
        p = K.pusula_coz(pusula(itirazlar=[{"onem": "kritik", "metin": "x"}], ozet="zzz"), "abc")
        self.assertEqual((p["oy"], p["gecerli"]), ("CEKIMSER", False))

    def test_somut_itirazlar_yalniz_kritik_ve_onemliyi_alir(self):
        pus = {"codex": K.pusula_coz(pusula(itirazlar=[{"onem": "küçük", "metin": "k"}, {"onem": "kritik", "metin": "K"},
                                                       {"onem": "önemli", "metin": "o"}]), "abc"),
               "claude": K.pusula_coz(pusula("KABUL", itirazlar=[{"onem": "önemli", "metin": "kabul eden"}]), "abc")}
        self.assertEqual(K.somut_itirazlar(pus), [("codex", "K"), ("codex", "o")])

    def test_eski_bicimli_pusula_somut_itirazlar_calisir(self):
        eski = {"codex": {"oy": "RET", "gecerli": True, "itirazlar": ["x"]}}
        self.assertEqual(K.somut_itirazlar(eski), [("codex", "x")])


class IkinciOylamaPusulaTesti(unittest.TestCase):
    def coz(self, itiraz):
        return K.pusula_coz(pusula(itirazlar=[itiraz]), "abc", ikinci_oylama=True)

    def test_degismeyen_metne_yonelik_onemli_itiraz_ek_not(self):
        p = self.coz({"onem": "önemli", "kaynak": "degismeyen", "metin": "eski cümle"})
        self.assertEqual((p["oy"], p["orijinal_oy"]), ("KABUL", "RET"))
        self.assertEqual(p["ek_notlar"][0]["kaynak"], "degismeyen")

    def test_ilk_itiraz_karsilanmadiysa_ret(self):
        self.assertEqual(self.coz({"onem": "önemli", "kaynak": "ilk", "metin": "x"})["oy"], "RET")

    def test_duzeltme_yeni_sorun_getirdiyse_ret(self):
        self.assertEqual(self.coz({"onem": "kritik", "kaynak": "yeni", "metin": "x"})["oy"], "RET")

    def test_kucuk_itiraz_ikinci_oylamada_da_ret_yapmaz(self):
        self.assertEqual(self.coz({"onem": "küçük", "kaynak": "ilk", "metin": "x"})["oy"], "KABUL")

    def test_kaynagi_belirtilmeyen_itiraz_temkinli_ret_sayilir_ve_isaretlenir(self):
        p = self.coz({"onem": "önemli", "metin": "x"})
        self.assertEqual(p["oy"], "RET")
        self.assertEqual(p["itiraz_ayrintilari"][0]["kaynak"], "belirtilmedi")
        self.assertFalse(p["itiraz_ayrintilari"][0]["kaynak_belirtildi"])

    def test_karisik_ikinci_oylama(self):
        p = K.pusula_coz(pusula(itirazlar=[{"onem": "önemli", "kaynak": "degismeyen", "metin": "d"},
                                           {"onem": "önemli", "kaynak": "yeni", "metin": "y"}]), "abc", True)
        self.assertEqual(p["oy"], "RET")
        self.assertEqual([a["metin"] for a in p["ek_notlar"]], ["d"])


class V024Tabani(V023Tabani):
    def setUp(self):
        super().setUp()
        for ad in ("claude", "codex", "gemini"):
            self.ayar["saglayicilar"][ad]["komut"] = [sys.executable, SAHTE_V024, ad]

    def rapor(self, s) -> str:
        return (Path(s["kayit_klasoru"]) / "rapor.md").read_text("utf-8")


class AkisTesti(V024Tabani):
    def test_yalniz_kucuk_itirazli_ilk_ret_kodla_kabul_duzeltme_yok(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        os.environ["SAHTE_V024_ITIRAZ_ILK"] = json.dumps([{"onem": "küçük", "metin": "ifade farkı"}], ensure_ascii=False)
        s = self.calistir()
        self.assertEqual(s["durum"], "OYBIRLIGI")
        self.assertNotIn("sentez_duzeltme", s)
        self.assertEqual(s["cagri_sayisi"], 10)  # tur0 3 + eleştiri 3 + sentez 1 + onay 3
        self.assertEqual(s["onay"]["pusulalar"]["codex"]["orijinal_oy"], "RET")
        r, a = self.rapor(s), self.ayrinti(s)
        self.assertIn("Ek notlar: oy sonucunu değiştirmeyen 1 itiraz", r)
        self.assertIn("1 RET oyu yalnızca bu tür itiraz içerdiği için kodla KABUL sayıldı", r)
        self.assertNotIn("ifade farkı", r)             # tam metin yalnızca ayrinti.md'de
        self.assertIn("## Ek notlar", a)
        self.assertIn("ifade farkı", a)

    def test_ilk_oylama_promptu_eksiksiz_itiraz_cumlesini_tasir(self):
        s = self.calistir()
        for ad in ("claude", "codex", "gemini"):
            self.assertIn("sonradan eklenen itirazlar düzeltilemez", self.tum_promptlar(s)[f"onay_{ad}.json"])

    def test_ikinci_oylama_fark_ve_ilk_itirazlari_gorur(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        s = self.calistir()
        for ad in ("claude", "codex", "gemini"):
            p = self.tum_promptlar(s)[f"onay2_{ad}.json"]
            self.assertIn("DÜZELTMEDEN ÖNCEKİ VE SONRAKİ METNİN FARKI", p)
            self.assertIn("DÜZELTİLDİ-SENTEZ", p)
            self.assertIn("[R1] (önem: önemli) önemli hata", p)
            self.assertIn("Sentez yazarının kararı: KABUL", p)
            blok = p[p.index("İLK OYLAMADAKİ İTİRAZLAR"):p.index("İTİRAZLAR SONU")]
            self.assertNotIn("codex", blok.lower())   # itiraz sahibi kimliksiz
        self.assertEqual(s["sentez_duzeltme"]["itirazlar"][0]["onem"], "önemli")

    def test_ikinci_oylamada_degismeyen_metne_itiraz_ek_not_sonuc_degismez(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        os.environ["SAHTE_V023_RET_IKINCI"] = "codex"
        os.environ["SAHTE_V024_ITIRAZ_IKINCI"] = json.dumps(
            [{"onem": "önemli", "kaynak": "degismeyen", "metin": "DEĞİŞMEYEN-KONU"}], ensure_ascii=False)
        s = self.calistir()
        self.assertEqual(s["sentez_duzeltme"]["ikinci_oylama"]["durum"], "OYBIRLIGI")
        self.assertEqual(s["durum"], "OYBIRLIGI")
        self.assertEqual(s["onay2"]["pusulalar"]["codex"]["orijinal_oy"], "RET")
        self.assertIn("Ek notlar: oy sonucunu değiştirmeyen 1 itiraz", self.rapor(s))
        self.assertIn("DEĞİŞMEYEN-KONU", self.ayrinti(s))
        self.assertNotIn("DEĞİŞMEYEN-KONU", self.rapor(s))
        self.assertEqual(s["cagri_sayisi"], 14)

    def test_ikinci_oylamada_ilk_itiraz_karsilanmadiysa_ret_kalir(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        os.environ["SAHTE_V023_RET_IKINCI"] = "codex"
        os.environ["SAHTE_V024_ITIRAZ_IKINCI"] = json.dumps(
            [{"onem": "önemli", "kaynak": "ilk", "metin": "R1 hâlâ yok"}], ensure_ascii=False)
        s = self.calistir()
        self.assertEqual(s["durum"], "COGUNLUK")
        self.assertEqual(s["onay2"]["pusulalar"]["codex"]["oy"], "RET")

    def test_ikinci_oylamada_yeni_kritik_sorun_ret_kalir(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        os.environ["SAHTE_V023_RET_IKINCI"] = "codex"
        os.environ["SAHTE_V024_ITIRAZ_IKINCI"] = json.dumps(
            [{"onem": "kritik", "kaynak": "yeni", "metin": "yeni hata"}], ensure_ascii=False)
        s = self.calistir()
        self.assertEqual(s["onay2"]["pusulalar"]["codex"]["oy"], "RET")

    def test_sentez_duzeltmesine_yalniz_kritik_ve_onemli_gider(self):
        os.environ["SAHTE_V023_RET_ILK"] = "codex"
        os.environ["SAHTE_V024_ITIRAZ_ILK"] = json.dumps(
            [{"onem": "önemli", "metin": "önemli hata"}, {"onem": "küçük", "metin": "KUCUK-ITIRAZ"}], ensure_ascii=False)
        s = self.calistir()
        yazar = s["sentez"]["yazar"]
        p = self.tum_promptlar(s)[f"sentez_duzeltme_{yazar}.json"]
        self.assertIn("[R1] önemli hata (önem: önemli)", p)
        self.assertNotIn("KUCUK-ITIRAZ", p)
        self.assertEqual(len(s["sentez_duzeltme"]["itirazlar"]), 1)
        self.assertIn("KUCUK-ITIRAZ", self.ayrinti(s))   # ek not olarak ayrıntıda
        self.assertIn("Ek notlar: oy sonucunu değiştirmeyen 1 itiraz", self.rapor(s))


if __name__ == "__main__":
    unittest.main()
