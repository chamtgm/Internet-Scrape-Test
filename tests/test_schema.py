from sqlalchemy import text

EXPECTED_TABLES = {
    "users",
    "collectors",
    "sources",
    "subscriptions",
    "items",
    "fetch_runs",
    "item_tags",
}


def test_all_tables_exist(session):
    rows = session.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    ).scalars().all()
    assert EXPECTED_TABLES.issubset(set(rows))


def test_items_has_generated_tsvector_column(session):
    row = session.execute(
        text(
            "SELECT is_generated FROM information_schema.columns "
            "WHERE table_name = 'items' AND column_name = 'content_tsv'"
        )
    ).scalar_one()
    assert row == "ALWAYS"


def test_tsvector_index_exists(session):
    names = session.execute(
        text("SELECT indexname FROM pg_indexes WHERE tablename = 'items'")
    ).scalars().all()
    assert "items_content_tsv_idx" in names
