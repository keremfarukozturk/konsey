"""
Adaptör katmanı: üç CLI'ı (claude, codex, agy) aynı arayüzle çağırır.

PROJE.md Bölüm 6'daki kurallara göre yazıldı:
- Her CLI kendi süreç grubunda başlar; zaman aşımında bütün grup öldürülür.
- Çıkış kodu ve yapılandırılmış hata alanları kontrol edilir; hata metni asla cevap gibi döndürülmez.
- Kota ve giriş hataları yalnızca hata mesajında aranır, modelin cevabında değil.
- API anahtarı ortam değişkenleri alt süreçlere aktarılmaz (abonelik dışına kaçışı kodla engeller).
- Ham çıktı her çağrıda dosyaya kaydedilir.

Not: Prompt komut satırı argümanı olarak verilir. macOS'te argüman sınırı yaklaşık 1 MB olduğu için
konsey prompt'ları için yeterli; üç CLI'ın da bu biçimde çalıştığı kurulum sırasında doğrulandı.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import hashlib
import os
import pwd
import re
import shutil
import signal
import sys
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Alt süreçlere asla aktarılmayacak ortam değişkenleri.
API_ANAHTARI_DEGISKENLERI = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENAI_API_KEY",
)

# Sağlayıcıya özel ortam temizliği (karar 44): çağrıyı API faturalandırmasına, başka bir sunucuya/sağlayıcıya,
# başka bir hesaba ya da başka bir yapılandırma klasörüne yönlendirebilecek değişkenler alt süreçten silinir.
# Claude: resmi belge code.claude.com/docs/en/env-vars (19 Kasım 2026). Codex: kurulu codex 0.169.0 ikilisinde adın
# bulunması + config-reference (resmi env sayfası ayrı ve okunamadı; adlar [DOĞRULANMADI · belge], ikilide görüldü).
# agy: changelog (`agy changelog`) ve belge. HTTP(S)_PROXY, NO_PROXY, SSL_CERT_FILE, NODE_EXTRA_CA_CERTS gibi
# ağ taşıma ayarları SİLİNMEZ (bağlantıyı bozabilir); bkz. belgeler/guvenlik.md 9.6.
CLAUDE_ORTAM_SILINECEK = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS",
    "ANTHROPIC_PROFILE", "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID", "ANTHROPIC_WORKSPACE_ID",
    "ANTHROPIC_AWS_API_KEY", "ANTHROPIC_AWS_WORKSPACE_ID", "ANTHROPIC_AWS_BASE_URL", "AWS_BEARER_TOKEN_BEDROCK",
    "ANTHROPIC_BEDROCK_BASE_URL", "ANTHROPIC_BEDROCK_MANTLE_BASE_URL", "ANTHROPIC_FOUNDRY_API_KEY",
    "ANTHROPIC_FOUNDRY_AUTH_TOKEN", "ANTHROPIC_FOUNDRY_BASE_URL", "ANTHROPIC_FOUNDRY_RESOURCE",
    "ANTHROPIC_GOOGLE_CLOUD_BASE_URL", "ANTHROPIC_GOOGLE_CLOUD_PROJECT", "ANTHROPIC_GOOGLE_CLOUD_LOCATION",
    "ANTHROPIC_GOOGLE_CLOUD_WORKSPACE_ID", "ANTHROPIC_VERTEX_BASE_URL", "ANTHROPIC_VERTEX_PROJECT_ID",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_MANTLE",
    "CLAUDE_CODE_USE_ANTHROPIC_AWS", "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD",
    "CLAUDE_CODE_SKIP_BEDROCK_AUTH", "CLAUDE_CODE_SKIP_VERTEX_AUTH", "CLAUDE_CODE_SKIP_FOUNDRY_AUTH",
    "CLAUDE_CODE_SKIP_MANTLE_AUTH", "CLAUDE_CODE_SKIP_ANTHROPIC_AWS_AUTH",
    "CLAUDE_CODE_SKIP_ANTHROPIC_GOOGLE_CLOUD_AUTH", "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST",
    "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "CLAUDE_CODE_EXTRA_BODY",
    "CLAUDE_CONFIG_DIR", "ENABLE_CLAUDEAI_MCP_SERVERS", "CLOUD_ML_REGION", "GOOGLE_APPLICATION_CREDENTIALS",
    "BETA_TRACING_ENDPOINT", "ENABLE_BETA_TRACING_DETAILED", "CLAUDE_CODE_ENABLE_TELEMETRY",
)
CLAUDE_ORTAM_ONEKLERI = ("ANTHROPIC_", "OTEL_")  # ANTHROPIC_DEFAULT_*_MODEL gibi takma ad yönlendirmeleri ve telemetri
CODEX_ORTAM_SILINECEK = (
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORGANIZATION", "OPENAI_PROJECT", "OPENAI_FEDERATION_RULE_ID",
    "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "CODEX_CONNECTORS_TOKEN", "CODEX_GITHUB_PERSONAL_ACCESS_TOKEN",
    "CODEX_OSS_BASE_URL", "CODEX_OSS_PORT", "CODEX_APP_SERVER_CHATGPT_BASE_URL", "CODEX_CLOUD_TASKS_BASE_URL",
    "CODEX_EXEC_SERVER_URL", "CODEX_REFRESH_TOKEN_URL_OVERRIDE", "CODEX_HOME", "CODEX_SQLITE_HOME",
    "AWS_BEARER_TOKEN_BEDROCK", "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION",
)
CODEX_ORTAM_ONEKLERI = ("OPENAI_",)
GEMINI_ORTAM_SILINECEK = (
    "AGY_ADC_AUTH", "GOOGLE_GEMINI_BASE_URL", "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
)
GEMINI_ORTAM_ONEKLERI = ("AGY_", "ANTIGRAVITY_")
# Codex ve agy'nin Claude CLI oturum değişkenlerine (ör. CLAUDE_CODE_MESSAGING_TOKEN) ihtiyacı yok; sızmasın.
BASKA_KOLTUK_ONEKLERI = ("CLAUDE_CODE_", "CLAUDECODE")
SAGLAYICI_ORTAMI = {
    "claude": (CLAUDE_ORTAM_SILINECEK, CLAUDE_ORTAM_ONEKLERI),
    "codex": (CODEX_ORTAM_SILINECEK, CODEX_ORTAM_ONEKLERI + BASKA_KOLTUK_ONEKLERI),
    "gemini": (GEMINI_ORTAM_SILINECEK, GEMINI_ORTAM_ONEKLERI + BASKA_KOLTUK_ONEKLERI),
}

# Hata mesajı sınıflandırma kalıpları. Kesin biçimler henüz doğrulanmadı (PROJE.md Bölüm 13);
# ilk gerçek kota hatasının ham çıktısıyla güncellenecek.
KOTA_KALIPLARI = re.compile(
    r"rate[ _-]?limit|usage limit|quota|\b429\b|too many requests|resource[_ ]exhausted"
    r"|limit reached|try again at|out of (credits|usage)",
    re.IGNORECASE,
)
GIRIS_KALIPLARI = re.compile(
    r"not logged in|log ?in required|/login|please log ?in|unauthori[sz]ed|\b401\b"
    r"|invalid api key|authentication (failed|required|error)|credentials",
    re.IGNORECASE,
)

MAKS_PROMPT_BAYT = 500_000  # macOS argüman sınırının güvenli altında

# Model doğrulama için okunan yerel kayıtlar (PROJE.md 6.2). Sağlayıcı ayarında "kayit_dizini" ile değiştirilebilir.
VARSAYILAN_KAYIT_DIZINI = {
    "gemini": "~/.gemini/antigravity-cli/conversations",
    "codex": "~/.codex/sessions",
}
# Model doğrulama düzeyleri
DOGRULAMA_SUNUCU = "sunucu"            # sunucunun bildirdiği model okundu ve istenenle uyuştu
DOGRULAMA_ISTEMCI = "istemci"          # yalnızca CLI'ın gönderdiği model okunabildi ve istenenle uyuştu
DOGRULAMA_YOK = "doğrulanamadı"        # model bilgisi okunamadı (çağrı yine de geçerli)
MODEL_UYUSMAZLIGI = "MODEL UYUŞMAZLIĞI"  # hata metni öneki
EFOR_EKI = re.compile(r"-(low|medium|high|xhigh|max)$")

# --------------------------------------------------------------------------- agy salt okunurluk (PROJE.md Bölüm 9, 6.6)
# agy'nin araçları kaldırılamıyor; üç katmanla engelleniyor ve denetleniyor:
#  1. Çalışma klasöründeki .agents/hooks.json: her araç çağrısına PreToolUse "deny" (ana engel).
#  2. --settings toolPermission=strict: headless modda her araç onay ister, yani reddedilir (yedek engel).
#  3. Çağrı sonrası transcript denetimi: tamamlanmış araç adımı varsa çağrı hata sayılır.
# useG1Credits=false: plan kotası bitince ücretli AI kredisine geçilmesin. Değer tipi `agy models` ile
# doğrulandı ("off" gibi metin değerleri agy'yi hata ile durduruyor).
AGY_AYARLARI = '{"toolPermission":"strict","useG1Credits":false}'
AGY_HOOK_NEDENI = "Konsey cagrisi: araclar kapali (salt okunur)."
AGY_HOOK_JSON = json.dumps({
    "konsey-salt-okunur": {
        "PreToolUse": [{
            "matcher": "*",
            "hooks": [{
                "type": "command",
                "command": "printf '%s' '" + json.dumps({"decision": "deny", "reason": AGY_HOOK_NEDENI}) + "'",
                "timeout": 5,
            }],
        }]
    }
}, indent=2) + "\n"
VARSAYILAN_AGY_BEYIN_DIZINI = "~/.gemini/antigravity-cli/brain"
AGY_YALITIM_HATASI = "AGY YALITIMI EKSİK"                # hata metni öneki


def varsayilan_agy_beyin_dizini(s: dict) -> str:
    """agy transcript klasörü: yalıtılmış HOME varsa onun altı (karar 44), yoksa gerçek ~/.gemini."""
    if s.get("home"):
        return str(Path(s["home"]).expanduser() / ".gemini" / "antigravity-cli" / "brain")
    return VARSAYILAN_AGY_BEYIN_DIZINI


def varsayilan_kayit_dizini(ad: str, s: dict) -> str:
    if ad == "gemini" and s.get("home"):
        return str(Path(s["home"]).expanduser() / ".gemini" / "antigravity-cli" / "conversations")
    return VARSAYILAN_KAYIT_DIZINI.get(ad, "")
CODEX_WEB_AYARI = 'web_search="disabled"'
CODEX_DUSUNME_AYARI = 'model_reasoning_effort="high"'
# Konsey Codex'ten yalnızca metin cevabı ister: komut, bağlayıcı (apps), eklenti, tarayıcı, bilgisayar kullanımı,
# görsel okuma/üretme, alt ajan ve hedef araçları kapalı. Ad doğruluğu `codex features list` ve --strict-config
# ile denetlenir (tanınmayan ad çağrıyı hata yapar). Kalan araçlar: bkz. belgeler/guvenlik.md 9.2.
CODEX_KAPALI_OZELLIKLER = ("shell_tool", "apps", "plugins", "remote_plugin", "browser_use", "computer_use",
                           "image_generation", "view_image", "goals", "multi_agent", "hooks")
CODEX_WEB_ERISIMI = "CODEX WEB ERİŞİMİ TESPİT EDİLDİ"    # hata metni öneki
ARAC_IHLALI = "ARAÇ İHLALİ"                              # hata metni öneki
ARAC_DENEMESI_BOS = "ARAÇ DENEMESİ NEDENİYLE BOŞ CEVAP"  # hata metni öneki
KANCA_HATASI = "SALT OKUNUR KANCASI HAZIRLANAMADI"       # hata metni öneki
AGY_BELIRSIZ_ADIM = "BELİRSİZ ADIM:"                    # agy transcript'inde DONE/ERROR dışı durumdaki araç adımı
# Araç denetimi düzeyleri
DENETIM_TEMIZ = "temiz"            # kayıt okundu, çalışan araç yok
DENETIM_IHLAL = "ihlal"            # kayıt okundu, çalışan araç var (agy: çağrı hata)
DENETIM_YOK = "yapılamadı"         # kayıt okunamadı
# Claude: "araçlar kapalı" = init araç/MCP listesi, sonuç değişmezleri ve asistan olayları gerçekten kontrol edildi
# ve temiz çıktı (v0.18, karar 42). Sabit bir beyan değildir: init olayı yoksa çağrı hata olur (CLAUDE_INIT_ZORUNLU).
DENETIM_KAPALI = "araçlar kapalı"
DENETIM_GORULDU = "kaydedildi"     # Codex: komutlar sayıldı (komut çalıştırmak hata değil)


class AyarHatasi(Exception):
    pass


@dataclass
class CagriSonucu:
    saglayici: str
    durum: str  # ok | rate_limited | auth_error | error | timeout
    metin: str = ""
    hata: str = ""
    istenen_model: str = ""
    gercek_model: str = ""  # CLI çıktısından ya da yerel kayıttan okunabildiyse
    sure_sn: float = 0.0
    ham_kayit: str = ""
    oturum_kimligi: str = ""  # agy conversation_id / Codex thread_id
    model_dogrulama: str = ""  # sunucu | istemci | doğrulanamadı (yalnızca başarılı çağrılarda)
    dogrulama_notu: str = ""
    kota: dict = field(default_factory=dict)  # şimdilik yalnızca Codex: oturum kaydındaki rate_limits
    arac_denetimi: str = ""  # temiz | ihlal | yapılamadı | araçlar kapalı | kaydedildi
    arac_ozeti: dict = field(default_factory=dict)  # denenen/reddedilen/çalışan araçlar, Codex komutları

    @property
    def basarili(self) -> bool:
        return self.durum == "ok"

    def sozluk(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- ayarlar


def ayarlari_yukle(yol: str | Path) -> dict:
    with open(yol, encoding="utf-8") as f:
        ayar = json.load(f)
    # Ortam değişkenleri ayar dosyasındaki varsayılanları değiştirir (yoksa varsayılanlar aynen kalır).
    if os.environ.get("KONSEY_OTURUM"):
        ayar["calisma_klasoru"] = os.environ["KONSEY_OTURUM"]
    if os.environ.get("KONSEY_AGY_HOME") and ayar.get("saglayicilar", {}).get("gemini"):
        ayar["saglayicilar"]["gemini"]["home"] = os.environ["KONSEY_AGY_HOME"]
    ayar["calisma_klasoru"] = str(Path(ayar["calisma_klasoru"]).expanduser())
    kayit = Path(ayar["kayit_klasoru"]).expanduser()
    if not kayit.is_absolute():  # göreli yol, ayar dosyasının bulunduğu klasöre göre çözülür
        kayit = Path(yol).resolve().parent / kayit
    ayar["kayit_klasoru"] = str(kayit)
    for ad, s in ayar["saglayicilar"].items():
        if ad not in ("claude", "codex", "gemini"):
            raise AyarHatasi(f"Bilinmeyen sağlayıcı: {ad}")
        komut = s["komut"]
        s["komut"] = [os.path.expanduser(x) for x in (komut if isinstance(komut, list) else [komut])]
        if not s.get("model"):
            raise AyarHatasi(f"{ad} için model belirtilmemiş. Model her zaman açıkça yazılmalı (PROJE.md 10.1).")
    gemini = ayar["saglayicilar"].get("gemini")
    if gemini:
        for anahtar in ("home", "gercek_gemini_dizini"):
            if gemini.get(anahtar):
                gemini[anahtar] = str(Path(gemini[anahtar]).expanduser())
    if gemini and not gemini["model"].startswith("gemini-"):
        raise AyarHatasi(
            f"Gemini koltuğu için seçilen model Gemini değil: {gemini['model']}. "
            "agy başka şirketlerin modellerini de sunuyor; konseyde yalnızca 'gemini-' ile başlayan modeller kullanılabilir."
        )
    return ayar


def program_var_mi(komut: list[str]) -> bool:
    ilk = komut[0]
    if os.sep in ilk:
        return os.path.isfile(ilk) and os.access(ilk, os.X_OK)
    return shutil.which(ilk) is not None


def temiz_ortam(ad: str | None = None, kaynak: dict | None = None) -> dict:
    """Alt süreç ortamı: API anahtarları silinir; `ad` verilirse o sağlayıcının yönlendirme değişkenleri de.
    `kaynak` verilmezse os.environ kullanılır."""
    env = {k: v for k, v in (os.environ if kaynak is None else kaynak).items() if k not in API_ANAHTARI_DEGISKENLERI}
    if ad in SAGLAYICI_ORTAMI:
        adlar, onekler = SAGLAYICI_ORTAMI[ad]
        env = {k: v for k, v in env.items() if k not in adlar and not k.startswith(onekler)}
    return env


def silinen_ortam_degiskenleri(ad: str, kaynak: dict | None = None) -> list[str]:
    """`temiz_ortam(ad)` ile silinecek değişken adları (değersiz); raporlama ve testler için."""
    kaynak = dict(os.environ) if kaynak is None else kaynak
    return sorted(set(kaynak) - set(temiz_ortam(ad, kaynak)))


def saglayici_ortami(ad: str, s: dict | None = None) -> dict:
    """Bir sağlayıcının alt süreç ortamı. agy için, `home` ayarı varsa HOME yalıtılmış klasöre çevrilir (karar 44)."""
    env = temiz_ortam(ad)
    if ad == "gemini" and s and s.get("home"):
        env["HOME"] = str(Path(s["home"]).expanduser())
    return env


# --------------------------------------------------------------------------- komutlar


def komut_olustur(ad: str, s: dict, prompt: str, zaman_asimi: int) -> list[str]:
    k, m = list(s["komut"]), s["model"]
    if ad == "claude":
        # Prompt değişken uzunluklu seçeneklerden önce gelmeli; yoksa onlara yutulur.
        # --tools "" tüm yerleşik araçları, --disallowedTools "mcp__*" MCP araçlarını kapatır (salt okunur).
        # stream-json + --verbose: init olayındaki tools / mcp_servers listesi denetlenir (karar 39).
        # (claude.ai bağlayıcıları -p modunda zaten yüklenmiyor; 19 Kasım 2026 yoklaması, guvenlik.md 9.4.)
        # --strict-mcp-config (v0.19, karar 47): `--mcp-config` verilmediği için hiçbir MCP kaynağı yüklenmez; kullanıcının
        # Claude'a kurduğu MCP sunucuları ve claude.ai bağlayıcıları konseye girmez (guvenlik.md 9.6'daki deney).
        # --setting-sources "" (v0.20, karar 48): kullanıcı/proje/yerel settings.json hiç yüklenmez (env bloğu, hooks,
        # apiKeyHelper, izinler, eklentiler). Deneyle: --safe-mode settings env'ini yüklemeye devam eder, --bare OAuth'u
        # okumaz; bu yüzden yalnızca --setting-sources "" seçildi. Abonelik girişi bozulmaz (apiKeySource none).
        return k + ["-p", prompt, "--output-format", "stream-json", "--verbose", "--model", m,
                    "--strict-mcp-config", "--setting-sources", "", "--disallowedTools", "mcp__*", "--tools", ""]
    if ad == "codex":
        # Salt okunur sandbox; konsey klasörü Git deposu olmadığı için depo kontrolü atlanır.
        # Yerleşik web araması sandbox'tan bağımsızdır (sunucu tarafında çalışır); bu yüzden açıkça kapatılır:
        # `-c web_search="disabled"` (resmi config belgesi: "disabled" aracı kaldırır; deneyle doğrulandı).
        # --strict-config: CLI bu ayarı tanımazsa (anahtar kalkmış/yeniden adlandırılmış) çağrı hata verir.
        # Araç yüzeyi: --ignore-user-config kullanıcının config.toml'unu (eklentiler, MCP sunucuları, notify
        # programı) yüklemez; hesap bağlayıcıları (apps: GitHub, Gmail, Drive, Notion...) config'ten bağımsız
        # geldiği için CODEX_KAPALI_OZELLIKLER ile ayrıca kapatılır. Kullanıcı config'i yüklenmediği için
        # düşünme seviyesi açıkça verilir (eskiden config'ten "high" geliyordu).
        kapat = [x for f in CODEX_KAPALI_OZELLIKLER for x in ("-c", f"features.{f}=false")]
        return k + ["exec", "--json", "--ignore-user-config", "--strict-config", "-c", CODEX_WEB_AYARI,
                    "-c", CODEX_DUSUNME_AYARI, *kapat,
                    "--skip-git-repo-check", "--sandbox", "read-only", "-m", m, prompt]
    if ad == "gemini":
        # Model sabit: agy bilinmeyen modelde sessizce başka modele düşmez, hata verir.
        # --settings: strict araç izni (yedek engel) ve ücretli krediye geçmeme; bkz. AGY_AYARLARI.
        return k + ["-p", prompt, "--output-format", "json", "--model", m,
                    "--print-timeout", f"{zaman_asimi}s", "--settings", AGY_AYARLARI]
    raise AyarHatasi(f"Bilinmeyen sağlayıcı: {ad}")


# --------------------------------------------------------------------------- süreç yönetimi


async def surec_grubunu_oldur(proc: asyncio.subprocess.Process) -> None:
    """Önce nazikçe (SIGTERM), sonra zorla (SIGKILL) bütün süreç grubunu kapatır."""
    pgid = proc.pid  # start_new_session=True olduğu için grup kimliği = süreç kimliği
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=3)
    except asyncio.TimeoutError:
        pass
    # Lider kapansa bile gruptaki alt süreçler (npm, node vb.) yaşıyor olabilir.
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=3)
    except asyncio.TimeoutError:
        pass


async def surec_calistir(komut: list[str], cwd: str, zaman_asimi: float,
                         ortam: dict | None = None) -> tuple[int | None, str, str, bool]:
    """(çıkış kodu, stdout, stderr, zaman_aşımı_oldu_mu) döndürür. `ortam` verilmezse temiz_ortam() kullanılır."""
    proc = await asyncio.create_subprocess_exec(
        *komut,
        cwd=cwd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=ortam if ortam is not None else temiz_ortam(),
        start_new_session=True,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=zaman_asimi)
    except asyncio.TimeoutError:
        await surec_grubunu_oldur(proc)
        return None, "", "", True
    except asyncio.CancelledError:
        await surec_grubunu_oldur(proc)
        raise
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), False


# --------------------------------------------------------------------------- çıktı çözümleme


def siniflandir(mesaj: str) -> str:
    if KOTA_KALIPLARI.search(mesaj or ""):
        return "rate_limited"
    if GIRIS_KALIPLARI.search(mesaj or ""):
        return "auth_error"
    return "error"


def _hata(ad: str, mesaj: str) -> CagriSonucu:
    mesaj = (mesaj or "").strip() or "Bilinmeyen hata (boş çıktı)"
    return CagriSonucu(ad, siniflandir(mesaj), hata=mesaj[-2000:])


def _json_yukle(metin: str):
    metin = (metin or "").strip()
    if not metin:
        return None
    try:
        return json.loads(metin)
    except json.JSONDecodeError:
        pass
    for satir in reversed(metin.splitlines()):  # bazı CLI'lar JSON'dan önce uyarı basabilir
        satir = satir.strip()
        if satir.startswith("{"):
            try:
                return json.loads(satir)
            except json.JSONDecodeError:
                continue
    return None


def claude_olaylari(out: str) -> list[dict]:
    """Claude stream-json çıktısındaki (ya da tek JSON çıktısındaki) nesneleri sırayla döndürür."""
    olaylar = []
    for satir in (out or "").splitlines():
        satir = satir.strip()
        if satir.startswith("{"):
            try:
                e = json.loads(satir)
            except json.JSONDecodeError:
                continue
            if isinstance(e, dict):
                olaylar.append(e)
    return olaylar


def _claude_coz(rc, out, err) -> CagriSonucu:
    olaylar = claude_olaylari(out)
    d = next((e for e in reversed(olaylar) if e.get("type") == "result"), None)
    if d is None and olaylar and any(e.get("type") == "system" for e in olaylar):
        return _hata("claude", err or f"Akışta result olayı yok (çıkış kodu {rc})")
    if d is None:
        d = _json_yukle(out)
    if not isinstance(d, dict):
        return _hata("claude", err or out or f"Çıkış kodu {rc}, JSON yok")
    if d.get("is_error") or rc != 0 or d.get("subtype") not in (None, "success"):
        return _hata("claude", str(d.get("result") or d.get("error") or err or d))
    metin = d.get("result") or ""
    if not str(metin).strip():
        return CagriSonucu("claude", "error", hata="Claude boş cevap döndürdü")
    modeller = list((d.get("modelUsage") or {}).keys())
    return CagriSonucu("claude", "ok", metin=str(metin), gercek_model=", ".join(modeller))


def _codex_coz(rc, out, err) -> CagriSonucu:
    olaylar = []
    for satir in (out or "").splitlines():
        satir = satir.strip()
        if satir.startswith("{"):
            try:
                olaylar.append(json.loads(satir))
            except json.JSONDecodeError:
                continue  # yarım kalmış satır
    hatalar = [e for e in olaylar if e.get("type") in ("turn.failed", "error")]
    if hatalar or rc != 0:
        mesaj = ""
        if hatalar:
            e = hatalar[-1]
            hata_alani = e.get("error")
            if isinstance(hata_alani, dict):
                mesaj = hata_alani.get("message") or ""
            mesaj = mesaj or e.get("message") or json.dumps(e, ensure_ascii=False)
        return _hata("codex", mesaj or err or f"Çıkış kodu {rc}")
    # Yalnızca son cevap mesajı alınır; akıl yürütme özetleri cevaba karıştırılmaz.
    mesajlar = [
        e["item"].get("text", "")
        for e in olaylar
        if e.get("type") == "item.completed"
        and isinstance(e.get("item"), dict)
        and e["item"].get("type") in ("agent_message", "assistant_message")
    ]
    mesajlar = [m for m in mesajlar if m and m.strip()]
    if not mesajlar:
        return CagriSonucu("codex", "error",
                           hata="Codex çıktısında cevap mesajı bulunamadı; olay biçimi değişmiş olabilir.")
    model = next((str(e["model"]) for e in olaylar if e.get("model")), "")
    return CagriSonucu("codex", "ok", metin=mesajlar[-1], gercek_model=model)


def _gemini_coz(rc, out, err) -> CagriSonucu:
    d = _json_yukle(out)
    if not isinstance(d, dict):
        return _hata("gemini", err or out or f"Çıkış kodu {rc}, JSON yok")
    hata = d.get("error")
    durum = str(d.get("status", "")).lower()
    if rc != 0 or hata or durum in ("error", "failed", "failure"):
        if isinstance(hata, str):
            mesaj = hata
        elif hata:
            mesaj = json.dumps(hata, ensure_ascii=False)
        else:
            mesaj = err or json.dumps(d, ensure_ascii=False)
        return _hata("gemini", mesaj)
    metin = d.get("response") or d.get("result") or ""
    reddedilen = d.get("denied_actions") if isinstance(d.get("denied_actions"), list) else []
    if not str(metin).strip():
        if reddedilen:
            # strict izin modu araç çağrısını reddedince agy turu cevapsız bitirir (kanarya testi, 19 Kasım 2026).
            eylemler = ", ".join(str(e.get("action", "?")) if isinstance(e, dict) else str(e) for e in reddedilen)
            return CagriSonucu("gemini", "error", hata=f"{ARAC_DENEMESI_BOS}: model araç kullanmaya çalıştı "
                                                       f"ve reddedildi ({eylemler})")
        return CagriSonucu("gemini", "error", hata="agy boş cevap döndürdü")
    model = str(d.get("model") or "")
    if model and not model.lower().startswith("gemini"):
        return CagriSonucu("gemini", "error",
                           hata=f"Gemini koltuğunda Gemini dışı bir model cevap verdi: {model}")
    return CagriSonucu("gemini", "ok", metin=str(metin), gercek_model=model)


def ciktiyi_coz(ad: str, rc, out: str, err: str) -> CagriSonucu:
    return {"claude": _claude_coz, "codex": _codex_coz, "gemini": _gemini_coz}[ad](rc, out, err)


# --------------------------------------------------------------------------- model doğrulama ve kota
#
# Buradaki okumalar CLI'ların belgelenmemiş iç kayıtlarına dayanır ve CLI güncellenince bozulabilir.
# Kural: okuma hangi nedenle başarısız olursa olsun istisna fırlatılmaz, sonuç "doğrulanamadı" olur.
# Çağrıyı yalnızca açık bir model uyuşmazlığı hata yapar.

KIMLIK_KALIBI = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{3,80}$")  # yol enjeksiyonuna karşı


def oturum_kimligi_bul(ad: str, out: str) -> str:
    """CLI çıktısından agy conversation_id'sini ya da Codex thread_id'sini çıkarır; bulamazsa ''."""
    try:
        if ad == "gemini":
            d = _json_yukle(out)
            kimlik = d.get("conversation_id") if isinstance(d, dict) else None
        elif ad == "codex":
            kimlik = None
            for satir in (out or "").splitlines():
                satir = satir.strip()
                if '"thread.started"' in satir:
                    try:
                        kimlik = json.loads(satir).get("thread_id")
                    except (json.JSONDecodeError, AttributeError):
                        pass
                    break
        else:
            return ""
        kimlik = str(kimlik or "")
        return kimlik if KIMLIK_KALIBI.match(kimlik) else ""
    except Exception:
        return ""


def _varint(b: bytes, i: int) -> tuple[int, int]:
    sonuc = kaydir = 0
    while True:
        if i >= len(b) or kaydir > 63:
            raise ValueError("bozuk varint")
        x = b[i]
        i += 1
        sonuc |= (x & 0x7F) << kaydir
        kaydir += 7
        if x < 0x80:
            return sonuc, i


def protobuf_alanlari(b: bytes) -> list[tuple[int, int, object]]:
    """Şemasız protobuf çözümü: [(alan_no, tel_tipi, değer)]. Uzunluklu alanlar bytes döner. Bozuksa ValueError."""
    alanlar, i = [], 0
    while i < len(b):
        anahtar, i = _varint(b, i)
        no, tip = anahtar >> 3, anahtar & 7
        if no == 0:
            raise ValueError("alan numarası 0")
        if tip == 0:
            deger, i = _varint(b, i)
        elif tip == 1:
            deger, i = b[i:i + 8], i + 8
        elif tip == 5:
            deger, i = b[i:i + 4], i + 4
        elif tip == 2:
            n, i = _varint(b, i)
            if i + n > len(b):
                raise ValueError("uzunluk taşması")
            deger, i = b[i:i + n], i + n
        else:
            raise ValueError(f"desteklenmeyen tel tipi {tip}")
        alanlar.append((no, tip, deger))
    if i != len(b):
        raise ValueError("artık bayt")
    return alanlar


def agy_kaydini_oku(klasor: str, kimlik: str) -> dict | None:
    """agy konuşma veritabanından sunucunun bildirdiği modeli okur.

    gen_metadata tablosundaki her üretim kaydında alan 1 bir mesajdır; onun içinde
    alan 19 = response_model, alan 20 = custom_metadata (anahtar 1 / değer 2) çiftleridir.
    Alan numaraları agy 1.5.11'in gömülü protobuf tanımından okundu (19 Kasım 2026).
    Döner: {"response_modeller": [...], "used_non_gemini_model": bool|None} ya da None.
    """
    try:
        if not kimlik or not KIMLIK_KALIBI.match(kimlik):
            return None
        yol = Path(klasor).expanduser() / f"{kimlik}.db"
        if not yol.is_file():
            return None
        con = sqlite3.connect(f"file:{yol}?mode=ro", uri=True, timeout=2)
        try:
            satirlar = con.execute("SELECT data FROM gen_metadata ORDER BY idx").fetchall()
        finally:
            con.close()
        modeller, non_gemini = [], None
        for (veri,) in satirlar:
            if not isinstance(veri, (bytes, bytearray)):
                continue
            try:
                for no, tip, ic in protobuf_alanlari(bytes(veri)):
                    if no != 1 or tip != 2:
                        continue
                    for no2, tip2, d2 in protobuf_alanlari(ic):
                        if no2 == 19 and tip2 == 2:
                            m = d2.decode("utf-8", "strict").strip()
                            if m:
                                modeller.append(m)
                        elif no2 == 20 and tip2 == 2:
                            kv = {n: v for n, t, v in protobuf_alanlari(d2) if t == 2}
                            if kv.get(1) == b"used_non_gemini_model":
                                deger = kv.get(2, b"").decode("utf-8", "replace").strip().lower()
                                if deger in ("true", "false"):
                                    non_gemini = bool(non_gemini) or deger == "true"
            except (ValueError, UnicodeDecodeError):
                continue  # bu kayıt çözülemedi; diğerlerine bak
        if not modeller and non_gemini is None:
            return None
        return {"response_modeller": modeller, "used_non_gemini_model": non_gemini}
    except Exception:
        return None


def codex_kaydini_bul(klasor: str, kimlik: str) -> Path | None:
    try:
        if not kimlik or not KIMLIK_KALIBI.match(kimlik):
            return None
        kok = Path(klasor).expanduser()
        if not kok.is_dir():
            return None
        adaylar = sorted(kok.glob(f"*/*/*/rollout-*-{kimlik}.jsonl"))
        return adaylar[-1] if adaylar else None
    except Exception:
        return None


def _zaman_damgasi(saniye) -> str:
    try:
        return dt.datetime.fromtimestamp(float(saniye)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def kota_ozeti(rate_limits: dict) -> dict:
    """Codex rate_limits nesnesini sade bir sözlüğe çevirir. Pencere adı window_minutes'ten çıkarılır."""
    ozet = {}
    if not isinstance(rate_limits, dict):
        return ozet
    for anahtar in ("primary", "secondary"):
        p = rate_limits.get(anahtar)
        if not isinstance(p, dict) or p.get("used_percent") is None:
            continue
        dk = p.get("window_minutes")
        ad = {300: "5_saat", 10080: "haftalik"}.get(dk, f"{dk}_dakika")
        try:
            yuzde = float(p["used_percent"])
        except (TypeError, ValueError):
            continue
        ozet[ad] = {"kullanilan_yuzde": yuzde, "sifirlanma": _zaman_damgasi(p.get("resets_at"))}
    if ozet:
        if rate_limits.get("plan_type"):
            ozet["plan"] = str(rate_limits["plan_type"])
        if rate_limits.get("rate_limit_reached_type"):
            ozet["sinira_ulasildi"] = str(rate_limits["rate_limit_reached_type"])
    return ozet


