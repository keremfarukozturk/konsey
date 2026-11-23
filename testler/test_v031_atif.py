"""v0.31 (karar 74): [K#] atıfları — kimlikleme, prompt kuralları, ayrıştırma, KOD denetimi, rapor bölümleri."""
import asyncio
import json
import os
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import arastirma as R  # noqa: E402
import atif as AT  # noqa: E402
import konsey as K  # noqa: E402
from test_elestiri_duzeltme import AkisTabani  # noqa: E402
from test_v025_arastirma import dizi, madde, sahte_arastirmaci  # noqa: E402

SAHTE_V031 = str(Path(__file__).resolve().parent / "sahte_v031_cli.py")
ACIK = K.V029_OZELLIKLERI


def mad(kimlik, tur="paket", etiketler=(), kaynak_turu="DİĞER", **ek):
    return {"kimlik": kimlik, "tur": tur, "baslik": ek.get("baslik", ""), "alan": ek.get("alan", "ornek.org"),
            "url": ek.get("url", f"https://ornek.org/{kimlik}"), "tarih": "2026-01-01", "etiketler": list(etiketler),
            "kaynak_turu": kaynak_turu}


class Ayristirma(unittest.TestCase):
    def test_bicimler_ve_dayaniklilik(self):
        m = "a [K3] b [K3, K7] c [K1;K2] d [ K4 ,K5 ] e [K10,K11,K12]"
        self.assertEqual(AT.atiflari_oku(m), ["K3", "K3", "K7", "K1", "K2", "K4", "K5", "K10", "K11", "K12"])

    def test_kod_bloklari_ve_satir_ici_kod_sayilmaz(self):
        m = "gerçek [K1]\n```\n[K2]\n```\nsatır içi `[K3]` ve ```[K4]``` sonra [K5]\n```açık blok kapanmamış\n[K6]"
        self.assertEqual(AT.atiflari_oku(m), ["K1", "K5"])

    def test_atif_olmayan_kaliplar_sayilmaz(self):
        for m in ("[K]", "[3]", "[K3a]", "K3", "[k3]", "(K3)", "[KK3]", "[K3 K4]", ""):
            self.assertEqual(AT.atiflari_oku(m), [], m)


