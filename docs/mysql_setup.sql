-- ============================================
-- HOSHINO Blog · MySQL 数据库初始化脚本
-- 使用方法：
--   mysql -u root -p < mysql_setup.sql
-- ============================================

-- 1. 创建数据库（如果不存在）
CREATE DATABASE IF NOT EXISTS `hoshino_blog`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

-- 2. 创建专用用户（如果不存在）
--    密码请务必修改为强密码！
CREATE USER IF NOT EXISTS 'hoshino'@'localhost'
  IDENTIFIED BY 'hoshino_pass';

-- 3. 授予该用户全部权限
GRANT ALL PRIVILEGES ON `hoshino_blog`.*
  TO 'hoshino'@'localhost';

-- 4. 刷新权限使生效
FLUSH PRIVILEGES;

-- 5. 验证
-- SELECT '数据库创建成功!' AS status;
-- SHOW DATABASES LIKE 'hoshino_blog';
