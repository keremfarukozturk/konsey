"""
Test yalıtımı (v0.26, karar 65): test koşusu gerçek ev klasörüne yazmamalıdır.

`kur()` çağrılınca:
1. HOME (ve USERPROFILE) geçici bir klasöre ayarlanır; `~` açılımları, `Path.home()` ve alt süreçler bunu görür.
2. Bir denetim kancası (sys.addaudithook) gerçek ev klasörü altına (depo klasörü ve geçici klasörler HARİÇ) yazma girişimini
   (yazma kipinde açma, mkdir, rename/replace, remove/rmdir, symlink/link, truncate, chmod, kopyalama/taşıma) yakalar,
   EvDizinineYazmaGirisimi (BaseException) fırlatır: `except Exception`/`except OSError` ile yutulamaz; unittest bunu test
   hatası sayar. Olay, asıl işlem yapılmadan önce gelir; yani dosya oluşmaz.

Kanca süreç boyunca kalır (Python denetim kancaları kaldırılamaz) ama yalnızca `kur()` sonrası etkindir. Alt süreçler (sahte CLI
betikleri) kancadan etkilenmez; onları HOME değişikliği korur.

Garanti sınırı: yalnızca Python'un denetim olayı üreten yazma yolları denetlenir; alt süreçlerin yazmalarını HOME değişikliği
sınırlar (gerçek evin mutlak yolunu kullanan bir alt süreç korunmaz). Koruma, `test_00_ev_korumasi.py` (alfabetik ilk, import
anında `kur()` çağırır) ya da `araclar/testleri_calistir.py` ile kurulur; tek bir test dosyası doğrudan çalıştırılırsa devrede
olmayabilir. Bu yüzden bütün paketi `python3 araclar/testleri_calistir.py` ile çalıştır.
"""
from __future__ import annotations

import atexit
import os
import pwd
import shutil
import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
GERCEK_EV = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()


class EvDizinineYazmaGirisimi(BaseException):
    """Test koşusunda gerçek ev klasörüne (depo ve geçici klasörler dışında) yazma girişimi."""


_durum = {"aktif": False, "gecici_ev": None, "izinli": [], "ihlaller": [], "ilk_goruntu": None}
_kanca_kuruldu = False

_YAZMA_BAYRAKLARI = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
# olay adı -> (yol sıra numaraları, son bileşen sembolik bağ olabilir mi: çözülmez)
_YOL_OLAYLARI = {
    "os.mkdir": ((0,), False), "os.rmdir": ((0,), True), "os.remove": ((0,), True), "os.rename": ((0, 1), True),
    "os.symlink": ((1,), True), "os.link": ((0, 1), True), "os.truncate": ((0,), False), "os.chmod": ((0,), False),
    "os.chown": ((0,), False), "shutil.copyfile": ((1,), False), "shutil.copymode": ((1,), False),
    "shutil.copystat": ((1,), False), "shutil.copytree": ((1,), False), "shutil.move": ((1,), False),
    "shutil.rmtree": ((0,), True), "os.utime": ((0,), False),
}


def _yol(x, son_bilesen_coz: bool) -> Path | None:
    try:
        if isinstance(x, int):
            return None
        ham = os.fsdecode(os.fspath(x))
    except TypeError:
        return None
    tam = os.path.abspath(ham)
    if son_bilesen_coz:
        return Path(os.path.realpath(tam))
    # sembolik bağın kendisine işlem (silme, yeniden adlandırma): yalnızca üst klasör çözülür
    return Path(os.path.realpath(os.path.dirname(tam))) / os.path.basename(tam)


def _altinda(y: Path, kok: Path) -> bool:
    return y == kok or kok in y.parents


def yasak_mi(y: Path | None) -> bool:
    if y is None:
        return False
    if not _altinda(y, GERCEK_EV):
        return False
    return not any(_altinda(y, Path(i)) for i in _durum["izinli"])


