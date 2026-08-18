"""initial migration

Revision ID: b76f487c0ae9
Revises: 
Create Date: 2026-07-14 14:49:25.200123

说明（修复记录）：
  原版 upgrade 对不存在的表/索引直接 DROP，导致空库执行 flask db upgrade 失败；
  downgrade 中 drop_constraint(None) 无约束名必抛错。本版为所有删除操作增加
  存在性检查，并为 comments 外键使用显式约束名，保证 upgrade/downgrade
  在空库和旧库上均可执行。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'b76f487c0ae9'
down_revision = None
branch_labels = None
depends_on = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def _has_index(bind, table: str, index_name: str) -> bool:
    try:
        insp = sa.inspect(bind)
        return index_name in {i['name'] for i in insp.get_indexes(table)}
    except sa.exc.NoSuchTableError:
        return False


def _has_column(bind, table: str, column_name: str) -> bool:
    try:
        insp = sa.inspect(bind)
        return column_name in {c['name'] for c in insp.get_columns(table)}
    except sa.exc.NoSuchTableError:
        return False


def upgrade():
    """清理旧项目遗留表/列 + 兼容性调整（全部幂等，空库可执行）。"""
    bind = op.get_bind()

    # ── 删除旧项目遗留表（存在才删）──
    for tname in ('contact_info', 'programs', 'map_hotspots',
                  'guide_items', 'campus_maps', 'school_locations'):
        if _has_table(bind, tname):
            op.drop_table(tname)

    # ── 遗留索引（表仍存在且索引存在才删）──
    for tname, iname in (
        ('programs', 'ix_programs_name'),
        ('map_hotspots', 'ix_map_hotspots_map_id'),
        ('guide_items', 'ix_guide_items_section'),
        ('school_locations', 'ix_school_locations_hotspot_id'),
        ('bili_subscriptions', 'ix_bili_sub_token'),
    ):
        if _has_table(bind, tname) and _has_index(bind, tname, iname):
            with op.batch_alter_table(tname, schema=None) as batch_op:
                batch_op.drop_index(iname)

    # ── 核心表调整（表不存在则跳过）──
    if _has_table(bind, 'bili_ups'):
        with op.batch_alter_table('bili_ups', schema=None) as batch_op:
            batch_op.alter_column('follower_count',
                   existing_type=mysql.INTEGER(),
                   comment='粉丝数',
                   existing_nullable=True,
                   existing_server_default=sa.text("'0'"))

    if _has_table(bind, 'bili_videos'):
        with op.batch_alter_table('bili_videos', schema=None) as batch_op:
            batch_op.alter_column('pub_datetime',
                   existing_type=mysql.DATETIME(),
                   comment='发布日期时间',
                   existing_nullable=True)

    if _has_table(bind, 'comments'):
        with op.batch_alter_table('comments', schema=None) as batch_op:
            # 旧外键名存在才删；新外键使用显式名称（downgrade 可精确回滚）
            try:
                batch_op.drop_constraint(batch_op.f('comments_ibfk_1'), type_='foreignkey')
            except Exception:
                pass
            batch_op.create_foreign_key(
                'fk_comments_post_id', 'posts', ['post_id'], ['id'], ondelete='CASCADE'
            )

    if _has_table(bind, 'posts'):
        with op.batch_alter_table('posts', schema=None) as batch_op:
            if not _has_index(bind, 'posts', 'ix_post_fulltext'):
                batch_op.create_index('ix_post_fulltext', ['title', 'content'], unique=False, mysql_prefix='FULLTEXT')
            if not _has_index(bind, 'posts', 'ix_posts_created_at'):
                batch_op.create_index(batch_op.f('ix_posts_created_at'), ['created_at'], unique=False)
            if not _has_index(bind, 'posts', 'ix_posts_is_published'):
                batch_op.create_index(batch_op.f('ix_posts_is_published'), ['is_published'], unique=False)

    if _has_table(bind, 'price_records'):
        with op.batch_alter_table('price_records', schema=None) as batch_op:
            batch_op.alter_column('price',
                   existing_type=mysql.FLOAT(),
                   type_=sa.Numeric(precision=10, scale=2),
                   existing_nullable=False)

    if _has_table(bind, 'product_sources'):
        with op.batch_alter_table('product_sources', schema=None) as batch_op:
            batch_op.alter_column('latest_price',
                   existing_type=mysql.FLOAT(),
                   type_=sa.Numeric(precision=10, scale=2),
                   existing_nullable=True)

    if _has_table(bind, 'users'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            for col in ('footer_qr1', 'logo', 'footer_qr2', 'bg_image'):
                if _has_column(bind, 'users', col):
                    batch_op.drop_column(col)


def downgrade():
    """回滚：恢复旧表/列（幂等）。"""
    bind = op.get_bind()

    if _has_table(bind, 'users'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            for col, server_default in (
                ('bg_image', "''"),
                ('footer_qr2', "''"),
                ('logo', "''"),
                ('footer_qr1', "''"),
            ):
                if not _has_column(bind, 'users', col):
                    batch_op.add_column(
                        sa.Column(col, mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=256),
                                  server_default=sa.text(server_default), nullable=True)
                    )

    if _has_table(bind, 'product_sources'):
        with op.batch_alter_table('product_sources', schema=None) as batch_op:
            batch_op.alter_column('latest_price',
                   existing_type=sa.Numeric(precision=10, scale=2),
                   type_=mysql.FLOAT(),
                   existing_nullable=True)

    if _has_table(bind, 'price_records'):
        with op.batch_alter_table('price_records', schema=None) as batch_op:
            batch_op.alter_column('price',
                   existing_type=sa.Numeric(precision=10, scale=2),
                   type_=mysql.FLOAT(),
                   existing_nullable=False)

    if _has_table(bind, 'posts'):
        with op.batch_alter_table('posts', schema=None) as batch_op:
            if _has_index(bind, 'posts', 'ix_posts_is_published'):
                batch_op.drop_index(batch_op.f('ix_posts_is_published'))
            if _has_index(bind, 'posts', 'ix_posts_created_at'):
                batch_op.drop_index(batch_op.f('ix_posts_created_at'))
            if _has_index(bind, 'posts', 'ix_post_fulltext'):
                batch_op.drop_index('ix_post_fulltext', mysql_prefix='FULLTEXT')

    if _has_table(bind, 'comments'):
        with op.batch_alter_table('comments', schema=None) as batch_op:
            try:
                batch_op.drop_constraint('fk_comments_post_id', type_='foreignkey')
            except Exception:
                pass
            batch_op.create_foreign_key(batch_op.f('comments_ibfk_1'), 'posts', ['post_id'], ['id'])

    if _has_table(bind, 'bili_videos'):
        with op.batch_alter_table('bili_videos', schema=None) as batch_op:
            batch_op.alter_column('pub_datetime',
                   existing_type=mysql.DATETIME(),
                   comment=None,
                   existing_comment='发布日期时间',
                   existing_nullable=True)

    if _has_table(bind, 'bili_ups'):
        with op.batch_alter_table('bili_ups', schema=None) as batch_op:
            batch_op.alter_column('follower_count',
                   existing_type=mysql.INTEGER(),
                   comment=None,
                   existing_comment='粉丝数',
                   existing_nullable=True,
                   existing_server_default=sa.text("'0'"))

    if _has_table(bind, 'bili_subscriptions') and not _has_index(bind, 'bili_subscriptions', 'ix_bili_sub_token'):
        with op.batch_alter_table('bili_subscriptions', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_bili_sub_token'), ['token'], unique=False)

    # ── 重建旧项目表（幂等）──
    if not _has_table(bind, 'school_locations'):
        op.create_table('school_locations',
        sa.Column('id', mysql.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('title', mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=128), nullable=False),
        sa.Column('summary', mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=256), nullable=True),
        sa.Column('content', mysql.TEXT(collation='utf8mb4_unicode_ci'), nullable=True),
        sa.Column('image', mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=256), nullable=True),
        sa.Column('hotspot_id', mysql.INTEGER(), autoincrement=False, nullable=True),
        sa.Column('sort_order', mysql.INTEGER(), autoincrement=False, nullable=True),
        sa.Column('is_active', mysql.TINYINT(display_width=1), autoincrement=False, nullable=True),
        sa.Column('created_at', mysql.DATETIME(), nullable=True),
        sa.Column('images', mysql.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['hotspot_id'], ['map_hotspots.id'], name=op.f('school_locations_ibfk_1')),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_default_charset='utf8mb4',
        mysql_engine='InnoDB'
        )
        with op.batch_alter_table('school_locations', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_school_locations_hotspot_id'), ['hotspot_id'], unique=False)

    if not _has_table(bind, 'campus_maps'):
        op.create_table('campus_maps',
        sa.Column('id', mysql.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('name', mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=128), nullable=True),
        sa.Column('image', mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=256), nullable=True),
        sa.Column('is_active', mysql.TINYINT(display_width=1), autoincrement=False, nullable=True),
        sa.Column('created_at', mysql.DATETIME(), nullable=True),
        sa.Column('updated_at', mysql.DATETIME(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_default_charset='utf8mb4',
        mysql_engine='InnoDB'
        )
    if not _has_table(bind, 'guide_items'):
        op.create_table('guide_items',
        sa.Column('id', mysql.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('section', mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=32), nullable=False),
        sa.Column('section_label', mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=64), nullable=True),
        sa.Column('title', mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=128), nullable=False),
        sa.Column('icon', mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=16), nullable=True),
        sa.Column('content', mysql.TEXT(collation='utf8mb4_unicode_ci'), nullable=True),
        sa.Column('sort_order', mysql.INTEGER(), autoincrement=False, nullable=True),
        sa.Column('is_active', mysql.TINYINT(display_width=1), autoincrement=False, nullable=True),
        sa.Column('created_at', mysql.DATETIME(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_default_charset='utf8mb4',
        mysql_engine='InnoDB'
        )
        with op.batch_alter_table('guide_items', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_guide_items_section'), ['section'], unique=False)

    if not _has_table(bind, 'map_hotspots'):
        op.create_table('map_hotspots',
        sa.Column('id', mysql.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('map_id', mysql.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('title', mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=128), nullable=False),
        sa.Column('link_url', mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=512), nullable=True),
        sa.Column('x_pos', mysql.FLOAT(), nullable=True),
        sa.Column('y_pos', mysql.FLOAT(), nullable=True),
        sa.Column('sort_order', mysql.INTEGER(), autoincrement=False, nullable=True),
        sa.Column('created_at', mysql.DATETIME(), nullable=True),
        sa.ForeignKeyConstraint(['map_id'], ['campus_maps.id'], name=op.f('map_hotspots_ibfk_1')),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_default_charset='utf8mb4',
        mysql_engine='InnoDB'
        )
        with op.batch_alter_table('map_hotspots', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_map_hotspots_map_id'), ['map_id'], unique=False)

    if not _has_table(bind, 'programs'):
        op.create_table('programs',
        sa.Column('id', mysql.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('name', mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=128), nullable=False),
        sa.Column('category', mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=64), nullable=True),
        sa.Column('content', mysql.TEXT(collation='utf8mb4_unicode_ci'), nullable=True),
        sa.Column('sort_order', mysql.INTEGER(), autoincrement=False, nullable=True),
        sa.Column('is_active', mysql.TINYINT(display_width=1), autoincrement=False, nullable=True),
        sa.Column('created_at', mysql.DATETIME(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_default_charset='utf8mb4',
        mysql_engine='InnoDB'
        )
        with op.batch_alter_table('programs', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_programs_name'), ['name'], unique=False)

    if not _has_table(bind, 'contact_info'):
        op.create_table('contact_info',
        sa.Column('id', mysql.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('title', mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=128), nullable=False),
        sa.Column('link_url', mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=512), nullable=True),
        sa.Column('qr_image', mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=256), nullable=True),
        sa.Column('sort_order', mysql.INTEGER(), autoincrement=False, nullable=True),
        sa.Column('is_active', mysql.TINYINT(display_width=1), autoincrement=False, nullable=True),
        sa.Column('created_at', mysql.DATETIME(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_default_charset='utf8mb4',
        mysql_engine='InnoDB'
        )