def codex_kaydini_oku(klasor: str, kimlik: str) -> dict | None:
    """Codex oturum kaydından CLI'ın gönderdiği modeli (turn_context.model) ve son rate_limits'i okur.
    Not: turn_context.model istemcinin isteğe koyduğu modeldir; sunucunun kullandığı model kayıtta yok."""
    try:
        yol = codex_kaydini_bul(klasor, kimlik)
        if yol is None:
            return None
        modeller, rate_limits = [], None
        with open(yol, encoding="utf-8", errors="replace") as f:
            for satir in f:
                try:
                    d = json.loads(satir)
                except json.JSONDecodeError:
                    continue  # yarım kalmış son satır olabilir
                if not isinstance(d, dict):
                    continue
                yuk = d.get("payload") if isinstance(d.get("payload"), dict) else {}
                if d.get("type") == "turn_context" and yuk.get("model"):
                    modeller.append(str(yuk["model"]))
                elif yuk.get("type") == "token_count" and isinstance(yuk.get("rate_limits"), dict):
                    rate_limits = yuk["rate_limits"]
        return {"istemci_modeller": modeller, "kota": kota_ozeti(rate_limits) if rate_limits else {}}
    except Exception:
        return None


def modeli_dogrula(ad: str, s: dict, sonuc: CagriSonucu) -> None:
    """Başarılı bir çağrının cevap veren modelini doğrular ve sonucu yerinde günceller.
    Açık uyuşmazlıkta sonucu hataya çevirir; bilgi okunamazsa yalnızca 'doğrulanamadı' der."""
    try:
        istenen = s["model"]
        klasor = s.get("kayit_dizini") or varsayilan_kayit_dizini(ad, s)
        if ad == "claude":
            if sonuc.gercek_model:
                sonuc.model_dogrulama = DOGRULAMA_SUNUCU
                sonuc.dogrulama_notu = "Claude çıktısındaki modelUsage"
            else:
                sonuc.model_dogrulama = DOGRULAMA_YOK
                sonuc.dogrulama_notu = "Claude çıktısında modelUsage yok"
            return

        if ad == "gemini":
            k = agy_kaydini_oku(klasor, sonuc.oturum_kimligi)
            if k is None:
                sonuc.model_dogrulama = DOGRULAMA_YOK
                sonuc.dogrulama_notu = "agy konuşma kaydı bulunamadı ya da okunamadı"
                return
            if k["used_non_gemini_model"] is True:
                _uyusmazlik(sonuc, "agy kaydına göre bu cevapta Gemini dışı bir model kullanıldı "
                                   "(used_non_gemini_model=true)")
                return
            beklenen = EFOR_EKI.sub("", istenen)
            farkli = sorted({m for m in k["response_modeller"] if m != beklenen})
            if farkli:
                _uyusmazlik(sonuc, f"istenen {istenen} (beklenen sunucu adı {beklenen}), "
                                   f"cevap veren {', '.join(farkli)}")
                return
            if not k["response_modeller"]:
                sonuc.model_dogrulama = DOGRULAMA_YOK
                sonuc.dogrulama_notu = "agy kaydında response_model alanı yok"
                return
            sonuc.gercek_model = beklenen
            sonuc.model_dogrulama = DOGRULAMA_SUNUCU
            sonuc.dogrulama_notu = "agy konuşma kaydındaki response_model; düşünme seviyesi doğrulanamıyor"
            return

        if ad == "codex":
            k = codex_kaydini_oku(klasor, sonuc.oturum_kimligi)
            if k is not None:
                sonuc.kota = k.get("kota") or {}
            if k is None or not k["istemci_modeller"]:
                sonuc.model_dogrulama = DOGRULAMA_YOK
                sonuc.dogrulama_notu = "Codex oturum kaydı bulunamadı ya da turn_context yok"
                return
            farkli = sorted({m for m in k["istemci_modeller"] if m != istenen})
            if farkli:
                _uyusmazlik(sonuc, f"istenen {istenen}, Codex'in gönderdiği {', '.join(farkli)}")
                return
            # gercek_model bilerek boş bırakılır: turn_context.model sunucunun kullandığı modeli göstermez.
            sonuc.model_dogrulama = DOGRULAMA_ISTEMCI
            sonuc.dogrulama_notu = "Codex oturum kaydındaki turn_context.model; sunucu tarafı doğrulanamıyor"
            return
    except Exception:
        sonuc.model_dogrulama = DOGRULAMA_YOK
        sonuc.dogrulama_notu = "doğrulama sırasında beklenmeyen hata"


