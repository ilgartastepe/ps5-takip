"""Kaynak erişilebilirlik testi: GitHub runner'ından her kaynağı dener, sonucu tablo olarak basar."""
import urllib.request, urllib.robotparser, urllib.parse, time, re

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

SOURCES = [
    ("feed", "Slickdeals ön sayfa arama", "https://slickdeals.net/newsearch.php?mode=frontpage&searcharea=deals&searchin=first&rss=1&q=ps5"),
    ("feed", "Slickdeals tüm fırsatlar arama", "https://slickdeals.net/newsearch.php?searcharea=deals&searchin=first&rss=1&q=ps5+slim"),
    ("feed", "9to5Toys arama", "https://9to5toys.com/?s=ps5&feed=rss2"),
    ("feed", "Dealnews arama", "https://www.dealnews.com/search?q=ps5&rss=1"),
    ("feed", "Reddit r/deals", "https://www.reddit.com/r/deals/search.rss?q=ps5&restrict_sr=1&sort=new"),
    ("feed", "Reddit r/PS5", "https://www.reddit.com/r/PS5/search.rss?q=deal&restrict_sr=1&sort=new"),
    ("feed", "Google News", "https://news.google.com/rss/search?q=%22PS5+Slim%22+deal&hl=en-US&gl=US&ceid=US:en"),
    ("store", "PlayStation Direct", "https://direct.playstation.com/en-us/buy-consoles"),
    ("store", "Amazon", "https://www.amazon.com/s?k=ps5+slim"),
    ("store", "Best Buy", "https://www.bestbuy.com/site/searchpage.jsp?st=ps5+slim"),
    ("store", "Best Buy API", "https://api.bestbuy.com/v1/products(search=ps5)?format=json"),
    ("store", "Walmart", "https://www.walmart.com/search?q=ps5+slim"),
    ("store", "Target", "https://www.target.com/s?searchTerm=ps5+slim"),
    ("store", "GameStop", "https://www.gamestop.com/search/?q=ps5+slim"),
    ("store", "Costco", "https://www.costco.com/CatalogSearch?keyword=ps5"),
    ("store", "Newegg", "https://www.newegg.com/p/pl?d=ps5+slim"),
]

def robots_ok(url):
    p = urllib.parse.urlparse(url)
    rp = urllib.robotparser.RobotFileParser()
    try:
        req = urllib.request.Request(f"{p.scheme}://{p.netloc}/robots.txt", headers={"User-Agent": UA})
        rp.parse(urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore").splitlines())
        return "izin var" if rp.can_fetch("*", url) else "YASAK"
    except Exception as e:
        return f"okunamadı ({type(e).__name__})"

for kind, name, url in SOURCES:
    t = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xml,*/*", "Accept-Language": "en-US"})
        r = urllib.request.urlopen(req, timeout=20)
        body = r.read().decode("utf-8", "ignore")
        status = r.status
    except urllib.error.HTTPError as e:
        status, body = e.code, ""
    except Exception as e:
        status, body = type(e).__name__, ""
    items = len(re.findall(r"<item[ >]|<entry[ >]", body))
    prices = len(re.findall(r"\$\d{3}", body))
    captcha = bool(re.search(r"captcha|robot check|access denied|are you a human|px-captcha", body, re.I))
    print(f"| {kind} | {name} | {status} | {len(body)} | items={items} | $fiyat={prices} | captcha={captcha} | robots={robots_ok(url)} | {time.time()-t:.1f}s |", flush=True)
