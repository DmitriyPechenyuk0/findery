"""initial schema

Revision ID: f2c0f57a6e4e
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "f2c0f57a6e4e"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "listings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("price_amount", sa.BigInteger(), nullable=True),
        sa.Column("price_currency", sa.String(length=3), nullable=True),
        sa.Column("price_uah", sa.BigInteger(), nullable=True),
        sa.Column("price_negotiable", sa.Boolean(), nullable=False),
        sa.Column("price_free", sa.Boolean(), nullable=False),
        sa.Column("seller_id", sa.String(length=64), nullable=True),
        sa.Column("seller_name", sa.String(), nullable=True),
        sa.Column("seller_is_business", sa.Boolean(), nullable=False),
        sa.Column("seller_registered_at", sa.DateTime(), nullable=True),
        sa.Column("city_id", sa.Integer(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("region_id", sa.Integer(), nullable=True),
        sa.Column("region", sa.String(), nullable=True),
        sa.Column("district_id", sa.Integer(), nullable=True),
        sa.Column("district", sa.String(), nullable=True),
        sa.Column("lat", sa.Double(), nullable=True),
        sa.Column("lon", sa.Double(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("category_type", sa.String(), nullable=True),
        sa.Column("photos", sa.JSON(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(), nullable=True),
        sa.Column("valid_to", sa.DateTime(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_listings")),
        sa.UniqueConstraint("source", "external_id", name=op.f("uq_listings_source")),
    )
    with op.batch_alter_table("listings", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_listings_price_uah"), ["price_uah"], unique=False)
        batch_op.create_index(batch_op.f("ix_listings_seller_id"), ["seller_id"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("telegram_id", name=op.f("uq_users_telegram_id")),
    )
    op.create_table(
        "listing_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("seen_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("price_amount", sa.BigInteger(), nullable=True),
        sa.Column("price_currency", sa.String(length=3), nullable=True),
        sa.Column("price_uah", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.id"],
            name=op.f("fk_listing_snapshots_listing_id_listings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_listing_snapshots")),
    )
    with op.batch_alter_table("listing_snapshots", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_listing_snapshots_listing_id"), ["listing_id"], unique=False
        )

    op.create_table(
        "profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("price_from", sa.Integer(), nullable=True),
        sa.Column("price_to", sa.Integer(), nullable=True),
        sa.Column("region_id", sa.Integer(), nullable=True),
        sa.Column("city_id", sa.Integer(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("private_only", sa.Boolean(), nullable=False),
        sa.Column("stop_words", sa.JSON(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_profiles_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profiles")),
    )
    with op.batch_alter_table("profiles", schema=None) as batch_op:
        batch_op.create_index("ix_profiles_due", ["is_active", "next_run_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_profiles_user_id"), ["user_id"], unique=False)

    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.id"],
            name=op.f("fk_matches_listing_id_listings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name=op.f("fk_matches_profile_id_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_matches")),
        sa.UniqueConstraint("profile_id", "listing_id", name=op.f("uq_matches_profile_id")),
    )
    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_matches_listing_id"), ["listing_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_matches_listing_id"))

    op.drop_table("matches")
    with op.batch_alter_table("profiles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_profiles_user_id"))
        batch_op.drop_index("ix_profiles_due")

    op.drop_table("profiles")
    with op.batch_alter_table("listing_snapshots", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_listing_snapshots_listing_id"))

    op.drop_table("listing_snapshots")
    op.drop_table("users")
    with op.batch_alter_table("listings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_listings_seller_id"))
        batch_op.drop_index(batch_op.f("ix_listings_price_uah"))

    op.drop_table("listings")
