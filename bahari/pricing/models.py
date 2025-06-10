from sqlalchemy import Column, Integer, Float, Boolean, String, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
Base = declarative_base()

class Fx(Base):
    __tablename__ = "fx"
    code   = Column(String, primary_key=True)     # “EUR”, “USD” …
    rate   = Column(Float, nullable=False)        # → local currency

class Category(Base):
    __tablename__ = "category"
    id     = Column(Integer, primary_key=True)
    name   = Column(String, unique=True)
    items  = relationship("Item", back_populates="category")

class Item(Base):
    __tablename__ = "item"
    id            = Column(Integer, primary_key=True)
    category_id   = Column(Integer, ForeignKey("category.id"))
    sub_category  = Column(String)
    name          = Column(String)                # “Norwegian Salmon | HOG | 2‑3 kg”
    pack          = Column(String)                # “IQF 20 kg”
    currency      = Column(String)                # original buy‑currency
    base_cost     = Column(Float)                 # supplier cost in *currency*
    margin_pct    = Column(Float, default=0.0)    # 0.15 = 15 %
    vat           = Column(Boolean, default=False)
    category      = relationship("Category", back_populates="items")

    # --- helper properties -----------------------------------------
    def landed_cost(self, fx: dict):
        return self.base_cost * fx.get(self.currency, 1) 

    def sell_price(self, fx: dict):
        p = self.landed_cost(fx) * (1 + self.margin_pct)
        return p * 1.18 if self.vat else p