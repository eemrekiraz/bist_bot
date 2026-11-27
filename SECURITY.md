# Güvenlik

- Token, şifre, kullanıcı/sohbet kimliği, sunucu erişimi ve özel anahtarları
  kaynak koduna, testlere, commit mesajlarına veya issue'lara yazma.
- `.env`, çalışma veritabanı, rapor, model, günlük, yedek ve SSH dosyaları
  bu depoya yüklenmez. `.env.example` yalnızca boş anahtar alanları içerir.
- GitHub Actions secrets ve Cloudflare secret bağlamaları kullanılır.
  Worker'ın webhook sırrı kontrol edilmeden gelen istekleri kabul edilmez.
- Herkese açık CI, pull request koduna yayın anahtarlarını vermez.
  Yayın yalnızca ana daldaki zamanlanmış veya elle başlatılmış görevden yapılır.
- Bir anahtar açığa çıktıysa dosyadan silmek yeterli değildir: sağlayıcıdan
  iptal et veya yenile; Git geçmişini, Actions günlüklerini ve çıktıları incele.
- Güvenlik açığını bildirirken anahtar veya kişisel veri paylaşma. GitHub'ın
  özel güvenlik bildirimi özelliği açıksa onu kullan.

Otomatik kontroller tüm açıkları veya bütün anahtar türlerini bulma garantisi
vermez. Depo görünürlüğü değişmeden önce hem mevcut dosyalar hem Git geçmişi
ayrıca denetlenmelidir.
