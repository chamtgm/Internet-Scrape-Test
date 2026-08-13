"""initial schema

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False, server_default=""),
        sa.Column("llm_provider", sa.String(40), nullable=True),
        sa.Column("llm_key_encrypted", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "collectors",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("identifier", sa.Text, nullable=False),
        sa.Column("tier", sa.Integer, nullable=False),
        sa.Column("config_json", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "identifier", name="uq_sources_kind_identifier"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.BigInteger, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(120), nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "source_id", name="uq_subscriptions_user_source"),
    )

    op.create_table(
        "items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.BigInteger, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.Text, nullable=False),
        sa.Column("owner_user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("author_handle", sa.String(200), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_text", sa.Text, nullable=False),
        sa.Column("raw_path", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "content_tsv",
            postgresql.TSVECTOR,
            sa.Computed(
                "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
                "setweight(to_tsvector('english', coalesce(content_text, '')), 'B')",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.UniqueConstraint("source_id", "external_id", name="uq_items_source_external"),
    )

    op.create_table(
        "fetch_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.BigInteger, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("collector_id", sa.BigInteger, sa.ForeignKey("collectors.id", ondelete="SET NULL"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("items_found", sa.Integer, nullable=False, server_default="0"),
        sa.Column("items_new", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_text", sa.Text, nullable=True),
    )

    op.create_table(
        "item_tags",
        sa.Column("item_id", sa.BigInteger, sa.ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag", sa.String(80), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.execute("CREATE INDEX items_content_tsv_idx ON items USING GIN (content_tsv)")
    op.execute("CREATE INDEX items_source_published_idx ON items (source_id, published_at DESC)")
    op.execute("CREATE INDEX fetch_runs_source_started_idx ON fetch_runs (source_id, started_at DESC)")


def downgrade() -> None:
    op.drop_table("item_tags")
    op.drop_table("fetch_runs")
    op.drop_table("items")
    op.drop_table("subscriptions")
    op.drop_table("sources")
    op.drop_table("collectors")
    op.drop_table("users")