def _uyusmazlik(sonuc: CagriSonucu, ayrinti: str) -> None:
    sonuc.durum = "error"
    sonuc.hata = f"{MODEL_UYUSMAZLIGI}: {ayrinti}"
    sonuc.metin = ""  # uyuşmayan modelin cevabı konseyde kullanılmaz
    sonuc.model_dogrulama = ""
    sonuc.dogrulama_notu = ""


# --------------------------------------------------------------------------- araç denetimi


def agy_kancasini_hazirla(calisma_klasoru: str) -> tuple[bool, str]:
    """Çalışma klasörüne salt okunur kancasını (.agents/hooks.json) yazar ve içeriğini doğrular.
    Dosya zaten doğruysa dokunmaz. Doğrulanamazsa (False, neden) döner; o zaman agy çağrılmamalıdır."""
    try:
        yol = Path(calisma_klasoru).expanduser() / ".agents" / "hooks.json"
        try:
            if yol.is_file() and yol.read_text(encoding="utf-8") == AGY_HOOK_JSON:
                return True, "kanca yerinde"
        except OSError:
            pass
        yol.parent.mkdir(parents=True, exist_ok=True)
        gecici = yol.with_name(f".hooks.json.{os.getpid()}.tmp")
        gecici.write_text(AGY_HOOK_JSON, encoding="utf-8")
        os.replace(gecici, yol)
        if yol.read_text(encoding="utf-8") != AGY_HOOK_JSON:
            return False, "kanca dosyası yazıldı ama içeriği doğrulanamadı"
        return True, "kanca yazıldı"
    except Exception as e:
        return False, f"kanca dosyası yazılamadı: {e}"


