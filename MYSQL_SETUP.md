# HOSHINO Blog · MySQL 配置指南

> 本文档详细说明如何将 HOSHINO Blog 从 SQLite 切换为 MySQL 数据库。

---

## 目录

- [切换方式对比](#切换方式对比)
- [前置条件](#前置条件)
- [方式一：一键脚本（推荐）](#方式一一键脚本推荐)
- [方式二：手动配置](#方式二手动配置)
- [验证连接](#验证连接)
- [从 SQLite 迁移数据到 MySQL](#从-sqlite-迁移数据到-mysql)
- [常见问题](#常见问题)

---

## 切换方式对比

| 特性 | SQLite | MySQL |
|------|--------|-------|
| 配置难度 | 零配置 | 需安装 MySQL 服务 |
| 适用场景 | 本地开发 / 单用户 | 生产环境 / 多用户并发 |
| 性能 | 单文件，低并发 | 高并发，企业级 |
| 数据管理 | 无密码保护 | 用户权限体系 |

---

## 前置条件

### 1. 安装 MySQL 服务

```bash
# Debian / Ubuntu
sudo apt update
sudo apt install mysql-server -y

# CentOS / RHEL
sudo yum install mysql-server -y

# macOS (Homebrew)
brew install mysql
```

### 2. 启动 MySQL

```bash
# Linux (systemd)
sudo systemctl start mysql
sudo systemctl enable mysql

# macOS
brew services start mysql
```

### 3. 安装 Python MySQL 驱动

```bash
pip install pymysql
```

> 如需从 `requirements.txt` 安装，先取消注释：
> ```bash
> # 编辑 requirements.txt，去掉 pymysql 前的 # 号
> pip install -r requirements.txt
> ```

---

## 方式一：一键脚本（推荐）

项目提供了自动初始化脚本，一键完成数据库和用户创建：

```bash
# 1. 进入项目目录
cd hoshino_blog

# 2. 执行建库脚本（会提示输入 root 密码）
mysql -u root -p < mysql_setup.sql

# 3. 设置环境变量使用 MySQL
export DB_TYPE=mysql
export DATABASE_URL="mysql+pymysql://hoshino:hoshino_pass@localhost:3306/hoshino_blog?charset=utf8mb4"

# 4. 启动（首次运行自动建表 + 创建管理员）
python app.py

# 5. 访问
# 前台: http://localhost:5000
# 后台: http://localhost:5000/admin
```

---

## 方式二：手动配置

### 步骤 1：登录 MySQL

```bash
mysql -u root -p
```

### 步骤 2：创建数据库和用户

```sql
-- 创建数据库
CREATE DATABASE IF NOT EXISTS `hoshino_blog`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

-- 创建用户（请修改为强密码）
CREATE USER IF NOT EXISTS 'hoshino'@'localhost'
  IDENTIFIED BY '你的强密码';

-- 授权
GRANT ALL PRIVILEGES ON `hoshino_blog`.*
  TO 'hoshino'@'localhost';

-- 刷新权限
FLUSH PRIVILEGES;

-- 退出
EXIT;
```

### 步骤 3：配置环境变量

**方法 A：使用 .env 文件（推荐）**

```bash
cp .env.example .env
```

编辑 `.env`：

```ini
# 切换为 MySQL
DB_TYPE=mysql

# 填写你的 MySQL 连接信息
DATABASE_URL=mysql+pymysql://hoshino:你的密码@localhost:3306/hoshino_blog?charset=utf8mb4

# 安全密钥
SECRET_KEY=你的随机密钥
```

**方法 B：使用环境变量**

```bash
export DB_TYPE=mysql
export DATABASE_URL="mysql+pymysql://hoshino:你的密码@localhost:3306/hoshino_blog?charset=utf8mb4"
export SECRET_KEY="你的随机密钥"
```

### 步骤 4：启动应用

```bash
python app.py
```

首次启动会自动建表并创建默认管理员（`admin / admin123`）。

---

## 验证连接

启动后查看日志，确认 MySQL 连接成功：

```bash
# 日志中应看到类似输出
# 无报错即连接成功

# 也可在 MySQL 中检查表是否创建
mysql -u hoshino -p

USE hoshino_blog;
SHOW TABLES;
-- 应看到: users, posts, categories, comments
```

---

## 从 SQLite 迁移数据到 MySQL

如果已有 SQLite 数据需要迁移到 MySQL：

### 方法 1：使用 Flask 脚本（推荐）

创建迁移脚本 `migrate_to_mysql.py`：

```python
"""将 SQLite 数据导出为 MySQL 可导入的 SQL"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'blog.db')

def export_sqlite_to_mysql():
    if not os.path.exists(DB_PATH):
        print('SQLite 数据库不存在，无需迁移')
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    for table in ['users', 'categories', 'posts', 'comments']:
        cur.execute(f'SELECT * FROM {table}')
        rows = cur.fetchall()
        print(f'{table}: {len(rows)} 条记录')

    conn.close()
    print('数据迁移准备就绪')
    print('1. 先启动 MySQL 版应用（自动创建空表）')
    print('2. 使用 mysql CLI 或 Sequel Ace 等工具导入数据')

if __name__ == '__main__':
    export_sqlite_to_mysql()
```

```bash
python migrate_to_mysql.py
```

### 方法 2：手动导出导入

```bash
# 1. 从 SQLite 导出 SQL（需安装 sqlite3 工具）
sqlite3 blog.db .dump > backup.sql

# 2. 手动编辑 backup.sql，调整语法差异：
#    - 将 AUTOINCREMENT 替换为 AUTO_INCREMENT
#    - 将 datetime('now') 替换为 NOW()
#    - 删除 PRAGMA 语句

# 3. 导入到 MySQL
mysql -u hoshino -p hoshino_blog < backup.sql
```

---

## 常见问题

### Q：MySQL 连接失败 "Access denied"

**原因**：用户名或密码错误。

```bash
# 检查能否直接用密码登录
mysql -u hoshino -p

# 如果失败，用 root 重置密码
mysql -u root -p
ALTER USER 'hoshino'@'localhost' IDENTIFIED BY '新密码';
FLUSH PRIVILEGES;
```

### Q：MySQL 连接失败 "Can't connect"

**原因**：MySQL 服务未启动或端口错误。

```bash
# 检查 MySQL 是否在运行
sudo systemctl status mysql

# 检查端口
ss -tlnp | grep 3306

# 启动 MySQL
sudo systemctl start mysql
```

### Q：pymysql 安装失败

```bash
# Ubuntu/Debian
sudo apt install python3-dev default-libmysqlclient-dev build-essential
pip install pymysql

# macOS
brew install mysql-client
export PATH="/usr/local/opt/mysql-client/bin:$PATH"
pip install pymysql
```

### Q：如何切换回 SQLite？

```bash
# 方式一：设置环境变量
export DB_TYPE=sqlite

# 方式二：编辑 .env 文件
# DB_TYPE=sqlite
```

### Q：MySQL 字符集乱码？

确保 `DATABASE_URL` 中包含 `?charset=utf8mb4`，且数据库和表的默认字符集为 `utf8mb4`：

```sql
ALTER DATABASE hoshino_blog CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

---

## 配置参考

### `config.py` 中的 MySQL 配置项

```python
class MySQLConfig(Config):
    SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://用户:密码@主机:端口/数据库?charset=utf8mb4'
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,        # 连接池大小
        'pool_recycle': 3600,   # 连接回收时间（秒）
        'pool_pre_ping': True,  # 连接前检查
        'max_overflow': 5,      # 最大溢出连接数
    }
```

### `.env` 完整配置示例

```ini
DB_TYPE=mysql
DATABASE_URL=mysql+pymysql://hoshino:your_password@localhost:3306/hoshino_blog?charset=utf8mb4
SECRET_KEY=your-strong-secret-key-here
FLASK_ENV=production
PORT=5000
```

---

## 目录结构（MySQL 相关文件）

```
hoshino_blog/
├── config.py              # ← 含 MySQLConfig / SQLiteConfig
├── .env.example           # 环境变量模板
├── mysql_setup.sql        # MySQL 建库建用户脚本
├── MYSQL_SETUP.md         # ← 本文档
└── requirements.txt       # ← 含 pymysql（可选）
```

---

*如有其他问题，请提交 Issue 或联系管理员。*
