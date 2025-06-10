# bahari/parse_pdf.py
import re
import pathlib
import pdfplumber
import sqlalchemy as sa

from .models import Base, Category, Item, Fx  # relative import

PDF = pathlib.Path("pricing/Pricelist CIF DAR January.pdf")
DB  = "sqlite:///bahari.db"

# ------------------------------------------------------------------
engine = sa.create_engine(DB, echo=False)
Base.metadata.create_all(engine)
session = sa.orm.Session(engine)

# Wipe any previous load so reruns stay idempotent
session.query(Item).delete()
session.query(Category).delete()

cat = None
subcat = None
categories = {}
price_re = re.compile(r"(\d+(?:,\d{2}))\s+(In Stock|On Request|During)", re.I)

with pdfplumber.open(PDF) as doc:
    for pg in doc.pages:
        for line in pg.extract_text().splitlines():
            line = line.strip()

            # --- CATEGORY lines e.g. "SALMON (Salmo salar) Price (€/kg) Availability"
            m_cat = re.match(r"^([A-Z][A-Z ]+)\s*\(", line)
            if m_cat and "Price" in line:
                cat_name = m_cat.group(1).strip().title()      # "Salmon"

                # reuse existing object within the same run to avoid UNIQUE errors
                if cat_name in categories:
                    cat = categories[cat_name]
                else:
                    cat = Category(name=cat_name)
                    session.add(cat)
                    categories[cat_name] = cat

                subcat = None
                continue

            # --- SUB‑CATEGORY lines: e.g. "Salmon whole"
            if cat and "|" not in line and price_re.search(line) is None:
                subcat = line
                continue

            # --- PRODUCT rows containing a price and stock status
            m = price_re.search(line)
            if cat and m:
                price = float(m.group(1).replace(",", "."))
                name_part = line.split(m.group(1))[0].strip()

                session.add(Item(
                    category=cat,
                    sub_category=subcat or "",
                    name=name_part,
                    pack="",                 # pack info not parsed here
                    currency="EUR",
                    base_cost=price,
                    margin_pct=0.0,
                    vat=False
                ))

session.commit()
print(
    f"Seeded {session.query(Category).count()} categories / "
    f"{session.query(Item).count()} items"
)
session.close()