def agy_transcript_denetle(beyin_dizini: str, kimlik: str) -> dict | None:
    """agy transcript'inde araç kullanımını sayar. Okunamazsa None.

    Kural (kanarya testleri, 19 Kasım 2026): PLANNER_RESPONSE adımlarındaki tool_calls = denenen araçlar;
    USER_INPUT ve PLANNER_RESPONSE dışındaki adımlar araç adımıdır: DONE = çalıştı, ERROR = reddedildi/başarısız.
    Bilinmeyen adım türleri de DONE ise çalışmış sayılır (güvenli yönde hata). DONE ve ERROR dışındaki
    (ya da durumsuz) araç adımı da ihlaldir: AGY_BELIRSIZ_ADIM önekiyle `calisan` listesine girer (karar 40)."""
    try:
        if not kimlik or not KIMLIK_KALIBI.match(kimlik):
            return None
        yol = (Path(beyin_dizini).expanduser() / kimlik / ".system_generated" / "logs" / "transcript_full.jsonl")
        if not yol.is_file():
            return None
        denenen, calisan, reddedilen, okunan = [], [], 0, 0
        with open(yol, encoding="utf-8", errors="replace") as f:
            for satir in f:
                try:
                    d = json.loads(satir)
                except json.JSONDecodeError:
                    continue  # yarım satır
                if not isinstance(d, dict):
                    continue
                okunan += 1
                tur, durum = str(d.get("type", "")), str(d.get("status", ""))
                if tur == "PLANNER_RESPONSE":
                    for c in d.get("tool_calls") or []:
                        if isinstance(c, dict):
                            denenen.append(str(c.get("name", "?")))
                elif tur != "USER_INPUT":
                    if durum == "DONE":
                        calisan.append(f"{tur}: {str(d.get('content', ''))[:120]}")
                    elif durum == "ERROR":
                        reddedilen += 1
                    else:  # çalışıyor/bekliyor/durum yok: ne olduğu bilinmeyen araç adımı (karar 40) -> ihlal
                        calisan.append(f"{AGY_BELIRSIZ_ADIM} {tur or '?'} durum={durum or '?'}")
        if okunan == 0:
            return None
        return {"denenen": denenen, "reddedilen": reddedilen, "calisan": calisan}
    except Exception:
        return None


