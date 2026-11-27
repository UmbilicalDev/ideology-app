"""Constituencies, candidatures and document scopes (constituencies-and-candidatures)

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-24 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# A literal copy of ideology_app.constituencies.CONSTITUENCIES (INE province
# codes; inverted articles moved to the front). A migration never imports
# application code; tests/test_constituencies.py keeps the two equal.
_CONSTITUENCIES = (
    ('01', 'Araba/Álava'),
    ('02', 'Albacete'),
    ('03', 'Alicante/Alacant'),
    ('04', 'Almería'),
    ('05', 'Ávila'),
    ('06', 'Badajoz'),
    ('07', 'Illes Balears'),
    ('08', 'Barcelona'),
    ('09', 'Burgos'),
    ('10', 'Cáceres'),
    ('11', 'Cádiz'),
    ('12', 'Castellón/Castelló'),
    ('13', 'Ciudad Real'),
    ('14', 'Córdoba'),
    ('15', 'A Coruña'),
    ('16', 'Cuenca'),
    ('17', 'Girona'),
    ('18', 'Granada'),
    ('19', 'Guadalajara'),
    ('20', 'Gipuzkoa'),
    ('21', 'Huelva'),
    ('22', 'Huesca'),
    ('23', 'Jaén'),
    ('24', 'León'),
    ('25', 'Lleida'),
    ('26', 'La Rioja'),
    ('27', 'Lugo'),
    ('28', 'Madrid'),
    ('29', 'Málaga'),
    ('30', 'Murcia'),
    ('31', 'Navarra'),
    ('32', 'Ourense'),
    ('33', 'Asturias'),
    ('34', 'Palencia'),
    ('35', 'Las Palmas'),
    ('36', 'Pontevedra'),
    ('37', 'Salamanca'),
    ('38', 'Santa Cruz de Tenerife'),
    ('39', 'Cantabria'),
    ('40', 'Segovia'),
    ('41', 'Sevilla'),
    ('42', 'Soria'),
    ('43', 'Tarragona'),
    ('44', 'Teruel'),
    ('45', 'Toledo'),
    ('46', 'Valencia/València'),
    ('47', 'Valladolid'),
    ('48', 'Bizkaia'),
    ('49', 'Zamora'),
    ('50', 'Zaragoza'),
    ('51', 'Ceuta'),
    ('52', 'Melilla'),
)


def upgrade() -> None:
    """Upgrade schema."""
    # Written by hand. Three new tables and two nullable columns on elections;
    # no existing row changes. Legacy Elections keep NULL sources and have no
    # candidature or scope rows. recreate='never' gives plain ALTER TABLE ...
    # ADD COLUMN: elections is never recreated, so with PRAGMA foreign_keys=ON
    # no Party, Source Document or Dataset Version is cascade-deleted.
    constituencies = op.create_table(
        'constituencies',
        sa.Column('code', sa.String(length=2), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint('code', name=op.f('pk_constituencies')),
        sa.UniqueConstraint('name', name=op.f('uq_constituencies_name')),
    )
    op.bulk_insert(
        constituencies, [{'code': code, 'name': name} for code, name in _CONSTITUENCIES]
    )
    op.create_table(
        'candidatures',
        sa.Column('party_id', sa.Integer(), nullable=False),
        sa.Column('constituency_code', sa.String(length=2), nullable=False),
        sa.ForeignKeyConstraint(
            ['party_id'],
            ['parties.id'],
            name=op.f('fk_candidatures_party_id_parties'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['constituency_code'],
            ['constituencies.code'],
            name=op.f('fk_candidatures_constituency_code_constituencies'),
        ),
        sa.PrimaryKeyConstraint('party_id', 'constituency_code', name=op.f('pk_candidatures')),
    )
    with op.batch_alter_table('candidatures', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_candidatures_constituency_code'), ['constituency_code'], unique=False
        )
    op.create_table(
        'source_document_constituencies',
        sa.Column('source_document_id', sa.Integer(), nullable=False),
        sa.Column('constituency_code', sa.String(length=2), nullable=False),
        sa.ForeignKeyConstraint(
            ['source_document_id'],
            ['source_documents.id'],
            name=op.f(
                'fk_source_document_constituencies_source_document_id_source_documents'
            ),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['constituency_code'],
            ['constituencies.code'],
            name=op.f('fk_source_document_constituencies_constituency_code_constituencies'),
        ),
        sa.PrimaryKeyConstraint(
            'source_document_id',
            'constituency_code',
            name=op.f('pk_source_document_constituencies'),
        ),
    )
    with op.batch_alter_table('elections', schema=None, recreate='never') as batch_op:
        batch_op.add_column(
            sa.Column('candidatures_source', sa.String(length=500), nullable=True)
        )
        batch_op.add_column(
            sa.Column('candidatures_source_url', sa.String(length=2048), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    # recreate='never': ALTER TABLE ... DROP COLUMN (SQLite >= 3.35), so no
    # child row of elections is cascade-deleted.
    with op.batch_alter_table('elections', schema=None, recreate='never') as batch_op:
        batch_op.drop_column('candidatures_source_url')
        batch_op.drop_column('candidatures_source')
    op.drop_table('source_document_constituencies')
    with op.batch_alter_table('candidatures', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_candidatures_constituency_code'))
    op.drop_table('candidatures')
    op.drop_table('constituencies')
