"""v0.27: değişiklik kaydı ayrıştırıcısı kalın/kodlu kimlik, numaralı liste ve tire çeşitlerini de okur;
kararı yazılmış hiçbir madde sessizce "kararı eksik" sayılmaz."""
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
import konsey as K  # noqa: E402

YAZIMLAR = [
    "- E1-3 KABUL: doğru, çünkü x; değişen: y", "E1-3: KABUL x", "[E1-3] KABUL x", "- **E1-3 KABUL**: x",
    "- **E1-3** KABUL: x", "1. E1-3 KABUL: x", "2) E1-3 KABUL: x", "- 1. **E1-3** KABUL: x", "E1-3 – KABUL: x",
    "E1-3 — KABUL: x", "- `E1-3` KABUL: x", "* _E1-3_ KABUL: x", "- [E1-3] **KABUL**: x", "  - **E1-3:** KABUL x",
]


class AyristiriciTesti(unittest.TestCase):
    def test_hepsi_okunur(self):
        for y in YAZIMLAR:
            k = K.karar_kayitlarini_oku(y)
            self.assertEqual(list(k), ["E1-3"], y)
            self.assertEqual(k["E1-3"]["karar"], "KABUL", y)

    def test_kismen_ve_red_yazimlari(self):
        self.assertEqual(K.karar_kayitlarini_oku("1. **E1-4** KISMEN KABUL: kısmen doğru, çünkü a; değişen: b")["E1-4"]["karar"], "KISMEN")
        self.assertEqual(K.karar_kayitlarini_oku("- E1-5 – RED: gerekçe")["E1-5"]["karar"], "RED")
        self.assertEqual(K.karar_kayitlarini_oku("3. `E2-1` RET: gerekçe")["E2-1"]["karar"], "RED")

    def test_gerekce_ve_degisen_bozulmaz(self):
        d = K.karar_kayitlarini_oku("1. **E1-3** KABUL: doğru, çünkü sayı yanlıştı; değişen: sayı düzeltildi")["E1-3"]
        self.assertEqual((d["gerekce"], d["degisen"]), ("sayı yanlıştı", "sayı düzeltildi"))

    def test_hicbir_madde_sessizce_eksik_sayilmaz(self):
        kayit = "\n".join(f"{y.split('E1-3')[0]}E1-{i}{y.split('E1-3', 1)[1]}" for i, y in enumerate(YAZIMLAR, 1))
        k = K.karar_kayitlarini_oku(kayit)
        idler = [f"E1-{i}" for i in range(1, len(YAZIMLAR) + 1)]
        self.assertEqual(sorted(k), sorted(idler))
        s = K.degisiklik_sayimi(idler, {i: d["karar"] for i, d in k.items()})
        self.assertEqual((s["kabul"], s["yanitsiz"]), (len(idler), 0))

    def test_duzeltme_coz_kalin_kimlikle(self):
        d = K.duzeltme_coz("DEĞİŞİKLİK KAYDI:\n1. **E1-1** KABUL: doğru, çünkü a; değişen: b\n- **E1-2** RED: yanlış\n"
                           "GÜNCEL CEVAP:\nCEVAP: yeni metin")
        self.assertEqual(d["kararlar"], {"E1-1": "KABUL", "E1-2": "RED"})

    def test_sentez_itiraz_kayitlari(self):
        for y in ("- R1 KABUL: x", "1. **R1** KABUL: x", "- `R1` – KABUL: x"):
            self.assertEqual(K.karar_kayitlarini_oku(y, K.ITIRAZ_KARAR_KALIBI)["R1"]["karar"], "KABUL", y)

    def test_yanlis_pozitif_yok(self):
        for y in ("E1-3 hakkında düşüncem", "KABUL ediyorum E1-3", "- E1-3 → KABUL", "Not: E1-3 ve E1-4 aynı", "1. Giriş KABUL"):
            self.assertEqual(K.karar_kayitlarini_oku(y), {}, y)


if __name__ == "__main__":
    unittest.main()
