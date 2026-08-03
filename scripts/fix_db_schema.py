"""数据库结构修复脚本 — 手动执行，修复缺失的 wordcloud_data.period 列。

用法:
    python scripts/fix_db_schema.py

背景:
    blog/models.py 的 WordCloudData 已定义 period 列，
    但若旧表创建时无此列且自动迁移未成功执行，
    词云/增量检查会报 Unknown column 'wordcloud_data.period'。
    本脚本强制检查并补加所有已知缺失的列/索引。
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from sqlalchemy import text
    from app import create_app

    app = create_app()
    with app.app_context():
        from blog import db

        engine = db.get_engine()
        dialect = engine.dialect.name
        print(f'数据库方言: {dialect}')
        if dialect != 'mysql':
            print('非 MySQL，跳过（SQLite 由 create_all 处理）')
            return

        inspector = db.inspect(engine)
        # 1. wordcloud_data 补列
        try:
            cols = {c['name'] for c in inspector.get_columns('wordcloud_data')}
            print('wordcloud_data 现有列:', sorted(cols))
            for col_name, col_type in [
                ('period', "VARCHAR(32) DEFAULT 'all'"),
                ('source', "VARCHAR(16) DEFAULT 'blog'"),
            ]:
                if col_name not in cols:
                    print(f'→ 添加列 {col_name} {col_type}')
                    db.session.execute(
                        text(f'ALTER TABLE wordcloud_data ADD COLUMN {col_name} {col_type}')
                    )
                    db.session.commit()
                else:
                    print(f'✓ 列 {col_name} 已存在')
        except Exception as e:
            print(f'wordcloud_data 迁移失败: {e}')
            db.session.rollback()

        # 2. 验证
        inspector = db.inspect(engine)
        cols = {c['name'] for c in inspector.get_columns('wordcloud_data')}
        if 'period' in cols:
            print('\n✅ wordcloud_data.period 已存在，修复成功')
        else:
            print('\n❌ wordcloud_data.period 仍缺失，请检查数据库权限')

    # 关闭 app 的数据库连接池
    try:
        db.session.remove()
    except Exception:
        pass


if __name__ == '__main__':
    main()