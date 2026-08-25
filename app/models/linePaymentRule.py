from sqlalchemy import Column, ForeignKey, Float, Integer
from app.db import Base


class LinePaymentRule(Base):
    __tablename__ = "line_payment_rules"

    id_line_payment_rule = Column(Integer, primary_key=True, index=True)
    id_line = Column(Integer, ForeignKey("lines.id_line"), nullable=False)
    payment_pct = Column(Float, nullable=False)
    payment_days = Column(Integer, nullable=False)
