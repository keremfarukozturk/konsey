"""
v0.22 düzeltmeleri (karar 55–58, 20 Kasım 2026 ilk gerçek koşunun analizi: kayitlar/2026-11-20_141555_38140):
sentez başlık kontrolü, GÜNCEL CEVAP ayrıştırıcısı, kodun verdiği sıralı madde kimlikleri, KISMEN KABUL, öneri maddeleri,
yalnızca kritik maddeye bakan erken durma, düzeltme prompt kuralları, Codex kota okumasının zaman damgası.
Gerçek CLI yerine sahte CLI'lar kullanılır. Gerçek kayıt klasörü (git dışı) varsa ona karşı da sınar; yoksa o testler atlanır.

Çalıştırma (konsey klasöründe):  python -m unittest discover -s testler -v
"""
import asyncio
import datetime as dt
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import konsey as K  # noqa: E402
from test_elestiri_duzeltme import AkisTabani  # noqa: E402

KRITIK_CLI = str(Path(__file__).resolve().parent / "sahte_kritik_cli.py")
GERCEK_KAYIT = KOK / "kayitlar" / "2026-11-20_141555_38140"
KAYIT_VAR = unittest.skipUnless(GERCEK_KAYIT.exists(), "gerçek kayıt klasörü yok (git dışı)")


class BaslikTesti(unittest.TestCase):
    """Madde 3: '## ÖZET' biçimi (iki nokta yok) eskiden 'başlık bulunamadı' uyarısı veriyordu."""

    SENTEZ = "## ÖZET\n\nEvet, ...\n\n## CEVAP\n\n### Alt başlık\n\nmetin\n\n## BELİRSİZLİKLER\n\n- tanım"

    def test_markdown_basligi_iki_noktasiz_taninir(self):
        self.assertEqual(K.bicim_uyarilari(self.SENTEZ), [])

    def test_biçimler(self):
        for t in ("ÖZET: kısa", "**ÖZET:** x", "## ÖZET\n", "**ÖZET**\n", "**ÖZET**: x", "### ÖZET:\nx", "ÖZET"):
            self.assertTrue(K.sentez_baslik_var_mi(t, "ÖZET"), t)

    def test_satir_icindeki_sozcuk_baslik_degildir(self):
        for t in ("Bu CEVAP verdim", "CEVAP verdim\n", "Sonuç ÖZET gibi", ""):
            self.assertFalse(K.sentez_baslik_var_mi(t, "CEVAP"), t)
            self.assertFalse(K.sentez_baslik_var_mi(t, "ÖZET"), t)

    def test_eksik_baslik_hala_uyarir(self):
        u = K.bicim_uyarilari("## ÖZET\n\nx\n\n## CEVAP\n\ny")
        self.assertEqual(len(u), 1)
        self.assertIn("BELİRSİZLİKLER", u[0])