def agy_araclarini_denetle(s: dict, sonuc: CagriSonucu) -> None:
    """agy çağrısından sonra araç kullanımını denetler. Çalışmış bir araç varsa başarılı çağrıyı hataya çevirir."""
    try:
        k = agy_transcript_denetle(s.get("beyin_dizini") or varsayilan_agy_beyin_dizini(s), sonuc.oturum_kimligi)
        if k is None:
            sonuc.arac_denetimi = DENETIM_YOK
            return
        sonuc.arac_ozeti = k
        if k["calisan"]:
            sonuc.arac_denetimi = DENETIM_IHLAL
            if sonuc.basarili:
                sonuc.durum = "error"
                sonuc.hata = (f"{ARAC_IHLALI}: agy salt okunur olması gereken konsey çağrısında araç çalıştırdı "
                              f"({len(k['calisan'])} adım"
                              + (f", {sum(x.startswith(AGY_BELIRSIZ_ADIM) for x in k['calisan'])} tanesi "
                                 "DONE/ERROR dışı durumda" if any(x.startswith(AGY_BELIRSIZ_ADIM) for x in k['calisan']) else "")
                              + "); cevap kullanılmadı")
                sonuc.metin = ""
                sonuc.model_dogrulama = ""
                sonuc.dogrulama_notu = ""
        else:
            sonuc.arac_denetimi = DENETIM_TEMIZ
    except Exception:
        sonuc.arac_denetimi = DENETIM_YOK


# --- Codex denetimi: izin listesi (karar 37). Gerçek kayıtlardan (kayitlar/, 49 çağrı) çıkarıldı; gereğinden geniş değil.
# Listede olmayan HER olay türü, adı bilinmese de, araç kullanımı sayılır ve çağrıyı hata yapar.
CODEX_BEKLENEN_UST = frozenset({"session_meta", "turn_context", "world_state", "token_usage_record"})
CODEX_BEKLENEN_OLAY_MSG = frozenset({"task_started", "task_complete", "thread_settings_applied", "token_count"})
CODEX_BEKLENEN_YANIT = frozenset({"additional_tools", "reasoning"})  # + "message" (rol denetimiyle)
CODEX_BEKLENEN_ROLLER = frozenset({"developer", "user", "assistant"})
CODEX_BEKLENEN_OGE = frozenset({"UserMessage", "AgentMessage", "Reasoning"})  # event_msg/item_completed içindeki öğe
# --json akışı
CODEX_BEKLENEN_AKIS = frozenset({"thread.started", "turn.started", "turn.completed", "turn.failed", "error"})
CODEX_AKIS_OGE_OLAYLARI = frozenset({"item.started", "item.updated", "item.completed"})
CODEX_BEKLENEN_AKIS_OGE = frozenset({"agent_message", "reasoning", "error"})  # reasoning: bkz. adaptor.md 6.2
# Bilinen araç olayları: sayılır ve raporlanır (karar 27). CODEX_BILINEN_ARAC_HATA=True yapılırsa hata olur.
CODEX_ARAC_YANITLARI = frozenset({"function_call", "custom_tool_call", "local_shell_call",
                                  "function_call_output", "custom_tool_call_output", "local_shell_call_output"})
CODEX_ARAC_OGELERI = frozenset({"CommandExecution"})
CODEX_ARAC_AKIS_OGELERI = frozenset({"command_execution", "mcp_tool_call", "file_change"})
CODEX_WEB_TURLERI = frozenset({"web_search_call", "web_search", "web_search_end"})
CODEX_WEB_OGELERI = frozenset({"web_search", "websearch"})
CODEX_BILINEN_ARAC_HATA = True
CODEX_BILINMEYEN_OLAY = "CODEX BİLİNMEYEN OLAY TÜRÜ"  # hata metni öneki
CODEX_ARAC_KULLANIMI = "CODEX ARAÇ KULLANIMI"           # hata metni öneki
# Claude denetimi (karar 39): init olayındaki araç ve MCP listesi bu izin listesinden farklıysa çağrı hata.
CLAUDE_BEKLENEN_ARACLAR = frozenset()
CLAUDE_BEKLENEN_MCP = frozenset()
# True: init olayı olmayan Claude çıktısı hata (araç/MCP listesi doğrulanamaz; kapalı-başarısız). v0.18'den beri True.
CLAUDE_INIT_ZORUNLU = True
# init.apiKeySource: gerçek çıktıda abonelik girişi için "none" (kurulu ikilide diğer kaynaklar: "ANTHROPIC_API_KEY",
# "apiKeyHelper", "/login managed key" = API faturalama). Yalnızca "none" kabul edilir (karar 48).
CLAUDE_BEKLENEN_KIMLIK_KAYNAGI = "none"
CLAUDE_YUZEYI = "CLAUDE ARAÇ YÜZEYİ"                    # hata metni öneki
CLAUDE_ARAC_BLOKLARI = frozenset({"tool_use", "server_tool_use", "mcp_tool_use"})


def codex_olay_sinifla(d: dict) -> tuple[str, str]:
    """Oturum kaydındaki tek satırı sınıflar: ('beklenen'|'arac'|'web'|'bilinmeyen', ad)."""
    ust = d.get("type")
    yuk = d.get("payload") if isinstance(d.get("payload"), dict) else {}
    pt = yuk.get("type")
    if ust in CODEX_BEKLENEN_UST:
        return "beklenen", str(ust)
    if ust == "event_msg":
        if pt in CODEX_BEKLENEN_OLAY_MSG:
            return "beklenen", f"event_msg/{pt}"
        if pt == "item_completed":
            it = yuk.get("item")
            ot = it.get("type") if isinstance(it, dict) else None
            if ot in CODEX_BEKLENEN_OGE:
                return "beklenen", f"event_msg/item_completed:{ot}"
            if ot in CODEX_ARAC_OGELERI:
                return "arac", f"event_msg/item_completed:{ot}"
            if str(ot).lower() in CODEX_WEB_OGELERI:
                return "web", f"event_msg/item_completed:{ot}"
            return "bilinmeyen", f"event_msg/item_completed:{ot}"
        if pt in CODEX_WEB_TURLERI:
            return "web", f"event_msg/{pt}"
        return "bilinmeyen", f"event_msg/{pt}"
    if ust == "response_item":
        if pt in CODEX_BEKLENEN_YANIT:
            return "beklenen", f"response_item/{pt}"
        if pt == "message":
            rol = yuk.get("role")
            if rol in CODEX_BEKLENEN_ROLLER:
                return "beklenen", f"response_item/message:{rol}"
            return "bilinmeyen", f"response_item/message:{rol}"
        if pt in CODEX_ARAC_YANITLARI:
            return "arac", f"response_item/{pt}"
        if pt in CODEX_WEB_TURLERI:
            return "web", f"response_item/{pt}"
        return "bilinmeyen", f"response_item/{pt}"
    return "bilinmeyen", f"{ust}" + (f"/{pt}" if pt else "")


def codex_akis_sinifla(e: dict) -> tuple[str, str]:
    """--json akışındaki tek olayı sınıflar (oturum kaydından bağımsız ikinci kaynak)."""
    t = e.get("type")
    if t in CODEX_BEKLENEN_AKIS:
        return "beklenen", f"akış:{t}"
    if t in CODEX_AKIS_OGE_OLAYLARI:
        it = e.get("item")
        ot = it.get("type") if isinstance(it, dict) else None
        if ot in CODEX_BEKLENEN_AKIS_OGE:
            return "beklenen", f"akış:{t}:{ot}"
        if ot in CODEX_ARAC_AKIS_OGELERI:
            return "arac", f"akış:{t}:{ot}"
        if str(ot).lower() in CODEX_WEB_OGELERI:
            return "web", f"akış:{t}:{ot}"
        return "bilinmeyen", f"akış:{t}:{ot}"
    return "bilinmeyen", f"akış:{t}"


def _web_olayi_ozeti(girdi) -> str:
    return (girdi if isinstance(girdi, str) else json.dumps(girdi, ensure_ascii=False))[:200]


def codex_akisini_say(cikti: str) -> dict:
    """--json akışını sınıflar: web aramaları, bilinen araç öğeleri ve bilinmeyen olay türleri (ad -> sayı).
    Araç öğeleri (komut, MCP çağrısı, dosya değişikliği) oturum kaydından bağımsız ikinci kaynaktır."""
    web: dict = {}  # öğe kimliği -> özet; aynı arama started ve completed olarak iki kez gelir
    bilinmeyen: dict = {}
    arac: dict = {}
    for satir in (cikti or "").splitlines():
        satir = satir.strip()
        if not satir.startswith("{"):
            continue
        try:
            e = json.loads(satir)
        except json.JSONDecodeError:
            continue
        if not isinstance(e, dict):
            continue
        sinif, ad = codex_akis_sinifla(e)
        if sinif == "bilinmeyen":
            bilinmeyen[ad] = bilinmeyen.get(ad, 0) + 1
        elif sinif == "arac":
            if e.get("type") != "item.started":  # aynı öğe started ve completed olarak iki kez gelir
                arac[ad] = arac.get(ad, 0) + 1
        elif sinif == "web":
            it = e.get("item") if isinstance(e.get("item"), dict) else {}
            ozet = _web_olayi_ozeti(it.get("action") or it.get("query") or it)
            anahtar = it.get("id") or f"_{len(web)}"
            if anahtar not in web or it.get("query"):  # completed olayı ayrıntıyı taşır
                web[anahtar] = ozet
    return {"web": list(web.values()), "bilinmeyen": bilinmeyen, "arac": arac}


def codex_komutlarini_say(klasor: str, kimlik: str) -> dict | None:
    """Codex oturum kaydındaki her satırı sınıflar. Okunamazsa None.
    Dönen sözlük: araç çağrıları, kayıtlı komutlar, web aramaları, bilinmeyen olay türleri (ad -> sayı).
    Not: --json akışı ve CommandExecution olayları eksik olabilir (kanarya testinde bir yazma denemesi yalnızca
    custom_tool_call girdisinde görünüyordu); bu yüzden araç çağrıları ayrıca sayılır."""
    try:
        yol = codex_kaydini_bul(klasor, kimlik)
        if yol is None:
            return None
        cagrilar, komutlar, web, bilinmeyen = [], [], [], {}
        with open(yol, encoding="utf-8", errors="replace") as f:
            for satir in f:
                try:
                    d = json.loads(satir)
                except json.JSONDecodeError:
                    continue
                if not isinstance(d, dict):
                    continue
                yuk = d.get("payload") if isinstance(d.get("payload"), dict) else {}
                pt = yuk.get("type")
                sinif, ad = codex_olay_sinifla(d)
                if sinif == "bilinmeyen":
                    bilinmeyen[ad] = bilinmeyen.get(ad, 0) + 1
                elif sinif == "web":
                    web.append(_web_olayi_ozeti(yuk.get("action") or (yuk.get("item") or {}).get("action") or yuk))
                elif sinif == "arac":
                    if pt in ("function_call", "custom_tool_call", "local_shell_call"):
                        girdi = yuk.get("input") or yuk.get("arguments") or yuk.get("action") or ""
                        cagrilar.append({"arac": str(yuk.get("name") or pt),
                                         "girdi": (girdi if isinstance(girdi, str) else json.dumps(girdi))[:200]})
                    elif pt == "item_completed" and isinstance(yuk.get("item"), dict):
                        it = yuk["item"]
                        komut = it.get("command")
                        if isinstance(komut, list):
                            komut = komut[-1] if len(komut) >= 3 and komut[-2] == "-c" else " ".join(map(str, komut))
                        komutlar.append({"komut": str(komut)[:200], "cikis": it.get("exit_code")})
        return {"arac_cagrisi": cagrilar, "komutlar": komutlar, "web_aramalari": web,
                "bilinmeyen_olaylar": bilinmeyen}
    except Exception:
        return None