class Denetim(unittest.TestCase):
    def tablo(self):
        return [mad("K1"), mad("K2", etiketler=["YÖNLENDİRME_ADRESİ"]), mad("K3", etiketler=["BAŞLIK_ALINTISI"]),
                mad("K4", etiketler=["NİCEL_İDDİA_ALINTIDA_YOK"]), mad("K5", etiketler=["TARİH_BUGÜN"]),
                mad("K6", kaynak_turu="VİDEO_SOSYAL"), mad("K7", etiketler=["TEKRAR_KAYNAK"]),
                mad("K8", tur="kullanici", etiketler=["KULLANICI_KANITI"]), mad("K9", etiketler=["GELECEK_TARİH"])]

    def test_gecerli_atif(self):
        d = AT.denetle("iddia [K1] ve [K7] ve [K8]", self.tablo())
        self.assertEqual((d["atif"], d["uydurma"], d["zayif"]), (3, [], []))     # TEKRAR_KAYNAK ve kullanıcı kanıtı zayıf değil

    def test_uydurma_atif(self):
        d = AT.denetle("iddia [K1] [K99] [K99, K100]", self.tablo())
        self.assertEqual(d["uydurma"], ["K99", "K100"])
        self.assertEqual(d["atif"], 4)

    def test_her_zayif_neden(self):
        d = AT.denetle("[K2] [K3] [K4] [K5] [K6]", self.tablo())
        self.assertEqual([z["kimlik"] for z in d["zayif"]], ["K2", "K3", "K4", "K6"])   # v1.0: TARİH_BUGÜN (K5) zayıf sayılmaz
        self.assertEqual(d["zayif"][3]["nedenler"], ["KAYNAK_TÜRÜ=VİDEO_SOSYAL"])
        self.assertEqual(AT.denetle("[K9]", self.tablo())["zayif"], [])   # GELECEK_TARİH listede yok

    def test_coklu_atif_ve_tekrar_bir_kez_listelenir(self):
        d = AT.denetle("a [K2, K3] b [K2] c [K99] d [K99]", self.tablo())
        self.assertEqual(d["atif"], 5)
        self.assertEqual([z["kimlik"] for z in d["zayif"]], ["K2", "K3"])
        self.assertEqual(d["uydurma"], ["K99"])

    def test_kod_blogu_icindeki_uydurma_sayilmaz(self):
        d = AT.denetle("```\n[K99]\n```\nnormal [K1]", self.tablo())
        self.assertEqual((d["atif"], d["uydurma"]), (1, []))

    def test_denetim_hesapla_ve_bolumler(self):
        t = self.tablo()
        d = AT.denetim_hesapla({"tur0": {"claude": "x [K1] [K98]", "gpt": "y"}, "sentez": {"gemini": "[K2] [K3]"}},
                               "nihai [K1] [K2] [K99] [K1]", t)
        self.assertEqual(d["madde_sayisi"], 9)
        self.assertEqual((d["paket_madde_sayisi"], d["kullanici_madde_sayisi"]), (8, 1))
        self.assertEqual(d["nihai_kullanilan_gecerli"], ["K1", "K2"])
        self.assertEqual(d["kullanilmayan_sayisi"], 7)
        self.assertEqual(d["uydurma_toplam"], 2)         # tur0 K98 + nihai K99
        self.assertEqual(d["zayif_toplam"], 3)           # sentez K2,K3 + nihai K2
        self.assertEqual(AT.uyari_satiri(d), "Nihai metinde pakette olmayan kaynak atfı var (K99).")
        self.assertIsNone(AT.uyari_satiri(AT.denetim_hesapla({}, "temiz [K1]", t)))
        kaynaklar = "\n".join(AT.kaynaklar_bolumu(d, t))
        self.assertIn("**K1**", kaynaklar)
        self.assertIn("**K2** — (başlık yok) · ornek.org · https://ornek.org/K2 · 2026-01-01 · YÖNLENDİRME_ADRESİ", kaynaklar)
        self.assertNotIn("K3", kaynaklar)                 # atıf yapılmayan maddeler listelenmez
        self.assertIn("Pakette 9 madde vardı; 2'ine atıf yapıldı.", kaynaklar)
        den = "\n".join(AT.denetim_bolumu(d))        # v1.0: raporda yalnızca tek satırlık özet
        self.assertIn("Toplam atıf: 4 (nihai metinde 4); uydurma atıf: K98, K99; nihai metinde zayıf dayanaklı kimlikler: K2 (1).", den)
        self.assertNotIn("tur0 / claude", den)
        tab = "\n".join(AT.ayrinti_tablosu(d))
        self.assertIn("tur0 / claude: K98", tab)
        self.assertIn("nihai metin: K99", tab)
        self.assertIn("sentez / gemini: K2 (YÖNLENDİRME_ADRESİ)", tab)
        self.assertIn("| tur0 | claude | 2 | 1 | 0 |", tab)
        self.assertIn("| nihai metin | — | 4 | 1 | 1 |", tab)

    def test_paket_yokken_bos(self):
        self.assertEqual(AT.kaynaklar_bolumu(None, []), [])
        self.assertEqual(AT.denetim_bolumu(None), [])
        self.assertEqual(AT.ayrinti_tablosu(None), [])
        self.assertIsNone(AT.uyari_satiri(None))


