"""add BiliVideo.tags, BiliVideoComment, WordCloudData.source length

Revision ID: 88e5c1b3f4d2
Revises: b76f487c0ae9
Create Date: 2026-07-22 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '88e5c1b3f4d2'
down_revision = 'b76f487c0ae9'
branch_labels = None
depends_on = None


def upgrade():
    # Create BiliVideoComment table
    op.create_table(
        'bili_video_comments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('video_id', sa.Integer(), sa.ForeignKey('bili_videos.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('author', sa.String(length=64), nullable=True),
        sa.Column('ctime', sa.Integer(), nullable=True),
        sa.Column('like_count', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    # Add tags column to bili_videos
    with op.batch_alter_table('bili_videos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tags', sa.JSON(), nullable=True))

    # Extend WordCloudData.source column length (8 → 16)
    with op.batch_alter_table('wordcloud_data', schema=None) as batch_op:
        batch_op.alter_column('source',
            existing_type=sa.String(length=8),
            type_=sa.String(length=16),
            existing_nullable=True,
        )


def downgrade():
    with op.batch_alter_table('wordcloud_data', schema=None) as batch_op:
        batch_op.alter_column('source',
            existing_type=sa.String(length=16),
            type_=sa.String(length=8),
            existing_nullable=True,
        )

    with op.batch_alter_table('bili_videos', schema=None) as batch_op:
        batch_op.drop_column('tags')

    op.drop_table('bili_video_comments')