def codex_araclarini_denetle(s: dict, sonuc: CagriSonucu, cikti: str = "") -> None:
    """Codex çağrısını izin listesine göre denetler (karar 36–38, 41).
    - Web araması (web_search / web_search_call): HATA; yerleşik web araması sandbox'tan bağımsızdır.
    - Listede olmayan her olay türü: HATA (adı raporda görünür); cevap kullanılmaz.
    - Bilinen araç olayları (komut, exec...): sayılıp raporlanır; CODEX_BILINEN_ARAC_HATA=True ise hata.
    İki kaynak taranır: --json akışı ve oturum kaydı; biri okunamazsa diğeri yeter."""
    try:
        k = codex_komutlarini_say(s.get("kayit_dizini") or VARSAYILAN_KAYIT_DIZINI["codex"], sonuc.oturum_kimligi)
        akis = codex_akisini_say(cikti)
        if k is None:
            sonuc.arac_denetimi = DENETIM_YOK
            if not akis["web"] and not akis["bilinmeyen"] and not (CODEX_BILINEN_ARAC_HATA and akis["arac"]):
                return
            k = {"arac_cagrisi": [], "komutlar": [], "web_aramalari": [], "bilinmeyen_olaylar": {}}
        sonuc.arac_denetimi = DENETIM_GORULDU
        k.setdefault("web_aramalari", [])
        k.setdefault("bilinmeyen_olaylar", {})
        if akis["arac"]:
            k["akis_arac_olaylari"] = dict(akis["arac"])
        for w in akis["web"]:
            if w not in k["web_aramalari"]:
                k["web_aramalari"].append(w)
        for ad, n in akis["bilinmeyen"].items():
            k["bilinmeyen_olaylar"][ad] = max(k["bilinmeyen_olaylar"].get(ad, 0), n)
        sonuc.arac_ozeti = k
        if k["web_aramalari"]:
            sonuc.arac_denetimi = DENETIM_IHLAL
            sonuc.durum = "error"
            sonuc.metin = ""
            sonuc.hata = (f"{CODEX_WEB_ERISIMI}: {len(k['web_aramalari'])} web arama olayı "
                          f"({k['web_aramalari'][0]}); cevap kullanılmadı")
        elif k["bilinmeyen_olaylar"]:
            adlar = ", ".join(f"{a} ×{n}" for a, n in sorted(k["bilinmeyen_olaylar"].items()))
            sonuc.arac_denetimi = DENETIM_IHLAL
            sonuc.durum = "error"
            sonuc.metin = ""
            sonuc.hata = (f"{CODEX_BILINMEYEN_OLAY}: {adlar}; izin listesinde olmayan olay araç kullanımı "
                          "sayıldı; cevap kullanılmadı")
        elif CODEX_BILINEN_ARAC_HATA and (k["arac_cagrisi"] or k["komutlar"] or akis["arac"]):
            sonuc.arac_denetimi = DENETIM_IHLAL
            sonuc.durum = "error"
            sonuc.metin = ""
            sonuc.hata = (f"{CODEX_ARAC_KULLANIMI}: {len(k['arac_cagrisi'])} araç çağrısı, "
                          f"{len(k['komutlar'])} komut, akışta {sum(akis['arac'].values())} araç öğesi; "
                          "komut ve bağlayıcılar kapalı olmalıydı; cevap kullanılmadı")
    except Exception:
        sonuc.arac_denetimi = DENETIM_YOK


def _claude_ad_listesi(liste) -> set[str] | None:
    if not isinstance(liste, list):
        return None
    return {str(x.get("name", "?")) if isinstance(x, dict) else str(x) for x in liste}


def claude_yuzeyini_denetle(out: str, sonuc: CagriSonucu) -> None:
    """Claude çağrısının araç yüzeyini ham çıktıdan doğrular (karar 39). Sabit "araçlar kapalı" yazmaz.
    Kontroller: init olayında araç ve MCP listesi izin listesinde mi; sonuçta num_turns == 1, permission_denials
    boş, sunucu tarafı web arama/getirme sayaçları sıfır; asistan olaylarında araç bloğu yok.
    init olayı varsa eksik alan da ihlaldir (kapalı-başarısız); CLAUDE_INIT_ZORUNLU açıkken init olayı yoksa da.
    Başarılı sonuç etiketi `araçlar kapalı` (DENETIM_KAPALI) bu kontrollerden geçildiği anlamına gelir."""
    try:
        olaylar = claude_olaylari(out)
        init = next((e for e in olaylar if e.get("type") == "system" and e.get("subtype") == "init"), None)
        sonuc_olayi = next((e for e in reversed(olaylar) if e.get("type") == "result"), None)
        siki = init is not None or CLAUDE_INIT_ZORUNLU
        ihlaller: list[str] = []
        ozet: dict = {"akis": init is not None}

        if init is None:
            if CLAUDE_INIT_ZORUNLU:
                ihlaller.append("init olayı yok (araç ve MCP listesi doğrulanamadı)")
        else:
            kaynak = init.get("apiKeySource")
            ozet["apiKeySource"] = kaynak
            if kaynak is None:
                ihlaller.append("init.apiKeySource yok (kimlik kaynağı doğrulanamadı)")
            elif kaynak != CLAUDE_BEKLENEN_KIMLIK_KAYNAGI:
                ihlaller.append(f"apiKeySource={kaynak!r}: abonelik girişi ({CLAUDE_BEKLENEN_KIMLIK_KAYNAGI!r}) "
                                "bekleniyordu, API anahtarı/faturalama olabilir")
            for alan, beklenen, etiket in (("tools", CLAUDE_BEKLENEN_ARACLAR, "araç"),
                                           ("mcp_servers", CLAUDE_BEKLENEN_MCP, "MCP sunucusu")):
                adlar = _claude_ad_listesi(init.get(alan))
                if adlar is None:
                    ihlaller.append(f"init.{alan} okunamadı")
                    continue
                ozet[alan] = sorted(adlar)
                fazla = sorted(adlar - beklenen)
                if fazla:
                    ihlaller.append(f"beklenmeyen {etiket}: {', '.join(fazla[:8])}" + (" …" if len(fazla) > 8 else ""))

        r = sonuc_olayi or {}
        if sonuc_olayi is None and siki:
            ihlaller.append("result olayı yok")

        def kontrol(alan: str, deger, uygun) -> None:
            if deger is None:
                if siki:
                    ihlaller.append(f"{alan} yok")
            elif not uygun(deger):
                ihlaller.append(f"{alan}={deger!r}")

        if sonuc_olayi is not None:
            kontrol("num_turns", r.get("num_turns"), lambda v: v == 1 and not isinstance(v, bool))
            kontrol("permission_denials", r.get("permission_denials"), lambda v: v == [])
            stu = (r.get("usage") or {}).get("server_tool_use") if isinstance(r.get("usage"), dict) else None
            kontrol("usage.server_tool_use", stu,
                    lambda v: isinstance(v, dict) and all(x == 0 for x in v.values())
                    and "web_search_requests" in v and "web_fetch_requests" in v)
            mu = r.get("modelUsage")
            kontrol("modelUsage", mu, lambda v: isinstance(v, dict) and bool(v))
            if isinstance(mu, dict):
                for model, m in mu.items():
                    if isinstance(m, dict):
                        kontrol(f"modelUsage.{model}.webSearchRequests", m.get("webSearchRequests"), lambda v: v == 0)
            ozet["num_turns"] = r.get("num_turns")

        blok = 0
        for e in olaylar:
            if e.get("type") == "assistant":
                icerik = (e.get("message") or {}).get("content") if isinstance(e.get("message"), dict) else None
                for b in icerik if isinstance(icerik, list) else []:
                    if isinstance(b, dict) and b.get("type") in CLAUDE_ARAC_BLOKLARI:
                        blok += 1
        if blok:
            ihlaller.append(f"asistan olaylarında {blok} araç bloğu")
        ozet["ihlaller"] = ihlaller
        sonuc.arac_ozeti = ozet
        if ihlaller:
            sonuc.arac_denetimi = DENETIM_IHLAL
            if sonuc.basarili:
                sonuc.durum = "error"
                sonuc.metin = ""
                sonuc.model_dogrulama = ""
                sonuc.dogrulama_notu = ""
                sonuc.hata = f"{CLAUDE_YUZEYI}: {'; '.join(ihlaller)}; cevap kullanılmadı"
        else:
            sonuc.arac_denetimi = DENETIM_KAPALI
    except Exception:
        sonuc.arac_denetimi = DENETIM_YOK


def arac_ozeti_metni(sonuc: CagriSonucu) -> str:
    """Tek bir çağrının araç denetimini insan okunur tek satıra çevirir."""
    d, o = sonuc.arac_denetimi, sonuc.arac_ozeti or {}
    if not d:
        return "denetlenmedi"
    if sonuc.saglayici == "claude" and d == DENETIM_IHLAL:
        return "ihlal: " + "; ".join(o.get("ihlaller") or ["?"])
    if d in (DENETIM_YOK, DENETIM_KAPALI):
        return d
    if sonuc.saglayici == "codex":
        n, km = len(o.get("arac_cagrisi", [])), o.get("komutlar", [])
        if o.get("web_aramalari"):
            return f"Codex web erişimi tespit edildi ({len(o['web_aramalari'])} web arama olayı)"
        if o.get("bilinmeyen_olaylar"):
            return "bilinmeyen olay türü: " + ", ".join(sorted(o["bilinmeyen_olaylar"]))
        if not n and not km:
            return "araç kullanmadı"
        liste = ", ".join(f"{x['komut']} (çıkış {x['cikis']})" for x in km[:3])
        return f"{n} araç çağrısı, {len(km)} kayıtlı komut" + (f": {liste}" if liste else "")
    metin = d
    if o.get("denenen"):
        metin += f" (denenen araç {len(o['denenen'])}, reddedilen {o.get('reddedilen', 0)}"
        metin += f", çalışan {len(o.get('calisan', []))})"
    return metin


