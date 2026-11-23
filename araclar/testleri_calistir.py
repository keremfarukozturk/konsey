#!/usr/bin/env python3
"""Bütün test paketini geçici HOME ile çalıştırır (karar 65). Kullanım: python3 araclar/testleri_calistir.py [unittest bayrakları]
Koruma `testler/ev_korumasi.py`'dedir; ayrıntı için oraya bak. Çıkış kodu unittest'inkidir."""
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "testler"))
sys.path.insert(0, str(KOK))
import ev_korumasi  # noqa: E402

ev_korumasi.kur()

if __name__ == "__main__":
    ek = sys.argv[1:]
    sys.exit(0 if unittest.main(module=None, argv=["unittest", "discover", "-s", str(KOK / "testler"), "-p", "test_*.py", *ek],
                                exit=False).result.wasSuccessful() else 1)
