import urllib.request, re, urllib.robotparser
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
def get(u):
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA, "Accept-Language": "en-US"}), timeout=20)
        return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e: return e.code, ""
    except Exception as e: return type(e).__name__, ""
for u in ["https://www.costco.com/CatalogSearch?keyword=ps5+slim", "https://www.costco.com/video-games.html",
          "https://direct.playstation.com/en-us/consoles", "https://direct.playstation.com/robots.txt"]:
    s, b = get(u)
    print("==", u, s, len(b))
    for m in list(re.finditer(r"(PlayStation|PS5)[^<>\"]{0,120}", b))[:12]:
        print("   ", m.group(0)[:130])
    print("   prices:", re.findall(r"\$\s?\d{3}\.\d\d", b)[:15])
    print("   blocked-words:", re.findall(r"captcha|Access Denied|robot check", b, re.I)[:3])
