"""HOSHINO Blog — 数据备份与恢复模块测试 (blog/backup.py)

纯函数（_json_default / _revive / _backup_dir / _zip_uploads）用 @pytest.mark.pure 标记，
不依赖 MySQL；涉及 DB 的备份/恢复/清理操作依赖 app/_db fixture，在 CI 配置 MySQL 后运行。
"""
# ruff: noqa: PLR2004, PLC0415
import base64
import datetime
import json
import os
import zipfile
from decimal import Decimal

import pytest

import blog.backup as backup_mod


# ── _json_default (纯函数) ─────────────────────────────────
@pytest.mark.pure
class TestJsonDefault:
    def test_datetime(self):
        dt = datetime.datetime(2024, 1, 2, 3, 4, 5)
        assert backup_mod._json_default(dt) == '2024-01-02 03:04:05'

    def test_datetime_with_timezone(self):
        cst = datetime.timezone(datetime.timedelta(hours=8))
        dt = datetime.datetime(2024, 6, 1, 12, 30, 0, tzinfo=cst)
        assert backup_mod._json_default(dt) == '2024-06-01 12:30:00'

    def test_date(self):
        assert backup_mod._json_default(datetime.date(2024, 1, 2)) == '2024-01-02'

    def test_time(self):
        assert backup_mod._json_default(datetime.time(3, 4, 5)) == '03:04:05'

    def test_timedelta(self):
        td = datetime.timedelta(hours=1, minutes=2, seconds=3)
        assert backup_mod._json_default(td) == 3723.0

    def test_timedelta_zero(self):
        assert backup_mod._json_default(datetime.timedelta()) == 0.0

    def test_bytes(self):
        b = b'hello'
        assert backup_mod._json_default(b) == {'__bytes__': base64.b64encode(b).decode('ascii')}

    def test_empty_bytes(self):
        assert backup_mod._json_default(b'') == {'__bytes__': ''}

    def test_decimal(self):
        assert backup_mod._json_default(Decimal('3.14')) == '3.14'

    def test_decimal_negative(self):
        assert backup_mod._json_default(Decimal('-0.5')) == '-0.5'

    def test_unserializable_raises_type_error(self):
        with pytest.raises(TypeError, match='不可序列化'):
            backup_mod._json_default(object())

    def test_set_unserializable(self):
        with pytest.raises(TypeError):
            backup_mod._json_default({1, 2, 3})

    def test_as_json_default(self):
        """作为 json.dump default 参数序列化复合结构。"""
        data = {
            'dt': datetime.datetime(2024, 6, 1, 12, 0, 0),
            'b': b'\x00\x01\xff',
            'td': datetime.timedelta(days=1),
            'dec': Decimal('1.5'),
        }
        s = json.dumps(data, default=backup_mod._json_default)
        loaded = json.loads(s)
        assert loaded['dt'] == '2024-06-01 12:00:00'
        assert loaded['b'] == {'__bytes__': base64.b64encode(b'\x00\x01\xff').decode('ascii')}
        assert loaded['td'] == 86400.0
        assert loaded['dec'] == '1.5'


# ── _revive (纯函数) ───────────────────────────────────────
@pytest.mark.pure
class TestRevive:
    def test_bytes_dict(self):
        v = {'__bytes__': base64.b64encode(b'data').decode('ascii')}
        assert backup_mod._revive(v) == b'data'

    def test_bytes_dict_empty(self):
        assert backup_mod._revive({'__bytes__': ''}) == b''

    def test_plain_dict(self):
        d = {'a': 1}
        assert backup_mod._revive(d) is d

    def test_non_dict(self):
        assert backup_mod._revive('x') == 'x'
        assert backup_mod._revive(123) == 123
        assert backup_mod._revive(None) is None
        assert backup_mod._revive([1, 2]) == [1, 2]

    def test_dict_without_marker(self):
        d = {'key': 'val', 'other': 1}
        assert backup_mod._revive(d) == {'key': 'val', 'other': 1}

    def test_roundtrip(self):
        original = {'data': b'\xff\xfe\xfd', 'name': '测试'}
        s = json.dumps(original, default=backup_mod._json_default)
        loaded = json.loads(s)
        revived = {k: backup_mod._revive(v) for k, v in loaded.items()}
        assert revived == original