class GuncelCevapTesti(unittest.TestCase):
    """Madde 2: başlıktan sonraki '[*\\s]*' gövdenin açılış '**' işaretini yutuyordu; tekrarlı 'CEVAP:' etiketi kalıyordu."""

    KAYIT = "DEĞİŞİKLİK KAYDI:\n- E1-1 KABUL: x\n"

    def coz(self, govde_oncesi_ve_govde: str) -> str:
        d = K.duzeltme_coz(self.KAYIT + govde_oncesi_ve_govde)
        self.assertTrue(d["gecerli"])
        return d["cevap"]

    def test_claude_ornegi_cevap_etiketi_ve_kalin_isaret(self):
        # gerçek kayıt: "GÜNCEL CEVAP:\n\n**CEVAP:**\nEvet, AGI'ye çok yakın ..." -> eskiden "CEVAP:**\nEvet..."
        c = self.coz("\nGÜNCEL CEVAP:\n\n**CEVAP:**\nEvet, AGI'ye çok yakın bir teknoloji.\n\nBu bir **tahmin**.")
        self.assertTrue(c.startswith("Evet, AGI'ye"), c[:40])
        self.assertNotIn("CEVAP:", c)

    def test_gpt_ornegi_acilis_kalin_isareti_korunur(self):
        # gerçek kayıt: "GÜNCEL CEVAP:\n\n**Evet. Bence ... 2030–2040.** ..." -> eskiden açılış ** yutuluyordu
        c = self.coz("\nGÜNCEL CEVAP:\n\n**Evet. Bence bir sistem geliştirilecek. En makul dönem 2030–2040.** Sonra devam.")
        self.assertTrue(c.startswith("**Evet."), c[:20])
        self.assertEqual(c.count("**") % 2, 0)

    def test_gemini_ornegi_tekrarli_cevap_etiketi(self):
        # gerçek kayıt: "GÜNCEL CEVAP:\nCEVAP:\n**Evet**, yüksek olasılıkla ..."
        c = self.coz("\nGÜNCEL CEVAP:\nCEVAP:\n**Evet**, yüksek olasılıkla önce AGI-benzeri.")
        self.assertTrue(c.startswith("**Evet**, yüksek"), c[:30])

    def test_kalin_baslik_kapanisi_tuketilir_govde_korunur(self):
        self.assertEqual(self.coz("\n**GÜNCEL CEVAP:**\n**Evet** dedi."), "**Evet** dedi.")
        self.assertEqual(self.coz("\n**GÜNCEL CEVAP**:\nMetin"), "Metin")
        self.assertEqual(self.coz("\n## GÜNCEL CEVAP:\n**Evet**"), "**Evet**")
        self.assertEqual(self.coz("\n**GÜNCEL CEVAP:** düz metin"), "düz metin")
        self.assertEqual(self.coz("\nGÜNCEL CEVAP: **Evet** dedi."), "**Evet** dedi.")

    def test_etiket_yalniz_basta_ve_yalniz_etiketin_kendisi_atilir(self):
        self.assertEqual(K.cevap_etiketini_sok("CEVAP: Evet.\nCEVAP: ikinci"), "Evet.\nCEVAP: ikinci")
        self.assertEqual(K.cevap_etiketini_sok("**CEVAP:** **Evet**"), "**Evet**")
        self.assertEqual(K.cevap_etiketini_sok("CEVAPLAR çeşitli"), "CEVAPLAR çeşitli")
        self.assertEqual(K.cevap_etiketini_sok("Evet. CEVAP: x"), "Evet. CEVAP: x")

    def test_govde_yalniz_etiketse_gecersiz(self):
        d = K.duzeltme_coz(self.KAYIT + "GÜNCEL CEVAP:\n**CEVAP:**\n")
        self.assertFalse(d["gecerli"])

    @KAYIT_VAR
    def test_gercek_kayit_uc_modelin_iki_turu(self):
        for tur in (1, 2):
            for m in ("claude", "codex", "gemini"):
                ham = json.loads((GERCEK_KAYIT / f"tur{tur}_duzeltme_{m}.json").read_text("utf-8"))["sonuc"]["metin"]
                d = K.duzeltme_coz(ham)
                self.assertTrue(d["gecerli"], (tur, m))
                c = d["cevap"]
                self.assertFalse(c.startswith("CEVAP:"), (tur, m, c[:30]))
                self.assertFalse(c.startswith("**CEVAP"), (tur, m, c[:30]))
                satir1 = c.splitlines()[0]
                self.assertEqual(satir1.count("**") % 2, 0, (tur, m, satir1[:80]))  # açılış/kapanış dengeli


# Gerçek kayıttaki (Claude, 2. tur) numaralama biçimi: alt başlıkta numara 1'e dönüyor.
CAKISAN = """=== CEVAP A HAKKINDA ===

HATALAR

- [1] (önem: önemli; güven: orta) birinci hata
- [2] (önem: küçük; güven: yüksek) ikinci hata

EKSİK NOKTALAR

- [1] (önem: önemli; güven: yüksek) birinci eksik
- [2] (önem: önemli; güven: orta) ikinci eksik
- [3] (önem: küçük; güven: yüksek) üçüncü eksik

KANITSIZ İDDİALAR

- [1] (önem: küçük; güven: orta) kanıtsız

İYİLEŞTİRME ÖNERİLERİ

- [1] (öneri) bir öneri
- [2] etiketsiz öneri

=== CEVAP B HAKKINDA ===

HATALAR

Sorun yok.

{"A": {"kritik": 0, "onemli": 3, "kucuk": 3}, "B": {"kritik": 0, "onemli": 0, "kucuk": 0}, "daha_iyi": "B"}
"""


