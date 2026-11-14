"""PS5 Slim fırsat takipçisi.

GitHub Actions üzerinde zamanlanmış olarak çalışır. Fırsat akışlarını (Slickdeals, 9to5Toys)
ve otomatik erişime izin veren mağaza sayfalarını (PlayStation Direct) okur, filtreden geçen
fırsatları Telegram'a Türkçe bildirir. Yalnızca Python standart kütüphanesini kullanır.

Ortam değişkenleri:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  (GitHub Secrets)  — yoksa mesajlar sadece log'a yazılır
  PRICE_LIMIT                           (GitHub Variables) — varsayılan 500
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
LOCAL_TZ = ZoneInfo("America/New_York")  # Atlanta
HEARTBEAT_HOUR = 9          # her gün yerel saatle 09:00'dan sonraki ilk çalışmada
ERROR_ALERT_AFTER = 3       # bir kaynak üst üste bu kadar hata verirse bildir
MIN_CONSOLE_PRICE = 200     # bunun altı konsol değil (oyun/aksesuar) kabul edilir
MAX_AGE_DAYS = 4            # fırsat akışlarında bundan eski ilanlar yok sayılır
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def price_limit() -> float:
    try:
        return float(os.environ.get("PRICE_LIMIT") or 500)
    except ValueError:
        return 500.0


# --------------------------------------------------------------------------- mağazalar
# anahtar -> (görünen ad, alan adı/kısa ad ipuçları, pazaryeri kontrolü gerekli mi)
TRUSTED_STORES = {
    "psdirect": ("PlayStation Direct", ("direct.playstation.com", "playstation direct", "playstation.com"), False),
    "amazon":   ("Amazon",   ("amazon.com", "amzn.to", "amazon"), True),
    "bestbuy":  ("Best Buy", ("bestbuy.com", "bestbuy", "best buy", "bestbuy.7tiv.net"), False),
    "walmart":  ("Walmart",  ("walmart.com", "walmart"), True),
    "target":   ("Target",   ("target.com", "target", "goto.target.com"), False),
    "gamestop": ("GameStop", ("gamestop.com", "gamestop"), False),
    "costco":   ("Costco",   ("costco.com", "costco"), False),
    "newegg":   ("Newegg",   ("newegg.com", "newegg"), True),
}

# Fırsat sitelerinde sık geçen ama listede OLMAYAN satıcılar: tespit edilirse sessizce elenir.
KNOWN_UNTRUSTED = (
    "ebay", "woot", "sam's club", "samsclub", "bjs", "bj's", "kohl", "macy", "dell", "antonline",
    "adorama", "b&h", "bhphotovideo", "mercari", "offerup", "facebook", "craigslist", "aliexpress",
    "temu", "rakuten", "quidd", "dailysteals", "meh.com", "groupon", "verizon", "at&t", "tiktok",
    "backmarket", "back market", "swappa", "gamefly", "microcenter", "micro center", "qvc", "hsn",
    "staples", "office depot", "big lots", "belk", "jcpenney", "best-buy-outlet",
)


def match_store(text: str) -> str | None:
    """Metindeki ilk güvenilir mağaza anahtarını döndürür."""
    t = text.lower()
    best = None
    for key, (_, hints, _) in TRUSTED_STORES.items():
        for h in hints:
            pat = r"(?<![a-z0-9])" + re.escape(h) + r"(?![a-z0-9])"
            m = re.search(pat, t)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), key)
    return best[1] if best else None


def is_untrusted_store(text: str) -> bool:
    t = text.lower()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(u) + r"(?![a-z0-9])", t) for u in KNOWN_UNTRUSTED)


# --------------------------------------------------------------------------- fırsat modeli
@dataclass
class Deal:
    source: str               # "Slickdeals", "9to5Toys", "PlayStation Direct"
    key: str                  # tekrar bildirimi önlemek için kalıcı kimlik
    title: str
    text: str = ""            # açıklama / gövde (düz metin)
    link: str = ""            # en iyi ürün linki
    source_link: str = ""     # fırsat sayfası (Slickdeals başlığı vb.)
    store_hint: str = ""      # kaynağın verdiği mağaza bilgisi (alan adı / ad)
    price: float | None = None
    trusted_model: bool = False   # kaynak modelin Slim olduğunu kesin biliyorsa (PS Direct)
    first_party: bool = False     # kaynak satıcının mağazanın kendisi olduğunu kesin biliyorsa


@dataclass
class Verdict:
    decision: str                      # "pass" | "unverified" | "reject"
    reason: str = ""                   # elenme nedeni (log için)
    notes: list[str] = field(default_factory=list)   # "doğrulanmadı" notları
    store: str | None = None
    edition: str = ""
    storage: str = ""
    bundle: str = ""
    price: float | None = None


PS5_RE = re.compile(r"\bps\s?5\b|playstation\s*5|playstation®\s*5", re.I)
PRO_RE = re.compile(r"(ps\s?5|playstation\s*®?\s*5)\s*(slim\s*)?pro\b|\bpro\s+console\b|\bps5pro\b", re.I)
PORTAL_RE = re.compile(r"\bportal\b", re.I)
SLIM_RE = re.compile(r"\bslim\b", re.I)
CONDITION_RE = re.compile(
    r"refurb|renewed|recertified|re-certified|open[\s-]?box|pre[\s-]?owned|\bused\b|like[\s-]new|"
    r"restored|\bgrade\s?[abc]\b|seller[\s-]refurbished|scratch(?:\s|-)and(?:\s|-)dent|damaged box", re.I)
CONSOLE_RE = re.compile(r"\bconsoles?\b|digital edition|disc edition|standard edition|\bbundle\b", re.I)
ACCESSORY_RE = re.compile(
    r"disc drive|controller|dualsense|headset|earbuds|\bcover|faceplate|face plate|\bplates?\b|\bskin|"
    r"\bstand\b|charg|\bcase\b|\bbag\b|cooling|\bfan\b|remote|cable|\bmount\b|dust|thumb grip|"
    r"gift card only|\bgame\b|edition\)\s*\(ps5\)|\(ps5\)|for ps5|for playstation|compatible", re.I)
OLD_MODEL_RE = re.compile(r"cfi-1[0-2]\d\d|original (ps5|playstation 5|model)|launch model|\bfat\b", re.I)
STORAGE_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s?(tb|gb)\b", re.I)
PRICE_RE = re.compile(r"\$\s?(\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?)")
NOT_SALE_PRICE_AFTER = re.compile(r"^\s*(off|gift|in |credit|reward|back|savings|promo|instant|e-?gift|digital gift|store credit|target gift|bonus)", re.I)
NOT_SALE_PRICE_BEFORE = re.compile(r"(save|reg\.?|regularly|was|list|msrp|orig\.?|originally|retail|value|\+|w/|with|get|earn|plus)\s*$", re.I)

FIRST_PARTY_RE = {
    "amazon": re.compile(r"(sold|shipped)(\s+and\s+(sold|shipped))?\s+by\s+amazon|ships from and sold by amazon|sold by amazon\.com", re.I),
    "walmart": re.compile(r"(sold|shipped)(\s+and\s+(sold|shipped))?\s+by\s+walmart|sold & shipped by walmart|walmart\.com is the seller", re.I),
    "newegg": re.compile(r"(sold|shipped)(\s+and\s+(sold|shipped))?\s+by\s+newegg|ships from newegg", re.I),
}
THIRD_PARTY_RE = re.compile(
    r"third[\s-]party|3rd[\s-]party|marketplace|\bvia\s+(an?\s+)?(amazon|walmart|newegg)?\s*seller|"
    r"sold by\s+(?!amazon|walmart|newegg)[a-z0-9]|ships from\s+(?!amazon|walmart|newegg)[a-z0-9]|"
    r"fulfilled by (amazon|walmart)\b(?!.*sold by (amazon|walmart))", re.I)


def extract_price(title: str, text: str = "") -> float | None:
    for src in (title, text):
        for m in PRICE_RE.finditer(src):
            before = src[max(0, m.start() - 15):m.start()]
            after = src[m.end():m.end() + 20]
            if NOT_SALE_PRICE_AFTER.search(after) or NOT_SALE_PRICE_BEFORE.search(before):
                continue
            val = float(m.group(1).replace(",", ""))
            if val < 20:   # kupon/kargo gibi küçük tutarlar
                continue
            return val
    return None


def evaluate(d: Deal, limit: float | None = None) -> Verdict:
    """Bir fırsatın tüm koşulları sağlayıp sağlamadığına karar verir."""
    limit = price_limit() if limit is None else limit
    full = f"{d.title}\n{d.text}"
    title = d.title
    notes: list[str] = []

    # 1) Model: PS5 olmalı, Pro/Portal olmamalı
    if not (d.trusted_model or PS5_RE.search(full)):
        return Verdict("reject", "PS5 değil")
    if PRO_RE.search(title) or PORTAL_RE.search(title):
        other = PRO_RE.sub(" ", PORTAL_RE.sub(" ", title))
        if SLIM_RE.search(other) or PS5_RE.search(other):
            notes.append("başlıkta PS5 Pro/Portal da geçiyor; ürünün Slim olduğunu kontrol et")
        else:
            return Verdict("reject", "PS5 Pro veya PlayStation Portal")
    if OLD_MODEL_RE.search(title):
        return Verdict("reject", "eski (Slim olmayan) model")

    # 2) Durum: sıfır olmalı
    if CONDITION_RE.search(title):
        return Verdict("reject", "yenilenmiş / açık kutu / ikinci el")
    if CONDITION_RE.search(d.text[:400]):
        notes.append("açıklamada yenilenmiş/açık kutu/ikinci el ifadesi geçiyor, sıfır olduğu doğrulanamadı")

    # 3) Konsol mu aksesuar mı?
    is_slim = bool(SLIM_RE.search(title))
    has_console = bool(CONSOLE_RE.search(title))
    has_accessory = bool(ACCESSORY_RE.search(title))
    storage_m = STORAGE_RE.search(title)
    storage = f"{storage_m.group(1)} {storage_m.group(2).upper()}" if storage_m else ""

    if not d.trusted_model:
        if not (has_console or is_slim):
            return Verdict("reject", "konsol değil (oyun/aksesuar)")
        if has_accessory and not has_console:
            return Verdict("reject", "tek başına aksesuar")
        if not is_slim:
            # 1 TB standart/dijital = Slim nesli (eski modeller 825 GB idi)
            if storage_m and storage.replace(" ", "").upper() == "1TB":
                pass
            else:
                notes.append("Slim olduğu başlıktan doğrulanamadı")
        if not has_console:
            notes.append("ürünün konsolun kendisi olduğu net değil")

    edition = "Dijital" if re.search(r"digital", title, re.I) else (
        "Diskli" if re.search(r"\bdisc\b|standard|1\s?tb", title, re.I) else "Diskli (muhtemelen)")

    bundle = ""
    if re.search(r"\bbundle\b|\s\+\s|\bw/|\bwith\b|\bincludes?\b", title, re.I):
        bundle = title

    # 4) Satıcı
    hint_store = match_store(d.store_hint) if d.store_hint else None
    if d.store_hint and not hint_store:
        return Verdict("reject", f"güvenilir listede olmayan satıcı: {d.store_hint}")
    store = hint_store or match_store(title) or match_store(d.text[:600])
    if not store:
        if is_untrusted_store(title) or is_untrusted_store(d.text[:300]):
            return Verdict("reject", "güvenilir listede olmayan satıcı")
        notes.append("satıcı belirlenemedi")
    elif TRUSTED_STORES[store][2] and not d.first_party:
        if FIRST_PARTY_RE[store].search(full):
            pass
        elif THIRD_PARTY_RE.search(full):
            return Verdict("reject", "pazaryeri / üçüncü taraf satıcı")
        else:
            notes.append(f"{TRUSTED_STORES[store][0]}'un kendisinin mi pazaryerinin mi sattığı doğrulanamadı")

    # 5) Fiyat
    price = d.price if d.price is not None else extract_price(title, d.text)
    if price is None:
        return Verdict("reject", "fiyat yok (haber/duyuru, fırsat değil)")
    else:
        if price < MIN_CONSOLE_PRICE:
            return Verdict("reject", f"${price:.2f} konsol fiyatı değil (aksesuar/oyun)")
        if price > limit:
            return Verdict("reject", f"fiyat ${price:.2f} > ${limit:.0f}", store=store,
                           edition=edition, storage=storage, price=price)

    return Verdict("unverified" if notes else "pass", notes=notes, store=store, edition=edition,
                   storage=storage, bundle=bundle, price=price)


def is_slim_candidate_ignoring_price(d: Deal) -> Verdict:
    """Günlük 'en düşük fiyat' için: fiyat eşiği hariç tüm kurallar."""
    return evaluate(d, limit=float("inf"))


# --------------------------------------------------------------------------- HTTP
class SourceError(Exception):
    pass


def http_get(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        raise SourceError(f"HTTP {e.code}") from e
    except Exception as e:  # zaman aşımı, DNS vb.
        raise SourceError(type(e).__name__) from e


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def resolve_redirect(url: str, max_hops: int = 4) -> str:
    """Slickdeals/affiliate yönlendirmesini takip ederek mağaza linkini bulur.
    Mağaza alanına ulaşınca durur (mağaza sayfasının kendisini indirmez)."""
    opener = urllib.request.build_opener(_NoRedirect)
    cur = url
    for _ in range(max_hops):
        host = urllib.parse.urlparse(cur).netloc.lower()
        if match_store(host) and "slickdeals" not in host:
            return cur
        try:
            req = urllib.request.Request(cur, headers={"User-Agent": UA}, method="GET")
            opener.open(req, timeout=15)
            return cur
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location")
            if e.code in (301, 302, 303, 307, 308) and loc:
                cur = urllib.parse.urljoin(cur, loc)
                continue
            return cur
        except Exception:
            return cur
    return cur


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).replace("*", "").strip()


def _parse_date(s):
    try:
        return parsedate_to_datetime(s) if s else None
    except (TypeError, ValueError):
        return None


def is_recent(item: dict) -> bool:
    pub = item.get("published")
    return pub is None or pub >= datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)


def parse_rss(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError as e:
        raise SourceError(f"RSS ayrıştırılamadı: {e}") from e
    ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
    out = []
    for it in root.iter("item"):
        out.append({
            "title": html.unescape(it.findtext("title") or "").strip(),
            "link": (it.findtext("link") or "").strip(),
            "guid": (it.findtext("guid") or it.findtext("link") or "").strip(),
            "description": it.findtext("description") or "",
            "content": it.findtext("content:encoded", namespaces=ns) or "",
            "published": _parse_date(it.findtext("pubDate")),
        })
    return out


# --------------------------------------------------------------------------- kaynaklar
SLICKDEALS_QUERIES = ["ps5 slim", "ps5 console", "playstation 5 console"]


def fetch_slickdeals() -> list[Deal]:
    deals: dict[str, Deal] = {}
    for q in SLICKDEALS_QUERIES:
        url = ("https://slickdeals.net/newsearch.php?searcharea=deals&searchin=first&rss=1&q="
               + urllib.parse.quote_plus(q))
        items = parse_rss(http_get(url))
        if not items:
            raise SourceError(f"'{q}' aramasında hiç sonuç yok (format değişmiş olabilir)")
        for it in filter(is_recent, items):
            m = re.search(r"/f/(\d+)", it["link"])
            tid = m.group(1) if m else it["guid"]
            raw = it["content"] or it["description"]
            exit_site = re.search(r'data-product-exitWebsite="([^"]+)"', raw)
            click = re.search(r'href="(https://slickdeals\.net/click\?[^"]+)"', raw)
            hint = exit_site.group(1) if exit_site else ""
            if not hint:
                m2 = re.match(r"\s*([A-Za-z][\w .&'-]{1,30}?)\s*\[([a-z0-9.-]+\.[a-z]{2,})\]", strip_tags(it["description"]))
                hint = m2.group(2) if m2 else ""
            deals[tid] = Deal(
                source="Slickdeals", key=f"sd:{tid}", title=it["title"],
                text=strip_tags(it["description"]) + "\n" + strip_tags(it["content"]),
                link=html.unescape(click.group(1)) if click else it["link"],
                source_link=it["link"].split("?")[0], store_hint=hint)
    return list(deals.values())


def fetch_9to5toys() -> list[Deal]:
    items = parse_rss(http_get("https://9to5toys.com/?s=ps5&orderby=date&order=DESC&feed=rss2"))
    if not items:
        raise SourceError("hiç sonuç yok (format değişmiş olabilir)")
    out = []
    for it in filter(is_recent, items):
        body = it["content"] or it["description"]
        store_link = ""
        for href in re.findall(r'href="([^"]+)"', body):
            h = html.unescape(href)
            host = urllib.parse.urlparse(h).netloc.lower()
            if "9to5" in host:
                continue
            if match_store(host) or match_store(h):
                store_link = h
                break
        out.append(Deal(
            source="9to5Toys", key=f"9t5:{it['guid']}", title=it["title"],
            text=strip_tags(body)[:3000], link=store_link or it["link"],
            source_link=it["link"]))
    return out


PS_DIRECT_PRODUCTS = [
    ("https://direct.playstation.com/en-us/buy-consoles/playstation5-console-1-tb",
     "PlayStation 5 Console (Slim) – Disc Edition 1 TB"),
    ("https://direct.playstation.com/en-us/buy-consoles/playstation5-digital-edition-console-825-gb",
     "PlayStation 5 Console (Slim) – Digital Edition 825 GB"),
]


def fetch_psdirect() -> list[Deal]:
    out = []
    for url, title in PS_DIRECT_PRODUCTS:
        page = http_get(url)
        pm = re.search(r'itemprop="price"\s+content="([\d.]+)"|"price"\s+content="([\d.]+)"', page)
        if not pm:
            raise SourceError(f"fiyat bulunamadı: {url.rsplit('/', 1)[-1]}")
        price = float(pm.group(1) or pm.group(2))
        in_stock = "schema.org/InStock" in page
        sku = re.search(r'"sku"\s+content="(\d+)"', page)
        out.append(Deal(
            source="PlayStation Direct", key=f"psd:{sku.group(1) if sku else url}",
            title=title + ("" if in_stock else " [stokta yok]"), link=url, source_link=url,
            store_hint="direct.playstation.com", price=price, trusted_model=True, first_party=True))
    return out


SOURCES = {
    "Slickdeals": fetch_slickdeals,
    "9to5Toys": fetch_9to5toys,
    "PlayStation Direct": fetch_psdirect,
}


# --------------------------------------------------------------------------- durum
def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            s = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        s = {}
    s.setdefault("notified", {})       # key -> {price, ts, title}
    s.setdefault("observations", [])   # son 24 saatte görülen Slim fiyatları
    s.setdefault("errors", {})         # kaynak -> {count, alerted, last}
    s.setdefault("last_heartbeat", "")
    s.setdefault("recent_alerts", [])  # mağaza+sürüm bazlı çapraz kaynak tekrarı önleme
    return s


def save_state(s: dict) -> None:
    cutoff_obs = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    s["observations"] = [o for o in s["observations"] if o["ts"] >= cutoff_obs]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    s["notified"] = {k: v for k, v in s["notified"].items() if v["ts"] >= cutoff}
    cutoff_alerts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    s["recent_alerts"] = [a for a in s["recent_alerts"] if a["ts"] >= cutoff_alerts]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1, sort_keys=True)


# --------------------------------------------------------------------------- Telegram
def send_telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("[telegram yok — mesaj yalnızca log'a yazıldı]\n" + text + "\n")
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "false"}).encode()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data, timeout=20) as r:
                if json.load(r).get("ok"):
                    return True
        except Exception as e:
            print(f"Telegram hatası (deneme {attempt + 1}): {type(e).__name__}", file=sys.stderr)
            time.sleep(2)
    return False


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def format_deal(d: Deal, v: Verdict, previous: float | None = None) -> str:
    store = TRUSTED_STORES[v.store][0] if v.store else "Belirlenemedi"
    head = "🎮 <b>PS5 Slim fırsatı</b>" if v.decision == "pass" else "⚠️ <b>PS5 Slim fırsatı — DOĞRULANMADI</b>"
    if previous is not None:
        head += f"\n📉 Fiyat düştü: ${previous:.2f} → ${v.price:.2f}"
    model = v.edition + (f", {v.storage}" if v.storage else "")
    lines = [
        head, "",
        f"<b>Mağaza:</b> {esc(store)}",
        f"<b>Model:</b> {esc(model)}",
        f"<b>Fiyat:</b> " + (f"${v.price:.2f} (vergisiz)" if v.price is not None else "okunamadı"),
    ]
    if v.bundle:
        lines.append(f"<b>Bundle içeriği:</b> {esc(v.bundle)}")
    lines.append(f"<b>Başlık:</b> {esc(d.title)}")
    if v.notes:
        lines.append("<b>Doğrulanmayanlar:</b> " + esc("; ".join(v.notes)))
    lines.append("")
    lines.append(f'🔗 <a href="{esc(d.link)}">Ürün linki</a>')
    if d.source_link and d.source_link != d.link:
        lines.append(f'ℹ️ <a href="{esc(d.source_link)}">Kaynak: {esc(d.source)}</a>')
    return "\n".join(lines)


# --------------------------------------------------------------------------- ana akış
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def process(state: dict, deals: list[Deal], send=send_telegram, resolve=resolve_redirect) -> int:
    sent = 0
    for d in deals:
        base = is_slim_candidate_ignoring_price(d)
        if base.decision != "reject" and base.price is not None:
            state["observations"].append({"ts": now_iso(), "price": base.price, "title": d.title,
                                          "store": TRUSTED_STORES[base.store][0] if base.store else "?",
                                          "link": d.link})
        v = evaluate(d)
        if v.decision == "reject":
            print(f"  ✗ [{d.source}] {d.title[:90]} — {v.reason}")
            continue
        prev = state["notified"].get(d.key)
        if prev and (v.price is None or prev.get("price") is None or v.price >= prev["price"]):
            print(f"  = [{d.source}] zaten bildirildi: {d.title[:80]}")
            continue
        # Aynı mağaza+sürüm+fiyat başka kaynaktan son 48 saatte bildirildiyse tekrar etme
        sig = f"{v.store}|{v.edition}|{v.storage}|{bool(v.bundle)}"
        if not prev and v.price is not None and any(
                a["sig"] == sig and a["price"] <= v.price for a in state["recent_alerts"]):
            print(f"  = [{d.source}] başka kaynaktan zaten bildirildi: {d.title[:80]}")
            state["notified"][d.key] = {"price": v.price, "ts": now_iso(), "title": d.title}
            continue
        if "slickdeals.net/click" in d.link:
            d.link = resolve(d.link)
            if v.store is None:  # yönlendirme mağazayı ortaya çıkarabilir
                d.store_hint = urllib.parse.urlparse(d.link).netloc
                v = evaluate(d)
                if v.decision == "reject":
                    print(f"  ✗ [{d.source}] {d.title[:90]} — {v.reason}")
                    continue
        msg = format_deal(d, v, previous=prev["price"] if prev and prev.get("price") else None)
        if not send(msg):
            print(f"  ! [{d.source}] mesaj gönderilemedi, sonraki çalışmada tekrar denenecek: {d.title[:80]}")
            continue
        sent += 1
        print(f"  ✓ [{d.source}] BİLDİRİLDİ ({v.decision}): {d.title[:90]}")
        state["notified"][d.key] = {"price": v.price, "ts": now_iso(), "title": d.title}
        if v.price is not None:
            state["recent_alerts"].append({"sig": sig, "price": v.price, "ts": now_iso()})
    return sent


def run_sources(state: dict, send=send_telegram) -> list[Deal]:
    all_deals: list[Deal] = []
    for name, fn in SOURCES.items():
        err = state["errors"].setdefault(name, {"count": 0, "alerted": False, "last": ""})
        try:
            deals = fn()
            print(f"{name}: {len(deals)} kayıt")
            all_deals.extend(deals)
            if err["alerted"]:
                send(f"✅ <b>{esc(name)}</b> kaynağı yeniden çalışıyor.")
            state["errors"][name] = {"count": 0, "alerted": False, "last": ""}
        except SourceError as e:
            err["count"] += 1
            err["last"] = str(e)
            print(f"{name}: HATA ({err['count']}. kez üst üste): {e}", file=sys.stderr)
            if err["count"] >= ERROR_ALERT_AFTER and not err["alerted"]:
                send(f"🛠️ <b>Kaynak hatası:</b> {esc(name)} üst üste {err['count']} kez hata verdi "
                     f"(son hata: {esc(str(e))}). Diğer kaynaklar çalışmaya devam ediyor.")
                err["alerted"] = True
    return all_deals


def maybe_heartbeat(state: dict, send=send_telegram, force: bool = False) -> None:
    local = datetime.now(LOCAL_TZ)
    today = local.date().isoformat()
    if not force and (state["last_heartbeat"] == today or local.hour < HEARTBEAT_HOUR):
        return
    obs = state["observations"]
    if obs:
        best = min(obs, key=lambda o: o["price"])
        low = (f"Son 24 saatte görülen en düşük PS5 Slim fiyatı: <b>${best['price']:.2f}</b> "
               f"({esc(best['store'])})\n<a href=\"{esc(best['link'])}\">{esc(best['title'][:100])}</a>")
    else:
        low = "Son 24 saatte filtreye uyan PS5 Slim fiyatı görülmedi."
    broken = [n for n, e in state["errors"].items() if e["count"] > 0]
    status = ("Tüm kaynaklar çalışıyor." if not broken
              else "Sorunlu kaynaklar: " + esc(", ".join(broken)))
    if send(f"🟢 <b>Sistem çalışıyor</b> ({local:%d.%m.%Y %H:%M})\n{low}\n"
            f"Eşik: ${price_limit():.0f}. {status}"):
        state["last_heartbeat"] = today


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    if mode == "test-message":
        sample = Deal(source="Test", key="test", title="[TEST] Sony PlayStation 5 Slim Digital Edition 1TB Console $399",
                      link="https://direct.playstation.com/en-us/consoles", store_hint="walmart.com",
                      text="Ships and sold by Walmart.com")
        ok = send_telegram("🧪 <b>Test mesajı</b> — PS5 takip sistemi Telegram'a bağlandı.\n"
                           "Aşağıdaki fırsat UYDURMADIR, sadece mesaj biçimini göstermek içindir.\n\n"
                           + format_deal(sample, evaluate(sample)))
        print("Test mesajı gönderildi." if ok else "Test mesajı GÖNDERİLEMEDİ.")
        return 0 if ok else 1
    state = load_state()
    deals = run_sources(state)
    n = process(state, deals)
    maybe_heartbeat(state, force=(mode == "heartbeat"))
    save_state(state)
    print(f"Bitti: {len(deals)} kayıt incelendi, {n} bildirim gönderildi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
