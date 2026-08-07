from datetime import datetime
from decimal import Decimal
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_code = Column(String(32), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(20), default="free")
    is_active = Column(Boolean, default=True)
    subscription_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    watchlists = relationship("Watchlist", back_populates="user")
    alerts = relationship("Alert", back_populates="user")
    subscriptions = relationship("Subscription", back_populates="user")


class Product(Base):
    __tablename__ = "products"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    brand = Column(String(255), nullable=True)
    category = Column(String(255), nullable=True)
    sku_normalized = Column(String(255), nullable=True, index=True)
    image_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    store_products = relationship("StoreProduct", back_populates="product")
    watchlists = relationship("Watchlist", back_populates="product")
    alerts = relationship("Alert", back_populates="product")


class ScrapingLog(Base):
    __tablename__ = "scraping_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    store = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)
    details = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class StoreProduct(Base):
    __tablename__ = "store_products"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    store = Column(String(50), nullable=False)
    store_sku = Column(String(255), nullable=True)
    url = Column(Text, nullable=True)
    current_price = Column(Numeric(10, 2), nullable=True)
    original_price = Column(Numeric(10, 2), nullable=True)
    # Precio exclusivo con tarjeta (CMR/Única). Se guarda aparte de current_price
    # porque no es el precio público, pero es donde aparecen los glitches virales.
    card_price = Column(Numeric(10, 2), nullable=True)
    discount_percentage = Column(Numeric(5, 2), nullable=True)
    in_stock = Column(Boolean, default=True)
    last_scraped_at = Column(DateTime(timezone=True), nullable=True)

    product = relationship("Product", back_populates="store_products")
    price_history = relationship("PriceHistory", back_populates="store_product")


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    store_product_id = Column(String(36), ForeignKey("store_products.id"), nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    original_price = Column(Numeric(10, 2), nullable=True)
    in_stock = Column(Boolean, default=True)
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())

    store_product = relationship("StoreProduct", back_populates="price_history")


class Watchlist(Base):
    __tablename__ = "watchlists"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    target_price = Column(Numeric(10, 2), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="watchlists")
    product = relationship("Product", back_populates="watchlists")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    store = Column(String(50), nullable=True)
    condition = Column(String(30), nullable=False)
    threshold_value = Column(Numeric(10, 2), nullable=False)
    notification_channels = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="alerts")
    product = relationship("Product", back_populates="alerts")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    plan = Column(String(20), nullable=False, default="free")
    culqi_subscription_id = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="active")
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="subscriptions")


class SystemConfiguration(Base):
    """Configuración de la plataforma (módulo Administración → Configuración).

    Una fila por (environment, category, key). `environment` permite tener
    Desarrollo / QA / Producción en la misma base sin pisarse.
    El valor se guarda como texto y `value_type` dice cómo interpretarlo; el
    catálogo (`app.services.settings_catalog`) es la fuente del tipo y del default.
    """

    __tablename__ = "system_configurations"
    __table_args__ = (
        UniqueConstraint("environment", "category", "key", name="uq_system_config_env_cat_key"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    environment = Column(String(20), nullable=False, default="development", index=True)
    category = Column(String(40), nullable=False, index=True)
    key = Column(String(60), nullable=False)
    value = Column(Text, nullable=True)
    value_type = Column(String(20), nullable=False, default="text")
    description = Column(Text, nullable=True)
    updated_by = Column(String(120), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SystemConfigurationAudit(Base):
    """Bitácora de cambios de configuración: quién, cuándo, antes y después."""

    __tablename__ = "system_configuration_audit"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    environment = Column(String(20), nullable=False, default="development", index=True)
    category = Column(String(40), nullable=False, index=True)
    key = Column(String(60), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    updated_by = Column(String(120), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