# ── _backup_dir (需 app context，不依赖 MySQL) ──────────────
@pytest.mark.pure
class TestBackupDir:
    def _make_app(self, tmp_path, with_backup_folder=True):
        from flask import Flask

        app = Flask(__name__)
        if with_backup_folder:
            app.config['BACKUP_FOLDER'] = str(tmp_path / 'backups')
        return app

    def test_returns_configured_folder(self, tmp_path):
        app = self._make_app(tmp_path)
        with app.app_context():
            result = backup_mod._backup_dir()
        assert result == str(tmp_path / 'backups')
        assert os.path.isdir(result)

    def test_falls_back_to_root_path(self, tmp_path):
        app = self._make_app(tmp_path, with_backup_folder=False)
        with app.app_context():
            result = backup_mod._backup_dir()
            expected = os.path.join(app.root_path, backup_mod.BACKUP_DIR_NAME)
        assert result == expected
        assert os.path.isdir(result)

    def test_creates_nested_missing(self, tmp_path):
        app = self._make_app(tmp_path)
        backup_dir = tmp_path / 'backups'
        assert not backup_dir.exists()
        with app.app_context():
            result = backup_mod._backup_dir()
        assert backup_dir.exists()
        assert result == str(backup_dir)

    def test_idempotent_existing_dir(self, tmp_path):
        app = self._make_app(tmp_path)
        backup_dir = tmp_path / 'backups'
        backup_dir.mkdir()
        with app.app_context():
            result = backup_mod._backup_dir()
        assert result == str(backup_dir)


# ── _zip_uploads (需 app context + 文件系统，不依赖 MySQL) ──
@pytest.mark.pure
class TestZipUploads:
    def _make_app(self, tmp_path, upload_dir=None):
        from flask import Flask

        app = Flask(__name__)
        app.config['UPLOAD_FOLDER'] = str(upload_dir or (tmp_path / 'uploads'))
        return app

    def test_empty_upload_dir(self, tmp_path):
        upload_dir = tmp_path / 'uploads'
        upload_dir.mkdir()
        app = self._make_app(tmp_path, upload_dir)
        zip_path = tmp_path / 'out.zip'
        with app.app_context():
            size = backup_mod._zip_uploads(str(zip_path))
        assert size > 0
        assert zip_path.exists()
        with zipfile.ZipFile(zip_path) as zf:
            assert zf.namelist() == []

    def test_packs_files_with_subdirs(self, tmp_path):
        upload_dir = tmp_path / 'uploads'
        upload_dir.mkdir()
        (upload_dir / 'a.txt').write_text('hello', encoding='utf-8')
        (upload_dir / 'sub').mkdir()
        (upload_dir / 'sub' / 'b.txt').write_text('world', encoding='utf-8')
        app = self._make_app(tmp_path, upload_dir)
        zip_path = tmp_path / 'out.zip'
        with app.app_context():
            size = backup_mod._zip_uploads(str(zip_path))
        assert size > 0
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        assert 'a.txt' in names
        # zip 内部统一用正斜杠作为分隔符（即使 Windows）
        assert 'sub/b.txt' in names
        assert len(names) == 2

    def test_missing_upload_dir(self, tmp_path):
        app = self._make_app(tmp_path, tmp_path / 'nope')
        zip_path = tmp_path / 'out.zip'
        with app.app_context():
            size = backup_mod._zip_uploads(str(zip_path))
        assert size > 0
        with zipfile.ZipFile(zip_path) as zf:
            assert zf.namelist() == []

    def test_preserves_content(self, tmp_path):
        upload_dir = tmp_path / 'uploads'
        upload_dir.mkdir()
        (upload_dir / 'a.txt').write_text('content-here', encoding='utf-8')
        app = self._make_app(tmp_path, upload_dir)
        zip_path = tmp_path / 'out.zip'
        with app.app_context():
            backup_mod._zip_uploads(str(zip_path))
        with zipfile.ZipFile(zip_path) as zf:
            assert zf.read('a.txt').decode('utf-8') == 'content-here'


