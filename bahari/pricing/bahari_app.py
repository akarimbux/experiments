"""
Streamlit front‑end for the Bahari price‑list tool.
"""

# --- ensure repo root is importable no matter where Streamlit runs ----
import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import streamlit as st
st.set_page_config(page_title="Bahari Price List", layout="wide")

import streamlit.components.v1 as components

import sqlalchemy as sa
import pandas as pd
import jinja2

from pricing.models import Base, Fx, Item, Category

engine = sa.create_engine("sqlite:///bahari.db")

# ------------------------------------------------------------------ FX helpers
def load_fx() -> dict:
    """Return FX rates as {code: rate}."""
    with sa.orm.Session(engine) as s:
        return {f.code: f.rate for f in s.query(Fx).all()}

def load_fx_df() -> pd.DataFrame:
    """Return FX table as DataFrame for the editor."""
    return pd.read_sql("SELECT code, rate FROM fx", engine)

# ------------------------------------------------------------------ Streamlit UI
st.sidebar.title("Bahari 🐟")

tab_fx, tab_price, tab_preview = st.tabs(["FX", "Price list", "Preview"])

# ---------------- FX TAB ------------------------------------------------------
with tab_fx:
    st.subheader("Exchange rates")

    fx_df = st.data_editor(
        load_fx_df(),
        num_rows="dynamic",
        key="fx_editor",
        use_container_width=True,
    )

    if st.button("Update FX", key="save_fx"):
        cleaned = (
            fx_df.dropna(subset=["code", "rate"])
                 .assign(code=lambda d: d["code"].str.strip().str.upper())
                 .query("code != ''")
        )
        with sa.orm.Session(engine) as s:
            s.query(Fx).delete()                 # overwrite
            s.bulk_save_objects(
                [Fx(code=row.code, rate=float(row.rate))
                 for row in cleaned.itertuples(index=False)]
            )
            s.commit()
        st.success("Exchange rates updated")

# ---------------- PRICE LIST TAB ---------------------------------------------
with tab_price:
    st.subheader("Products")

    q = (
        "SELECT item.id, category.name AS cat, item.sub_category, "
        "item.name AS name, item.pack, item.currency, item.base_cost, "
        "item.margin_pct, item.vat "
        "FROM item JOIN category ON item.category_id = category.id "
        "ORDER BY item.id"
    )

    df = pd.read_sql(q, engine)
    df["fx_rate"] = df["currency"].map(load_fx())

    edited = st.data_editor(
        df,
        num_rows="dynamic",
        key="items",
        use_container_width=True,
    )

    if st.button("Update products"):
        with sa.orm.Session(engine) as s:
            for row in edited.itertuples(index=False):
                itm = s.get(Item, row.id) if row.id else Item()
                itm.category = (
                    s.query(Category).filter_by(name=row.cat).first()
                    or Category(name=row.cat)
                )
                # normalise incoming values before saving
                itm.sub_category = row.sub_category
                itm.name         = row.name
                itm.pack         = row.pack
                itm.currency     = row.currency
                itm.base_cost    = float(row.base_cost or 0)

                # margin_pct can be entered as 0.2 or 20 → always store decimal
                try:
                    m = float(row.margin_pct or 0)
                    itm.margin_pct = m / 100 if m > 1 else m
                except ValueError:
                    itm.margin_pct = 0.0

                # vat column accepts 0/1, 0/18, true/false, yes/no
                v = str(row.vat).strip().lower()
                if v in ("1", "true", "yes", "y", "18", "vat"):
                    itm.vat = True
                else:
                    itm.vat = False
                s.add(itm)
            s.commit()
        st.success("Products updated")

# ---------------- PREVIEW TAB -------------------------------------------------
with tab_preview:
    st.subheader("Live price list")

    fx = load_fx()
    df = pd.read_sql(q, engine)
    df["sell px"] = (
        df.apply(
            lambda r: Item.sell_price(
                Item(base_cost=r.base_cost,
                     currency=r.currency,
                     margin_pct=r.margin_pct,
                     vat=r.vat),
                fx),
            axis=1)
        .round(2)
    )
    df["fx_rate"] = df["currency"].map(fx)

    # build a view with original cost, margin %, and VAT flag
    view_cols = ["cat", "sub_category", "name", "pack",
                 "currency", "base_cost", "margin_pct", "vat",
                 "fx_rate", "sell px"]

    st.dataframe(
        df[view_cols].rename(columns={
            "base_cost": "orig px",
            "margin_pct": "margin %",
            "vat": "VAT",
            "fx_rate": "fx_rate",
            "sell px": "sell px"
        }),
        use_container_width=True,
    )

    # ------------- HTML preview -------------------------------------------
    # build hierarchical structure in DB order
    df_sorted = df.copy()

    pdf_groups = []
    for cat_name, cat_df in df_sorted.groupby("cat", sort=False):
        cat_rec = {"cat": cat_name, "subs": []}
        for sub_name, sub_df in cat_df.groupby("sub_category",
                                               sort=False,
                                               dropna=False):
            cat_rec["subs"].append({
                "sub": sub_name or "",
                "rows": sub_df.to_dict("records")
            })
        pdf_groups.append(cat_rec)

    template_dir = pathlib.Path(__file__).parent
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(template_dir)))
    html_preview = env.get_template("pricelist.html").render(groups=pdf_groups)

    # force white background when Streamlit is in dark mode
    styled_preview = (
        "<style>body{background:#fff;color:#000}</style>" + html_preview
    )
    with st.expander("⬇️ HTML preview"):
        components.html(styled_preview, height=600, scrolling=True)

    if st.button("Generate PDF"):
        import jinja2, weasyprint, tempfile

        # write the PDF from the same html_preview
        tmp = pathlib.Path(tempfile.mktemp(suffix=".pdf"))
        weasyprint.HTML(string=html_preview).write_pdf(tmp)

        st.success("PDF ready")
        st.download_button(
            "📥 Download",
            tmp.read_bytes(),
            "price_list.pdf",
            "application/pdf"
        )