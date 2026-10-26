"""Index a fixed-length SHA-256 digest of UI source text."""
import hashlib

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("ui_content")}
    if "source_text_sha256" not in columns:
        op.add_column("ui_content", sa.Column("source_text_sha256", sa.String(64), nullable=True))
    rows = connection.execute(sa.text("SELECT id, source_text FROM ui_content ORDER BY id"))
    seen = {}
    for content_id, source_text in rows:
        digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        if digest in seen:
            raise RuntimeError(f"Duplicate UI source text or SHA-256 collision: ids {seen[digest]} and {content_id}")
        seen[digest] = content_id
        connection.execute(sa.text("UPDATE ui_content SET source_text_sha256 = :digest WHERE id = :id"),
                           {"digest": digest, "id": content_id})
    inspector = sa.inspect(connection)
    unique_constraints = inspector.get_unique_constraints("ui_content")
    digest_unique = any(item["column_names"] == ["source_text_sha256"] for item in unique_constraints)
    if connection.dialect.name == "sqlite":
        digest_unique |= any(item.get("unique") and item["column_names"] == ["source_text_sha256"] for item in inspector.get_indexes("ui_content"))
        if not digest_unique:
            op.create_index("uq_ui_content_source_text_sha256", "ui_content", ["source_text_sha256"], unique=True)
    else:
        op.alter_column("ui_content", "source_text_sha256", existing_type=sa.String(64), nullable=False)
        for item in unique_constraints:
            if item["column_names"] == ["source_text"]:
                op.drop_constraint(item["name"], "ui_content", type_="unique")
        if not digest_unique:
            op.create_unique_constraint("uq_ui_content_source_text_sha256", "ui_content", ["source_text_sha256"])


def downgrade():
    op.drop_constraint("uq_ui_content_source_text_sha256", "ui_content", type_="unique")
    op.create_unique_constraint("ui_content_source_text_key", "ui_content", ["source_text"])
    op.drop_column("ui_content", "source_text_sha256")
