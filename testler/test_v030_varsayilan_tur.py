"""v0.30 (karar 69): varsayılan eleştiri-düzeltme turu 1; --tur 2 ve --tur 3 aynen çalışır."""
import subprocess
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import konsey as K  # noqa: E402
from test_elestiri_duzeltme import AkisTabani  # noqa: E402


class VarsayilanTur(AkisTabani):
    def test_sabit_ve_cli_varsayilani_bir(self):
        self.assertEqual(K.VARSAYILAN_TUR, 1)
        self.assertEqual(K.Konsey(self.ayar).tur, 1)
        yardim = subprocess.run([sys.executable, str(KOK / "konsey.py"), "--help"], capture_output=True, text=True).stdout
        self.assertIn("varsayılan 1)", yardim)

    def test_aralik_degismedi(self):
        self.assertEqual((K.TUR_MIN, K.TUR_MAKS), (1, 3))
        for n in (1, 2, 3):
            self.assertEqual(K.Konsey(self.ayar, tur=n).tur, n)
        for n in (0, 4):
            with self.assertRaises(ValueError):
                K.Konsey(self.ayar, tur=n)

    def test_kritik_eleştiri_varsayilanda_bir_tur_sinirinda_durur_tur2_devam_eder(self):
        import os
        os.environ["SAHTE_ELESTIRI"] = "madde"
        s1 = self.calistir()
        self.assertEqual((s1["tur_siniri"], s1["tur_sayisi"]), (1, 1))
        s3 = self.calistir(tur=3)
        self.assertEqual(s3["tur_siniri"], 3)


if __name__ == "__main__":
    unittest.main()
