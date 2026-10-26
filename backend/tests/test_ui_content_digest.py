import hashlib
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import UIContent


def test_long_source_text_digest_and_uniqueness():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[UIContent.__table__])
    source = "Long UI string 🌐" * 1000
    with Session(engine) as db:
        row = UIContent(source_text=source, rendered_text="Original")
        db.add(row)
        db.commit()
        assert row.source_text == source
        assert row.source_text_sha256 == hashlib.sha256(source.encode()).hexdigest()
        row.rendered_text = "Changed"
        db.commit()
        assert row.source_text_sha256 == hashlib.sha256(source.encode()).hexdigest()
        row.source_text = source + "!"
        db.commit()
        assert row.source_text_sha256 == hashlib.sha256((source + "!").encode()).hexdigest()
        db.add(UIContent(source_text=source + "!", rendered_text="Duplicate"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_migration_backfills_and_handles_empty_table():
    path = Path(__file__).parents[1] / "migrations/versions/0014_ui_content_source_digest.py"
    spec = importlib.util.spec_from_file_location("ui_content_0014", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    for sources in ([], ["A" * 10000, "other"], ["duplicate", "duplicate"]):
        engine = sa.create_engine("sqlite://")
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE ui_content (id INTEGER PRIMARY KEY, source_text TEXT NOT NULL)"))
            for source in sources:
                connection.execute(sa.text("INSERT INTO ui_content (source_text) VALUES (:source)"), {"source": source})

            class Operations:
                def get_bind(self): return connection
                def add_column(self, table, column):
                    connection.execute(sa.text("ALTER TABLE ui_content ADD COLUMN source_text_sha256 VARCHAR(64)"))
                def alter_column(self, *args, **kwargs): pass
                def drop_constraint(self, *args, **kwargs): pass
                def create_unique_constraint(self, *args, **kwargs): pass
                def create_index(self, name, table, columns, unique=False):
                    connection.execute(sa.text(f"CREATE UNIQUE INDEX {name} ON {table} ({', '.join(columns)})"))

            with patch.object(migration, "op", Operations()):
                if sources == ["duplicate", "duplicate"]:
                    with pytest.raises(RuntimeError, match="Duplicate UI source text"):
                        migration.upgrade()
                    continue
                migration.upgrade()
            rows = connection.execute(sa.text("SELECT source_text, source_text_sha256 FROM ui_content")).all()
            assert rows == [(source, hashlib.sha256(source.encode()).hexdigest()) for source in sources]