class KimlikTesti(unittest.TestCase):
    """Madde 3: kimlikler modelin numarasından bağımsız, kodun sırasıyla verilir; çakışma yok."""

    def test_cakisan_numaralar_tekil_kimlik_olur(self):
        c = K.elestiri_coz(CAKISAN, ["A", "B"])
        nolar = [m["no"] for m in c["maddeler"]["A"]]
        self.assertEqual(nolar, [1, 2, 1, 2, 3, 1, 1, 2])  # modelin numaraları çakışıyor
        metin, kimlikler = K.elestiri_metni_hazirla(1, c, "A")
        self.assertEqual(kimlikler, [f"E1-{i}" for i in range(1, 9)])
        self.assertEqual(len(set(kimlikler)), len(c["maddeler"]["A"]))
        for i in kimlikler:
            self.assertEqual(metin.count(f"[{i}]"), 1, i)
        self.assertIn("[E1-6] (önem: küçük; güven: orta) kanıtsız", metin)
        self.assertIn("- [E1-8] etiketsiz öneri", metin)

    def test_kimlik_numarasi_degerlendirici_sirasina_gore(self):
        c = K.elestiri_coz(CAKISAN, ["A", "B"])
        _, kimlikler = K.elestiri_metni_hazirla(2, c, "A")
        self.assertEqual(kimlikler[0], "E2-1")

    def test_degisiklik_sayimi_cakisan_numaralarda_tum_maddeleri_sayar(self):
        c = K.elestiri_coz(CAKISAN, ["A", "B"])
        _, kimlikler = K.elestiri_metni_hazirla(1, c, "A")
        kararlar = {k: "KABUL" for k in kimlikler}
        s = K.degisiklik_sayimi(kimlikler, kararlar)
        self.assertEqual((s["madde"], s["kabul"], s["yanitsiz"]), (8, 8, 0))

    @KAYIT_VAR
    def test_gercek_kayit_claude_eleştirileri(self):
        # eskiden: A bölümü 9 madde ama 4 benzersiz numara (2. tur), B bölümü 11 madde / 3 numara
        for tur, beklenen in ((1, {"A": 9, "B": 9}), (2, {"A": 9, "B": 11})):
            c = K.elestiri_coz((GERCEK_KAYIT / f"tur{tur}" / "elestiri_claude.md").read_text("utf-8"), ["A", "B"])
            for e, n in beklenen.items():
                _, kimlikler = K.elestiri_metni_hazirla(1, c, e)
                self.assertEqual(len(kimlikler), n, (tur, e))
                self.assertEqual(len(set(kimlikler)), n, (tur, e))

    @KAYIT_VAR
    def test_gercek_kayit_tum_eleştirilerde_kimlikler_tekil(self):
        for tur in (1, 2):
            for m in ("claude", "codex", "gemini"):
                c = K.elestiri_coz((GERCEK_KAYIT / f"tur{tur}" / f"elestiri_{m}.md").read_text("utf-8"), ["A", "B"])
                for e in ("A", "B"):
                    _, k = K.elestiri_metni_hazirla(1, c, e)
                    self.assertEqual(len(k), len(set(k)))
                    self.assertEqual(len(k), len(c["maddeler"][e]))


