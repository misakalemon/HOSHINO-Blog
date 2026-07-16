"""修复因 default=datetime.datetime.now(...) 固定值缺陷导致的错误时间戳。

所有 default / onupdate 传入了 datetime.datetime.now(datetime.timezone.utc) 的求值结果
而非可调用对象，导致同进程内所有新记录共用同一个时间戳。

本脚本对历史数据表按 video_id / up_id / product_id 分组，以主键 id 为序均匀分配时间戳。
"""
import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['CONFIG_PATH'] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')

from app import create_app
from blog.models import db, BiliVideoHistory, BiliUpHistory, PriceRecord, ExchangeRate

app = create_app()

HISTORY_MODELS = [
    ('BiliVideoHistory', BiliVideoHistory, 'video_id'),
    ('BiliUpHistory', BiliUpHistory, 'up_id'),
    ('PriceRecord', PriceRecord, 'product_id'),
    ('ExchangeRate', ExchangeRate, None),
]

INTERVAL = datetime.timedelta(minutes=30)

def fix_table(name, model, group_col):
    with app.app_context():
        if group_col:
            groups = (
                db.session.query(model.__table__.c[group_col])
                .distinct()
                .all()
            )
            group_ids = [g[0] for g in groups]
        else:
            group_ids = [None]

        total_fixed = 0
        for gid in group_ids:
            query = model.query.order_by(model.id.asc())
            if gid is not None:
                records = query.filter(model.__table__.c[group_col] == gid).all()
            else:
                records = query.all()

            if len(records) < 2:
                continue

            base_time = records[-1].recorded_at or datetime.datetime.now(datetime.timezone.utc)
            for i, rec in enumerate(records):
                offset = (i - len(records) + 1) * INTERVAL
                new_time = base_time + offset
                if rec.recorded_at != new_time:
                    rec.recorded_at = new_time
            total_fixed += len(records)

        if total_fixed:
            db.session.commit()
            print(f'{name}: fixed {total_fixed} records')
        else:
            print(f'{name}: no records to fix (0 or <2 per group)')

if __name__ == '__main__':
    for name, model, group_col in HISTORY_MODELS:
        fix_table(name, model, group_col)
    print('Done.')
