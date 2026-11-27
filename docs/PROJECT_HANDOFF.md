# Claude için proje devri

Güncelleme tarihi: 28 Kasım 2026. Bu dosya mevcut kod ve tamamlanan kontrollerin
özetidir; bütün eski konuşmaların veya eski özel projenin aktarımı değildir.

## 1. Amaç ve kullanıcı beklentisi

Ücretsiz hizmetlerle ayakta kalan, herkese açık Türkçe BİST araştırma botu.
Finansal olarak iyi görünen şirketleri seçer; gerekçelerini, risklerini ve
karşılaştırma puanını sade maddelerle gösterir. Sektör ve portföy isimlerine
dokunulduğunda sonuç doğrudan açılmalıdır. Kullanıcı için okunabilirlik önemlidir.

Komutlar: `/komutlar`, `/sektor`, `/portfoy`, `/tara HISSE`, `/haber HISSE`;
`/start` menüyü açar. Yöneticiye özel `/yonetim` kullanıcı menüsünde görünmez.
Özel eski sürümün `/izle`, otomatik işlem takibi veya eğitim komutları bu
sürümde varmış gibi davranılmamalıdır.

## 2. Mimari ve dosya haritası

| Dosya | Görev |
| --- | --- |
| `src/bist_ai_radar/public_jobs.py` | Fiyat, şirket evreni, bilanço, KAP ve makro veri yenilemesi |
| `src/bist_ai_radar/public_research.py` | Uygunluk, finansal/teknik puanlama, ana sektörler ve okunaklı raporlar |
| `src/bist_ai_radar/public_worker_export.py` | Raporları ve menü dizinini Worker varlıklarına aktarma |
| `cloudflare/worker.mjs` | Telegram mesajları, inline düğmeler, sayfalar, yetki ve güncellik kontrolü |
| `src/bist_ai_radar/public_worker_register.py` | Token, canlı menüler, webhook ve düğme aboneliğini doğrulama |
| `.github/workflows/public-telegram.yml` | Günlük tarama, önbellek denetimi ve Cloudflare yayını |
| `.github/workflows/public-telegram-activate.yml` | Bağlantıyı ayrıca doğrulama/etkinleştirme |
| `.github/workflows/security.yml` | Dosya sınırları, tüm erişilebilir Git geçmişinde Gitleaks ve testler |
| `scripts/check_public_safety.py` | Özel dosya türleri ve olası gizli bilgi denetimi |
| `scripts/check_public_cache.py` | Önbelleğe kullanıcı kimliği/token karışmasını engelleme |

GitHub Actions, `31 16 * * *` ile günlük 19.31 Türkiye saati için planlıdır;
başlangıç gecikebilir. Fiyat toplama bütçesi 12 dakika, finansal toplama bütçesi
yaklaşık 4 dakika; tüm yayın görevinin sınırı 30 dakikadır. Kaynak erişimi ve
ücretsiz kotalar veri kapsamını etkileyebilir. Her komutta yeniden tarama yapılmaz.

KAP, Yahoo Finance ve makro haber kaynakları kullanılır. Çalışma veritabanı ayrı
`data/public-cloud.sqlite3` dosyasıdır. Raporlar `cloudflare/reports` altında
üretilir; ikisi de Git'e eklenmez. GitHub önbelleği yeniden kullanılabilir ama
kalıcı, yedekli bir öğrenme kayıt sistemi olarak kabul edilmemelidir.

Worker yalnızca gizli webhook başlığı doğrulanan istekleri işler. Bot tokeni,
düğme alındı bildirimini Telegram'a göndermek için Worker secret olarak tutulur.
Rapor dosyalarının doğrudan URL üzerinden sunulması engellenir. Sahiplik
kontrolünde gerçek yönetici kimliği GitHub/Cloudflare secret alanlarından gelir.

## 3. Mevcut analiz ne yapıyor, ne yapmıyor?

