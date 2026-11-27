# Telegram botu için Cloudflare Workers ve GitHub Actions

GitHub Actions her gün Türkiye saatiyle 19:31 için planlanır. Python görevi fiyat,
finansal tablo ve haberleri toplar. Taramadan çıkan metinleri Cloudflare Worker'a
aktarır. Telegram komutları hazır metinlerden yanıtlanır.

Fiyat taramasının süresi 12 dakika, finansal güncellemenin süresi yaklaşık
4 dakika ile sınırlandırılır. GitHub işi toplam 30 dakikadan uzun çalışmaz.
İlk çalıştırmada veri sıfırdan birikir. GitHub önbelleğindeki ayrı piyasa SQLite
dosyası sonraki çalıştırmaları hızlandırır. Önceki VDS veritabanı, Telegram
sohbetleri, kişisel portföy ve yerel `.env` bu aktarıma dahil edilmez.
Önbellek silinirse tarama veriyi kaynaklardan yeniden toplar.

## İlk yayın

1. Kodu özel bir GitHub deposunun varsayılan dalına yükle. Workflow dosyası
   `.github/workflows/public-telegram.yml` altında olmalı.
2. Cloudflare hesabında Workers Free kullan. Bu hesaba kapsamlanmış Workers
   dağıtım API anahtarını ve hesap kimliğini hazırla.
3. GitHub deposunda **Settings → Secrets and variables → Actions** altında
   `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `TELEGRAM_WEBHOOK_SECRET`,
   `TELEGRAM_CHAT_ID` ve `TELEGRAM_BOT_TOKEN` secret'larını ekle. Bot tokeni
   halka açık bot için BotFather'dan alınmalı. Webhook sırrı rastgele ve en az
   32 karakter olmalı. Chat ID yalnızca yönetici paneline kimin gireceğini belirler.
4. **Actions → Public Telegram radar → Run workflow** ile ilk taramayı çalıştır.
   Hesapta `workers.dev` adresi yoksa `workers_subdomain` alanına istediğin adı
   gir. Hesabın mevcut `workers.dev` adresi varsa bu adım onu değiştirmez.
   Worker adresini dağıtım çıktısından al ve GitHub Actions değişkeni
   `PUBLIC_BOT_WORKER_URL` olarak ekle. Yalnızca `https://...workers.dev` kök
   adresini yaz.
5. Halka açık botun tokenini GitHub Actions secret'ı `TELEGRAM_BOT_TOKEN` olarak
   ekle. Workflow'u **Activate Telegram webhook** seçili olarak bir kez çalıştır.
   Çalışan eski botla paralel kullanım için BotFather'dan ayrı bot tokeni kullan.
6. Telegram'da `/komutlar`, `/sektor banka` ve yönetici hesabından `/yonetim`
   yanıtlarını kontrol et.

`/sektor` ana sektör menüsünü açar. KAP alt sektörleri 12 ana başlıkta
toplanır; şirketin özgün KAP sınıflaması finansal analizde korunur. Menüdeki
düğmeler, kısa adlar (`/sektor finans`) veya o menüdeki sıra numarası
kullanılabilir. `/sektör` yazımı da Worker tarafından kabul edilir. Finans
başlığı bankaları ve diğer finans kuruluşlarını kapsar; `/sektor banka`
aynı başlığı açar. Adaylar puana göre sıralanır, tüm uygun adaylar sayfalanır.
Puan başarı olasılığı değildir. Portföy seçimi farklı ana sektörleri gözetir.

Worker menülerinde sektör ve portföy isimleri mesaj içi düğmelerdir.
Düğmeler raporu aynı mesajda açar; önceki/sonraki sayfa ve menüye dönüş
düğmeleri de bulunur. Bu sürüme ilk geçişte **Activate Telegram webhook**
seçilmelidir; kayıt `message` yanında `callback_query` güncellemelerini de
açar. Bot tokeni, düğmeye basıldığını Telegram'a bildirmek için Worker'ın
şifreli secret bağlamasında tutulur; raporlara veya kaynak koduna yazılmaz.

Şirket özetlerindeki 12 aylık fiyat senaryoları, son 60 seansın düzeltilmiş
logaritmik getirilerinin standart sapmasının 252 seansa ölçeklenmesiyle
hesaplanır. Merkez son işlem fiyatıdır; alt/üst senaryo fiyatın
`exp(-yıllık oynaklık)` / `exp(yıllık oynaklık)` katıdır. Sıfır logaritmik
sürüklenme varsayılır. Bunlar eğitilmiş tahmin, temel değerleme, yıl içi
minimum/maksimum veya doğrulanmış olasılık aralığı değildir. Sabit, yetersiz,
geçersiz veya aşırı oynak fiyat geçmişinde hesaplama yapılmaz. Sonuçlar
sınırları aşabilir; düşük/yüksek seviyeler garanti edilmez.

Zamanlanmış çalıştırmalar raporları yeniler. Webhook kaydı yalnızca yönetici
manuel çalıştırmada aktivasyonu seçtiğinde yapılır. GitHub Actions ve Cloudflare
Workers kotaları hesapta kullanılan diğer projelerle birlikte değerlendirilir.
İlk kurulum beklerken **Scan only** seçeneğiyle veri çekimini, önbelleği ve
Worker raporlarının üretimini GitHub üzerinde ayrı olarak test edebilirsin.

## Yerel doğrulama

```sh
python -m unittest discover -s tests
node --test cloudflare/worker.test.mjs
```
