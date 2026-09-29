"""Create webhook delivery and CRM simulator tables."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260929_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "delivering",
                "delivered",
                "retrying",
                "dead_letter",
                name="eventstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhook_events_event_type", "webhook_events", ["event_type"])
    op.create_index(
        "ix_webhook_events_provider_event_id",
        "webhook_events",
        ["provider_event_id"],
        unique=True,
    )
    op.create_index("ix_webhook_events_status", "webhook_events", ["status"])

    op.create_table(
        "delivery_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["webhook_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "crm_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=False),
        sa.Column("customer_email", sa.String(length=320), nullable=True),
        sa.Column("amount_total", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=12), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_crm_records_source_event_id",
        "crm_records",
        ["source_event_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_crm_records_source_event_id", table_name="crm_records")
    op.drop_table("crm_records")
    op.drop_table("delivery_attempts")
    op.drop_index("ix_webhook_events_status", table_name="webhook_events")
    op.drop_index("ix_webhook_events_provider_event_id", table_name="webhook_events")
    op.drop_index("ix_webhook_events_event_type", table_name="webhook_events")
    op.drop_table("webhook_events")
