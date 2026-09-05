"""
HOSHINO Blog — 数据备份与恢复

提供数据库数据导出（JSON）与 uploads 文件打包（zip），支持：
  - full  : DB 数据 + uploads 文件（一个 zip）
  - db    : 仅 DB 数据（JSON）
  - uploads: 仅 uploads 文件（zip）

设计要点：
  - 纯 Python 实现，无 mysqldump 等外部依赖
  - DB 备份只导数据，schema 由 models.py + db.create_all() 重建
  - 表按拓扑顺序导出/恢复，恢复时临时禁用外键检查
  - datetime 序列化为 MySQL 友好格式（'YYYY-MM-DD HH:MM:SS'）
  - bytes 用 base64 + 标记字典保留
  - 备份文件存放在项目根 backups/ 目录（.gitignore 已忽略）
"""

import base64
import datetime
import json
import logging
import os
import zipfile

from flask import current_app
from sqlalchemy import LargeBinary

from .models import BackupRecord, db
from .utils import now_cst

logger = logging.getLogger(__name__)

BACKUP_DIR_NAME = 'backups'
_VALID_KINDS = ('full', 'db', 'uploads')


def _backup_dir():
    """返回备份目录绝对路径，不存在则创建。"""
    d = current_app.config.get('BACKUP_FOLDER') or os.path.join(
        current_app.root_path, BACKUP_DIR_NAME
    )
    os.makedirs(d, exist_ok=True)
    return d


def _json_default(o):
    """JSON 序列化：处理 datetime/date/time/bytes/Decimal 等非原生类型。"""
    if isinstance(o, datetime.datetime):
        return o.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(o, datetime.date):
        return o.strftime('%Y-%m-%d')
    if isinstance(o, datetime.time):
        return o.strftime('%H:%M:%S')
    if isinstance(o, datetime.timedelta):
        return o.total_seconds()
    if isinstance(o, bytes):
        return {'__bytes__': base64.b64encode(o).decode('ascii')}
    try:
        from decimal import Decimal
        if isinstance(o, Decimal):
            return str(o)
    except Exception:
        pass
    raise TypeError(f'不可序列化的类型: {type(o)}')


def _revive(value):
    """反序列化：把 JSON 里的标记字典还原为 bytes。"""
    if isinstance(value, dict) and '__bytes__' in value:
        return base64.b64decode(value['__bytes__'])
    return value


def _export_db_data():
    """导出所有表数据为 {table_name: [row_dict, ...]}，按拓扑顺序。"""
    metadata = db.metadata
    result = {}
    for tbl in metadata.sorted_tables:
        try:
            rows = db.session.execute(tbl.select()).fetchall()
        except Exception as e:
            logger.warning('备份: 跳过表 %s（查询失败: %s）', tbl.name, e)
            result[tbl.name] = []
            continue
        cols = [c.name for c in tbl.columns]
        result[tbl.name] = [dict(zip(cols, row)) for row in rows]
    return result


def _write_db_json(path):
    """把 DB 数据写入 JSON 文件，返回文件大小。"""
    payload = {
        'version': 1,
        'created_at': now_cst().strftime('%Y-%m-%d %H:%M:%S'),
        'tables': _export_db_data(),
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, default=_json_default)
    return os.path.getsize(path)


def _zip_uploads(zip_path):
    """把 uploads 目录打包成 zip，返回大小。"""
    upload_dir = current_app.config['UPLOAD_FOLDER']
    count = 0
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        if os.path.isdir(upload_dir):
            for root, _dirs, files in os.walk(upload_dir):
                for fn in files:
                    full = os.path.join(root, fn)
                    arc = os.path.relpath(full, upload_dir)
                    zf.write(full, arc)
                    count += 1
    logger.info('备份: uploads 打包 %d 个文件', count)
    return os.path.getsize(zip_path)


def _zip_full(zip_path):
    """full 备份：zip 含 db.json + uploads/，返回大小。"""
    upload_dir = current_app.config['UPLOAD_FOLDER']
    tmp_json = os.path.join(_backup_dir(), '_tmp_db.json')
    try:
        _write_db_json(tmp_json)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp_json, 'db.json')
            if os.path.isdir(upload_dir):
                for root, _dirs, files in os.walk(upload_dir):
                    for fn in files:
                        full = os.path.join(root, fn)
                        arc = os.path.relpath(full, upload_dir)
                        zf.write(full, os.path.join('uploads', arc))
        return os.path.getsize(zip_path)
    finally:
        if os.path.exists(tmp_json):
            os.remove(tmp_json)


