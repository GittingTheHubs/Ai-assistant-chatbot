"""
test_ict68.py
-------------
Offline tests for the ICT68 engine (ict68.py + its route in main.py).
Reuses test_recommend's Ollama stubs, so no model is needed.

Run:
    python test_ict68.py
"""

import sys

from test_recommend import bot, check, section, FAILURES  # installs stubs
import test_recommend
import ict68


def ask(question, memory=None):
    answer, _, _, kind = bot.process_question(
        question, None, None, memory or [], False
    )
    return answer, kind


def nums(question):
    return [i["item"] for i in ict68.find_items(question)]


def test_data():
    section("ICT68 data matches the PDF")

    check(len(ict68.ITEMS) == 70, "70 items")
    check([i["item"] for i in ict68.ITEMS] == list(range(1, 71)), "items numbered 1..70")
    check(all(i["price"] > 0 for i in ict68.ITEMS), "every item has a price")
    check(all(str(i["specs"]).strip() for i in ict68.ITEMS), "every item has specs")

    # Every ราคากลาง, read a second time from the PDF headings.
    pdf_prices = [
        130000, 330000, 780000, 20000, 24000, 34000, 20000, 26000, 19000, 24000,
        30000, 17000, 21000, 10000, 22000, 35000, 590000, 8000, 13000, 18000,
        50000, 400000, 850000, 220000, 1000000, 330000, 1400000, 350000, 18000, 22000,
        2400, 3500, 13000, 100000, 4000, 22000, 33000, 200000, 24000, 27000,
        4100, 3400, 8900, 16000, 12000, 25000, 53000, 8000, 11000, 16000,
        40000, 11000, 15000, 23000, 33000, 700, 3000, 4300, 2500, 6000,
        12000, 29000, 260000, 40000, 5500, 45500, 18500, 11000, 4500, 700,
    ]
    for n, price in enumerate(pdf_prices, 1):
        check(ict68.BY_NO[n]["price"] == price, f"item {n} price {price:,}")

    titles = set(bot.df["Title"])
    missing = set(ict68.PRODUCT_MAP["title"]) - titles
    check(not missing, f"every mapped product exists in the catalog {missing or ''}")

    for _, row in ict68.PRODUCT_MAP.iterrows():
        price = bot.df.loc[bot.df["Title"] == row["title"], "Price_num"].iloc[0]
        limit = ict68.BY_NO[row["item"]]["price"]
        check(price <= limit, f"{row['title']} ({price:,.0f}) within item {row['item']} ({limit:,})")


def test_intent():
    section("ICT68 intent")

    for q in [
        "โน้ตบุ๊กตามเกณฑ์ ICT68", "ราคากลาง firewall", "สเปคราชการ UPS",
        "ict 68 คืออะไร", "ต้องการจัดซื้อตาม spec ict", "หน่วยงานรัฐซื้อ switch",
    ]:
        check(ict68.is_ict68_query(q), f"ICT68: {q}")

    for q in [
        "zcrLog ICT1 ราคาเท่าไหร่", "Recommend me a laptop", "แนะนำ firewall",
        "Compare Safetica and Safetica Pro", "ราคา SRAN NG50",
    ]:
        check(not ict68.is_ict68_query(q), f"not ICT68: {q}")


def test_item_detection():
    section("ICT68 item detection")

    cases = {
        "ข้อ 24": [24],
        "โน้ตบุ๊กสำนักงานตามเกณฑ์ ICT68": [9],
        "notebook ai ict68": [11],
        "โน้ตบุ๊ก office ตามเกณฑ์ ict68": [9],
        "Log ICT แบบที่ 2": [19, 22],
        "log cloud ราคากลาง": [18, 19, 20],
        "อุปกรณ์จัดเก็บ log แบบที่ 3 ราคากลาง": [23],
        "UPS 1.5 kVA ราคากลางเท่าไหร่": [60],
        "ราคากลาง firewall": [24, 25],
        "ราคากลางเครื่องพิมพ์เลเซอร์สี": [45, 46],
        "ราคากลาง multifunction สี": [50],
        "ราคากลาง ตู้ rack 42U": [30],
        "ราคากลางคอมพิวเตอร์ จอ 27 นิ้ว": [6],
        "ราคากลางจอ 23 นิ้ว": [57],
        "ราคากลาง os server": [66],
        "โปรแกรมสำนักงาน ราคากลาง": [67, 68, 69],
        "โน้ตบุ๊ก งบ 20,000 ict68": [9, 12],
        "ict68 คืออะไร": [],
    }
    for q, expected in cases.items():
        got = nums(q)
        check(got == expected, f"{q!r} -> {expected} (got {got})")


def test_answers():
    section("ICT68 answers through process_question")

    answer, kind = ask("Log ICT แบบที่ 1 ราคากลาง")
    check(kind == "ICT68 Engine", "routed to ICT68 Engine")
    check("ข้อ 18" in answer and "ข้อ 21" in answer, "shows both tier-1 log items")
    check("50,000 บาท" in answer and "8,000 บาท/เดือน" in answer, "exact ราคากลาง")
    for title in ["zcrLog ICT1 - Log พรบ. ICT 1", "SRAN NG50 - Log ICT 1", "NetEvid V110 ICT 1"]:
        check(title in answer, f"links {title}")
    check("https://mon.co.th/products/" in answer, "has a product link")
    check("ธันวาคม 2568" in answer, "has the disclaimer")

    answer, kind = ask("ราคากลาง firewall ict68 แบบที่ 1")
    check(kind == "ICT68 Engine", "firewall routed to ICT68 Engine")
    check("220,000 บาท" in answer, "firewall ราคากลาง")
    check("sales@mon.co.th" in answer, "no confirmed product -> sales contact")
    check("ธันวาคม 2568" in answer, "disclaimer on unmapped item")

    answer, kind = ask("SRAN NG100 เข้าเกณฑ์ ict68 ข้อไหน")
    check(kind == "ICT68 Engine", "product question routed to ICT68 Engine")
    check("ข้อ 22" in answer, "SRAN NG100 -> item 22")

    answer, _ = ask("ict68 คืออะไร")
    check("70 รายการ" in answer, "overview for a general question")

    answer, _ = ask("ราคากลางเครื่องพิมพ์")
    check("ระบุแบบที่" in answer, "many items -> short list with a hint")


if __name__ == "__main__":

    for test in [test_data, test_intent, test_item_detection, test_answers]:
        try:
            test()
        except Exception as exc:
            FAILURES.append(f"{test.__name__} crashed: {exc!r}")
            import traceback
            traceback.print_exc()

    checks = test_recommend.CHECKS
    print()
    print("=" * 70)
    print(f"{checks - len(FAILURES)} / {checks} checks passed")
    print("=" * 70)
    for failure in FAILURES:
        print(f"  FAIL  {failure}")
    sys.exit(1 if FAILURES else 0)
