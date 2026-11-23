# Konsey kullanım kılavuzu

Konsey, aynı soruyu Claude, GPT ve Gemini'ye sorar. Modeller birbirinin cevabını eleştirir, düzeltir, ortak bir metin yazılır ve üç model bu metne oy verir. Oyları kod sayar. Bu kılavuz bilgisayarda nasıl kullanılacağını anlatır.

## 1. Başlamadan önce

- Bilgisayar şarjda olsun. Bir soru 1–10 dakika sürer.
- Kapağı kapatma. Kapak kapanırsa bilgisayar uyur ve çağrılar kesilir.
- Komutu her zaman `caffeinate -i` ile başlat. Bu, komut sürerken bilgisayarın uyumasını engeller.
- İnternet açık kalsın. Wi-Fi'ı kapatma.
- Komutu depo klasöründe çalıştır. Kurulum için README'ye bak (`python3 araclar/kurulum.py`).
- İlk kez ya da uzun aradan sonra: `caffeinate -i python3 konsey.py --duman`. Bu, üç modele küçük bir soru sorar ve kurulumu denetler (yaklaşık 1 dakika).

## 2. Soru sorma

En basit kullanım:

```
caffeinate -i python3 konsey.py "Sorunuz burada?"
```

Uzun soruyu dosyadan ver: `caffeinate -i python3 konsey.py -f soru.md`.

Bütün seçenekler (`python3 konsey.py --help` ile doğrulandı):

| Seçenek | Ne yapar |
|---|---|
| `soru` | Sorunun metni (tırnak içinde). |
| `-f`, `--soru-dosyasi DOSYA` | Soruyu dosyadan okur. |
| `--kanit DOSYA` | Üç modele aynen verilecek kanıt paketi (kaynak metin). Modeller web'e çıkmaz; bu dosya tek dayanaktır. |
| `--baglam DOSYA` | Soran kişi hakkında bilgi (durumun, kısıtların). Her turda "SORAN KİŞİ HAKKINDA" başlığıyla gider. Kanıt sayılmaz, doğrulanmış kabul edilmez. |
| `--tur N` | En fazla eleştiri-düzeltme turu (1–3). Varsayılan 1. 2 tur süreyi ve kotayı yaklaşık iki katına çıkarır. |
| `--arastir` | İki araştırmacı (Gemini ve GPT) yalnızca soruyla web'de kaynak toplar. Paket konsey kanıtına eklenir. Yalnızca bu soru için, daha çok kota harcar. |
| `--arastir-onay` | `--arastir` gibi; ama toplanan paketi konseyden önce ekranda gösterir ve onay ister (gerçek terminal gerekir; `echo e |` ile onay verilemez). Onaylamadan önce paket özetine bak: "sınır benzeri metin etkisizleştirildi" yazıyorsa ya da bir araştırmacı başarısız olduysa onaylama. |
| `--erken-cikis-yok` | Sayısal sorularda Tur 0 erken çıkışını kapatır; soru tam konseyden geçer. Yalnızca kontrol içindir. |
| `--tolerans X` | Erken çıkış için üç sayının en çok ne kadar ayrılabileceği (varsayılan 0.01, yani %1). |
| `--ayrinti` | `ayrinti.md` içeriğini ekrana da basar. |
| `--duman` | Kurulum kontrolü (küçük soru, araç ve yalıtım denetimleri, GPT kotası). |
| `--duman-web` | Araştırmacının web'e ulaşıp ulaşmadığını sınar. |
| `--zaman-asimi SN` | Bir çağrının en uzun süresi (varsayılan 600 sn). |
| `--ayar DOSYA` | Ayar dosyası (varsayılan `modeller.json`). |
| `--tohum N` | Rastgele sıralama tohumu. Aynı koşuyu yeniden üretmek için. |

