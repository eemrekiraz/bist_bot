# Proje çalışma kuralları

Bu depo, herkese açık BİST araştırma botunun Cloudflare + GitHub sürümüdür.
Önce `README.md`, `SECURITY.md`, `docs/PROJECT_HANDOFF.md` ve
`deploy/CLOUDFLARE.md` dosyalarını oku. Bu dosya ile devir özeti, geçmiş
konuşmaların otomatik aktarımı değil; doğrulanabilir proje bağlamıdır.

## Kapsam ve güvenlik

- Yalnızca bu depo üzerinde çalış. Üst dizindeki eski özel bot, VDS betikleri,
  özel veritabanı, model dosyaları, günlükler ve yedekler kapsam dışındadır.
- Eski botu veya herhangi bir VDS'yi değiştirme, dağıtım yapma ya da eğitim için kullanma.
- Bu depo herkese açıktır. `.env`, token, şifre, özel anahtar, kullanıcı/sohbet
  kimliği, özel sunucu adresi veya kişisel dosya yolunu commit etme.
- Anahtarları konuşmaya veya günlüklere yazma. Dağıtım için mevcut GitHub
  Actions secrets ve Cloudflare secret bağlamalarını kullan.
- Git geçmişi, kişisel e-posta temizliği için yeniden başlatıldı. Eski özel
  geçmişi bu depoya geri yükleme. Commit kimliğinde kişisel e-posta yayımlama.
- Kullanıcı izni olmadan depoyu yeniden adlandırma, geçmişi yeniden yazma,
  gerçek Telegram kullanıcılarına deneme mesajı gönderme veya hizmet satın alma.

## Kullanıcı tercihleri

- Türkçe, kısa ve anlaşılır mesajlar; ayrı başlıklar ve madde işaretleri kullan.
- Sektör ve portföy seçimi mesaj içi düğmelerle doğrudan açılmalı.
- Uzun KAP alt sektör adlarını kullanıcıya yazdırma; 12 ana sektör düzenini koru.
- Mevcut kamuya açık komutlar: `/start`, `/komutlar`, `/sektor`, `/portfoy`,
  `/tara`, `/haber`. `/yonetim` yalnızca yöneticiye özel kalmalı.
- Kullanıcıya faydalı bulup bulmadığını soran anketler, gereksiz sistem bildirimleri
  ve tekrar eden bakım mesajları gönderme.

## Eğitim kararı — kullanıcının son talimatı

- Eğitimler **yalnızca ihtiyaç oluştuğunda** yapılacak. Her hafta/ay/cumartesi
  gibi sabit bir eğitim takvimi kurma; bilgisayar açılışında eğitim başlatma.
- Veri yenileme, eğitim ihtiyacı değerlendirmesi ve model eğitimi ayrı işlemlerdir.
  Eğitim ihtiyacı düzenli kontrol edilebilir; bu, otomatik eğitim izni değildir.
- İhtiyaç oluşursa yalnızca yöneticiye gerekçeli, tekrarsız Telegram bildirimi
  gönderilir. Kod `training_need.py` ve `recommendation_jobs.py` içindedir; eşik
  dosyası (`training_policy.json`) olmadan karar verilmez ve bildirim gitmez.
- Eğitim kullanıcının açık başlatma talimatıyla güçlü yerel bilgisayarında
  yapılmalı; VDS, Worker veya GitHub Actions üzerinde ağır eğitim başlatma.
- Yeni yöntemi ancak zaman-kör, maliyetli, BIST/sektör karşılaştırmalı ve farklı
  piyasa rejimlerini kapsayan testlerde mevcut yönteme göre yeterli kanıt varsa yayınla.
- Tek kötü haftayla model değiştirme; test skorunu yükseltmek için kalite
  eşiklerini gevşetme, başarısız örnekleri silme veya holdout'a göre ayarlama yapma.

## Gerçek mevcut durum

- Bu sürümde eğitilmiş bir ML modeli veya öneri sonuçlarından öğrenen kapalı
  döngü henüz bağlı değildir. Geçmiş özel projedeki eğitimleri burada var sayma.
- Günlük veri/rapor yenilemesi 19.31 Türkiye saati için planlıdır; bu eğitim değildir.
- 12 aylık fiyat seviyeleri geçmiş oynaklık senaryosudur. Eğitilmiş model tahmini,
  adil değer, güvenilir olasılık aralığı veya yıl içi minimum/maksimum diye sunma.
- Öneri defteri, olgun sonuç değerlendirmesi ve eğitim ihtiyacı kontrolü kodda
  var; defter `recommendation-ledger` veri dalında tutulur. Ayrıntı:
  `docs/RECOMMENDATION_LEDGER.md`. Eşikler gerçek sonuçlar birikince belirlenecek.

## Doğrulama ve yayın

Aktif Python ortamında, depo kökünde çalıştır:

```sh
python -m unittest discover -s tests
node --test cloudflare/worker.test.mjs
python scripts/check_public_safety.py
```

- Son doğrulamada 91 Python testi ve 9 Worker testi geçti; yeni değişikliklerde
  yeniden çalıştır. Eski özel projenin test sayısını bu sürüme ait gibi raporlama.
- Dağıtım `.github/workflows/public-telegram.yml` ile yapılır. Kod değişikliği
  tek başına canlıya yansımaz; mevcut görev otomatik olarak her push'ta yayın yapmaz.
- Webhook bağlantısı ve `callback_query` aboneliği
  `.github/workflows/public-telegram-activate.yml` ile doğrulanır.
- Yapılan, test edilen, canlıya alınan ve yalnızca planlanan işleri açıkça ayır.
- İş bitince bu bağlamı güncelle; gizli bilgi ekleme ve finansal başarı garantisi verme.
