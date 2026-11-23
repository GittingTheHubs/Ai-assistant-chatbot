"""
ict68.py
--------
ICT68 Assistant: answers questions about the DE Ministry's
"เกณฑ์ราคากลางและคุณลักษณะพื้นฐานการจัดหาอุปกรณ์และระบบคอมพิวเตอร์
ฉบับเดือนธันวาคม 2568" and points to MON products that meet an item.

Deterministic on purpose, like the comparison engine: the answer is
built in Python from two CSV files, so the LLM cannot invent a price
or a spec.

    data/ict68/ict68_items.csv        70 items: price + minimum specs
    data/ict68/ict68_product_map.csv  item -> MON product title,
                                      only where it is confirmed

shortcut: ict68_items.csv was transcribed by hand from the PDF in
data/ict68/, re-transcribe (or add a PDF parser) when the next
edition comes out.
"""

import os
import re
from typing import List, Optional

import pandas as pd


HERE = os.path.dirname(os.path.abspath(__file__))
ITEMS_CSV = os.path.join(HERE, "data", "ict68", "ict68_items.csv")
MAP_CSV = os.path.join(HERE, "data", "ict68", "ict68_product_map.csv")

ITEMS = pd.read_csv(ITEMS_CSV, encoding="utf-8").to_dict("records")
BY_NO = {item["item"]: item for item in ITEMS}
PRODUCT_MAP = pd.read_csv(MAP_CSV, encoding="utf-8")

SOURCE = (
    "เกณฑ์ราคากลางและคุณลักษณะพื้นฐานการจัดหาอุปกรณ์และระบบคอมพิวเตอร์ "
    "ฉบับเดือนธันวาคม 2568 (กระทรวงดิจิทัลเพื่อเศรษฐกิจและสังคม)"
)

DISCLAIMER = (
    f"_อ้างอิง: {SOURCE} ประกาศ 1 ธ.ค. 2568 ราคากลางรวม VAT 7% "
    "ค่าขนส่งและติดตั้ง และรับประกันอย่างน้อย 1 ปี สเปคที่แสดงเป็น"
    "คุณลักษณะขั้นต่ำแบบย่อ กรุณาตรวจกับเอกสารฉบับจริงและฝ่ายขาย"
    "ก่อนนำไปใช้ใน TOR_"
)

CONTACT = (
    "ติดต่อฝ่ายขายเพื่อเสนอสินค้าที่เข้าเกณฑ์: Line @monsteronline, "
    "โทร 02-026-6664, sales@mon.co.th"
)


# ============================================================
# INTENT
# ============================================================

INTENT = re.compile(
    r"ict\s*-?\s*6\d"
    r"|ราคากลาง|คุณลักษณะพื้นฐาน|งบราชการ|ราชการ|ภาครัฐ|หน่วยงานรัฐ"
    r"|\btor\b|กระทรวงดิจิทัล|กระทรวง\s*de\b"
    r"|(?:spec|สเปค|สเปก|เกณฑ์|ตาม|เข้า)\s*ict"
)


def is_ict68_query(question: str) -> bool:
    return bool(INTENT.search(question.lower()))


# ============================================================
# ITEM DETECTION
# ============================================================

