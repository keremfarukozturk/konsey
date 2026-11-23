# Konsey

Konsey, aynı soruyu Claude, GPT ve Gemini'ye resmi komut satırı araçlarıyla (kendi aboneliklerinizle, API anahtarı olmadan) sorar; modellere birbirinin cevabını kimliksiz eleştirtir, ortak bir cevap yazar ve her modele ayrı ayrı oy verdirir; oyları kod sayar.

English: [README.md](README.md)

## Nasıl çalışır

1. **Bağımsız cevaplar (Tur 0).** Soru üç modele ayrı ayrı gider. Her cevapta bir "GEÇERLİLİK SINIRLARI" alanı bulunur: cevabın hangi koşullarda yanlış olacağı.
2. **Kimliksiz eleştiri ve düzeltme.** Varsayılan bir tur (`--tur 1`, en çok 3). Her model diğer cevapları, yazarlarını bilmeden ve kendi cevabını görmeden eleştirir. Cevabın yazarı her maddeyi dayanağıyla kabul ya da reddeder. Hangi maddelerin düzeltmeye gideceğini kod süzer.
3. **Sentez.** Bir model düzeltilmiş cevaplardan ortak bir metin yazar. Sonuç üzerinde karar yetkisi yoktur.
4. **Ayrı onay.** Üç modelden her biri metni onaylar (KABUL) ya da somut itirazlarla reddeder (RET). Oyları model değil kod sayar.
5. **Rapor.** Sonuç oybirliği, çoğunluk ya da "uzlaşı yok" olarak raporlanır; metin, kalan anlaşmazlıklar, belirsizlikler ve her çağrının kaydı birlikte verilir. RET somut itirazla geldiyse metin bir kez düzeltilir ve ikinci kez oylanır.

Sayısal sorularda Tur 0'daki üç cevap bir toleransla uyuşursa tartışma atlanır (`TUR0_UZLASI`; bu oybirliği değildir).

Orkestratör sıradan bir Python programıdır: durum, zaman aşımı, oy sayımı ve güvenlik denetimleri kodla yapılır, modele rica edilmez.

## Gereksinimler

