"""Один платёж — один заказ: ограничение в базе (аудит F69).

Дубль заказа был защищён ТОЛЬКО проверкой в коде, хотя в платёжном журнале
F49 такое же правило с самого начала стоит ограничением в базе. Между
проверкой «такого заказа ещё нет» и вставкой помещается вторая доставка
того же апдейта — и покупатель получает две посылки за одни деньги.

NULL допустим намеренно: заказ может существовать без платежа (создан
вручную), а в SQL уникальность на NULL не срабатывает, что здесь как раз
нужно — таких заказов может быть много.

Revision ID: 0046_order_charge_unique
Revises: 0045_shop
"""

from __future__ import annotations

from alembic import op

revision = "0046_order_charge_unique"
down_revision = "0045_shop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Индекс по `charge_id` уже есть (неуникальный) — заменяем его на
    # уникальное ограничение через batch: SQLite не умеет ADD CONSTRAINT.
    op.drop_index("ix_orders_charge_id", table_name="orders")
    with op.batch_alter_table("orders") as batch:
        batch.create_unique_constraint("uq_order_charge", ["charge_id"])
    op.create_index("ix_orders_charge_id", "orders", ["charge_id"])


def downgrade() -> None:
    op.drop_index("ix_orders_charge_id", table_name="orders")
    with op.batch_alter_table("orders") as batch:
        batch.drop_constraint("uq_order_charge", type_="unique")
    op.create_index("ix_orders_charge_id", "orders", ["charge_id"])
