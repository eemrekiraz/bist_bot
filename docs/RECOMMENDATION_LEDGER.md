# Öneri defteri, sonuç değerlendirmesi ve eğitim ihtiyacı

Bu belge `recommendation_ledger.py`, `recommendation_outcomes.py`,
`training_need.py` ve `recommendation_jobs.py` modüllerini anlatır.
Hiçbiri model eğitmez veya eğitim takvimlemez.

## Ne yapılıyor?

- **Öneri defteri:** Yayımlanan dengeli/kalite/büyüme portföylerindeki her hisse,
  yayın anında `recommendations.jsonl` dosyasına bir kez yazılır. Kayıtta yayın
  zamanı, gerçek kayıt zamanı, veri kesim tarihi, hisse, ana ve özgün KAP sektörü,
  aynı ana sektördeki işlem gören şirketler, kapanış tarihi/fiyatı, bilanço
  dönemi, gerekçe, risk, puan, yöntem adı ve `METHOD_VERSION` bulunur.
- **Değişmezlik:** Her satır bir önceki satırın SHA-256 özetini taşır. Düzenleme,
  silme veya sıra değişikliği okuma sırasında hata verir. 6 saatten eski bir
  tarama kaydedilmez; sonradan üretilmiş öneri, gerçek zamanlı kayıt gibi görünmez.
- **Olgun sonuç:** 5, 21, 63, 126 ve 252 seanslık vadeler yalnızca o kadar seans
  gerçekten geçtiğinde hesaplanır. Düzeltilmiş kapanış kullanılır; kurumsal
  aksiyon içeren pencereler işaretlenir. Varsayılan gidiş-dönüş maliyet varsayımı
  `%0,2`'dir ve her özette yazılır; ölçülmüş maliyet değildir.
- **Karşılaştırma:** BIST 100 (`XU100`) ve kayıt anındaki aynı ana sektör
  şirketlerinin eşit ağırlıklı getirisi. Sektör için en az 3 şirket gerekir.
- **Hata ayrımı:** `basarili`, `piyasa_kaynakli_zarar` (zarar var ama BIST'i
  geçti), `endeksin_gerisinde_kar`, `secim_hatasi`, `karsilastirma_eksik`.
  Piyasa rejimi (boğa/ayı/yatay/kriz) aynı pencerede BIST'e göre ayrıca yazılır.
  Bot emir veya stop uygulamadığı için uygulama/stop başarısı ölçülmez; bu not
  özete eklenir.

## Eğitim ihtiyacı kontrolü

`training-check`, ledger klasöründeki `training_policy.json` dosyasını okur.
**Dosya yoksa karar verilmez** (`esik_tanimsiz`) ve bildirim gitmez. Eşikleri
yönetici gerçek sonuçlara bakarak yazar; kodda canlı eşik yoktur.

| Alan | Zorunlu | Anlamı |
| --- | --- | --- |
| `horizon` | evet | Değerlendirilecek vade (seans): 5, 21, 63, 126 veya 252 |
| `evaluated_method_version` | evet | Son değerlendirilen/eğitilen yöntem sürümü |
| `trained_through` | hayır | Son eğitimde kullanılan son yayın tarihi (YYYY-AA-GG) |
| `min_new_matured` | hayır | Bu tarihten sonra gereken yeni olgun sonuç sayısı |
| `degradation` | hayır | `window_size`, `consecutive_windows` (≥2), `max_mean_excess`, isteğe bağlı `min_regimes` |
| `drift` | hayır | `sample_size`, `max_psi` (ana sektör dağılımı) |

Belgede sayı önerilmez; değerler gerçek sonuçlar birikince yönetici tarafından seçilir.

- `consecutive_windows` 2'den küçükse politika reddedilir: tek kötü pencere gerekçe olmaz.
- Bozulma BIST'e göre fark üzerinden ölçülür; düşen piyasadaki mutlak zarar tek başına sayılmaz.
- `calendar_days`, `max_age_days`, `schedule` gibi takvim alanları reddedilir.
- Gerekçeler: yeni olgun veri, kalıcı göreli bozulma, sektör dağılımı değişimi (PSI),
  canlı yöntem sürümü ile değerlendirilen sürümün farklı olması.

Gerekçe oluşursa yalnızca `TELEGRAM_CHAT_ID` secret'ındaki yöneticiye tek mesaj
gider. Aynı gerekçe kümesi için ikinci mesaj gönderilmez (`training_notices.jsonl`).
Mesaj eğitimin başlatılmadığını ve yerel bilgisayarda açık talimat gerektiğini yazar.

## Komutlar

```sh
python -m bist_ai_radar.recommendation_jobs record data/ledger
python -m bist_ai_radar.recommendation_jobs evaluate data/ledger
python -m bist_ai_radar.recommendation_jobs training-check data/ledger          # yalnızca kontrol
python -m bist_ai_radar.recommendation_jobs training-check data/ledger --send   # yöneticiye bildir
```

## Kalıcılık

Defter aynı depodaki ayrı `recommendation-ledger` veri dalında tutulur (yönetici
kararı, 27 Kasım 2026). Günlük görevde ayrı `ledger` işi:

- yalnızca yayın ve menü doğrulaması başarılı olduğunda çalışır,
- dalı klonlar, yeni önerileri ekler, olgun sonuçları ve eğitim ihtiyacını değerlendirir,
- `recommendations.jsonl` içinde silinen/değişen satır varsa yayını reddeder,
- yalnızca ileri (fast-forward) push yapar; geçmiş yeniden yazılmaz.

Git geçmişi ve her klon yedek görevi görür. Depo herkese açık olduğu için defter
de herkese açıktır; içinde kullanıcı kimliği veya gizli bilgi yoktur.
`training_policy.json` dosyası da bu dala eklenir. Yazma izni yalnızca `ledger`
işine verilir; Worker yayını yapan iş salt okunur kalır.

## Bilinen sınırlar

- Fiyat yenilemesi son yaklaşık 220 günü çeker; daha eski satırlar önbellekteki
  veritabanında kalır. Önbellek kaybolursa uzun vadeler için geçmiş eksik kalabilir.
- Sonradan gelen temettü/bölünme düzeltmesi yalnızca yeniden çekilen günlere
  uygulanır; bu pencereler `corporate_action_in_window` ile işaretlenir.
- Kayıt anından sonra işlem görmeyi bırakan sektör şirketleri sektör getirisine
  girmez; kullanılan şirket sayısı her sonuçta yazılır.