def codex_kotasini_oku(s: dict, kimlik: str) -> dict:
    try:
        k = codex_kaydini_oku(s.get("kayit_dizini") or VARSAYILAN_KAYIT_DIZINI["codex"], kimlik)
        return (k or {}).get("kota") or {}
    except Exception:
        return {}


# --------------------------------------------------------------------------- ana çağrı


async def cagir(ad: str, s: dict, prompt: str, zaman_asimi: int, calisma_klasoru: str,
                kayit_yolu: str | Path | None = None) -> CagriSonucu:
    """Bir sağlayıcıyı bir kez çağırır. Hiçbir durumda istisna fırlatmaz; sonucu durum alanıyla bildirir."""
    t0 = time.monotonic()
    if len(prompt.encode("utf-8")) > MAKS_PROMPT_BAYT:
        return CagriSonucu(ad, "error", hata="Prompt çok uzun", istenen_model=s["model"])
    if not program_var_mi(s["komut"]):
        return CagriSonucu(ad, "error", hata=f"Program bulunamadı: {s['komut'][0]}", istenen_model=s["model"])
    if ad == "gemini":
        kanca_tamam, kanca_mesaji = agy_kancasini_hazirla(calisma_klasoru)
        if not kanca_tamam:  # salt okunurluk sağlanamıyorsa agy hiç çalıştırılmaz
            return CagriSonucu(ad, "error", hata=f"{KANCA_HATASI}: {kanca_mesaji}; agy çağrılmadı",
                               istenen_model=s["model"])
    if ad == "gemini" and s.get("home"):
        sorunlar = agy_yalitimini_dogrula(s, calisma_klasoru)
        if sorunlar:  # yalıtım sağlanamıyorsa agy gerçek HOME ile ASLA çalıştırılmaz (kapalı-başarısız)
            return CagriSonucu(ad, "error", istenen_model=s["model"],
                               hata=f"{AGY_YALITIM_HATASI}: {'; '.join(sorunlar)}; agy çağrılmadı. "
                                    "Çözüm: python3 araclar/agy_yalitim_kur.py")
    komut = komut_olustur(ad, s, prompt, zaman_asimi)
    # agy'nin kendi süre sınırının dolup temiz çıkmasına fırsat ver
    dis_sure = zaman_asimi + 15 if ad == "gemini" else zaman_asimi
    try:
        rc, out, err, zaman_doldu = await surec_calistir(komut, calisma_klasoru, dis_sure, saglayici_ortami(ad, s))
    except OSError as e:
        return CagriSonucu(ad, "error", hata=f"Program çalıştırılamadı: {e}", istenen_model=s["model"])

    if zaman_doldu:
        sonuc = CagriSonucu(ad, "timeout", hata=f"{dis_sure} saniyede cevap gelmedi; süreç grubu kapatıldı")
    else:
        sonuc = ciktiyi_coz(ad, rc, out, err)
        sonuc.oturum_kimligi = oturum_kimligi_bul(ad, out)
        if sonuc.basarili:
            modeli_dogrula(ad, s, sonuc)
        if ad == "codex" and sonuc.oturum_kimligi and not sonuc.kota:
            sonuc.kota = codex_kotasini_oku(s, sonuc.oturum_kimligi)  # kota hatasında da bilgi verir
        # Araç denetimi başarısız çağrılarda da yapılır (ör. araç denemesi yüzünden boş cevap)
        if ad == "gemini":
            agy_araclarini_denetle(s, sonuc)
        elif ad == "codex":
            codex_araclarini_denetle(s, sonuc, out)
        elif ad == "claude":
            claude_yuzeyini_denetle(out, sonuc)
    sonuc.istenen_model = s["model"]
    sonuc.sure_sn = round(time.monotonic() - t0, 1)

    if kayit_yolu:
        kayit_yolu = Path(kayit_yolu)
        kayit_yolu.parent.mkdir(parents=True, exist_ok=True)
        with open(kayit_yolu, "w", encoding="utf-8") as f:
            json.dump({"saglayici": ad, "komut": komut, "cikis_kodu": rc, "zaman_asimi": zaman_doldu,
                       "stdout": out, "stderr": err, "sonuc": sonuc.sozluk()}, f, ensure_ascii=False, indent=2)
        sonuc.ham_kayit = str(kayit_yolu)
    return sonuc


# --------------------------------------------------------------------------- ön kontroller


async def claude_giris_kontrol(s: dict, calisma_klasoru: str) -> tuple[bool, str]:
    """Claude'un API anahtarıyla değil, Claude aboneliğiyle giriş yaptığını doğrular."""
    if not program_var_mi(s["komut"]):
        return False, f"Program bulunamadı: {s['komut'][0]}"
    rc, out, err, zaman_doldu = await surec_calistir(s["komut"] + ["auth", "status"], calisma_klasoru, 30,
                                                     saglayici_ortami("claude", s))
    if zaman_doldu:
        return False, "'claude auth status' 30 saniyede cevap vermedi"
    d = _json_yukle(out)
    if not isinstance(d, dict):
        return False, f"'claude auth status' çıktısı okunamadı: {(err or out)[:300]}"
    if not d.get("loggedIn"):
        return False, "Claude'a giriş yapılmamış. Çözüm: claude auth login"
    if d.get("authMethod") != "claude.ai":
        return False, (f"Claude abonelikle değil '{d.get('authMethod')}' yöntemiyle giriş yapmış; "
                       "bu API'den ücretlendirme demek. Çözüm: claude auth login ile Claude hesabınla giriş yap.")
    return True, f"Claude girişi abonelikle ({d.get('subscriptionType', '?')})"


# --------------------------------------------------------------------------- agy yalıtımı (karar 44-45)
# Konseyin agy çağrıları kullanıcının genel agy yapılandırmasından (~/.gemini: settings.json, config/ mcp_config.json,
# plugins/, kurallar, projects/, geçmiş) yalıtılır: agy bütün yolları $HOME'dan türetir, resmi bir "kullanıcı ayarlarını
# yok say" bayrağı yoktur (guvenlik.md 9.6). Konsey agy'yi HOME=<home> (varsayılan ~/.konsey-agy) ile çalıştırır.
# Giriş bilgisi macOS Keychain'dedir ve Keychain arama listesi HOME'dan türer; yeniden giriş gerekmesin diye yalnızca
# <home>/Library/Keychains gerçek Keychains klasörüne sembolik bağlanır (hedefe asla yazılmaz/silinmez).
# agy settings.json'u kendisi yeniden yazar ve varsayılana eşit değerleri (useG1Credits=false) düşürür; bu yüzden dosyada
# `toolPermission` "strict" olmalı, `useG1Credits` yok ya da false olmalı (true olamaz). Asıl zorlama her çağrıda
# `--settings` ile yapılır (AGY_AYARLARI); dosya yedek katmandır.
AGY_YALITIM_AYARLARI = {"toolPermission": "strict", "useG1Credits": False}
KIMLIK_DOSYASI_KALIBI = re.compile(r"(cred|secret|token|oauth|keyring|passw|auth)", re.I)


def gercek_ev_dizini() -> Path:
    """Kullanıcının gerçek ev klasörü (HOME ortam değişkeni değiştirilmiş olsa bile)."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def gercek_gemini_dizini(s: dict | None = None) -> Path:
    return Path((s or {}).get("gercek_gemini_dizini") or gercek_ev_dizini() / ".gemini")


def _yalitim_home(s: dict) -> Path:
    return Path(s["home"]).expanduser()


def agy_yalitimini_dogrula(s: dict, calisma_klasoru: str) -> list[str]:
    """Yalıtılmış agy HOME'unun beklenen durumda olduğunu denetler; sorun listesi (boş = tamam). Hiçbir şeyi değiştirmez."""
    sorunlar: list[str] = []
    try:
        home = _yalitim_home(s)
        gercek = gercek_ev_dizini()
        if home.resolve() in (gercek.resolve(), Path("/").resolve()) or gercek_gemini_dizini(s).resolve() == (home / ".gemini").resolve():
            return [f"home gerçek ev klasörüyle aynı ya da gerçek ~/.gemini'ye işaret ediyor ({home})"]
        if not home.is_dir():
            return [f"{home} yok"]
        mod = home.stat().st_mode & 0o777
        if mod != 0o700:
            sorunlar.append(f"{home} izinleri {oct(mod)}, 0o700 olmalı")
        ayar_yolu = home / ".gemini" / "antigravity-cli" / "settings.json"
        try:
            ayar = json.loads(ayar_yolu.read_text(encoding="utf-8"))
            if ayar.get("toolPermission") != "strict":
                sorunlar.append(f"settings.json: toolPermission = {ayar.get('toolPermission')!r}, 'strict' olmalı")
            if ayar.get("useG1Credits", False) is not False:
                sorunlar.append(f"settings.json: useG1Credits = {ayar.get('useG1Credits')!r}, false (ya da yok) olmalı")
            if str(Path(calisma_klasoru).expanduser()) not in (ayar.get("trustedWorkspaces") or []):
                sorunlar.append("settings.json: çalışma klasörü trustedWorkspaces içinde değil")
        except (OSError, json.JSONDecodeError) as e:
            sorunlar.append(f"settings.json okunamadı: {e}")
        if sys.platform == "darwin":
            bag = home / "Library" / "Keychains"
            hedef = gercek / "Library" / "Keychains"
            if not bag.is_symlink():
                sorunlar.append("Library/Keychains sembolik bağ değil/yok (giriş bilgisine erişilemez)")
            elif Path(os.readlink(bag)) != hedef:
                sorunlar.append(f"Library/Keychains başka bir yere işaret ediyor: {os.readlink(bag)}")
            elif not hedef.is_dir():
                sorunlar.append("Library/Keychains hedefi yok")
    except Exception as e:
        sorunlar.append(f"doğrulama hatası: {e}")
    return sorunlar