# ── DB 依赖测试 fixtures ────────────────────────────────────
@pytest.fixture
def backup_dir(app, monkeypatch, tmp_path):
    """把备份目录与 uploads 目录重定向到 tmp_path，避免污染项目目录。"""
    d = tmp_path / 'backups'
    d.mkdir()
    upload = tmp_path / 'uploads'
    upload.mkdir()
    monkeypatch.setitem(app.config, 'BACKUP_FOLDER', str(d))
    monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(upload))
    return d


# ── _export_db_data ─────────────────────────────────────────
class TestExportDbData:
    def test_empty_db(self, app, _db):
        with app.app_context():
            data = backup_mod._export_db_data()
        assert isinstance(data, dict)
        assert 'users' in data
        assert data['users'] == []

    def test_with_user(self, app, _db, admin_user):
        with app.app_context():
            data = backup_mod._export_db_data()
        assert len(data['users']) == 1
        assert isinstance(data['users'][0], dict)
        assert data['users'][0]['username'] == 'testadmin'

    def test_contains_all_tables(self, app, _db):
        from blog.models import db

        with app.app_context():
            data = backup_mod._export_db_data()
            table_names = {t.name for t in db.metadata.sorted_tables}
        assert set(data.keys()) == table_names


# ── _write_db_json ──────────────────────────────────────────
class TestWriteDbJson:
    def test_writes_valid_json(self, app, _db, backup_dir):
        with app.app_context():
            path = str(backup_dir / 'test.json')
            size = backup_mod._write_db_json(path)
        assert size > 0
        with open(path, encoding='utf-8') as f:
            payload = json.load(f)
        assert payload['version'] == 1
        assert 'created_at' in payload
        assert 'tables' in payload
        assert isinstance(payload['tables'], dict)

    def test_includes_user_data(self, app, _db, backup_dir, admin_user):
        with app.app_context():
            path = str(backup_dir / 'test.json')
            backup_mod._write_db_json(path)
        with open(path, encoding='utf-8') as f:
            payload = json.load(f)
        assert len(payload['tables']['users']) == 1


# ── run_backup ──────────────────────────────────────────────
class TestRunBackup:
    def test_db_kind(self, app, _db, backup_dir):
        with app.app_context():
            record = backup_mod.run_backup('db')
            assert record.kind == 'db'
            assert record.status == 'ok'
            assert record.size_bytes > 0
            assert record.filename.startswith('backup_db_')
            assert record.filename.endswith('.json')
            assert (backup_dir / record.filename).exists()

    def test_uploads_kind(self, app, _db, backup_dir):
        with app.app_context():
            record = backup_mod.run_backup('uploads')
            assert record.kind == 'uploads'
            assert record.status == 'ok'
            assert record.filename.startswith('backup_uploads_')
            assert record.filename.endswith('.zip')
            assert (backup_dir / record.filename).exists()

    def test_full_kind(self, app, _db, backup_dir):
        with app.app_context():
            record = backup_mod.run_backup('full')
            assert record.kind == 'full'
            assert record.status == 'ok'
            assert record.filename.startswith('backup_full_')
            assert record.filename.endswith('.zip')
            assert (backup_dir / record.filename).exists()

    def test_invalid_kind_defaults_full(self, app, _db, backup_dir):
        with app.app_context():
            record = backup_mod.run_backup('bogus')
            assert record.kind == 'full'
            assert record.status == 'ok'

    def test_default_kind_is_full(self, app, _db, backup_dir):
        with app.app_context():
            record = backup_mod.run_backup()
            assert record.kind == 'full'

    def test_full_zip_contains_db_json(self, app, _db, backup_dir):
        with app.app_context():
            record = backup_mod.run_backup('full')
            with zipfile.ZipFile(backup_dir / record.filename) as zf:
                names = zf.namelist()
        assert 'db.json' in names

    def test_failure_records_error(self, app, _db, backup_dir, monkeypatch):
        def boom(path):
            raise RuntimeError('disk full')

        monkeypatch.setattr(backup_mod, '_zip_full', boom)
        with app.app_context():
            record = backup_mod.run_backup('full')
            assert record.status == 'failed'
            assert 'disk full' in record.error_msg

    def test_failure_cleans_partial_file(self, app, _db, backup_dir, monkeypatch):
        def boom(path):
            # 创建部分文件后失败
            with open(path, 'w', encoding='utf-8') as f:
                f.write('partial')
            raise RuntimeError('fail mid-write')

        monkeypatch.setattr(backup_mod, '_zip_full', boom)
        with app.app_context():
            record = backup_mod.run_backup('full')
            filename = record.filename
            assert record.status == 'failed'
            assert not (backup_dir / filename).exists()