**[K#] atıfları:** `--arastir` ile ya da `--kanit` verdiğinde her madde sabit bir kimlik alır: K1, K2, … (pakette maddenin başında yazar; `--kanit` dosyan başlıklarına göre maddelere bölünür ve `KULLANICI_KANITI` etiketi taşır). Modeller, bir maddeye dayanan her olgusal iddianın sonuna kimliği köşeli parantezle yazar: `[K3]` ya da `[K3, K7]`. Atıfsız cümle, modelin kendi bilgisi ya da hesabıdır.

Sayısal soru yazarsan (tek sayı isteyen) son satırı şöyle iste: `SONUÇ: <sayı> <birim>`. Birimsiz sonuçta (oran, görev oranı) birim yerine `-`, `1`, `boyutsuz` ya da hiçbir şey yazılsa da hepsi aynı sayılır Cevapta birden çok `SONUÇ:` satırı varsa sonuncusu kullanılır; satır sayısı kayda yazılır.

## 3. Sonucu okuma

Ekranda kısa bir rapor çıkar; aynısı `kayitlar/<tarih>_<tohum>/rapor.md` dosyasındadır. Başlıkta sonuç durumu yazar:

| Durum | Anlamı |
|---|---|
| `OYBIRLIGI` | Üç model de ortak metni kabul etti. |
| `COGUNLUK` | En az ikisi kabul etti. Karşı görüş rapora yazılır. |
| `UZLASI_YOK` | Yeterli kabul yok. Taslak "ONAYLANMADI" etiketiyle gösterilir. |
| `TUR0_UZLASI` | Sayısal soruda üç cevap aynı çıktı; tartışma ve oy atlandı. Bu oybirliği değildir. |
| `YETERSIZ_KATILIM` | Ikiden az model cevap verebildi. |
| `ARASTIRMA_DURDU` | `--arastir` iki araştırmacıyla da başarısız oldu ya da onaylanmadı. |

Rapor bölümleri: **ÖZET** (2–4 cümle), **CEVAP** (gerekçeli tam cevap), **KALAN ANLAŞMAZLIKLAR** (yalnızca gerçek anlaşmazlıkta), **BELİRSİZLİKLER** (doğrulanamayan iddialar, varsayımlar), **Konsey notu** (oylar, tur sayısı, sentez yazarı, doğrulama durumu, kayıt klasörü).

- **Yazar dışı oylar:** Ortak metni bir model yazar. Onun oyu "kendi yazdığına oy" olduğu için ayrıca gösterilir: "Yazar dışı oylar: 2/2 KABUL". Asıl bağımsız onay budur.
- **Bu bir doğruluk garantisi değildir.** Üç modelin hemfikir olması cevabı doğru yapmaz; hepsi aynı hatayı yapabilir. Kanıt paketi verilmediyse "olgusal iddialar doğrulanmamış ortak kanaattir" notu çıkar.
- **GEÇERLİLİK SINIRLARI:** Her modelin Tur 0 cevabında "bu cevap hangi koşulda geçersiz olur" satırı bulunur Sentez bu sınırları kapsam bilgisi olarak kullanır; cevaptaki genel kurallar koşullarıyla yazılmalıdır. Rapor tek başına yetmiyorsa `tur0_<model>.json` dosyalarındaki ham cevaplara bak.
- **`ayrinti.md`:** her turun eleştirileri, düzeltmeye giden ve gitmeyen maddeler, karar sayıları (KABUL / KISMEN KABUL / RED / ÇÖZÜLEMEDİ), nötr hakem, oyların gerekçeleri, araç denetimi, çalışma bilgisi ve kota (önce/sonra).
- **[K#] atıfları ve iki kod bölümü:** Kanıt paketi ya da `--kanit` varken raporda iki bölüm çıkar; bunları model değil KOD yazar. **Kaynaklar:** nihai metinde atıf yapılan her K# için başlık, alan adı, URL, tarih ve etiketler; atıf yapılmayan maddeler listelenmez, yalnızca sayısı yazılır ("Pakette 30 madde vardı; 11'ine atıf yapıldı"). **Atıf denetimi (raporda tek satır özet; aşama × model × kimlik dökümü `ayrinti.md`'de):** (1) *uydurma atıf*: pakette olmayan bir kimlik; (2) *zayıf dayanak*: atıf yapılan madde YÖNLENDİRME_ADRESİ (gerçek alan adı bilinmiyor), BAŞLIK_ALINTISI, NİCEL_İDDİA_ALINTIDA_YOK (iddiadaki birimli ya da yüzdeli ölçüm sayısı alıntıda yok; parça numarası, yıl, oran ve soruda geçen sayılar sayılmaz) ya da video/sosyal kaynak etiketi taşıyor. TARİH_BUGÜN yalnızca bilgi etiketidir (erişim tarihi olabilir), zayıflık sayılmaz. Etiketler yalnızca bilgidir; madde silinmez. **Uydurma atıf uyarısı** (durum satırının altında "Nihai metinde pakette olmayan kaynak atfı var (K#)") görürsen o iddiaya güvenme; kaynağı kendin kontrol et. Zayıf dayanak her zaman yanlış demek değildir ama kaynağa kendin bakmanı ister. Bu denetim atıfın *var olduğunu* ve etiketlerini kontrol eder; atıfın içeriğin gerçekten desteklediğini doğrulamaz (bunu yalnızca oylamada üyeler kontrol eder). Orkestratör kaynaklara internet isteği atmaz.
- Diğer dosyalar: `telemetri.json` (süreler, kelime sayıları), `taslak.md` (ortak metnin kendisi), `kayit.json` (ham kayıt).

## 4. Hangi sorular için

- **İyi:** tek sayılı sayısal sorular. Cevaplar çoğunlukla Tur 0'da uzlaşır ve 1–4 dakikada biter. Konseyin tek modelden daha doğru olduğu ölçülmedi; bakımcının küçük test setleri modelleri birbirinden ayıramadı.
- **Orta:** açık uçlu tasarım ve karşılaştırma soruları. Çıkan metin uzun olur (1000–2000 kelime), 6–10 dakika sürer. Eleştiri turunda önemli bazı ayrıntılar elenebilir; uzun cevap istiyorsan önce Tur 0 dosyalarına bak.
- **Zayıf:** güncel olay, fiyat, mevzuat. Modeller çevrimdışıdır; `--arastir` ya da `--kanit` kullan ve sonucu yine kontrol et.
- Sorunun kendi başına anlaşılır olsun: tüm parametreleri ver.

## 5. Gizlilik

- Sorun, kanıt paketin ve bağlam dosyan üç şirketin (Anthropic, OpenAI, Google) sunucularına gider. Gizli bilgi, kişisel veri, şifre ya da başkasının özel yazısını verme.
- API anahtarı kullanılmaz; yalnızca üç aboneliğin resmi komut satırı araçları çalışır. Kimlik bilgileri başka yere çıkarılmaz.
- Kayıtlar bu bilgisayarda `kayitlar/` altında durur (Git'e girmez). İstemediğin kaydı klasörünü silerek sil.

## 6. Kota

OpenAI 5 saatlik penceresi çoğunlukla en dar olandır. Süre ve kota kullanımı soruya ve hesap planına göre değişir; README'deki gözlemler tek hesapta küçük örneklemdir.

- Kural önerisi: 5 saatlik kota %70'i geçtiyse yeni soru başlatma; sıfırlanmayı bekle. Sıfırlanma saati duman çıktısındaki "GPT kotası" satırında yazar.
- `--tur 2` süreyi ve kotayı yaklaşık ikiye katlar; `--arastir` daha da artırır.
- Claude ve Gemini kotası konsey raporunun `ayrinti.md` dosyasında "Kota: çalıştırmadan önce ve sonra" bölümündedir.

## 7. Bir sorun çıkarsa

- **Kota hatası** ("rate_limited … try again at 7:25 PM"): GPT kotası bitti. O koltuğun cevabı eksik sayılır; konsey iki modelle devam edebilir (en az iki model gerekir). Saat geçtikten sonra soruyu yeniden sor.
- **Duman testi ✗ verirse** (araç denetimi, yalıtım ya da koltuk kontrolü): soru sorma; çıktının tamamını sakla ve nedenini araştır. Güvenlik denetimlerini kapatma.
- **"YALITIM DENETİMİ BAŞARISIZ":** sonuçları kullanma.
- **Çıkış kodu 2 / ÖN KONTROL BAŞARISIZ:** genellikle Claude girişi ya da ayar. `claude auth status` ile girişi kontrol et.
- **Süre doldu (zaman aşımı):** bir çağrı 600 sn'den uzun sürdü. Soruyu bölmeyi dene.
- **Sonuç satırı okunamadı:** sayısal soruda son `SONUÇ:` satırı sayı içermiyorsa ya da birim beklenenden farklıysa (ör. `mV` yerine `V`) o cevap "sonuç yok" sayılır ve erken çıkış olmaz. Cevap yine de `tur0_<model>.json` dosyalarında okunabilir.

## 8. Bilgisayarı ya da interneti kapatmadan önce

- Çalışan bir soru olmadığından emin ol (terminalde komut sürmesin, `pgrep -f konsey.py` boş dönsün).
- Soru sürerken kapatırsan o soru yarım kalır ve kota boşuna harcanır; yeniden sorman gerekir.
- Uyku için `caffeinate` yeterli değildir; kapak kapanırsa yine uyur.

## 9. Günün sonunda

1. Önemli bir kayıt klasörünü başka yere kopyala: `kayitlar/` bir yedeklemeye bağlı değildir.
2. İsteğe bağlı: `python3 konsey.py --duman` ile ertesi güne hazır olduğunu kontrol et.
3. Konsey arka planda hiçbir şey çalıştırmaz; kota harcamak istemiyorsan başka bir şey yapma.