def agy_yalitimini_kur(s: dict, calisma_klasoru: str) -> list[str]:
    """Yalıtılmış agy HOME'unu kurar (idempotent). Yapılanları döndürür; hata olursa AyarHatasi.
    Gerçek ~/.gemini'ye ve Keychains hedefine dokunmaz. settings.json'daki bilinmeyen anahtarlar korunur."""
    home = _yalitim_home(s)
    gercek = gercek_ev_dizini()
    if home.resolve() == gercek.resolve() or gercek_gemini_dizini(s).resolve() == (home / ".gemini").resolve():
        raise AyarHatasi(f"home gerçek ev klasörüyle çakışıyor: {home}")
    yapilan = []
    if not home.is_dir():
        home.mkdir(parents=True, exist_ok=True)
        yapilan.append(f"{home} oluşturuldu")
    if (home.stat().st_mode & 0o777) != 0o700:
        home.chmod(0o700)
        yapilan.append(f"{home} izinleri 0o700 yapıldı")
    ayar_yolu = home / ".gemini" / "antigravity-cli" / "settings.json"
    ayar_yolu.parent.mkdir(parents=True, exist_ok=True)
    yeni_dosya = not ayar_yolu.exists()
    if not yeni_dosya:
        try:
            ayar = json.loads(ayar_yolu.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise AyarHatasi(f"{ayar_yolu} okunamadı/bozuk, üzerine yazılmadı: {e}")
    else:
        ayar = {"useG1Credits": False}  # niyet görünür olsun; agy sonra varsayılana eşit değeri düşürebilir
    eski = json.dumps(ayar, sort_keys=True)
    ayar["toolPermission"] = "strict"
    if ayar.get("useG1Credits", False) is not False:
        ayar["useG1Credits"] = False
    guvenilen = list(ayar.get("trustedWorkspaces") or [])
    cal = str(Path(calisma_klasoru).expanduser())
    if cal not in guvenilen:
        guvenilen.append(cal)
    ayar["trustedWorkspaces"] = guvenilen
    if json.dumps(ayar, sort_keys=True) != eski or not ayar_yolu.exists():
        gecici = ayar_yolu.with_name(".settings.json.tmp")
        gecici.write_text(json.dumps(ayar, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(gecici, ayar_yolu)
        yapilan.append("settings.json yazıldı (strict, güvenilen çalışma klasörü; useG1Credits her çağrıda --settings ile)")
    if sys.platform == "darwin":
        hedef = gercek / "Library" / "Keychains"
        if not hedef.is_dir():
            raise AyarHatasi(f"{hedef} yok; giriş bilgisi (Keychain) bulunamıyor")
        bag = home / "Library" / "Keychains"
        bag.parent.mkdir(parents=True, exist_ok=True)
        if bag.is_symlink():
            if Path(os.readlink(bag)) != hedef:
                raise AyarHatasi(f"{bag} başka bir yere işaret ediyor ({os.readlink(bag)}); elle inceleyin")
        elif bag.exists():
            raise AyarHatasi(f"{bag} bir sembolik bağ değil; elle inceleyin")
        else:
            os.symlink(hedef, bag)
            yapilan.append(f"{bag} -> {hedef} sembolik bağı oluşturuldu")
    return yapilan


def dizin_ozeti(kok: str | Path, hash_alt_yollari: tuple[str, ...] = ("config", "antigravity-cli/settings.json")) -> dict:
    """Bir klasör ağacının {göreli yol: (mtime_ns, boyut, sha256 ya da '')} özeti. Sembolik bağlar izlenmez.
    Küçük yapılandırma dosyaları (config/, settings.json) ayrıca hash'lenir. Klasör yoksa {}."""
    kok = Path(kok)
    ozet: dict = {}
    if not kok.is_dir():
        return ozet
    for dizin, altlar, dosyalar in os.walk(kok, followlinks=False):
        for ad in list(altlar) + dosyalar:
            yol = Path(dizin) / ad
            try:
                st = yol.lstat()
            except OSError:
                continue
            gorece = str(yol.relative_to(kok))
            h = ""
            if (yol.is_file() and not yol.is_symlink() and st.st_size < 1_000_000
                    and any(gorece == a or gorece.startswith(a + "/") for a in hash_alt_yollari)):
                try:
                    h = hashlib.sha256(yol.read_bytes()).hexdigest()
                except OSError:
                    h = "okunamadı"
            ozet[gorece] = (st.st_mtime_ns, st.st_size, h)
    return ozet


def ozet_farki(once: dict, sonra: dict) -> dict:
    """İki dizin_ozeti arasındaki fark: yeni, silinen, degisen (yol listeleri)."""
    return {"yeni": sorted(set(sonra) - set(once)), "silinen": sorted(set(once) - set(sonra)),
            "degisen": sorted(k for k in set(once) & set(sonra) if once[k] != sonra[k])}


def agy_yalitim_sorunlari(gercek_fark: dict, iz_fark: dict) -> list[str]:
    """Konsey agy çağrısı sonrası: gerçek ~/.gemini'de hiçbir şey değişmemeli; yalıtılmış HOME'da log ve konuşma
    dosyası oluşmuş olmalı. Sorun listesi (boş = tamam)."""
    sorunlar = []
    for tur, ad in (("yeni", "yeni dosya"), ("degisen", "değişen dosya"), ("silinen", "silinen dosya")):
        if gercek_fark[tur]:
            sorunlar.append(f"gerçek ~/.gemini'de {ad}: {', '.join(gercek_fark[tur][:5])}"
                            + (f" (+{len(gercek_fark[tur]) - 5})" if len(gercek_fark[tur]) > 5 else ""))
    yeni = iz_fark["yeni"]  # yollar yalıtılmış HOME köküne göre (.gemini/antigravity-cli/...)
    if not any("antigravity-cli/log/" in y for y in yeni):
        sorunlar.append("yalıtılmış HOME'da yeni agy log dosyası oluşmadı (agy yalıtılmış HOME'u kullanmamış olabilir)")
    if not any("antigravity-cli/conversations/" in y or "antigravity-cli/brain/" in y for y in yeni):
        sorunlar.append("yalıtılmış HOME'da yeni konuşma dosyası oluşmadı")
    return sorunlar


def agy_kimlik_dosyalari(home: str | Path) -> list[str]:
    """Yalıtılmış HOME'da, adı kimlik bilgisi izlenimi veren dosyalar (Library/ ve agy'nin kendi builtin/ klasörü
    hariç). Beklenen: yok (giriş Keychain'de). Varsa agy girişi dosyaya yazmıştır: kullanıcıya uyarı."""
    home = Path(home)
    bulunan = []
    if not home.is_dir():
        return bulunan
    for dizin, altlar, dosyalar in os.walk(home, followlinks=False):
        gorece = Path(dizin).relative_to(home)
        if gorece.parts[:1] == ("Library",) or gorece.parts[:3] == (".gemini", "antigravity-cli", "builtin"):
            altlar[:] = []
            continue
        for ad in dosyalar:
            if KIMLIK_DOSYASI_KALIBI.search(ad):
                bulunan.append(str(gorece / ad))
    return sorted(bulunan)


def calisma_alani_sorunlari(calisma_klasoru: str | Path) -> list[str]:
    """Konsey çalışma klasörü (çalışma alanı katmanı, karar 45): yalnızca `.agents/hooks.json` (beklenen sabit kanca
    içeriğiyle) bulunmalı; klasör ve üstlerinde Git kökü olmamalı (agy yürüyüşü proje köküne kadar gider)."""
    cal = Path(calisma_klasoru).expanduser()
    sorunlar = []
    if not cal.is_dir():
        return [f"{cal} yok"]
    ust = sorted(x.name for x in cal.iterdir())
    if ust != [".agents"]:
        fazla = [x for x in ust if x != ".agents"]
        sorunlar.append(f"çalışma klasöründe beklenmeyen öğeler: {', '.join(fazla) or '(.agents yok)'}")
    ag = cal / ".agents"
    if ag.is_dir():
        icerik = sorted(x.name for x in ag.iterdir())
        if icerik != ["hooks.json"]:
            sorunlar.append(f".agents içinde hooks.json dışında öğeler: {', '.join(x for x in icerik if x != 'hooks.json') or '(hooks.json yok)'}")
        else:
            try:
                if (ag / "hooks.json").read_text(encoding="utf-8") != AGY_HOOK_JSON:
                    sorunlar.append(".agents/hooks.json beklenen kanca içeriğinden farklı")
            except OSError as e:
                sorunlar.append(f"hooks.json okunamadı: {e}")
    for d in [cal, *cal.resolve().parents]:
        if (d / ".git").exists():
            sorunlar.append(f"{d} içinde .git var (proje kökü olur; agy üst klasörleri tarar)")
            break
    return sorunlar


# agy hesap/eklenti yüzeyi (karar 43): konsey ayarlarında hiç MCP sunucusu ve eklenti kurulu olmamalı.
# Boş çıktının tam metni agy 1.5.x'ten (19 Kasım 2026); başka her çıktı "boş değil" sayılır (kapalı-başarısız).
AGY_YUZEY_KOMUTLARI = (
    ("agy mcp list", ("mcp", "list"), re.compile(r"^\s*no mcp servers configured\.?\s*$", re.I)),
    ("agy plugin list", ("plugin", "list"), re.compile(r"^\s*no plugins installed\.?\s*$", re.I)),
)
YUZEY_BOS, YUZEY_DOLU, YUZEY_YOKLANAMADI = "boş", "boş değil", "yoklanamadı"


def agy_gercek_mi(s: dict) -> bool:
    """Komutun programı agy mi? (Sahte CLI'larla yapılan testlerde yüzey yoklaması atlanır; duman testi bunu yazar.)"""
    try:
        return Path(os.path.expanduser(str(s["komut"][0]))).name == "agy"
    except Exception:
        return False


async def agy_yuzeyini_yokla(s: dict, calisma_klasoru: str, zaman_asimi: float = 30) -> list[dict]:
    """`agy mcp list` ve `agy plugin list` çalıştırır. Her biri için {komut, durum, cikti}:
    boş = tanınan "yok" mesajı; boş değil = başka her çıktı (bulunan gösterilir); yoklanamadı = çalışmadı,
    sıfırdan farklı çıkış, zaman aşımı. Giriş yapmaz, hiçbir şeyi değiştirmez (yalnızca listeler)."""
    sonuc = []
    for etiket, argumanlar, bos_kalibi in AGY_YUZEY_KOMUTLARI:
        try:
            rc, out, err, zaman_doldu = await surec_calistir(list(s["komut"]) + list(argumanlar),
                                                             calisma_klasoru, zaman_asimi,
                                                             saglayici_ortami("gemini", s))
        except OSError as e:
            sonuc.append({"komut": etiket, "durum": YUZEY_YOKLANAMADI, "cikti": f"çalıştırılamadı: {e}"})
            continue
        cikti = (out or "").strip() or (err or "").strip()
        if zaman_doldu:
            durum, cikti = YUZEY_YOKLANAMADI, f"{zaman_asimi:g} saniyede cevap gelmedi"
        elif rc != 0:
            durum = YUZEY_YOKLANAMADI
            cikti = f"çıkış kodu {rc}: {cikti}"[:800]
        elif bos_kalibi.match(cikti):
            durum = YUZEY_BOS
        else:
            durum, cikti = YUZEY_DOLU, cikti[:800]
        sonuc.append({"komut": etiket, "durum": durum, "cikti": cikti})
    return sonuc


async def surum_al(s: dict, calisma_klasoru: str, ad: str | None = None) -> str:
    if not program_var_mi(s["komut"]):
        return "bulunamadı"
    try:
        rc, out, err, zaman_doldu = await surec_calistir(s["komut"] + ["--version"], calisma_klasoru, 20,
                                                         saglayici_ortami(ad, s) if ad else None)
    except OSError:
        return "çalıştırılamadı"
    if zaman_doldu:
        return "cevap yok"
    satirlar = [x.strip() for x in (out or err).splitlines() if x.strip()]
    return satirlar[0] if satirlar else "bilinmiyor"