- Şirket seçimi güncel fiyat/bilanço, temel finansal kalite, fiyat eğilimi,
  likidite ve KAP risklerine dayanır. Formüller için kodu esas al.
- 12 ana sektör altında KAP alt sektörleri birleştirilmiştir. Özgün KAP
  sınıflaması finansal hesaplamada korunur; portföy seçimi ana sektör çeşitliliğini gözetir.
- Tarama puanı başarı olasılığı değildir. Tüm uygun sektör adayları sayfalanır;
  keyfî bir hisse sayısı sınırıyla sessizce elenmez.
- 12 aylık fiyat senaryosu, son en çok 60 seansın düzeltilmiş logaritmik
  getirilerinin standart sapmasını 252 seansa ölçekler. Merkez son işlem fiyatı,
  aşağı/yukarı senaryo bunun `exp(-oynaklık)` ve `exp(oynaklık)` katıdır.
- Sıfır logaritmik sürüklenme varsayılır. Bu, temel değerleme veya eğitilmiş
  tahmin değildir; aralığın aşılma olasılığı kalibre edilmemiştir. Yıl içi görülecek
  en düşük/en yüksek fiyatı söylemez. Yetersiz/geçersiz/sabit/aşırı oynak seride hesaplanmaz.
- **Bağlı bir ML eğitim/öğrenme döngüsü yoktur.** Öneri sonuçlarının kalıcı
  kaydı, gerçekleşen başarıya göre öğrenme ve yeni eğitim ihtiyacı bildirimi de
  henüz uygulanmış değildir. Veri yenilenmesi bu eksikleri kendiliğinden tamamlamaz.

## 4. Eğitimle ilgili son kullanıcı kararı

**Eğitim sabit takvimle değil, yalnızca ihtiyaç halinde olacak.** Kullanıcı
eğitimin gerekli olduğunu öğrenmek istiyor; bilgisayarını açıp açıkça başlatma
talimatı verecek. Açılış görevi, cumartesi eğitimi, haftalık/aylık otomatik eğitim
veya sessiz arka plan eğitimi kurulmayacak. Ağır eğitim güçlü yerel bilgisayarda
yapılacak; VDS'ye, Cloudflare'a veya GitHub Actions'a taşınmayacak.

İhtiyaç kontrolü ile eğitim başlatılması ayrı tasarlanmalı. Gereksinim ortaya
çıktığında yöneticiye gerekçe ve veri özetiyle tek bildirim gönderilmeli; diğer
bot kullanıcıları görmemeli. Aynı ihtiyaç için tekrar tekrar bildirim atılmamalı.
Bunlar tamamlanmış özellik değil, sonraki geliştirme gereksinimleridir.

## 5. Sıradaki geliştirmeler ve kabul ölçütleri

1. **Değişmez öneri defteri:** Yayın zamanı, veri kesim zamanı, hisse, ana/özgün
   sektör, kapanış tarihi/fiyatı, gerekçe, kullanılan yöntem ve sürümü kaydedilmeli.
   Sonradan üretilen geçmiş öneriler, gerçek zamanında kaydedilmiş öneri gibi sunulmamalı.
2. **Kalıcılık:** Öneri defteri GitHub cache'ten bağımsız ve yedekli tutulmalı.
   Henüz seçilmiş veya kurulmuş kalıcı öğrenme servisi yoktur. Ücretsiz hizmet,
   veri güvenliği ve erişim ihtiyaçlarını doğrulamadan kurulmuş gibi anlatma.
3. **Olgunlaşmış sonuçlar:** Vadelere uygun gerçekleşen fiyatlar, BIST ve sektör
   getirisi, maliyetler ve kurumsal aksiyonlar değerlendirilir. Yıllık etiket,
   süresi dolmadan gerçek yıllık sonuç sayılamaz. Tarihsel veri kullanımı, yayımlandığı
   tarihte bilinen bilanço/haber ve işlem gören evrenle sınırlanmalı.