def run_backup(kind='full'):
    """执行一次备份，写入 BackupRecord 并返回。

    Args:
        kind: full / db / uploads

    Returns:
        BackupRecord
    """
    kind = kind if kind in _VALID_KINDS else 'full'
    ts = now_cst().strftime('%Y%m%d_%H%M%S')
    backup_dir = _backup_dir()

    if kind == 'db':
        filename = f'backup_db_{ts}.json'
        path = os.path.join(backup_dir, filename)
    else:
        filename = f'backup_{kind}_{ts}.zip'
        path = os.path.join(backup_dir, filename)

    record = BackupRecord(filename=filename, kind=kind, status='ok')
    try:
        if kind == 'db':
            size = _write_db_json(path)
        elif kind == 'uploads':
            size = _zip_uploads(path)
        else:
            size = _zip_full(path)
        record.size_bytes = size
        logger.info('备份完成: kind=%s file=%s size=%d', kind, filename, size)
    except Exception as e:
        record.status = 'failed'
        record.error_msg = str(e)[:2000]
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        logger.error('备份失败: kind=%s err=%s', kind, e, exc_info=True)
    db.session.add(record)
    db.session.commit()
    return record


def restore_db_from_record(record):
    """从 DB 备份（kind=db 的 JSON 或 kind=full 的 zip 内 db.json）恢复数据。

    恢复流程：禁用外键 → 按拓扑顺序 DELETE 各表 → 按顺序 INSERT → 重置外键。
    恢复后调用方应重启服务以刷新内存缓存。

    Returns:
        dict: {'tables': N, 'rows': N}
    """
    backup_dir = _backup_dir()
    path = os.path.join(backup_dir, record.filename)

    if record.kind == 'db':
        with open(path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    elif record.kind == 'full':
        with zipfile.ZipFile(path, 'r') as zf:
            with zf.open('db.json') as f:
                payload = json.load(f)
    else:
        raise ValueError('uploads 备份不能用于恢复 DB')

    tables_data = payload.get('tables', {})
    metadata = db.metadata
    engine = db.get_engine()
    is_mysql = engine.dialect.name == 'mysql'

    total_rows = 0
    table_count = 0
    try:
        if is_mysql:
            db.session.execute(db.text('SET FOREIGN_KEY_CHECKS=0'))
        for tbl in metadata.sorted_tables:
            name = tbl.name
            if name not in tables_data:
                continue
            table_count += 1
            db.session.execute(tbl.delete())
            rows = tables_data[name]
            if rows:
                cols = [c.name for c in tbl.columns]
                clean_rows = []
                for r in rows:
                    clean = {}
                    for c in cols:
                        if c in r:
                            clean[c] = _revive(r[c])
                    if clean:
                        clean_rows.append(clean)
                if clean_rows:
                    db.session.execute(tbl.insert(), clean_rows)
                    total_rows += len(clean_rows)
        if is_mysql:
            db.session.execute(db.text('SET FOREIGN_KEY_CHECKS=1'))
        db.session.commit()
    except Exception:
        if is_mysql:
            try:
                db.session.execute(db.text('SET FOREIGN_KEY_CHECKS=1'))
                db.session.commit()
            except Exception:
                pass
        db.session.rollback()
        raise

    logger.info('恢复完成: tables=%d rows=%d', table_count, total_rows)
    return {'tables': table_count, 'rows': total_rows}


def delete_backup(record):
    """删除备份文件与记录。"""
    path = os.path.join(_backup_dir(), record.filename)
    if os.path.isfile(path):
        os.remove(path)
    db.session.delete(record)
    db.session.commit()


def cleanup_old_backups(keep=7):
    """保留最近 keep 份 full 备份，删除更早的（含文件与记录）。"""
    keep = max(1, int(keep))
    records = (
        BackupRecord.query.filter_by(kind='full', status='ok')
        .order_by(BackupRecord.created_at.desc())
        .all()
    )
    removed = 0
    for record in records[keep:]:
        try:
            delete_backup(record)
            removed += 1
        except Exception:
            db.session.rollback()
            logger.warning('清理旧备份失败: id=%d', record.id)
    if removed:
        logger.info('清理旧备份: 删除 %d 份（保留 %d 份）', removed, keep)
    return removed