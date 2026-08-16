"""
build_dataset.py
-----------------
Step 1 of 2. Deterministic cleaning. No AI, no API key, no cost.

Rebuilds the product dataset from the ORIGINAL Shopify export
(products_export_1.csv) instead of products_cleaned.xlsx, because the
xlsx has two bugs:

  1. It gave all 986 non-product rows a fake price of 1110.0
  2. It threw away 245 REAL variant rows that carry real prices
     (e.g. M Cloud has 10 tiers from 260 to 59,920 THB)

Output: products_base.csv  (720 rows, one per product)

Run:  python build_dataset.py
"""

import html
import re

import pandas as pd
from bs4 import BeautifulSoup

SRC = "products_export_1.csv"
OUT = "products_base.csv"


# ---------------------------------------------------------------
# 1. Brand name cleanup  (assignment item #10)
# ---------------------------------------------------------------
# Manual overrides win. Anything not listed falls back to
# "most frequent casing in the file", which fixes typos automatically.
BRAND_OVERRIDES = {
    "zoom": "Zoom",
    "zoom ": "Zoom",
    "vmware": "VMware",
    "sonicwall": "SonicWall",
    "bittitan": "BitTitan",
    "eset nod32": "ESET NOD32",
    "proofpoint": "Proofpoint",
    "syndome": "Syndome",
    "alibabacloud": "Alibaba Cloud",
    "paloaltonetworks": "Palo Alto Networks",
    "cloudflare": "Cloudflare",
    "trendmicro": "Trend Micro",
    "green radar": "Green Radar",
    "sophoscentral": "Sophos Central",
    "sophoscentraly": "Sophos Central",
    "freshworkcrm": "Freshworks CRM",
    "huawei": "Huawei",
    "zcrlog": "zcrLog",
    "socradar": "SOCRadar",
    "sran": "SRAN",
    "prtg": "PRTG",
}


def build_brand_map(values):
    """lowercase key -> canonical display name."""
    counts = {}
    for v in values.dropna():
        key = v.strip().lower()
        counts.setdefault(key, {})
        counts[key][v.strip()] = counts[key].get(v.strip(), 0) + 1

    mapping = {}
    for key, variants in counts.items():
        if key in BRAND_OVERRIDES:
            mapping[key] = BRAND_OVERRIDES[key]
        else:
            # most frequent spelling; ties broken by longest (usually the
            # properly-capitalised one, e.g. "SonicWall" over "Sonicwall")
            mapping[key] = sorted(
                variants.items(), key=lambda kv: (-kv[1], -len(kv[0]))
            )[0][0]
    return mapping


def clean_brand(value, mapping):
    if pd.isna(value) or not str(value).strip():
        return ""
    return mapping.get(str(value).strip().lower(), str(value).strip())