# ── restore_db_from_record ──────────────────────────────────
class TestRestoreDbFromRecord:
    def test_uploads_kind_raises(self, app, _db, backup_dir):
        from blog.models import BackupRecord

        with app.app_context():
            rec = BackupRecord(filename='x.zip', kind='uploads')
            _db.session.add(rec)
            _db.session.commit()
            with pytest.raises(ValueError, match='uploads'):
                backup_mod.restore_db_from_record(rec)

    def test_restore_empty_db(self, app, _db, backup_dir):
        with app.app_context():
            record = backup_mod.run_backup('db')
            result = backup_mod.restore_db_from_record(record)
            assert result['tables'] >= 1
            assert result['rows'] == 0

    def test_backup_and_restore_user(self, app, _db, backup_dir):
        from blog.models import User
        from sqlalchemy import inspect as sa_inspect

        # SQLite DateTime 不接受字符串（MySQL 驱动自动转换），跳过
        with app.app_context():
            if sa_inspect(_db.engine).dialect.name == 'sqlite':
                pytest.skip('SQLite DateTime 不接受字符串 datetime，需 MySQL')

            u = User(username='restore_me', email='r@r.com')
            u.set_password('pw')
            _db.session.add(u)
            _db.session.commit()
            record = backup_mod.run_backup('db')
            _db.session.delete(u)
            _db.session.commit()
            assert User.query.filter_by(username='restore_me').first() is None
            result = backup_mod.restore_db_from_record(record)
            assert result['rows'] >= 1
            restored = User.query.filter_by(username='restore_me').first()
            assert restored is not None
            assert restored.email == 'r@r.com'

    def test_restore_full_backup(self, app, _db, backup_dir):
        with app.app_context():
            record = backup_mod.run_backup('full')
            result = backup_mod.restore_db_from_record(record)
            assert result['tables'] >= 1

    def test_restore_skips_unknown_tables(self, app, _db, backup_dir):
        """payload 中含未知表名时跳过，不报错。"""
        from blog.models import BackupRecord

        with app.app_context():
            path = backup_dir / 'custom.json'
            payload = {'version': 1, 'tables': {'__nonexistent_table__': [{'a': 1}]}}
            path.write_text(json.dumps(payload), encoding='utf-8')
            rec = BackupRecord(filename='custom.json', kind='db')
            _db.session.add(rec)
            _db.session.commit()
            result = backup_mod.restore_db_from_record(rec)
            assert result['tables'] == 0
            assert result['rows'] == 0

    def test_restore_failure_rolls_back(self, app, _db, backup_dir):
        """恢复无效数据时回滚并抛异常。"""
        from blog.models import BackupRecord, User

        with app.app_context():
            u = User(username='keep_me', email='k@k.com')
            u.set_password('pw')
            _db.session.add(u)
            _db.session.commit()
            path = backup_dir / 'bad.json'
            # users 表 NOT NULL 列缺失 → INSERT 失败
            payload = {'version': 1, 'tables': {'users': [{'username': None}]}}
            path.write_text(json.dumps(payload), encoding='utf-8')
            rec = BackupRecord(filename='bad.json', kind='db')
            _db.session.add(rec)
            _db.session.commit()
            with pytest.raises(Exception):
                backup_mod.restore_db_from_record(rec)
            # 原有用户应保留（回滚）
            assert User.query.filter_by(username='keep_me').first() is not None


