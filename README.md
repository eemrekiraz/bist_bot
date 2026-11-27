# BİST Araştırma Botu

Borsa İstanbul şirketlerini finansal kalite, fiyat eğilimi ve KAP haberleriyle
inceleyen, hazır araştırma raporlarını Telegram üzerinden sunan bir uygulama.

## Kullanım

- `/komutlar`: sektör ve portföy seçim düğmeleri.
- `/sektor`: 12 ana sektör arasından seçim.
- `/portfoy`: dengeli, güçlü bilanço veya büyüme odaklı örnek portföy.
- `/tara THYAO`: şirketin güçlü yanları, riskleri ve fiyat senaryoları.
- `/haber THYAO`: önemli şirket bildirimleri; `/haber`: genel gündem.

Fiyatlar anlık değildir. 12 aylık seviyeler geçmiş oynaklığa dayalı senaryolardır;
eğitilmiş model tahmini, şirketin adil değeri veya garanti edilmiş sınırlar değildir.
Bu sürüm kendi kendini eğiten bir ML modeli içermez. Kişiye özel yatırım tavsiyesi vermez.

## Çalışma şekli

GitHub Actions her gün Türkiye saatiyle 19.31 için veri yenilemesi planlar.
Başlangıç gecikebilir; veri kaynaklarının erişilebilirliği ve ücretsiz hizmet
kotaları geçerlidir. Python raporları üretir; Cloudflare Worker, Telegram
webhook isteklerini hazır raporlardan yanıtlar. Kullanıcının bilgisayarı açık
kalmak zorunda değildir.

Kurulum: [Cloudflare ve GitHub rehberi](deploy/CLOUDFLARE.md).

```sh
python -m venv .venv
python -m pip install .
python -m bist_ai_radar.public_jobs public-cloud-refresh
python -m bist_ai_radar.public_jobs public-cloud-news
python -m bist_ai_radar.public_worker_export cloudflare/reports
```

Yerel komutlardan önce `.env.example` dosyasını `.env` olarak kopyalayıp yalnızca
gereken ayarları doldur. Gerçek anahtarlar GitHub Actions ve Cloudflare secrets
alanlarında tutulur; bu depoda bulunmamalıdır.

## Dosya düzeni

- `src/bist_ai_radar/`: veri kaynakları, araştırma, rapor üretimi ve webhook kaydı.
- `cloudflare/`: Telegram menüleri ve Worker.
- `.github/workflows/`: günlük yayın, bağlantı ve güvenlik kontrolleri.
- `tests/`: mevcut herkese açık sürümün testleri.

Eski özel bot, VDS betikleri, model eğitimi, kişisel portföy ve kullanıcı takibi
bu sürümün parçası değildir. Çalışma veritabanı ve raporlar kaynak koduna eklenmez.

## Kontroller

```sh
python -m unittest discover -s tests
node --test cloudflare/worker.test.mjs
python scripts/check_public_safety.py
```

Güvenlik kuralları: [SECURITY.md](SECURITY.md).