# ---------------------------------------------------------------
# 2. HTML -> plain text
# ---------------------------------------------------------------
def html_to_text(raw):
    """Strip Shopify's Body (HTML) down to clean plain text."""
    if pd.isna(raw) or not str(raw).strip():
        return ""

    soup = BeautifulSoup(str(raw), "lxml")

    for tag in soup(["script", "style", "iframe", "noscript"]):
        tag.decompose()

    # keep table rows readable instead of mashing cells together
    for td in soup.find_all(["td", "th"]):
        td.insert_after(" | ")
    for br in soup.find_all(["br", "tr", "li", "p", "h1", "h2", "h3", "h4"]):
        br.insert_after("\n")

    text = soup.get_text()
    text = html.unescape(text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\| *\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------
# 3. Deployment detection  (assignment item #7)
# ---------------------------------------------------------------
DEPLOYMENT_RULES = [
    ("SaaS", [r"\bsaas\b", r"software as a service"]),
    ("Cloud", [r"\bcloud\b", r"คลาวด์", r"\bazure\b", r"\baws\b", r"\bgcp\b"]),
    ("On-Premise", [r"on-?premise", r"on-?prem\b", r"ออนพรีมิส", r"ติดตั้งภายในองค์กร"]),
    ("Virtual Appliance", [r"virtual appliance", r"\bova\b", r"\bvm\b", r"virtual machine"]),
    ("Hardware Appliance", [r"\bappliance\b", r"\brack\b", r"\b1u\b", r"hardware"]),
    ("Endpoint Agent", [r"\bagent\b", r"\bendpoint\b", r"เอเจนต์"]),
]


def detect_deployment(text):
    found = []
    low = text.lower()
    for label, patterns in DEPLOYMENT_RULES:
        if any(re.search(p, low) for p in patterns):
            found.append(label)
    return ", ".join(found)


# ---------------------------------------------------------------
# 4. Main
# ---------------------------------------------------------------
def main():
    df = pd.read_csv(SRC, low_memory=False)
    print(f"Loaded {len(df)} raw rows / {df['Handle'].nunique()} handles")

    vendor_map = build_brand_map(df["Vendor"])
    type_map = build_brand_map(df["Type"])

    records = []

    for handle, group in df.groupby("Handle", sort=False):
        # the parent row is the one that actually carries the Title
        parent_rows = group[group["Title"].notna()]
        if parent_rows.empty:
            continue
        parent = parent_rows.iloc[0]

        # --- variants: keep the REAL ones the xlsx deleted -------------
        variant_rows = group[
            group["Option1 Value"].notna()
            & (group["Option1 Value"] != "Default Title")
            & group["Variant Price"].notna()
        ]

        prices = group["Variant Price"].dropna()
        prices = prices[prices > 0]

        if len(variant_rows) > 0:
            variants = [
                f"{str(r['Option1 Value']).strip()} = {r['Variant Price']:,.0f} THB"
                for _, r in variant_rows.iterrows()
            ]
            variants_str = " ; ".join(variants)
            option_label = str(
                variant_rows["Option1 Name"].dropna().iloc[0]
                if variant_rows["Option1 Name"].notna().any()
                else ""
            ).strip()
        else:
            variants_str = ""
            option_label = ""

        if len(prices) == 0:
            price_min = price_max = None
            price_display = "ติดต่อสอบถาม / Contact for pricing"
        else:
            price_min, price_max = prices.min(), prices.max()
            if price_min == price_max:
                price_display = f"{price_min:,.0f} THB"
            else:
                price_display = f"{price_min:,.0f} - {price_max:,.0f} THB"

        description = html_to_text(parent.get("Body (HTML)"))

        records.append(
            {
                "Handle": handle,
                "Title": str(parent["Title"]).strip(),
                "Vendor": clean_brand(parent.get("Vendor"), vendor_map),
                "Type_Original": clean_brand(parent.get("Type"), type_map),
                "Category_Original": (
                    "" if pd.isna(parent.get("Product Category"))
                    else str(parent["Product Category"]).strip()
                ),
                "Tags": "" if pd.isna(parent.get("Tags")) else str(parent["Tags"]).strip(),
                "Price_Min": price_min,
                "Price_Max": price_max,
                "Price_Display": price_display,
                "Variant_Count": len(variant_rows),
                "Option_Label": option_label,
                "Variants": variants_str,
                "Deployment": detect_deployment(f"{parent['Title']} {description}"),
                "Description": description,
                "Description_Length": len(description),
                "URL": f"https://mon.co.th/products/{handle}",
            }
        )

    out = pd.DataFrame(records)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")

    print(f"\nWrote {OUT}: {len(out)} products")
    print(f"  with real variants : {(out['Variant_Count'] > 0).sum()}")
    print(f"  variant rows kept  : {out['Variant_Count'].sum()}")
    print(f"  empty description  : {(out['Description_Length'] == 0).sum()}")
    print(f"  deployment detected: {(out['Deployment'] != '').sum()}")
    print(f"  median desc length : {out['Description_Length'].median():.0f}")


if __name__ == "__main__":
    main()