class KismenKabulTesti(unittest.TestCase):
    """Madde 4: üçüncü karar KISMEN KABUL ayrı sayılır (eskiden 'yanıtsız' görünüyordu)."""

    def test_ayristirma(self):
        d = K.duzeltme_coz("DEĞİŞİKLİK KAYDI:\n- E2-8 KISMEN KABUL: yarısı\n- E2-9 kısmen kabul: x\n- E2-10 KABUL: y\n"
                           "- E2-11 RED: z\nGÜNCEL CEVAP:\nmetin")
        self.assertEqual(d["kararlar"], {"E2-8": "KISMEN", "E2-9": "KISMEN", "E2-10": "KABUL", "E2-11": "RED"})

    def test_sayim_ayri_ve_yanitsiz_azalir(self):
        ids = ["E1-1", "E1-2", "E1-3", "E1-4", "E1-5"]
        s = K.degisiklik_sayimi(ids, {"E1-1": "KABUL", "E1-2": "KISMEN", "E1-3": "RED", "E1-4": "KISMEN"})
        self.assertEqual((s["kabul"], s["kismen"], s["red"], s["yanitsiz"]), (1, 2, 1, 1))
        s = K.degisiklik_sayimi(None, {"E1-1": "KISMEN"})
        self.assertEqual((s["kimlikli"], s["kismen"], s["madde"]), (False, 1, None))

    @KAYIT_VAR
    def test_gercek_kayit_claude_2_tur_iki_kismen(self):
        ham = json.loads((GERCEK_KAYIT / "tur2_duzeltme_claude.json").read_text("utf-8"))["sonuc"]["metin"]
        k = K.duzeltme_coz(ham)["kararlar"]
        self.assertEqual(sorted(i for i, v in k.items() if v == "KISMEN"), ["E2-8", "E2-9"])


class OneriVeOnemTesti(unittest.TestCase):
    """Madde 5: İYİLEŞTİRME ÖNERİLERİ maddeleri önem taşımaz ve ağır madde sayılmaz."""

    def test_oneri_alti_onem_etiketi_olsa_da_oneridir(self):
        m = ("=== CEVAP A HAKKINDA ===\nHATALAR\n- [1] (önem: küçük; güven: orta) h\nİYİLEŞTİRME ÖNERİLERİ\n"
             "- [2] (önem: önemli; güven: yüksek) etiketli öneri\n- [3] (öneri) öneri\n- [4] etiketsiz\n")
        c = K.elestiri_coz(m, ["A"])
        self.assertEqual([x["onem"] for x in c["maddeler"]["A"]], ["kucuk", "oneri", "oneri", "oneri"])
        self.assertTrue(c["maddeler"]["A"][1]["etiketli_oneri"])
        self.assertEqual(c["agir_madde_metinde"], 0)
        self.assertEqual(c["kritik_madde_metinde"], 0)

    def test_oneri_etiketi_baska_alt_basligin_altinda_da_oneridir(self):
        c = K.elestiri_coz("=== CEVAP A HAKKINDA ===\nEKSİK NOKTALAR\n- [1] (öneri) x\n", ["A"])
        self.assertEqual(c["maddeler"]["A"][0]["onem"], "oneri")

    def test_alt_baslik_bolumler_arasinda_sifirlanir(self):
        m = ("=== CEVAP A HAKKINDA ===\nİYİLEŞTİRME ÖNERİLERİ\n- [1] (öneri) a\n=== CEVAP B HAKKINDA ===\n"
             "- [1] etiketsiz satır alt başlıksız madde sayılmaz\n")
        c = K.elestiri_coz(m, ["A", "B"])
        self.assertEqual(len(c["maddeler"]["A"]), 1)
        self.assertEqual(len(c["maddeler"].get("B", [])), 0)

    def test_oneri_json_sayisina_girmez_prompt_soyluyor(self):
        p = K.p_elestiri("S", None, [("A", "x"), ("B", "y")], None, {})   # v0.28 promptu açıkça istenir
        self.assertIn("öneri maddeleri sayılmaz", p)
        self.assertIn("- [5] (öneri) <öneri>", p)
        self.assertIn("HATALAR, EKSİK NOKTALAR ve KANITSIZ İDDİALAR altındaki", p)
        self.assertIn("Numara bölüm boyunca sürekli olsun; alt başlıklarda sıfırlanmasın.", p)
        self.assertIn("Aynı sorunu bir kez yaz; başka bir alt başlıkta tekrar etme.", p)
        self.assertNotIn("Madde numarası her bölümde 1'den başlar", p)