# ── delete_backup ───────────────────────────────────────────
class TestDeleteBackup:
    def test_deletes_file_and_record(self, app, _db, backup_dir):
        from blog.models import BackupRecord

        with app.app_context():
            record = backup_mod.run_backup('db')
            filename = record.filename
            file_path = backup_dir / filename
            assert file_path.exists()
            backup_mod.delete_backup(record)
            assert not file_path.exists()
            assert BackupRecord.query.count() == 0

    def test_missing_file_ok(self, app, _db, backup_dir):
        from blog.models import BackupRecord

        with app.app_context():
            rec = BackupRecord(filename='nonexistent.json', kind='db')
            _db.session.add(rec)
            _db.session.commit()
            backup_mod.delete_backup(rec)
            assert BackupRecord.query.count() == 0


# ── cleanup_old_backups ─────────────────────────────────────
class TestCleanupOldBackups:
    def test_keep_recent(self, app, _db, backup_dir):
        from blog.models import BackupRecord

        with app.app_context():
            for i in range(5):
                rec = BackupRecord(filename=f'backup_full_{i}.zip', kind='full', status='ok')
                rec.created_at = backup_mod.now_cst() - datetime.timedelta(days=i)
                _db.session.add(rec)
            _db.session.commit()
            removed = backup_mod.cleanup_old_backups(keep=2)
            assert removed == 3
            assert BackupRecord.query.count() == 2

    def test_keep_minimum_one(self, app, _db, backup_dir):
        from blog.models import BackupRecord

        with app.app_context():
            rec = BackupRecord(filename='f.zip', kind='full', status='ok')
            _db.session.add(rec)
            _db.session.commit()
            removed = backup_mod.cleanup_old_backups(keep=0)
            assert removed == 0
            assert BackupRecord.query.count() == 1

    def test_no_records(self, app, _db, backup_dir):
        with app.app_context():
            removed = backup_mod.cleanup_old_backups(keep=7)
        assert removed == 0

    def test_only_full_kind_counted(self, app, _db, backup_dir):
        from blog.models import BackupRecord

        with app.app_context():
            for kind in ('db', 'uploads'):
                rec = BackupRecord(filename=f'f.{kind}', kind=kind, status='ok')
                _db.session.add(rec)
            _db.session.commit()
            removed = backup_mod.cleanup_old_backups(keep=1)
            assert removed == 0

    def test_only_ok_status_counted(self, app, _db, backup_dir):
        from blog.models import BackupRecord

        with app.app_context():
            rec = BackupRecord(filename='f.zip', kind='full', status='failed')
            _db.session.add(rec)
            _db.session.commit()
            removed = backup_mod.cleanup_old_backups(keep=1)
            assert removed == 0

    def test_keep_more_than_available(self, app, _db, backup_dir):
        from blog.models import BackupRecord

        with app.app_context():
            for i in range(3):
                rec = BackupRecord(filename=f'f{i}.zip', kind='full', status='ok')
                _db.session.add(rec)
            _db.session.commit()
            removed = backup_mod.cleanup_old_backups(keep=10)
            assert removed == 0
            assert BackupRecord.query.count() == 3