class Kimlikleme(unittest.TestCase):
    def test_kanit_basliklara_gore_maddelenir_ve_etiketlenir(self):
        metin, m = AT.kanit_kimlikle("# Giriş\ngövde bir\n## Veri\ngövde iki\n")
        self.assertEqual([x["kimlik"] for x in m], ["K1", "K2"])
        self.assertTrue(metin.startswith("K1. KULLANICI_KANITI — Giriş\ngövde bir"))
        self.assertIn("K2. KULLANICI_KANITI — Veri\ngövde iki", metin)
        self.assertTrue(all(x["etiketler"] == ["KULLANICI_KANITI"] and x["tur"] == "kullanici" for x in m))

    def test_basliksiz_kanit_tek_madde_ve_baslangic(self):
        metin, m = AT.kanit_kimlikle("sadece düz metin", baslangic=3)
        self.assertEqual([x["kimlik"] for x in m], ["K4"])
        self.assertTrue(metin.startswith("K4. KULLANICI_KANITI\nsadece düz metin"))
        self.assertEqual(AT.kanit_kimlikle("  \n"), ("", []))

    def test_paket_kimlikleri_birlestirmede(self):
        pk = {"gemini": [dict(madde(url="https://a.org/1", iddia="IDDIA-A"))], "codex": [dict(madde(url="https://b.org/2", iddia="IDDIA-B"))]}
        pk2 = json.loads(json.dumps(pk))
        b = R.birlestir(pk, etiketle=True, kimlik_baslangic=0)
        self.assertEqual([m["kimlik"] for m in b["maddeler"]], ["K1", "K2"])
        self.assertIn("K1. İddia: IDDIA-A", b["metin"])
        self.assertIn("K2. İddia: IDDIA-B", b["metin"])
        b2 = R.birlestir(pk2, etiketle=True, kimlik_baslangic=2)          # kullanıcı kanıtı 2 madde ise paket K3'ten
        self.assertEqual([m["kimlik"] for m in b2["maddeler"]], ["K3", "K4"])
        self.assertIn("K3. İddia: IDDIA-A", b2["metin"])
        b3 = R.birlestir(json.loads(json.dumps(pk)), etiketle=True)       # eski numaralama
        self.assertIn("1. İddia: IDDIA-A", b3["metin"])
        self.assertNotIn("K1.", b3["metin"])
        self.assertEqual(len(AT.paket_maddeleri({"maddeler": b["maddeler"]})), 2)


class Promptlar(unittest.TestCase):
    def test_kanit_varken_kural_her_promptta(self):
        kr = K.ATIF_KURALI
        self.assertIn(kr, K.p_tur0("S", "KANIT"))
        self.assertIn(kr, K.p_tur0("S", "KANIT", None, {"atif": True}))
        self.assertIn(kr, K.p_duzeltme("S", "KANIT", "c", ["e"]))                         # dayanak sürümü
        self.assertIn(kr, K.p_duzeltme("S", "KANIT", "c", ["e"], None, False, {"atif": True}))   # v0.28 sürümü
        sentez = K.p_sentez("S", "KANIT", ["a", "b"])
        self.assertIn(kr, sentez)
        self.assertIn(K.SENTEZ_ATIF_MADDESI, sentez)
        for s in ("Pakette olmayan bir kimlik yazma.", "[K3, K7]", "etiketli (zayıf) bir maddeye"):
            self.assertIn(s, sentez)

    def test_oylama_atif_kontrolu_yalniz_ilk_oylamada_ve_kanit_varken(self):
        ilk = K.p_onay("S", "KANIT", "M", "abc", "k")
        self.assertIn("Kapsam kontrolü: Metinde koşulu belirtilmemiş genel bir iddia var mı? Varsa itiraz olarak yaz "
                      "(önem derecesiyle). " + K.ONAY_ATIF_KONTROLU, ilk)
        self.assertNotIn(K.ONAY_ATIF_KONTROLU, K.p_onay("S", "KANIT", "M", "abc", "k", None, {"itirazlar": []}))
        self.assertNotIn(K.ONAY_ATIF_KONTROLU, K.p_onay("S", None, "M", "abc", "k"))

    def test_kanit_yokken_promptlar_degismez(self):
        for p in (K.p_tur0("S", None), K.p_duzeltme("S", None, "c", ["e"]), K.p_sentez("S", None, ["a"]),
                  K.p_onay("S", None, "M", "abc", "k"), K.p_tur0("S", ""), K.p_sentez("S", "", ["a"])):
            self.assertNotIn(K.ATIF_KURALI, p)
            self.assertNotIn(K.ONAY_ATIF_KONTROLU, p)
            self.assertNotIn(K.SENTEZ_ATIF_MADDESI, p)
        # bayrak kapalıyken kanıt olsa da değişmez
        for p in (K.p_tur0("S", "KANIT", None, {}), K.p_duzeltme("S", "KANIT", "c", ["e"], None, False, {}),
                  K.p_sentez("S", "KANIT", ["a"], None, None, {}), K.p_onay("S", "KANIT", "M", "abc", "k", None, None, {})):
            self.assertNotIn(K.ATIF_KURALI, p)
            self.assertNotIn(K.SENTEZ_ATIF_MADDESI, p)

    def test_kanit_yokken_bayrakli_ve_bayraksiz_prompt_ayni_atif_acisindan(self):
        a = K.p_tur0("S", None, None, {"gecerlilik": True, "atif": True})
        b = K.p_tur0("S", None, None, {"gecerlilik": True})
        self.assertEqual(a, b)
        self.assertEqual(K.p_sentez("S", None, ["a"], None, None, {"gecerlilik": True, "atif": True}),
                         K.p_sentez("S", None, ["a"], None, None, {"gecerlilik": True}))