class ErkenDurmaTesti(unittest.TestCase):
    """Madde 6 (karar 55 [GEÇİCİ]): yalnızca kritik madde sonraki tura geçirir."""

    @staticmethod
    def c(a=(0, 0, 0), b=(0, 0, 0), metin="", **kw):
        j = {"A": dict(zip(("kritik", "onemli", "kucuk"), a)), "B": dict(zip(("kritik", "onemli", "kucuk"), b)),
             "daha_iyi": "A"}
        return K.elestiri_coz(metin + "\n" + json.dumps(j), ["A", "B"])

    def karar(self, **cozumler):
        return K.erken_durma_karari(cozumler)

    def test_onemli_maddeler_durmayi_engellemez_ve_nedende_sayilar_ayri(self):
        dur, neden = self.karar(claude=self.c(a=(0, 12, 2)), codex=self.c(b=(0, 20, 1)))
        self.assertTrue(dur)
        self.assertIn("0 kritik, 32 önemli madde bildirildi", neden)

    def test_tek_kritik_devam_ettirir(self):
        dur, neden = self.karar(claude=self.c(), codex=self.c(b=(1, 4, 0)))
        self.assertFalse(dur)
        self.assertEqual(neden, "1 kritik, 4 önemli madde bildirildi")

    def test_json_sifir_ama_metinde_kritik_tutarsiz_ve_durmaz(self):
        m = ("=== CEVAP A HAKKINDA ===\nHATALAR\n- [1] (önem: kritik; güven: yüksek) x\n=== CEVAP B HAKKINDA ===\n"
             "HATALAR\nSorun yok.")
        c = self.c(metin=m)
        self.assertTrue(c["tutarsiz"])
        dur, neden = self.karar(claude=c)
        self.assertFalse(dur)
        self.assertIn("tutarsız", neden)

    def test_onemi_okunamayan_madde_temkinli_sayilir(self):
        m = "=== CEVAP A HAKKINDA ===\nHATALAR\n- [1] (önem: ???; güven: yüksek) x\n"
        self.assertTrue(self.c(metin=m)["tutarsiz"])

    def test_json_okunamazsa_durmaz(self):
        c = K.elestiri_coz("=== CEVAP A HAKKINDA ===\nHATALAR\nSorun yok.\n", ["A"])
        self.assertFalse(K.erken_durma_karari({"claude": c})[0])


