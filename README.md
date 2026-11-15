# PS5 Slim fırsat takipçisi

15 dakikada bir GitHub Actions üzerinde çalışır (tetikleyici: cron-job.org, yedek: GitHub'ın kendi zamanlaması), 500 $ (vergisiz) altındaki **sıfır PS5 Slim**
fırsatlarını güvenilir mağazalarla sınırlı olarak bulur ve Telegram'dan Türkçe bildirir.

## Kaynaklar (GitHub sunucularından erişim testi, 14.11.2026)

| Kaynak | Sonuç | Kullanım |
|---|---|---|
| Slickdeals RSS (arama) | ✅ 200, robots.txt izin veriyor | Fırsat akışı (tüm mağazalar) |
| 9to5Toys RSS (arama) | ✅ 200, robots.txt izin veriyor | Fırsat akışı (tüm mağazalar) |
| PlayStation Direct ürün sayfaları | ✅ 200, fiyat schema.org etiketinde | Doğrudan fiyat |
| Amazon | ❌ 503 (engelli) | Akışlar üzerinden |
| Best Buy | ❌ zaman aşımı; resmi API anahtar istiyor | Akışlar üzerinden |
| Walmart, Target, GameStop | ❌ bot doğrulaması + robots.txt yasak | Akışlar üzerinden |
| Costco | ⚠️ sayfa geliyor ama fiyatlar yok (bot doğrulaması) | Akışlar üzerinden |
| Newegg | ❌ 403 | Akışlar üzerinden |
| Reddit, Google News | ❌ engelli / robots.txt yasak | Kullanılmıyor |

Testi tekrar çalıştırmak için: Actions → **Kaynak erisim testi** → Run workflow.

## Filtre kuralları (`tracker.py` → `evaluate`)

- PS5 Slim (diskli/dijital, her depolama). PS5 Pro, Portal, eski model, tek başına aksesuar/oyun elenir.
- Sıfır ürün; refurbished / renewed / open box / used / pre-owned elenir.
- Fiyat ≤ eşik (bundle ise toplam fiyat). Fiyatı olmayan haber yazıları elenir.
- Satıcı: PlayStation Direct, Amazon, Best Buy, Walmart, Target, GameStop, Costco, Newegg.
  Amazon/Walmart/Newegg'de üçüncü taraf satıcı açıkça yazıyorsa elenir; belirsizse "doğrulanmadı".
  Listede olmayan satıcı sessizce elenir.
- Emin olunamayan durumlar (Slim mi, satıcı kim) **"DOĞRULANMADI"** başlığıyla gönderilir.
- Aynı fırsat bir kez bildirilir; fiyatı düşerse yeniden bildirilir.

## Kullanım

- **Durdurmak:** GitHub'da depo → Actions → soldan *PS5 Slim takip* → sağ üstte `...` → **Disable workflow**.
  (Yeniden başlatmak için aynı yerden *Enable workflow*.) İstersen cron-job.org'daki *PS5 takip* işini de kapat.
- **Zamanlama:** GitHub'ın kendi zamanlayıcısı bu depoda tetiklenmediği için çalışmaları cron-job.org başlatıyor
  (`POST .../actions/workflows/takip.yml/dispatches`, sadece bu depoda Actions yazma izni olan anahtar,
  bitiş 15.01.2027). Anahtar biterse sistem durur; uzatmak için GitHub'da yeni anahtar oluşturup cron-job.org'daki
  `Authorization` başlığını güncelle.
- **Sıklık sınırı:** İki tetikleyici (cron-job.org ve GitHub) üst üste gelse bile kaynaklara en fazla ~15 dakikada bir
  gidilir: son kontrolden 12 dakika geçmediyse çalışma hiç istek atmadan biter (`MIN_INTERVAL_MIN`, `tracker.py`).
- **Fiyat eşiğini değiştirmek:** depo → Settings → Secrets and variables → Actions → **Variables** sekmesi →
  `PRICE_LIMIT` değerini düzenle (ör. `450`). Kod değişmez, bir sonraki çalışmadan itibaren geçerli.
- **/durum komutu:** Telegram'da bota `/durum` yaz; anında sistem durumu, son kontrol zamanı ve en düşük fiyat gelir.
  Cloudflare Worker olarak çalışır (`bot/`, adres: ps5-takip-bot.rockhill.workers.dev), sadece kayıtlı sohbete cevap verir.
  Gizli değerler (`TELEGRAM_BOT_TOKEN`, `CHAT_ID`, `WEBHOOK_SECRET`) Cloudflare'de durur. Kapatmak için:
  Cloudflare panosu → Workers & Pages → *ps5-takip-bot* → Settings → Delete (fırsat bildirimleri etkilenmez).
  Yerel test: `node bot/test-worker.mjs`
- **Test mesajı:** Actions → *PS5 Slim takip* → Run workflow → mode: `test-message`.
- **Filtre testleri (yerelde):** `python3 -m unittest discover -s tests -v`

Gizli bilgiler (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) sadece GitHub Secrets'ta durur.