- macOS. Yalnızca macOS'ta geliştirildi ve denendi; agy yalıtım adımı macOS Keychains klasörünü bağlar, diğer platformlar denenmedi.
- Python 3. 3.13 ile denendi; 3.10 ve üstü beklenir ama doğrulanmadı. Yalnızca standart kütüphane kullanılır; `requirements.txt` yoktur.
- Üç resmi CLI; her biri abonelik hesabıyla (API anahtarıyla değil) giriş yapılmış olmalı:
  - `claude` (Anthropic'nin Claude komut satırı aracı)
  - `codex` (OpenAI Codex CLI)
  - `agy` (Google Antigravity CLI)

## Kurulum

```
git clone https://github.com/keremfarukozturk/konsey.git
cd konsey
python3 araclar/kurulum.py
```

`araclar/kurulum.py` idempotenttir ve var olan dosyaları ezmez. Python'u ve üç komutu denetler, oturum klasörünü (`~/konsey-oturum`) oluşturur, içine salt okunur agy kancasını (`.agents/hooks.json`) yazar ve `araclar/agy_yalitim_kur.py` ile yalıtılmış agy HOME klasörünü (`~/.konsey-agy`) kurar. Hiçbir şeyi değiştirmeden denetlemek için `--kontrol` kullanın.

Sonra:

1. `claude`, `codex` ve `agy` komutlarında birer kez giriş yapın.
2. `modeller.json` dosyasını düzenleyin. Dosyadaki model adları bakımcının koltuklarıdır; hesabınızın kullanabildiği modellerle değiştirin. Model adını her zaman tam yazın. Gemini koltuğu adı `gemini-` ile başlayan bir model olmalıdır. `agy` `~/.local/bin/agy` yolunda değilse `komut` alanına gerçek yolunu yazın.
3. İsteğe bağlı: başka konumlar için ortam değişkenlerini ayarlayın: `KONSEY_OTURUM` (oturum klasörü) ve `KONSEY_AGY_HOME` (yalıtılmış agy HOME'u). Oturum klasörü depo klasörünün dışında olmalıdır.

## İlk çalıştırma

```
caffeinate -i python3 konsey.py --duman
```

Duman testi her modele küçük bir soru sorar ve kurulumu denetler: araç yüzeyi, yalıtım, model kimliği ve okunabildiği yerde kota. Yaklaşık bir dakika sürer. Başarısızlık bildirirse, çözülene kadar gerçek soru sormayın.

## Örnek kullanım

```
caffeinate -i python3 konsey.py "Sorunuz burada?"
caffeinate -i python3 konsey.py -f soru.md
caffeinate -i python3 konsey.py --arastir "Güncel kaynak gerektiren bir soru?"
```

Bir soru yaklaşık 1–10 dakika sürer. Çalışırken bilgisayarı açık ve çevrimiçi tutun (`caffeinate -i` macOS'ta boşta uykuyu engeller).

Sayısal sorularda son satırı `SONUÇ: <sayı> <birim>` biçiminde isteyin; kod erken çıkış denetimi için bunu kullanır.

## Seçenekler

`python3 konsey.py --help` çıktısıyla doğrulanmıştır.

| Seçenek | Anlamı |
|---|---|
| `soru` | Sorunun metni. |
| `-f`, `--soru-dosyasi DOSYA` | Soruyu dosyadan okur. |
| `--kanit DOSYA` | Üç modele aynen verilen kanıt dosyası. Modeller çevrimdışıdır; tek dayanak budur. |
| `--baglam DOSYA` | Soran kişi hakkında bilgi. Her turda ayrı başlıkla gider; kanıt sayılmaz. |
| `--tur N` | En fazla eleştiri-düzeltme turu, 1–3 (varsayılan 1). Her ek tur süreyi ve kotayı artırır. |
| `--arastir` | İki araştırmacı (Gemini ve Codex) yalnızca soru metniyle web kaynağı toplar; paket kanıta eklenir. Daha çok kota harcar. |
| `--arastir-onay` | `--arastir` gibi; ama paketi önce gösterir ve onay ister (gerçek terminal gerekir). |
| `--erken-cikis-yok` | Sayısal sorularda Tur 0 erken çıkışını kapatır. |
| `--tolerans X` | Erken çıkış için üç sayısal sonucun en büyük göreli farkı (varsayılan 0.01). |
| `--ayrinti` | `ayrinti.md` içeriğini ekrana da basar. |
| `--duman` | Duman testi. |
| `--duman-web` | Araştırmacının web'e ulaşıp ulaşmadığını sınar. |
| `--zaman-asimi SN` | Çağrı başına süre sınırı, saniye (varsayılan `modeller.json`'dan, 600). |
| `--ayar DOSYA` | Ayar dosyası (varsayılan `modeller.json`). |
| `--tohum N` | Sıralama için rastgele tohum; koşuyu yeniden üretmek için. |

`--arastir` ya da `--kanit` ile her kanıt maddesi bir kimlik alır (K1, K2, …). Modeller maddelere `[K3]` biçiminde atıf yapar; kod atıfları denetler (olmayan kimlik, zayıf dayanak etiketleri) ve rapora "Kaynaklar" ile "Atıf denetimi" bölümlerini ekler. Denetim atıf yapılan maddenin var olduğunu ve etiketlerini gösterir; maddenin iddiayı desteklediğini doğrulamaz.

## Çıktılar

Her koşu `kayitlar/<tarih>_<tohum>/` klasörünü yazar (Git dışı). Ana dosyalar:

- `rapor.md`: rapor (ekrana da basılır). Durum, özet, cevap, kalan anlaşmazlıklar, belirsizlikler; oylar ve doğrulama durumunu içeren bir not.
- `ayrinti.md`: her eleştiri, düzeltmeye giden ve gitmeyen maddeler, karar sayıları, gerekçeli oylar, araç denetimi, çalışma bilgisi ve çalıştırmadan önce/sonra kota.
- `taslak.md`: ortak metin.
- `telemetri.json`: süreler ve kelime sayıları.
- `kayit.json` ve `tur0_<model>.json`: ham kayıtlar.

Sonuç durumları: `OYBIRLIGI` (üçü de onayladı), `COGUNLUK` (en az ikisi onayladı), `UZLASI_YOK` (yeterli onay yok; taslak onaylanmadı etiketiyle gösterilir), `TUR0_UZLASI` (sayısal erken çıkış), `YETERSIZ_KATILIM` (ikiden az model cevap verdi), `ARASTIRMA_DURDU` (araştırma başarısız oldu ya da onaylanmadı).

Kayıtlar sorularınızı ve model cevaplarını içerir. Bir koşu klasörünü paylaşmadan önce bunu aklınızda tutun.

## Kota notları

Pratik sınır kotadır; çoğunlukla en dar olan OpenAI 5 saatlik penceresidir. Bakımcının tek bir tüketici hesap kümesindeki koşularında: Tur 0'da uzlaşan sayısal soru yaklaşık 1–4 dakika; bir turlu açık uçlu soru yaklaşık 6–10 dakika sürdü ve 5 saatlik pencerenin yaklaşık %5–11'ini kullandı. Bunlar tek hesapta küçük örneklem gözlemidir, garanti değildir. `--tur 2` süreyi ve kotayı yaklaşık iki katına çıkarır, `--arastir` daha da artırır. Raporun `ayrinti.md` dosyası, CLI'ların gösterdiği yerde, her koşunun öncesi ve sonrası kotasını yazar. Bir modelin kotası biterse o koltuğun cevabı eksik kalır ve konsey iki modelle devam eder (en az iki model gerekir).

## Güvenlik modeli

- API anahtarı ve API kredisi yoktur. Yalnızca resmi CLI'lar, giriş yaptığınız hesaplarla çalışır. Çağrıyı API faturalandırmasına ya da başka bir hesaba yönlendirebilecek sağlayıcıya özel ortam değişkenleri alt süreçlerden silinir.
- Modeller araçsız çalışır: Claude'un araçları ve MCP kaynakları kapalıdır, Codex'in kabuğu, bağlayıcıları, eklentileri ve web araması kapalıdır, agy ayrı yalıtılmış bir HOME'da her araç çağrısını reddeden bir kancayla çalışır. Çağrılar depo dışındaki bir klasörden yapılır.
- Bu kurallar her çağrıdan sonra kodla denetlenir (araç listeleri, oturum kayıtları, izin ret kayıtları, API anahtarı kaynağı). İhlal çağrıyı hata yapar; prompt'a bırakılmaz.
- Araştırma paketi internetten gelen güvenilmeyen veridir. Sınırlar ve etiketler enjekte edilmiş talimat riskini azaltır, ortadan kaldırmaz.
- Orkestratör kendi başına hiçbir HTTP isteği atmaz.

## Bilinen sınırlar

- Oybirliği doğruluk değildir. Üç model aynı hatayı yapabilir. Ölçülmeyen: konseyin tek modelden daha doğru olup olmadığı. Bakımcının küçük test setlerinde konsey ve tek modeller aynı sonucu verdi; setler bunları ayırt edemedi.
- Atıf denetimi yukarıda anlatıldığı kadardır; bir kaynağın iddiayı destekleyip desteklemediğini yalnızca modellerin oyları kontrol eder.
- agy otomatik güncellemesi kapatılamadı; CLI sürümleri sessizce değişebilir. Duman testi ve sürüm kayıtları tek önlemdir.
- Uyma kontrollerinde kullanılan test setleri küçük ve kolaydı; dalkavukluk eğilimi tam ölçülmedi.
- Sayısal ayrıştırma `SONUÇ: <sayı> <birim>` ister; farklı birim ya da okunamayan satır "sonuç yok" sayılır ve erken çıkış yapılmaz.
- Kanıt paketi verilmeyen olgusal iddialar modellerin doğrulanmamış ortak kanaatidir.
- Yalnızca macOS'ta denendi. Ekip ya da çok kullanıcılı bir araç değildir.

## Kullanım şartları

Konsey, sağlayıcıların resmi komut satırı araçlarını sizin hesaplarınızla çalıştırır. Her sağlayıcının güncel kullanım şartlarına uymak kullanıcının sorumluluğundadır. Bazı sağlayıcılar tüketici aboneliklerinin otomatik ya da çok ajanlı kullanımını kısıtlayabilir (özellikle Google Antigravity CLI için şartları kontrol edin). Bu yazılım hiçbir sağlayıcıyla bağlantılı değildir ve onlar tarafından onaylanmamıştır.

## Lisans

Apache License 2.0. Bkz. [LICENSE](LICENSE).

## Testler

```
python3 araclar/testleri_calistir.py
```

Paket sahte CLI'lar kullanır; gerçek model çağrısı yapmaz. Bu betikle çalıştırın (geçici bir HOME kullanır ve bir test gerçek ev klasörüne yazmaya kalkarsa başarısız olur).