def _kanca(olay: str, args: tuple) -> None:
    if not _durum["aktif"]:
        return
    hedefler: list[Path | None] = []
    if olay == "open":
        yol, _kip, bayrak = (args + (None, None, None))[:3]
        if isinstance(bayrak, int) and bayrak & _YAZMA_BAYRAKLARI:
            hedefler.append(_yol(yol, True))
    elif olay in _YOL_OLAYLARI:
        sirlar, coz = _YOL_OLAYLARI[olay]
        for i in sirlar:
            if i < len(args):
                hedefler.append(_yol(args[i], not coz))
    for y in hedefler:
        if yasak_mi(y):
            mesaj = f"{olay}: gerçek ev klasörüne yazma girişimi engellendi: {y}"
            _durum["ihlaller"].append(mesaj)
            raise EvDizinineYazmaGirisimi(mesaj)


def kur() -> Path:
    """Koruma kurulur (idempotent); geçici HOME'un yolunu döndürür."""
    global _kanca_kuruldu
    if _durum["gecici_ev"]:
        return Path(_durum["gecici_ev"])
    gecici = Path(tempfile.mkdtemp(prefix="konsey-test-ev-")).resolve()
    if _altinda(gecici, GERCEK_EV):   # TMPDIR gerçek evin içindeyse koruma anlamsız olur
        raise RuntimeError(f"geçici klasör gerçek ev klasörünün içinde: {gecici}")
    _durum["ilk_goruntu"] = ev_goruntusu()
    _durum["gecici_ev"] = str(gecici)
    _durum["izinli"] = [str(KOK), str(gecici), str(Path(tempfile.gettempdir()).resolve())]
    # Salt-okunur istisna: test_codex_izin_listesi gerçek Codex oturum kayıtlarını OKUR (geriye dönük tarama). Yalnızca bu
    # klasör sembolik bağlanır; bağ üzerinden yazma, realpath çözümüyle gerçek ev altında sayılır ve kanca tarafından engellenir.
    gercek_oturumlar = GERCEK_EV / ".codex" / "sessions"
    if gercek_oturumlar.is_dir():
        (gecici / ".codex").mkdir()
        os.symlink(gercek_oturumlar, gecici / ".codex" / "sessions")
    os.environ["HOME"] = str(gecici)
    os.environ["USERPROFILE"] = str(gecici)
    if not _kanca_kuruldu:
        sys.addaudithook(_kanca)
        _kanca_kuruldu = True
    _durum["aktif"] = True
    atexit.register(_temizle)
    return gecici


def _temizle() -> None:
    gecici = _durum["gecici_ev"]
    if gecici:
        # temizlik sırasında kanca da etkin kalır: geçici klasör izinlidir
        shutil.rmtree(gecici, ignore_errors=True)


def ev_goruntusu() -> dict:
    """Gerçek evde konseye ait üst düzey girdilerin (`konsey*`, `.konsey*`; depo klasörü hariç) anlık görüntüsü:
    {ad: ((göreli yol, mtime_ns, boyut), …)}. Test koşusunun bunları değiştirmediğini denetlemek içindir."""
    sonuc = {}
    try:
        adlar = sorted(os.listdir(GERCEK_EV))
    except OSError:
        return sonuc
    for ad in adlar:
        if not (ad.startswith("konsey") or ad.startswith(".konsey")) or (GERCEK_EV / ad) == KOK:
            continue
        kok = GERCEK_EV / ad
        girdiler = []
        for yol, klasorler, dosyalar in os.walk(kok, followlinks=False):
            for dosya in sorted(klasorler + dosyalar):
                tam = os.path.join(yol, dosya)
                try:
                    st = os.lstat(tam)
                except OSError:
                    continue
                girdiler.append((os.path.relpath(tam, GERCEK_EV), st.st_mtime_ns, st.st_size))
        sonuc[ad] = tuple(girdiler)
    return sonuc


def aktif_mi() -> bool:
    return bool(_durum["aktif"])


def gecici_ev() -> Path | None:
    return Path(_durum["gecici_ev"]) if _durum["gecici_ev"] else None


def ihlaller() -> list[str]:
    return list(_durum["ihlaller"])


def ilk_goruntu() -> dict | None:
    return _durum["ilk_goruntu"]
