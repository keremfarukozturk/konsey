"""v0.30: birimsiz sonuç yazımları eşdeğer, birden çok SONUÇ satırında sonuncusu kullanılır ve
sayısı kayda yazılır; TUR0_UZLASI kararı bu değişiklikten nasıl etkilenir (kilitli). Codex kota okuyucusu sınır sonrası da son
okunan değeri ve zamanını gösterir."""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
import konsey as K  # noqa: E402
import sayisal as S  # noqa: E402


def c(sonuc_satirlari, govde="CEVAP: bulundu."):
    return {"durum": "ok", "metin": govde + "\n" + "\n".join(sonuc_satirlari)}


def uc(a, b, g, **kw):
    return {"claude": c(a), "codex": c(b), "gemini": c(g)}


class BirimsizYazimlar(unittest.TestCase):
    def test_birimsiz_sonuc_yazimlari_okunur(self):
        for yazim in ("-", "1", "boyutsuz", "birimsiz", "", "—", "BOYUTSUZ", "*boyutsuz*", "dimensionless"):
            d, b, n = S.sonuc_cikar(f"SONUÇ: 0.2262 {yazim}".rstrip(), "")
            self.assertEqual(d, 0.2262, yazim)
            self.assertEqual(n, "")

    def test_birimli_sorularda_birimsiz_yazim_kabul_edilmez(self):
        for yazim in ("-", "boyutsuz", "1"):
            d, _b, n = S.sonuc_cikar(f"SONUÇ: 0.2 {yazim}", "V")
            self.assertIsNone(d, yazim)
            self.assertIn("birim beklenenden", n)
        self.assertEqual(S.sonuc_cikar("SONUÇ: 0.2 V", "V")[0], 0.2)
        self.assertIsNone(S.sonuc_cikar("SONUÇ: 0.2 mV", "V")[0])

    def test_birimsiz_beklerken_gercek_birim_yazilirsa_reddedilir(self):
        self.assertIsNone(S.sonuc_cikar("SONUÇ: 0.2 V", "")[0])


class BirdenCokSonucSatiri(unittest.TestCase):
    def test_sonuncusu_kullanilir_ve_sayi_yazilir(self):
        m = "ara adım\nSONUÇ: D ≈ 0.2079.\nsonra\nSONUÇ: 0.208 -"
        self.assertEqual(S.sonuc_satir_sayisi(m), 2)
        self.assertEqual(S.sonuc_oku(m)[0], 0.208)
        self.assertEqual(S.sonuc_cikar(m, "")[0], 0.208)
        self.assertEqual(S.sonuc_satir_sayisi("SONUÇ yok burada"), 0)
        self.assertEqual(S.sonuc_satir_sayisi("SONUÇ: 1 V\nSONUÇ: 2 V\nSONUÇ: 3 V"), 3)

    def test_farkli_degerli_satirlarda_sonuncu(self):
        self.assertEqual(S.sonuc_cikar("SONUÇ: 0.0806 V\nSONUÇ: 0.284 V", "V")[0], 0.284)

    def test_sonuncu_okunamazsa_yok(self):
        d, _b, n = S.sonuc_oku("SONUÇ: 5 V\nSONUÇ: yaklaşık beş")
        self.assertIsNone(d)
        self.assertIn("sayı okunamadı", n)

    def test_eski_kural_acikca_istenirse_calisir(self):
        self.assertIsNone(S.sonuc_oku("SONUÇ: 1 V\nSONUÇ: 2 V", sonuncu=False)[0])
        self.assertEqual(S.sonuc_oku("SONUÇ: 1 V\nSONUÇ: 1 V", sonuncu=False)[0], 1.0)