class Akis(AkisTabani):
    def setUp(self):
        super().setUp()
        for ad in ("claude", "codex", "gemini"):
            self.ayar["saglayicilar"][ad]["komut"] = [sys.executable, SAHTE_V031, ad]
        self.eski_ar = R.arastirmaci_calistir

    def tearDown(self):
        R.arastirmaci_calistir = self.eski_ar
        super().tearDown()

    def rapor(self, s):
        return (Path(s["kayit_klasoru"]) / "rapor.md").read_text("utf-8")

    def test_kullanici_kaniti_atif_denetimi_ve_rapor_bolumleri(self):
        os.environ["SAHTE_V031_TUR0"] = "[K1] [K9]"
        os.environ["SAHTE_V031_SENTEZ"] = "[K1, K2] ve uydurma [K9] ve `[K7]`"
        s = self.calistir(kanit="# Birinci\nilk kanit\n# İkinci\nikinci kanit\n# Üçüncü\nüçüncü kanit", v029=ACIK)
        r = self.rapor(s)
        # durum satırının hemen altında uyarı; durum hesabı değişmedi
        satirlar = r.splitlines()
        self.assertTrue(satirlar[0].startswith("# Konsey: OYBIRLIGI"), satirlar[0])
        self.assertEqual(satirlar[2], "> ⚠ **UYARI:** Nihai metinde pakette olmayan kaynak atfı var (K9).")
        self.assertIn("## Kaynaklar", r)
        self.assertIn("- **K1** — Birinci · KULLANICI_KANITI (--kanit)", r)
        self.assertIn("- **K2** — İkinci · KULLANICI_KANITI (--kanit)", r)
        self.assertNotIn("Üçüncü ·", r)
        self.assertIn("Pakette 3 madde vardı; 2'ine atıf yapıldı.", r)
        self.assertIn("## Atıf denetimi", r)
        self.assertIn("Toplam atıf: 15 (nihai metinde 3); uydurma atıf: K9; nihai metinde zayıf dayanaklı kimlikler: yok.", r)
        self.assertNotIn("tur0 / claude: K9", r)                               # ayrıntı raporda değil ayrinti.md'de
        k = json.loads((Path(s["kayit_klasoru"]) / "kayit.json").read_text("utf-8"))
        d = k["atif_denetimi"]
        self.assertEqual(d["nihai_kullanilan_gecerli"], ["K1", "K2"])
        self.assertEqual(d["kullanilmayan_sayisi"], 1)
        self.assertEqual(d["asamalar"]["tur0"]["claude"]["uydurma"], ["K9"])
        self.assertNotIn("K7", json.dumps(d["nihai"]["idler"]))             # satır içi kod sayılmadı
        # ayrinti ve telemetri
        a = (Path(s["kayit_klasoru"]) / "ayrinti.md").read_text("utf-8")
        self.assertIn("## Atıf denetimi (kod; [K#] atıfları)", a)
        self.assertIn("| tur0 | claude | 2 | 1 | 0 |", a)
        self.assertIn("Uydurma atıf (pakette olmayan kimlik): 8", a)          # 3 Tur 0 + 3 düzeltilmiş cevap + sentez + nihai metin
        self.assertIn("  - nihai metin: K9", a)
        t = json.loads((Path(s["kayit_klasoru"]) / "telemetri.json").read_text("utf-8"))["atif"]
        self.assertEqual((t["madde_sayisi"], t["nihai_kullanilan"], t["kullanilmayan"]), (3, 2, 1))
        self.assertEqual(t["asamalar"]["tur0"]["claude"], {"atif": 2, "uydurma": 1, "zayif": 0})
        # promptlarda kimlikli kanıt ve kural var
        tur0 = next(x for x in json.loads((Path(s["kayit_klasoru"]) / "tur0_claude.json").read_text("utf-8"))["komut"] if "KANIT PAKETİ" in x)
        self.assertIn("K1. KULLANICI_KANITI — Birinci", tur0)
        self.assertIn(K.ATIF_KURALI, tur0)

    def test_gecerli_atifta_uyari_yok_ve_durum_ayni(self):
        os.environ["SAHTE_V031_SENTEZ"] = "[K1]"
        s = self.calistir(kanit="tek parça kanıt", v029=ACIK)
        r = self.rapor(s)
        self.assertNotIn("pakette olmayan kaynak atfı", r)
        self.assertIn("Pakette 1 madde vardı; 1'ine atıf yapıldı.", r)
        self.assertEqual(s["durum"], "OYBIRLIGI")

    def test_kanit_yoksa_hicbir_sey_degismez(self):
        os.environ["SAHTE_V031_TUR0"] = "[K1]"
        s = self.calistir(v029=ACIK)
        r = self.rapor(s)
        for yok in ("## Kaynaklar", "## Atıf denetimi", "pakette olmayan kaynak"):
            self.assertNotIn(yok, r)
        k = json.loads((Path(s["kayit_klasoru"]) / "kayit.json").read_text("utf-8"))
        self.assertNotIn("atif_denetimi", k)
        self.assertNotIn("atif", json.loads((Path(s["kayit_klasoru"]) / "telemetri.json").read_text("utf-8")))
        tur0 = max(json.loads((Path(s["kayit_klasoru"]) / "tur0_claude.json").read_text("utf-8"))["komut"], key=len)
        self.assertNotIn("[K3, K7]", tur0)

    def test_bayraksiz_konsey_atif_uretmez(self):
        os.environ["SAHTE_V031_SENTEZ"] = "[K1]"
        s = self.calistir(kanit="tek parça kanıt", v029={})
        self.assertNotIn("## Kaynaklar", self.rapor(s))
        self.assertNotIn("atif_denetimi", s)

    def test_arastirma_paketi_kimlikleri_zayif_ve_kaynaklar(self):
        sonuclar = {"gemini": ("ok", dizi(madde(url="https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc",
                                                 iddia="GEMINI-BULGUSU"))),
                    "codex": ("ok", dizi({**madde(url="https://codex-kaynak.org/y", iddia="CODEX-BULGUSU"), "baslik": "Codex Başlık"}))}
        R.arastirmaci_calistir = sahte_arastirmaci(sonuclar, [])
        os.environ["SAHTE_V031_SENTEZ"] = "[K1] [K2] [K5]"
        s = self.calistir(arastir=True, kanit="kullanıcı kanıtı", v029=ACIK)      # kullanıcı K1, paket K2-K3
        r = self.rapor(s)
        k = json.loads((Path(s["kayit_klasoru"]) / "kayit.json").read_text("utf-8"))
        kimlikler = [m["kimlik"] for m in k["kaynak_maddeleri"]]
        self.assertEqual(kimlikler, ["K1", "K2", "K3"])
        self.assertEqual(k["kaynak_maddeleri"][0]["tur"], "kullanici")
        self.assertIn("K2. İddia: GEMINI-BULGUSU", (Path(s["kayit_klasoru"]) / "arastirma_paketi.md").read_text("utf-8"))
        self.assertIn("(K5).", r)                                                     # uydurma
        self.assertIn("nihai metinde zayıf dayanaklı kimlikler: K2 (1)", r)           # yönlendirme adresi zayıf
        self.assertIn("Pakette 3 madde vardı; 2'ine atıf yapıldı.", r)         # K1 ve K2 atıflı (K5 uydurma)


if __name__ == "__main__":
    unittest.main()
