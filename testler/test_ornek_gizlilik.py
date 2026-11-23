"""testler/ornekler/ gizlilik taraması (açık soru 21).

Örnek dosyalar gerçek CLI kayıtlarından alınır; depoya hesap/kimlik bilgisi girmesin diye her çalıştırmada taranır.
Başarısız olur eğer: (1) e-posta adresi, (2) bilinen token/anahtar kalıbı, (3) adı `user_id` ya da `account_id`
ile biten bir alanda yer tutucu olmayan değer bulunursa. Tarayıcının kendisi de sentetik kötü girdilerle sınanır."""
import json
import re
import tempfile
import unittest
from pathlib import Path

ORNEKLER = Path(__file__).resolve().parent / "ornekler"
YER_TUTUCULAR = frozenset({"user-ORNEK", "hesap-ORNEK"})
EPOSTA = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
TOKEN_KALIPLARI = {
    "JWT": re.compile(r"eyJ[A-Za-z0-9_-]{10,}"),
    "sk- anahtarı": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "Google API anahtarı": re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),
    "AWS anahtar kimliği": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Bearer": re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}"),
}
KIMLIK_ANAHTARI = re.compile(r"(user_id|account_id)$", re.I)
# Metin düzeyinde ikinci kontrol (JSON olmayan içerik ya da kaçışlı iç içe JSON için)
KIMLIK_METNI = re.compile(r'"([A-Za-z0-9_]*(?:user_id|account_id))\\*"\s*:\s*\\*"([^"\\]*)', re.I)


def _kimlik_alanlari(x, yol=""):
    if isinstance(x, dict):
        for k, v in x.items():
            if KIMLIK_ANAHTARI.search(str(k)):
                yield f"{yol}/{k}", v
            yield from _kimlik_alanlari(v, f"{yol}/{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _kimlik_alanlari(v, f"{yol}[{i}]")


def tara_metin(ad: str, metin: str) -> list[str]:
    """Bir dosyanın içeriğindeki sorunları döndürür (boş liste = temiz). Değerleri sızdırmamak için kısaltır."""
    sorunlar = []
    for m in EPOSTA.findall(metin):
        sorunlar.append(f"{ad}: e-posta adresi ({m[:3]}…)")
    for etiket, kalip in TOKEN_KALIPLARI.items():
        if kalip.search(metin):
            sorunlar.append(f"{ad}: {etiket} kalıbı")
    for anahtar, deger in KIMLIK_METNI.findall(metin):
        if deger not in YER_TUTUCULAR and deger != "":
            sorunlar.append(f"{ad}: `{anahtar}` alanında yer tutucu olmayan değer ({deger[:4]}…)")
    if ad.endswith((".json", ".jsonl")):
        satirlar = metin.splitlines() if ad.endswith(".jsonl") else [metin]
        for no, satir in enumerate(satirlar, 1):
            if not satir.strip():
                continue
            try:
                veri = json.loads(satir)
            except json.JSONDecodeError:
                sorunlar.append(f"{ad}:{no}: JSON olarak okunamadı (taranamayan içerik)")
                continue
            for yol, deger in _kimlik_alanlari(veri):
                if deger not in (None, "") and deger not in YER_TUTUCULAR:
                    sorunlar.append(f"{ad}:{no}: {yol} yer tutucu değil")
    return sorunlar


class OrnekGizlilikTesti(unittest.TestCase):
    def test_ornekler_temiz(self):
        dosyalar = [f for f in sorted(ORNEKLER.rglob("*")) if f.is_file()]
        self.assertGreater(len(dosyalar), 10, "örnek dosyalar bulunamadı")
        sorunlar = []
        for f in dosyalar:
            sorunlar += tara_metin(str(f.relative_to(ORNEKLER)),
                                   f.read_text(encoding="utf-8", errors="strict"))
        self.assertEqual(sorunlar, [], "\n".join(sorunlar))

    def test_yer_tutuculu_alanlar_hala_var(self):
        """Tarama boş dosyalarla geçmesin: ayıklanmış örneklerde yer tutucular gerçekten bulunmalı."""
        metin = "".join(f.read_text(encoding="utf-8") for f in ORNEKLER.rglob("*oturum.jsonl"))
        self.assertIn("user-ORNEK", metin)
        self.assertIn("hesap-ORNEK", metin)


class TarayiciKendiniSinarTesti(unittest.TestCase):
    """Tarayıcı gerçekten yakalıyor mu? Hepsi sentetik ve zararsız değerler."""

    def sorunlar(self, ad, metin):
        return tara_metin(ad, metin)

    def test_eposta(self):
        self.assertTrue(self.sorunlar("a.txt", "iletişim: ayse.demir@ornek-firma.com.tr"))

    def test_token_kaliplari(self):
        for metin in ("eyJhbGciOiJIUzI1NiJ9abcdef", "sk-" + "a" * 20, "ghp_" + "A1" * 12, "xoxb-1234567890-abc",
                      "AIza" + "B" * 30, "AKIA" + "A" * 16, "Authorization: Bearer " + "x" * 24):
            with self.subTest(metin=metin[:8]):
                self.assertTrue(self.sorunlar("a.txt", metin))

    def test_kimlik_alani_yer_tutucu_degilse(self):
        for anahtar in ("creator_user_id", "creator_account_id", "user_id", "account_id", "owner_USER_ID"):
            with self.subTest(anahtar=anahtar):
                self.assertTrue(self.sorunlar("a.jsonl", json.dumps({"payload": {anahtar: "gercek-deger-123"}})))

    def test_kimlik_alani_yer_tutucuysa_temiz(self):
        satir = json.dumps({"payload": {"creator_user_id": "user-ORNEK", "creator_account_id": "hesap-ORNEK",
                                        "account_id": None, "user_id": ""}})
        self.assertEqual(self.sorunlar("a.jsonl", satir), [])

    def test_ic_ice_kacisli_json_yakalanir(self):
        ic = json.dumps({"account_id": "gercek-deger-123"})
        self.assertTrue(self.sorunlar("a.jsonl", json.dumps({"text": ic})))

    def test_kimlik_alani_ic_listede(self):
        self.assertTrue(self.sorunlar("a.json", json.dumps({"a": [{"x": {"user_id": "gercek"}}]})))

    def test_okunamayan_json_taranamayan_icerik_sayilir(self):
        self.assertTrue(self.sorunlar("a.jsonl", "{bozuk"))

    def test_temiz_metin(self):
        self.assertEqual(self.sorunlar("a.txt", "Python'da liste ile demet arasındaki fark nedir? user_id kavramı"), [])

    def test_dizin_taramasi_kotu_dosyayi_bulur(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "kotu.jsonl").write_text(json.dumps({"creator_user_id": "gercek-1"}) + "\n", encoding="utf-8")
            sorunlar = []
            for f in Path(d).rglob("*"):
                sorunlar += tara_metin(f.name, f.read_text(encoding="utf-8"))
        self.assertTrue(sorunlar)


if __name__ == "__main__":
    unittest.main()