class Tur0Uzlasi(unittest.TestCase):
    def test_farkli_birimsiz_yazimlar_artik_uzlasi(self):
        # F2/S18 durumu: Claude "-", GPT boş, Gemini "boyutsuz"
        k = S.tur0_uzlasi(uc(["SONUÇ: 0.226 -"], ["SONUÇ: 0.22623"], ["SONUÇ: 0.2262 boyutsuz"]), 0.01)
        self.assertTrue(k["uzlasi"], k["kosullar"])
        self.assertEqual(k["birim"], "birimsiz")
        self.assertAlmostEqual(k["ortanca"], 0.2262)
        k = S.tur0_uzlasi(uc(["SONUÇ: 0.676 -"], ["SONUÇ: 0.675602 1"], ["SONUÇ: 0.6756"]), 0.01)   # S09 durumu
        self.assertTrue(k["uzlasi"], k["kosullar"])

    def test_birimli_ile_birimsiz_karisirsa_uzlasi_yok(self):
        k = S.tur0_uzlasi(uc(["SONUÇ: 0.2 V"], ["SONUÇ: 0.2 -"], ["SONUÇ: 0.2 V"]), 0.01)
        self.assertFalse(k["uzlasi"])
        self.assertIn("c_birim_ayni", k["saglanmayan"])

    def test_milivolt_volt_hala_farkli(self):
        self.assertFalse(S.tur0_uzlasi(uc(["SONUÇ: 12 V"], ["SONUÇ: 12 mV"], ["SONUÇ: 12 V"]), 0.01)["uzlasi"])
        self.assertFalse(S.tur0_uzlasi(uc(["SONUÇ: 12 V"], ["SONUÇ: 12 MV"], ["SONUÇ: 12 V"]), 0.01)["uzlasi"])

    def test_tolerans_disi_uzlasi_yok_birimsiz_olsa_da(self):
        k = S.tur0_uzlasi(uc(["SONUÇ: 0.20 -"], ["SONUÇ: 0.25"], ["SONUÇ: 0.20 boyutsuz"]), 0.01)
        self.assertFalse(k["uzlasi"])
        self.assertEqual(k["saglanmayan"], ["d_tolerans_icinde"])

    def test_erken_cikis_zaten_sonuncu_satiri_okurdu_kararlar_ayni(self):
        # ara adımda "SONUÇ: ..." yazan cevap: eskiden de son satır okunuyordu; satır sayısı artık kayda yazılır
        k = S.tur0_uzlasi(uc(["SONUÇ: D ≈ 0.2079.", "SONUÇ: 0.208 -"], ["SONUÇ: 0.2079"], ["SONUÇ: 0.2079"]), 0.01)
        self.assertTrue(k["uzlasi"])
        self.assertEqual(k["sonuc_satir_sayisi"], {"claude": 2, "codex": 1, "gemini": 1})
        json.dumps(k)    # kayit.json'a yazılabilir
        self.assertEqual(k["degerler"]["claude"], 0.208)

    def test_son_satir_okunamazsa_uzlasi_yok(self):
        k = S.tur0_uzlasi(uc(["SONUÇ: 0.2079", "SONUÇ: yaklaşık"], ["SONUÇ: 0.2079"], ["SONUÇ: 0.2079"]), 0.01)
        self.assertFalse(k["uzlasi"])
        self.assertIn("b_sonuc_okunur", k["saglanmayan"])

    def test_satir_yoksa_ya_da_cagri_basarisizsa_uzlasi_yok(self):
        self.assertFalse(S.tur0_uzlasi({"claude": c([]), "codex": c(["SONUÇ: 1"]), "gemini": c(["SONUÇ: 1"])})["uzlasi"])
        t = uc(["SONUÇ: 1"], ["SONUÇ: 1"], ["SONUÇ: 1"])
        t["codex"]["durum"] = "hata"
        self.assertFalse(S.tur0_uzlasi(t)["uzlasi"])

    def test_konsey_kaydina_giden_sozluk_satir_sayisini_icerir(self):
        k = S.tur0_uzlasi(uc(["SONUÇ: 1 V"], ["SONUÇ: 1 V"], ["SONUÇ: 1 V"]))
        self.assertEqual(k["sonuc_satir_sayisi"], {"claude": 1, "codex": 1, "gemini": 1})
        self.assertEqual(K.sayisal.tur0_uzlasi.__module__, "sayisal")