# First match wins, so the specific groups come before the
# generic ones ("multifunction" before "printer", "load balancer"
# and "OS" before "server").
GROUPS = [
    (r"load\s*balanc|กระจายการทำงาน", [38]),
    (r"co-?location|เช่าพื้นที่", [64]),
    (r"ระบบปฏิบัติการ|\bos\b", [65, 66]),
    (r"แอนตี้ไวรัส|anti-?virus|ไวรัส", [70]),
    (r"e-?mail|อีเมล|spam|สแปม", [28]),
    (r"โปรแกรม\S*สำนักงาน|office\s*(?:suite|software|365)|microsoft office|\bword\b|excel", [67, 68, 69]),
    (r"multi\s*-?function|มัลติฟังก์ชั่?น", [48, 49, 50]),
    (r"all\s*-?in\s*-?one|\baio\b|ออลอินวัน", [7, 8]),
    (r"แท็บเล็ต|แท็ปเล็ต|tablet|ipad", [14, 15]),
    (r"โน้?๊?ตบุ๊[กค]|โน๊ตบุ๊[กค]|notebook|laptop|แล็?ปท็อป|chromebook", [9, 10, 11, 12, 13]),
    (r"แม่ข่าย|server|เซิร์ฟเวอร์", [1, 2, 3]),
    (r"\bnas\b", [16]),
    (r"\bsan\b", [17]),
    (r"\blog\b|ล็อก|log\s*file", [18, 19, 20, 21, 22, 23]),
    (r"firewall|ไฟร์วอลล์|ngfw", [24, 25]),
    (r"\bips\b|intrusion|บุกรุก", [26, 27]),
    (r"rack|ตู้", [29, 30]),
    (r"\bl3\b|layer\s*3", [34]),
    (r"switch|สวิตช์|สวิทช์", [31, 32, 33, 34]),
    (r"access\s*point|\bap\b|wi-?fi|ไวไฟ|ไร้สาย", [35, 36]),
    (r"router|เราเตอร์", [37]),
    (r"dot\s*-?matrix|ดอทเมทริกซ์|แคร่", [39, 40]),
    (r"\b3d\b|3\s*มิติ", [51]),
    (r"thermal|ความร้อน|บาร์โค้ด|barcode|label|ฉลาก", [52]),
    (r"ink\s*-?tank|อิงค์แทงค์|ฉีดหมึก", [41, 48]),
    (r"เลเซอร์|laser|\bled\b|\ba3\b", [42, 43, 44, 45, 46, 47]),
    (r"printer|ปริ้น|พริ้น|เครื่องพิมพ์", list(range(39, 53))),
    (r"สแกน|scanner", [53, 54, 55]),
    (r"smart\s*card|เครื่องอ่านบัตร|บัตรประชาชน", [56]),
    (r"\bups\b|สำรองไฟ", [59, 60, 61, 62, 63]),
    (r"คอมพิวเตอร์|คอม|\bpc\b|desktop", [4, 5, 6]),
    (r"จอ|monitor", [57, 58]),
]

# Words in the question -> text that must appear in the item name.
USAGE = [
    (r"สำนักงาน|office|เอกสาร", "สำนักงาน"),
    (r"ประมวลผล|กราฟิก|ตัดต่อ|render|วิศว", "ประมวลผล"),
    (r"\bai\b|ปัญญาประดิษฐ์", "ปัญญาประดิษฐ์"),
    (r"เว็บ|browser|chromebook|ออนไลน์", "เว็บเบราว์เซอร์"),
    (r"cloud|คลาวด์|เช่า|รายเดือน", "Cloud"),
    (r"appliance|อุปกรณ์จัดเก็บ", "อุปกรณ์จัดเก็บ"),
    # Thai tone marks are not \w, so "สี่" (four) would pass \bสี\b.
    (r"สี(?![ก-๙])|colou?r", " สี "),
    (r"ขาวดำ|mono", "ขาวดำ"),
    (r"แม่ข่าย|server", "แม่ข่าย"),
]

THAI_UNITS = {"k": 1e3, "พัน": 1e3, "หมื่น": 1e4, "แสน": 1e5, "ล้าน": 1e6}


def _narrow(items: List[dict], keep) -> List[dict]:
    """Apply a filter only if something survives it."""
    kept = [item for item in items if keep(item)]
    return kept or items


def find_items(question: str) -> List[dict]:
    q = question.lower()

    explicit = re.search(r"ข้อ(?:ที่)?\s*(\d{1,2})\b|item\s*(\d{1,2})\b", q)
    if explicit:
        number = int(explicit.group(1) or explicit.group(2))
        if number in BY_NO:
            return [BY_NO[number]]

    numbers = next(
        (nums for pattern, nums in GROUPS if re.search(pattern, q)),
        None,
    )
    if numbers is None:
        return []

    items = [BY_NO[n] for n in numbers]

    for pattern, needle in USAGE:
        if re.search(pattern, q):
            items = _narrow(items, lambda i, n=needle: n in f" {i['name']} ")

    tier = re.search(r"(?:แบบที่|แบบ|type|tier|ict)\s*([1-3])\b", q)
    if tier:
        items = _narrow(items, lambda i: f"แบบที่ {tier.group(1)}" in i["name"])

    size = re.search(r"(\d+(?:\.\d+)?)\s*(kva|va|u\b|นิ้ว|ช่อง|หน้า)", q)
    if size:
        token = (size.group(1) + size.group(2)).replace(" ", "")
        items = _narrow(
            items,
            lambda i: token in i["name"].lower().replace(" ", ""),
        )

    budget = re.search(r"งบ[^\d]{0,12}([\d,]+(?:\.\d+)?)\s*(k|พัน|หมื่น|แสน|ล้าน)?", q)
    if budget:
        amount = float(budget.group(1).replace(",", ""))
        amount *= THAI_UNITS.get(budget.group(2) or "", 1)
        items = _narrow(items, lambda i: i["price"] <= amount)

    return items


