"""Exclude incorrectly discovered external addresses without deleting mail history."""
from alembic import op
import sqlalchemy as sa

revision="0016"
down_revision="0015"


def upgrade():
    employees=sa.table("employees",sa.column("email",sa.String),sa.column("active",sa.Boolean))
    op.execute(employees.update().where(~sa.func.lower(sa.func.trim(employees.c.email)).like("%@indianinfotech.org")).values(active=False))


def downgrade():
    # Do not reactivate removed employees or guess which external records were active.
    pass