class KritikAkisTesti(AkisTabani):
    """Sahte CLI eleştirilerde 'kritik' madde üretir (sahte_kritik_cli.py); düzeltme 'DÜZELTİLDİ' yazar, sonraki
    eleştiri temiz döner."""

    def setUp(self):
        super().setUp()
        import os
        os.environ["SAHTE_ELESTIRI"] = "madde"
        for ad in self.ayar["saglayicilar"]:
            self.ayar["saglayicilar"][ad]["komut"][1] = KRITIK_CLI

    def test_kritik_ikinci_tura_gecirir_ikinci_turda_temiz_durur(self):
        s = self.calistir(tur=2)   # v0.30 (karar 69): varsayılan tur 1 oldu; ikinci tura geçiş için sınır 2 verilir
        # tur0 3 + tur1 (3 + 3) + tur2 (3 eleştiri, düzeltme atlanır) + sentez 1 + onay 3
        self.assertEqual(s["cagri_sayisi"], 16)
        self.assertEqual(s["tur_sayisi"], 2)
        self.assertFalse(s["turlar"][0]["erken_durma"])
        self.assertEqual(s["turlar"][0]["erken_durma_nedeni"], "6 kritik, 0 önemli madde bildirildi")
        self.assertTrue(s["turlar"][1]["erken_durma"])
        self.assertIn("2. turda kritik madde bildirilmedi", s["durma_nedeni"])

    def test_tur_siniri_bir_kritik_sureerse_sinira_ulasilir(self):
        s = self.calistir(tur=1)
        self.assertEqual(s["tur_sayisi"], 1)
        self.assertIn("tur sınırına (1) ulaşıldı", s["durma_nedeni"])
        self.assertIn("6 kritik, 0 önemli", s["durma_nedeni"])

    def test_tur_siniri_uc_kritik_her_turda_surerse(self):
        import os
        os.environ["SAHTE_DUZELTME"] = "bozuk"
        s = self.calistir(tur=3)
        self.assertEqual(s["cagri_sayisi"], 3 + 18 + 1 + 3)
        self.assertEqual([t["tur"] for t in s["turlar"]], [1, 2, 3])
        self.assertIn("tur sınırına (3) ulaşıldı", s["durma_nedeni"])

    def test_sayim_kismen_alani_ve_ayrinti_satiri(self):
        s = self.calistir(tur=1)
        for ad in ("claude", "codex", "gemini"):
            sayim = s["turlar"][0]["duzeltmeler"][ad]["sayim"]
            self.assertEqual(sayim["kismen"], 0)
            self.assertEqual(sayim["madde"], 2)
        self.assertIn("KABUL 1, KISMEN KABUL 0, RED 1, yanıtsız 0", s["ayrinti"])
        self.assertIn("kritik 1, önemli 0, küçük 0", s["ayrinti"])

    def test_kritikli_tutarsizlik_durmayi_engeller_ve_ayrintida_gorunur(self):
        import os
        os.environ["SAHTE_ELESTIRI"] = "tutarsiz"  # sahte: önemli madde + JSON 0; sarmalayıcı maddeyi kritik yapar, JSON 0 kalır
        s = self.calistir(tur=1)
        self.assertFalse(s["turlar"][0]["erken_durma"])
        self.assertIn("tutarsız", s["turlar"][0]["erken_durma_nedeni"])
        self.assertIn("JSON 0 kritik diyor ama metinde kritik ya da önemi okunamayan madde var", s["ayrinti"])

    def test_kayit_protokol_surumu(self):
        s = self.calistir(tur=1)
        self.assertEqual(json.loads((Path(s["kayit_klasoru"]) / "kayit.json").read_text("utf-8"))["protokol"], K.KOD_SURUMU)


class DuzeltmePromptuTesti(unittest.TestCase):
    """Madde 7: düzeltme prompt'una iki kural ve üçüncü karar eklendi."""

    def test_kurallar_ve_kayit_bicimi(self):
        p = K.p_duzeltme("S", None, "kendi", ["e1"])
        self.assertIn("Kabul ettiğin düzeltmeleri mevcut metne işle; yeni paragraflar yığma, tekrar yaratma. "
                      "Gereksiz hale gelen kısımları çıkar.", p)
        self.assertIn("Bir eleştiri olgusal olarak yanlışsa, soruyla ilgisizse ya da önemi abartılmışsa RED et. "
                      "RED etmek bir başarısızlık değildir.", p)
        self.assertIn("- E1-2 KISMEN KABUL:", p)

    def test_kimlikleri_sahte_cevaptan_degil_koddan_alir(self):
        # düzeltme prompt'una giren eleştiri metninde kimlikler E<k>-<sıra>
        c = K.elestiri_coz(CAKISAN, ["A", "B"])
        metin, _ = K.elestiri_metni_hazirla(3, c, "A")
        self.assertEqual(re.findall(r"\[(E3-\d+)\]", metin), [f"E3-{i}" for i in range(1, 9)])


