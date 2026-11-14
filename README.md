# PS5 Slim fırsat takipçisi

GitHub Actions üzerinde 15 dakikada bir çalışır, 500 $ (vergisiz) altındaki **sıfır PS5 Slim**
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
  (Yeniden başlatmak için aynı yerden *Enable workflow*.) Terminalden: `gh workflow disable takip.yml -R <kullanıcı>/ps5-takip`
- **Fiyat eşiğini değiştirmek:** depo → Settings → Secrets and variables → Actions → **Variables** sekmesi →
  `PRICE_LIMIT` değerini düzenle (ör. `450`). Kod değişmez, bir sonraki çalışmadan itibaren geçerli.
- **Test mesajı:** Actions → *PS5 Slim takip* → Run workflow → mode: `test-message`.
- **Filtre testleri (yerelde):** `python3 -m unittest discover -s tests -v`

Gizli bilgiler (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) sadece GitHub Secrets'ta durur.