4. **Hata ayrımı:** Tahmin yönü, stop/uygulama sistemi, piyasa rejimi ve endekse
   göre başarı ayrı tutulmalı. Düşen endekste mutlak zarar otomatik olarak model
   bozulması sayılmamalı; tek kötü hafta yeni eğitime gerekçe olmamalı.
5. **İhtiyaca bağlı eğitim kararı:** Yeterli yeni etiketli veri, kalıcı performans
   bozulması, veri/özellik değişimi veya yöntem uyumsuzluğu gibi ölçülebilir
   gerekçelerle değerlendirilmeli. Eşikler gerçek sonuçlarla belirlenmeli; bu
   belgede önerilmiş sayılar canlıda varmış gibi kullanılmamalı. Sadece yaşa veya
   takvim gününe bakarak eğitim zorunlu sayılmamalı.
6. **Yerel aday eğitimi ve korumalı yayın:** Kullanıcının açık başlatma talimatı,
   zaman sıralı/purged walk-forward değerlendirme, dokunulmamış holdout, maliyet,
   BIST/sektör karşılaştırması ve boğa/ayı/yatay/kriz rejimleri gerekir. Birkaç
   işlemde yüzde 100 sonuç yeterli kanıt değildir. Aday yöntemi başarısızsa mevcut
   finansal/teknik yöntem korunur; eşikler sonucu güzelleştirmek için düşürülmez.

Takvim tabanlı eğitim ya da bu altyapı olmadan otomatik "kendini eğitiyor"
iddiası, bu gereksinimleri karşılamaz. Kalite garantisi veya kârlılık sözü verilmez.

## 6. Güvenli geliştirme ve doğrulama

Bu depo herkese açıktır. Eski özel ana klasörü veya eski sohbeti bütünüyle buraya
taşıma; geçmişte paylaşılmış anahtarlar ve özel veriler bulunabilir. Yerel
özel yedekler bu deponun dışındadır; yalnızca bu çalışma kopyasında değişiklik yap.

Son tamamlanan doğrulamada 75 Python testi, 9 Worker testi, canlı menü/portföy
yanıtları ve veri önbelleği denetimi geçti. Yeni değişikliklerde yeniden doğrula:

```sh
python -m unittest discover -s tests
node --test cloudflare/worker.test.mjs
python scripts/check_public_safety.py
```

GitHub secret scanning ve push protection açılmıştır. Otomatik tarama her tür
gizli bilgiyi bulma garantisi vermez. Token yenilemesi, sahip kimliği veya canlı
dağıtım gerektiğinde gizli değerleri kullanıcıdan sohbete yapıştırmasını isteme.

Kod push'u yalnızca güvenlik CI'sini başlatır; canlı yayın görevi ayrıca elle
başlatılır veya günlük planını bekler. Yayın yapmadan önce görev kapsamını ve
mevcut secret isimlerini doğrula; başka bot veya sunucuya geçme. Mevcut secret
değerlerini okumak/dökümlemek veya yönetici dışındaki kullanıcılara bakım mesajı
göndermek gerekmez. Her adımda planlanan, uygulanan ve doğrulanan işleri ayır.

## 7. Bu devir hazırlığının aktarım durumu

`CLAUDE.md`, bu belge ve README'deki devir bağlantısı 2026-11-27 tarihinde
GitHub deposuna ayrı bir dal ve PR ile aktarıldı. Önceki denemedeki HTTP 401
sorunu bu aktarımda yaşanmadı. Kaynak kod veya canlı bot değiştirilmedi; yeni
eğitim başlatılmadı. Aktarım öncesinde 75 Python ve 9 Worker testi ile dosya
güvenlik kontrolü yeniden geçti.

Sonraki oturumlarda da önce `git status` ve güncel uzak dalı kontrol et; başka
değişiklikleri ezme. Token dökümü alma, sohbete token isteme veya kişisel e-posta
içeren commit oluşturma. Bu belgeyi iş bittikçe güncel tut.