class KotaZamanDamgasiTesti(unittest.TestCase):
    """Madde 8: GPT kota okuması olay zamanı ve kayıt dosyası adını taşır; eskiyse 'GÜNCEL DEĞİL'."""

    def kayit_yaz(self, kok: Path, olay_utc: dt.datetime, sifirlanma_5s: dt.datetime, sifirlanma_hf: dt.datetime) -> Path:
        klasor = kok / "2026" / "11" / "20"
        klasor.mkdir(parents=True)
        yol = klasor / "rollout-2026-11-20T00-00-00-ornek.jsonl"
        olay = {"timestamp": olay_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "type": "event_msg",
                "payload": {"type": "token_count", "rate_limits": {
                    "primary": {"used_percent": 15.0, "window_minutes": 300, "resets_at": sifirlanma_5s.timestamp()},
                    "secondary": {"used_percent": 15.0, "window_minutes": 10080, "resets_at": sifirlanma_hf.timestamp()},
                    "plan_type": "plus"}}}
        yol.write_text("bozuk satir\n" + json.dumps(olay) + "\n", encoding="utf-8")
        return yol

    def hazirla(self, olay_dk_once: int, sifirlanma_5s_dk: int):
        gecici = tempfile.TemporaryDirectory()
        self.addCleanup(gecici.cleanup)
        simdi = dt.datetime.now().replace(microsecond=0)
        utc_simdi = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)
        yol = self.kayit_yaz(Path(gecici.name), utc_simdi - dt.timedelta(minutes=olay_dk_once),
                             simdi + dt.timedelta(minutes=sifirlanma_5s_dk), simdi + dt.timedelta(days=4))
        return {"kayit_dizini": gecici.name}, yol, simdi

    def test_okuma_olay_zamani_ve_dosya_adini_icerir_guncelse_uyari_yok(self):
        ayar, yol, simdi = self.hazirla(olay_dk_once=2, sifirlanma_5s_dk=290)
        k = K._son_codex_kotasi(ayar)
        self.assertEqual(k["kayit_dosyasi"], yol.name)
        self.assertTrue(k["olay_zamani"].endswith("Z"))
        self.assertEqual(k["5_saat"]["kullanilan_yuzde"], 15.0)
        self.assertEqual(K.kota_eskilik(k, simdi), [])
        metin = K.kota_metni(k, simdi)
        self.assertIn(f"kayıt: {yol.name}, olay: ", metin)
        self.assertNotIn("GÜNCEL DEĞİL", metin)

    def test_sifirlanma_gecmisse_guncel_degil(self):
        ayar, yol, simdi = self.hazirla(olay_dk_once=2, sifirlanma_5s_dk=-60)
        metin = K.kota_metni(K._son_codex_kotasi(ayar), simdi)
        self.assertIn("GÜNCEL DEĞİL", metin)
        self.assertIn("5 saatlik pencerenin sıfırlanma zamanı", metin)

    def test_olay_eskiyse_guncel_degil(self):
        ayar, yol, simdi = self.hazirla(olay_dk_once=K.KOTA_ESKI_DAKIKA + 90, sifirlanma_5s_dk=120)
        k = K._son_codex_kotasi(ayar)
        nedenler = K.kota_eskilik(k, simdi)
        self.assertEqual(len(nedenler), 1)
        self.assertIn("dakika önce", nedenler[0])
        self.assertIn("GÜNCEL DEĞİL", K.kota_metni(k, simdi))

    def test_goruntu_codex_metni_zaman_damgasini_tasir(self):
        ayar, yol, _ = self.hazirla(olay_dk_once=1, sifirlanma_5s_dk=200)
        sonuc = asyncio.run(K.kota_goruntusu({"saglayicilar": {"codex": {"komut": ["codex"], "kayit_dizini": ayar["kayit_dizini"]}}},
                                             tempfile.gettempdir()))
        self.assertEqual(sonuc["codex"]["durum"], "ok")
        self.assertIn(yol.name, sonuc["codex"]["metin"])
        self.assertIn("olay:", sonuc["codex"]["metin"])

    def test_zaman_damgasi_yoksa_eski_bicim_bozulmaz(self):
        self.assertEqual(K.kota_metni({"5_saat": {"kullanilan_yuzde": 15.0, "sifirlanma": "2026-11-20 19:17"}}),
                         "5 saatlik %15 kullanıldı (sıfırlanma 2026-11-20 19:17)")


if __name__ == "__main__":
    unittest.main()
