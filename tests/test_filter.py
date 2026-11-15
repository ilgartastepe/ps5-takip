"""Uydurma fırsatlarla filtre testleri. Çalıştırma: python -m unittest -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timedelta, timezone  # noqa: E402
from tracker import Deal, evaluate, extract_price, is_recent, process, too_soon  # noqa: E402


def sd(title, hint="", text=""):
    return Deal(source="Slickdeals", key="sd:" + title, title=title, store_hint=hint, text=text,
                link="https://example.invalid/p", source_link="https://slickdeals.net/f/1")


class GecmesiGerekenler(unittest.TestCase):
    def test_bestbuy_slim_disc_449(self):
        v = evaluate(sd("Sony PlayStation 5 Slim Console Disc Edition 1TB $449.99 + Free Shipping", "bestbuy.com"), 500)
        self.assertEqual(v.decision, "pass")
        self.assertEqual(v.store, "bestbuy")
        self.assertEqual(v.price, 449.99)
        self.assertEqual(v.edition, "Diskli")
        self.assertEqual(v.storage, "1 TB")

    def test_walmart_first_party_digital_399(self):
        v = evaluate(sd("PS5 Slim Digital Edition Console $399", "walmart.com", "Sold and shipped by Walmart.com"), 500)
        self.assertEqual(v.decision, "pass")
        self.assertEqual(v.edition, "Dijital")

    def test_bundle_tam_500(self):
        v = evaluate(sd("PlayStation 5 Slim Console - Call of Duty Bundle $499.99 (Reg. $599.99)", "target.com"), 500)
        self.assertEqual(v.decision, "pass")
        self.assertEqual(v.price, 499.99)
        self.assertTrue(v.bundle)

    def test_ssd_pro_markasi_pro_sanilmamali(self):
        v = evaluate(sd("Samsung 990 Pro 1TB SSD + PS5 Slim Digital Console Bundle $479.99", "newegg.com",
                        "Newegg has ... sold and shipped by Newegg"), 500)
        self.assertEqual(v.decision, "pass")

    def test_hediye_karti_fiyat_sanilmamali(self):
        v = evaluate(sd("PS5 Slim Console Disc 1TB $475 + $50 Gift Card", "costco.com"), 500)
        self.assertEqual(v.price, 475)
        self.assertEqual(v.decision, "pass")


class DogrulanmadiNotuylaGidenler(unittest.TestCase):
    def test_amazon_satici_belirsiz(self):
        v = evaluate(sd("Sony PS5 Slim Digital Console 1TB $429", "amazon.com"), 500)
        self.assertEqual(v.decision, "unverified")
        self.assertTrue(any("Amazon" in n for n in v.notes))

    def test_slim_belirsiz(self):
        v = evaluate(sd("PlayStation 5 Digital Edition Console 825GB $399", "gamestop.com"), 500)
        self.assertEqual(v.decision, "unverified")
        self.assertTrue(any("Slim" in n for n in v.notes))

    def test_satici_bilinmiyor(self):
        v = evaluate(Deal(source="9to5Toys", key="x", title="PS5 Slim console falls to $419 for Black Friday"), 500)
        self.assertEqual(v.decision, "unverified")


class KarisikBasliklar(unittest.TestCase):
    def test_slim_ve_pro_ayni_baslikta(self):
        v = evaluate(sd("PS5 Slim $399 and PS5 Pro $649 Black Friday console deals", "walmart.com", "sold by Walmart"), 500)
        self.assertEqual(v.decision, "unverified")
        self.assertEqual(v.price, 399)


class ElenmesiGerekenler(unittest.TestCase):
    def test_fiyatsiz_haber(self):
        self.assertEqual(evaluate(sd("Sony unveils new PlayStation 5 Slim console", ""), 500).decision, "reject")

    def test_eski_ilan(self):
        old = {"published": datetime.now(timezone.utc) - timedelta(days=30)}
        new = {"published": datetime.now(timezone.utc) - timedelta(hours=3)}
        self.assertFalse(is_recent(old))
        self.assertTrue(is_recent(new))

    def test_yenilenmis(self):
        self.assertEqual(evaluate(sd("Sony PS5 Slim Console 1TB (Refurbished) $349", "walmart.com"), 500).decision, "reject")

    def test_amazon_renewed(self):
        self.assertEqual(evaluate(sd("PlayStation 5 Slim Digital Console (Renewed) $329", "amazon.com"), 500).decision, "reject")

    def test_acik_kutu(self):
        self.assertEqual(evaluate(sd("Open-Box PS5 Slim Disc Console $379", "bestbuy.com"), 500).decision, "reject")

    def test_ps5_pro(self):
        self.assertEqual(evaluate(sd("Sony PlayStation 5 Pro Console 2TB $449", "bestbuy.com"), 500).decision, "reject")

    def test_portal(self):
        self.assertEqual(evaluate(sd("PlayStation Portal Remote Player $169", "target.com"), 500).decision, "reject")

    def test_aksesuar(self):
        self.assertEqual(evaluate(sd("PS5 Slim Console Covers Cobalt Blue $44.99", "amazon.com"), 500).decision, "reject")
        self.assertEqual(evaluate(sd("DualSense Wireless Controller for PS5 Slim $49", "target.com"), 500).decision, "reject")

    def test_oyun(self):
        self.assertEqual(evaluate(sd("Astro Bot (PS5) $39.99", "amazon.com"), 500).decision, "reject")

    def test_ucuncu_taraf_amazon(self):
        v = evaluate(sd("PS5 Slim Disc Console 1TB $399", "amazon.com", "Ships from and sold by GameDealsUSA"), 500)
        self.assertEqual(v.decision, "reject")

    def test_ucuncu_taraf_walmart(self):
        v = evaluate(sd("PS5 Slim Digital Console $389", "walmart.com", "Sold by a third-party marketplace seller"), 500)
        self.assertEqual(v.decision, "reject")

    def test_listede_olmayan_satici(self):
        self.assertEqual(evaluate(sd("PS5 Slim Disc Console $379", "ebay.com"), 500).decision, "reject")
        self.assertEqual(evaluate(sd("PS5 Slim Disc Console $379", "antonline.com"), 500).decision, "reject")

    def test_500_ustu(self):
        v = evaluate(sd("PlayStation 5 Slim Console Disc 1TB $529.99", "bestbuy.com"), 500)
        self.assertEqual(v.decision, "reject")
        self.assertIn(">", v.reason)

    def test_500_ustu_bundle(self):
        v = evaluate(sd("Sony PS5 Slim Console + Extra Controller Bundle $549", "walmart.com", "sold by Walmart"), 500)
        self.assertEqual(v.decision, "reject")


class Yardimcilar(unittest.TestCase):
    def test_sik_calisma_atlanir(self):
        now = datetime.now(timezone.utc)
        self.assertFalse(too_soon({}, now))
        self.assertTrue(too_soon({"last_check": (now - timedelta(minutes=5)).isoformat()}, now))
        self.assertFalse(too_soon({"last_check": (now - timedelta(minutes=14)).isoformat()}, now))

    def test_fiyat_ayiklama(self):
        self.assertEqual(extract_price("$100 off PS5 Slim, now $399"), 399)
        self.assertEqual(extract_price("Save $150 on PS5 Slim Console $449.99"), 449.99)
        self.assertIsNone(extract_price("PS5 Slim deal"))

    def test_tekrar_bildirim_ve_fiyat_dususu(self):
        state = {"notified": {}, "observations": [], "errors": {}, "last_heartbeat": "", "recent_alerts": []}
        sent = []
        no_resolve = lambda u: u  # noqa: E731
        d1 = sd("PS5 Slim Disc Console 1TB $449", "bestbuy.com")
        self.assertEqual(process(state, [d1], send=lambda m: sent.append(m) or True, resolve=no_resolve), 1)
        # aynı fırsat tekrar → mesaj yok
        self.assertEqual(process(state, [sd("PS5 Slim Disc Console 1TB $449", "bestbuy.com")],
                                 send=lambda m: sent.append(m) or True, resolve=no_resolve), 0)
        # aynı fırsat, fiyat düştü → yeniden mesaj
        d3 = sd("PS5 Slim Disc Console 1TB $449", "bestbuy.com")
        d3.price = 429
        self.assertEqual(process(state, [d3], send=lambda m: sent.append(m) or True, resolve=no_resolve), 1)
        self.assertIn("Fiyat düştü", sent[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