def items_for_product(title: str) -> List[dict]:
    rows = PRODUCT_MAP[PRODUCT_MAP["title"] == title]
    return [BY_NO[n] for n in rows["item"]]


# ============================================================
# FORMATTING
# ============================================================

def _price(item: dict) -> str:
    return f"{item['price']:,} {item['unit']}"


def _products(item: dict, catalog: pd.DataFrame) -> List[str]:
    lines = []
    for _, mapped in PRODUCT_MAP[PRODUCT_MAP["item"] == item["item"]].iterrows():
        row = catalog[catalog["Title"] == mapped["title"]]
        if row.empty:
            continue
        row = row.iloc[0]
        lines.append(
            f"- [{row['Title']}]({row['URL']}) ราคา {row['Price_Display']} "
            f"({mapped['basis']})"
        )
    return lines


def _item_block(item: dict, catalog: pd.DataFrame) -> str:
    specs = "\n".join(f"- {s.strip()}" for s in item["specs"].split(" | "))
    products = _products(item, catalog)
    product_text = (
        "\n".join(products)
        if products
        else "- ยังไม่มีสินค้าในระบบที่ยืนยันว่าเข้าเกณฑ์ข้อนี้ " + CONTACT
    )
    return (
        f"### ข้อ {item['item']}: {item['name']}\n"
        f"**ราคากลาง:** {_price(item)}\n\n"
        f"**คุณลักษณะพื้นฐาน (ขั้นต่ำ):**\n{specs}\n\n"
        f"**สินค้า MON ที่ตรงเกณฑ์ข้อนี้:**\n{product_text}"
    )


def _item_line(item: dict) -> str:
    mapped = (PRODUCT_MAP["item"] == item["item"]).sum()
    note = f" (มีสินค้า MON {mapped} รุ่น)" if mapped else ""
    return f"- ข้อ {item['item']}: {item['name']} ราคากลาง {_price(item)}{note}"


def _overview() -> str:
    mapped = sorted(set(PRODUCT_MAP["item"]))
    return (
        f"**{SOURCE}** มีทั้งหมด {len(ITEMS)} รายการ ครอบคลุมเครื่องแม่ข่าย, "
        "คอมพิวเตอร์/โน้ตบุ๊ก/แท็บเล็ต, Storage, ระบบจัดเก็บ Log, Firewall, IPS, "
        "e-Mail Security, Switch, Access Point, Router, เครื่องพิมพ์, สแกนเนอร์, "
        "จอ, UPS และซอฟต์แวร์\n\n"
        "ถามได้เช่น \"โน้ตบุ๊กสำนักงานตามเกณฑ์ ICT68\", \"Log ICT แบบที่ 2\", "
        "\"UPS 1.5 kVA ราคากลางเท่าไหร่\" หรือ \"ข้อ 24\"\n\n"
        f"ข้อที่ MON มีสินค้ายืนยันว่าเข้าเกณฑ์: "
        f"{', '.join(str(n) for n in mapped)}"
    )


def answer(
    question: str,
    catalog: pd.DataFrame,
    product_title: Optional[str] = None,
) -> str:
    """Build the full ICT68 answer. Always ends with the disclaimer."""

    # main.resolve_product misses short model names ("SRAN NG100"),
    # so also look for the model part of every mapped title.
    if not product_title:
        q = question.lower()
        product_title = next(
            (t for t in PRODUCT_MAP["title"] if t.split(" - ")[0].lower() in q),
            None,
        )

    if product_title:
        items = items_for_product(product_title)
        if items:
            body = (
                f"**{product_title}** ตรงกับเกณฑ์ "
                + ", ".join(f"ข้อ {i['item']}" for i in items)
                + "\n\n"
                + "\n\n".join(_item_block(i, catalog) for i in items)
            )
        else:
            body = (
                f"ยังไม่มีข้อมูลยืนยันว่า **{product_title}** เข้าเกณฑ์ข้อใด"
                f"ในฉบับ ธ.ค. 2568 {CONTACT}"
            )
        return f"{body}\n\n{DISCLAIMER}"

    items = find_items(question)

    if not items:
        body = _overview()
    elif len(items) <= 2:
        body = "\n\n".join(_item_block(i, catalog) for i in items)
    else:
        body = (
            f"เกณฑ์ที่เกี่ยวข้องมี {len(items)} ข้อ:\n"
            + "\n".join(_item_line(i) for i in items)
            + "\n\nระบุแบบที่ ขนาด การใช้งาน หรืองบประมาณ "
            "(เช่น \"แบบที่ 2\" หรือ \"งบ 20,000\") เพื่อดูสเปคขั้นต่ำเต็ม"
        )

    return f"{body}\n\n{DISCLAIMER}"
