"""canonicalise existing users.email to the stored form

Revision ID: 0003
Revises: 0002

`api/auth.normalize_email` applies `.strip().lower()` at every point an address
enters or is looked up, but `users.email` is a case-SENSITIVE unique `String`,
not `citext`, and there is no functional index on `lower(email)`. So any row
written before that normalisation landed could hold `Alice@Example.com` while
every lookup now asks for `alice@example.com` -- the row becomes unreachable,
login returns the deliberately identical "incorrect" 401, and setup would
happily insert a second row for the same person. This backfills those rows.

No rows need it in any database that exists today; this exists so that a
database cloned from an earlier commit on this branch cannot arrive broken.

If two rows differ only by case, this UPDATE fails on the unique constraint.
That is the correct outcome: a human has to decide which account survives.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET email = lower(btrim(email)) WHERE email <> lower(btrim(email))")


def downgrade() -> None:
    # Irreversible by nature: the original casing is not recorded anywhere, so
    # there is nothing to restore. A no-op keeps `downgrade` runnable.
    pass