class KotaSinirSonrasi(unittest.TestCase):
    def olay(self, z, rate):
        return json.dumps({"timestamp": z, "type": "event_msg", "payload": {"type": "token_count", "rate_limits": rate}})

    def kur(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        klasor = Path(t.name) / "2026" / "11" / "22"
        klasor.mkdir(parents=True)
        simdi = dt.datetime.now(dt.timezone.utc)
        iyi = {"primary": {"used_percent": 99.0, "window_minutes": 300, "resets_at": (simdi + dt.timedelta(hours=1)).timestamp()},
               "secondary": {"used_percent": 45.0, "window_minutes": 10080, "resets_at": (simdi + dt.timedelta(days=3)).timestamp()},
               "plan_type": "plus"}
        bos = {"limit_id": "premium", "primary": None, "secondary": None, "plan_type": None}
        eski = (simdi - dt.timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        yeni = (simdi - dt.timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        (klasor / "rollout-2026-11-22T10-00-00-a.jsonl").write_text(self.olay(eski, iyi) + "\n", encoding="utf-8")
        (klasor / "rollout-2026-11-22T10-01-00-b.jsonl").write_text(self.olay(yeni, bos) + "\n", encoding="utf-8")
        (klasor / "rollout-2026-11-22T10-02-00-c.jsonl").write_text(self.olay(yeni, bos) + "\n", encoding="utf-8")
        (klasor / "rollout-2026-11-22T10-03-00-d.jsonl").write_text(self.olay(yeni, bos) + "\n", encoding="utf-8")
        return {"kayit_dizini": t.name}, eski, yeni

    def test_sinir_sonrasi_bos_kayitlarda_son_okunan_deger_ve_zaman(self):
        ayar, eski, yeni = self.kur()
        k = K._son_codex_kotasi(ayar)        # eskiden: son 3 dosya boş → {}
        self.assertEqual(k["5_saat"]["kullanilan_yuzde"], 99.0)
        self.assertEqual(k["haftalik"]["kullanilan_yuzde"], 45.0)
        self.assertEqual(k["olay_zamani"], eski)
        self.assertEqual(k["sinir_sonrasi_bos_kayit"], yeni)
        metin = K.kota_metni(k)
        self.assertIn("5 saatlik %99", metin)
        self.assertIn("kota sınırına çarpıldı", metin)
        self.assertIn(yeni, metin)

    def test_normal_durumda_sinir_notu_yok(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        klasor = Path(t.name) / "2026" / "11" / "22"
        klasor.mkdir(parents=True)
        simdi = dt.datetime.now(dt.timezone.utc)
        rate = {"primary": {"used_percent": 10.0, "window_minutes": 300, "resets_at": (simdi + dt.timedelta(hours=2)).timestamp()},
                "secondary": {"used_percent": 20.0, "window_minutes": 10080, "resets_at": (simdi + dt.timedelta(days=3)).timestamp()}}
        (klasor / "rollout-x.jsonl").write_text(self.olay(simdi.strftime("%Y-%m-%dT%H:%M:%S.000Z"), rate) + "\n", encoding="utf-8")
        k = K._son_codex_kotasi({"kayit_dizini": t.name})
        self.assertNotIn("sinir_sonrasi_bos_kayit", k)
        self.assertNotIn("kota sınırına çarpıldı", K.kota_metni(k))

    def test_hic_okunabilir_kayit_yoksa_bos(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        klasor = Path(t.name) / "2026" / "11" / "22"
        klasor.mkdir(parents=True)
        (klasor / "rollout-x.jsonl").write_text(self.olay("2026-11-22T10:00:00.000Z", {"primary": None, "secondary": None}) + "\n",
                                                encoding="utf-8")
        self.assertEqual(K._son_codex_kotasi({"kayit_dizini": t.name}), {})


if __name__ == "__main__":
    unittest.main()
