"""Store Microsoft app credentials per mailbox."""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"

def upgrade():
    for name, column in (("azure_client_id", sa.String(128)), ("azure_tenant_id", sa.String(128)),
                         ("azure_secret_ciphertext", sa.Text()), ("azure_secret_nonce", sa.String(64)),
                         ("azure_secret_key_id", sa.String(64))):
        op.add_column("mailboxes", sa.Column(name, column, nullable=True))

def downgrade():
    for name in ("azure_secret_key_id", "azure_secret_nonce", "azure_secret_ciphertext", "azure_tenant_id", "azure_client_id"):
        op.drop_column("mailboxes", name)
