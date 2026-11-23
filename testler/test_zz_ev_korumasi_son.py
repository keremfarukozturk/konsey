"""
v0.26 testleri (karar 65): test_zz_ ön eki keşifte son sırada yüklenip çalışır; bütün paketin gerçek ev klasörüne
yazmadığını (kanca ihlali yok; ~/.konsey-agy-arastirma, ~/konsey-arastirma-* dahil `konsey*` girdileri değişmedi) doğrular.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ev_korumasi as EK  # noqa: E402


class PaketSonuTesti(unittest.TestCase):
    def test_koruma_hala_etkin(self):
        self.assertTrue(EK.aktif_mi(), "test_00_ev_korumasi yüklenmeden koşulmuş: bütün paketi araclar/testleri_calistir.py ile çalıştır")

    def test_gercek_eve_yazma_girisimi_kaydi_yok(self):
        # test_00'daki bilinçli denemeler hariç ihlal olmamalı: yalnızca "deneme" yolu geçenler bilinçlidir
        beklenmeyen = [x for x in EK.ihlaller() if ".konsey-test-ev-korumasi-deneme-" not in x]
        self.assertEqual(beklenmeyen, [])

    def test_gercek_evdeki_konsey_girdileri_degismedi(self):
        once, sonra = EK.ilk_goruntu(), EK.ev_goruntusu()
        self.assertIsNotNone(once)
        yeni = sorted(set(sonra) - set(once))
        self.assertEqual(yeni, [], f"gerçek evde yeni klasör oluştu: {yeni}")
        degisen = sorted(a for a in once if once[a] != sonra.get(a))
        self.assertEqual(degisen, [], f"gerçek evdeki girdiler değişti: {degisen}")


if __name__ == "__main__":
    unittest.main()
