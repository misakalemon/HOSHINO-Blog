# -*- coding: utf-8 -*-
"""
HOSHINO Blog — 价格数据模块

数据来源：
  - Selenium + Docker Chrome → Baidu 搜索 → 价格提取
  - 手动录入（管理员网页输入）

新品发布后，管理员可在网页上添加商品，系统自动尝试获取价格。
"""
import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models import db, ProductSource, PriceRecord, Product

logger = logging.getLogger(__name__)

_MAX_WORKERS = 3
_SELENIUM_URL = 'http://localhost:4444/wd/hub'
_BROWSER_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'


# ═══════════════════════════════════════════════
# Selenium 工具
# ═══════════════════════════════════════════════

def _create_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('user-agent=' + _BROWSER_UA)
    return webdriver.Remote(command_executor=_SELENIUM_URL, options=options)


# ═══════════════════════════════════════════════
# Baidu 搜索价格提取
# ═══════════════════════════════════════════════

def crawl_via_baidu(product_name):
    """通过百度搜索 + Selenium 提取产品价格。"""
    driver = None
    try:
        driver = _create_driver()
        driver.get(f'https://www.baidu.com/s?wd={product_name}+价格')
        import time; time.sleep(2.5)
        html = driver.page_source

        prices = set()
        for pat in [
            r'(?:价格|售价|到手价)[：:\s]*[¥￥]?\s*([\d,]+(?:\.\d{2})?)',
            r'[¥￥]\s*([\d,]+(?:\.\d{2})?)',
            r'([\d,]+(?:\.\d{2})?)\s*元',
        ]:
            for m in re.finditer(pat, html):
                try:
                    v = float(m.group(1).replace(',', ''))
                    if 100 < v < 99999:
                        prices.add(v)
                except (ValueError, IndexError):
                    continue
        if not prices:
            return None
        sorted_p = sorted(prices)
        n = len(sorted_p)
        if n >= 4:
            mid = sorted_p[n // 4: 3 * n // 4]
            return round(sum(mid) / len(mid), 2)
        return sorted_p[0]
    except Exception as e:
        logger.error('Baidu搜索失败 %s: %s', product_name, e)
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def crawl_price(site, url):
    """爬取价格入口（兼容旧接口）。"""
    return crawl_via_baidu(url) if site == 'baidu' else None


def crawl_all_active_sources():
    """爬取所有无价格记录的商品。"""
    products = Product.query.all()
    count = 0
    for product in products:
        if product.latest_price():
            continue  # 已有价格，跳过
        logger.info('正在爬取: %s', product.name)
        price = crawl_via_baidu(product.name)
        if price is not None:
            source = ProductSource.query.filter_by(
                product_id=product.id, site='baidu'
            ).first()
            if not source:
                source = ProductSource(
                    product_id=product.id, site='baidu', url='', is_active=True,
                )
                db.session.add(source)
                db.session.flush()
            record = PriceRecord(
                source_id=source.id, product_id=product.id, price=price,
            )
            db.session.add(record)
            source.latest_price = price
            count += 1
            logger.info('✅ %s → ¥%.0f', product.name, price)
        else:
            logger.warning('❌ %s: 未获取到价格', product.name)
    if count > 0:
        db.session.commit()
    logger.info('爬取完成: %d/%d 成功', count, len(products))
    return count


# ═══════════════════════════════════════════════
# 全品类电子元器件数据库
# ═══════════════════════════════════════════════

ALL_PRODUCTS = [
    # ═══ Intel CPU ═══
    {'name': 'Intel Core Ultra 9 285K',       'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core Ultra 7 265K',       'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core Ultra 5 245K',       'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core i9-14900K',          'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core i7-14700K',          'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core i5-14600K',          'brand': 'Intel',  'category': 'CPU'},
    {'name': 'Intel Core i3-14100F',          'brand': 'Intel',  'category': 'CPU'},

    # ═══ AMD CPU ═══
    {'name': 'AMD Ryzen 9 9950X',             'brand': 'AMD',    'category': 'CPU'},
    {'name': 'AMD Ryzen 9 9900X',             'brand': 'AMD',    'category': 'CPU'},
    {'name': 'AMD Ryzen 7 9800X3D',           'brand': 'AMD',    'category': 'CPU'},
    {'name': 'AMD Ryzen 7 9700X',             'brand': 'AMD',    'category': 'CPU'},
    {'name': 'AMD Ryzen 5 9600X',             'brand': 'AMD',    'category': 'CPU'},
    {'name': 'AMD Ryzen 5 7600',              'brand': 'AMD',    'category': 'CPU'},

    # ═══ NVIDIA 显卡 ═══
    {'name': 'NVIDIA RTX 5090',               'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 5080',               'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 5070 Ti',            'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 5070',               'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 4090',               'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 4080 Super',         'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 4070 Ti Super',      'brand': 'NVIDIA', 'category': '显卡'},
    {'name': 'NVIDIA RTX 4060',               'brand': 'NVIDIA', 'category': '显卡'},

    # ═══ AMD 显卡 ═══
    {'name': 'AMD Radeon RX 9070 XT',         'brand': 'AMD',    'category': '显卡'},
    {'name': 'AMD Radeon RX 9070',            'brand': 'AMD',    'category': '显卡'},
    {'name': 'AMD Radeon RX 7900 XTX',        'brand': 'AMD',    'category': '显卡'},
    {'name': 'AMD Radeon RX 7800 XT',         'brand': 'AMD',    'category': '显卡'},

    # ═══ 内存 DDR5 ═══
    {'name': 'Kingston Fury DDR5 32GB 6000MHz','brand': 'Kingston', 'category': '内存'},
    {'name': 'Kingston Fury DDR5 16GB 5600MHz','brand': 'Kingston', 'category': '内存'},
    {'name': 'Corsair Vengeance DDR5 32GB',   'brand': 'Corsair', 'category': '内存'},
    {'name': 'G.Skill Trident Z5 DDR5 32GB',  'brand': 'G.Skill', 'category': '内存'},
    {'name': 'Crucial DDR5 Pro 32GB 5600MHz', 'brand': 'Crucial', 'category': '内存'},

    # ═══ 固态硬盘 ═══
    {'name': 'Samsung 990 Pro 2TB NVMe',      'brand': 'Samsung', 'category': '固态硬盘'},
    {'name': 'Samsung 990 Pro 1TB NVMe',      'brand': 'Samsung', 'category': '固态硬盘'},
    {'name': 'WD Black SN850X 2TB',           'brand': 'WD',      'category': '固态硬盘'},
    {'name': 'WD Black SN850X 1TB',           'brand': 'WD',      'category': '固态硬盘'},
    {'name': 'Seagate FireCuda 530 2TB',      'brand': 'Seagate', 'category': '固态硬盘'},
    {'name': 'SK Hynix Platinum P41 1TB',     'brand': 'SK Hynix','category': '固态硬盘'},

    # ═══ Intel 主板 ═══
    {'name': 'ASUS ROG STRIX Z890-E',         'brand': 'ASUS',    'category': '主板'},
    {'name': 'ASUS ROG STRIX Z790-E',         'brand': 'ASUS',    'category': '主板'},
    {'name': 'MSI MEG Z890 ACE',              'brand': 'MSI',     'category': '主板'},
    {'name': 'MSI MPG Z790 CARBON',           'brand': 'MSI',     'category': '主板'},
    {'name': 'Gigabyte Z890 AORUS MASTER',    'brand': 'Gigabyte','category': '主板'},
    {'name': 'ASUS TUF B760M-PLUS',           'brand': 'ASUS',    'category': '主板'},

    # ═══ AMD 主板 ═══
    {'name': 'ASUS ROG CROSSHAIR X870E',      'brand': 'ASUS',    'category': '主板'},
    {'name': 'MSI MEG X670E ACE',             'brand': 'MSI',     'category': '主板'},
    {'name': 'ASUS TUF B650M-PLUS',           'brand': 'ASUS',    'category': '主板'},
    {'name': 'Gigabyte B650 AORUS ELITE',     'brand': 'Gigabyte','category': '主板'},

    # ═══ 电源 ═══
    {'name': 'Corsair RM1000x 1000W',         'brand': 'Corsair', 'category': '电源'},
    {'name': 'Corsair RM850x 850W',           'brand': 'Corsair', 'category': '电源'},
    {'name': 'Seasonic Prime TX-1000',        'brand': 'Seasonic','category': '电源'},
    {'name': 'EVGA SuperNOVA 1000 G7',        'brand': 'EVGA',    'category': '电源'},
    {'name': 'Cooler Master MWE 850W',        'brand': 'CoolerMaster','category':'电源'},

    # ═══ 散热器 ═══
    {'name': 'NZXT Kraken X73 360mm',         'brand': 'NZXT',    'category': '散热器'},
    {'name': 'Corsair H150i Elite 360mm',     'brand': 'Corsair', 'category': '散热器'},
    {'name': 'Noctua NH-D15',                'brand': 'Noctua',  'category': '散热器'},
    {'name': 'DeepCool AK620',                'brand': 'DeepCool','category': '散热器'},
    {'name': 'Thermalright Peerless Assassin','brand': 'Thermalright','category':'散热器'},

    # ═══ 机箱 ═══
    {'name': 'NZXT H7 Flow',                  'brand': 'NZXT',    'category': '机箱'},
    {'name': 'Corsair 5000D Airflow',         'brand': 'Corsair', 'category': '机箱'},
    {'name': 'Lian Li O11 Dynamic EVO',       'brand': 'Lian Li', 'category': '机箱'},
    {'name': 'Fractal Design North',          'brand': 'Fractal', 'category': '机箱'},

    # ═══ 显示器 ═══
    {'name': 'Dell U2724D 4K 27"',            'brand': 'Dell',    'category': '显示器'},
    {'name': 'ASUS ROG PG32UCDM 4K OLED',     'brand': 'ASUS',    'category': '显示器'},
    {'name': 'Samsung Odyssey OLED G8 34"',   'brand': 'Samsung', 'category': '显示器'},
    {'name': 'LG 27GP950 4K 144Hz',           'brand': 'LG',      'category': '显示器'},

    # ═══ 智能手机 ═══
    {'name': 'Apple iPhone 16 Pro Max',       'brand': 'Apple',   'category': '手机'},
    {'name': 'Apple iPhone 16 Pro',           'brand': 'Apple',   'category': '手机'},
    {'name': 'Samsung Galaxy S25 Ultra',      'brand': 'Samsung', 'category': '手机'},
    {'name': 'Samsung Galaxy S25',            'brand': 'Samsung', 'category': '手机'},
    {'name': 'Xiaomi 15 Pro',                 'brand': 'Xiaomi',  'category': '手机'},
    {'name': 'OnePlus 13',                    'brand': 'OnePlus', 'category': '手机'},
    {'name': 'Google Pixel 10 Pro',           'brand': 'Google',  'category': '手机'},

    # ═══ 平板 ═══
    {'name': 'Apple iPad Pro M4 13"',         'brand': 'Apple',   'category': '平板'},
    {'name': 'Apple iPad Air M3 11"',         'brand': 'Apple',   'category': '平板'},
    {'name': 'Samsung Galaxy Tab S10 Ultra',  'brand': 'Samsung', 'category': '平板'},

    # ═══ 笔记本电脑 ═══
    {'name': 'Apple MacBook Air M4',          'brand': 'Apple',   'category': '笔记本'},
    {'name': 'Apple MacBook Pro 14 M4 Pro',   'brand': 'Apple',   'category': '笔记本'},
    {'name': 'Lenovo ThinkPad X1 Carbon',     'brand': 'Lenovo',  'category': '笔记本'},
    {'name': 'ASUS ROG Zephyrus G16',         'brand': 'ASUS',    'category': '笔记本'},
    {'name': 'Dell XPS 16',                   'brand': 'Dell',    'category': '笔记本'},
    {'name': 'HP Spectre x360 16',            'brand': 'HP',      'category': '笔记本'},
    {'name': 'Razer Blade 16',                'brand': 'Razer',   'category': '笔记本'},

    # ═══ 耳机 ═══
    {'name': 'Sony WH-1000XM5',               'brand': 'Sony',    'category': '耳机'},
    {'name': 'Apple AirPods Pro 2 USB-C',     'brand': 'Apple',   'category': '耳机'},
    {'name': 'Bose QuietComfort Ultra',       'brand': 'Bose',    'category': '耳机'},
    {'name': 'Sennheiser Momentum 4',         'brand': 'Sennheiser','category':'耳机'},

    # ═══ 智能手表 ═══
    {'name': 'Apple Watch Ultra 2',           'brand': 'Apple',   'category': '手表'},
    {'name': 'Apple Watch Series 10',         'brand': 'Apple',   'category': '手表'},
    {'name': 'Samsung Galaxy Watch Ultra',    'brand': 'Samsung', 'category': '手表'},
    {'name': 'Huawei Watch GT 5 Pro',         'brand': 'Huawei',  'category': '手表'},

    # ═══ 相机 ═══
    {'name': 'Sony A7M5 (A7 V)',             'brand': 'Sony',    'category': '相机'},
    {'name': 'Canon EOS R5 Mark II',          'brand': 'Canon',   'category': '相机'},
    {'name': 'Nikon Z8',                      'brand': 'Nikon',   'category': '相机'},
    {'name': 'Fujifilm X-T5',                 'brand': 'Fujifilm','category': '相机'},

    # ═══ 键鼠外设 ═══
    {'name': 'Logitech MX Master 3S',         'brand': 'Logitech','category': '鼠标'},
    {'name': 'Razer DeathAdder V3 Pro',       'brand': 'Razer',   'category': '鼠标'},
    {'name': 'Logitech G Pro X Superlight 2', 'brand': 'Logitech','category': '鼠标'},
    {'name': 'Keychron Q1 Pro',               'brand': 'Keychron','category': '键盘'},
    {'name': 'Razer BlackWidow V4 Pro',       'brand': 'Razer',   'category': '键盘'},

    # ═══ 游戏主机 ═══
    {'name': 'Sony PS5 Pro',                  'brand': 'Sony',    'category': '游戏机'},
    {'name': 'Sony PS5 Slim',                 'brand': 'Sony',    'category': '游戏机'},
    {'name': 'Xbox Series X',                 'brand': 'Microsoft','category':'游戏机'},
    {'name': 'Nintendo Switch OLED',          'brand': 'Nintendo','category': '游戏机'},

    # ═══ 路由器/网络 ═══
    {'name': 'ASUS RT-AX86U Pro',             'brand': 'ASUS',    'category': '路由器'},
    {'name': 'TP-Link Archer AX11000',        'brand': 'TP-Link', 'category': '路由器'},
    {'name': 'Ubiquiti UniFi 6 Pro',          'brand': 'Ubiquiti','category': '路由器'},
    {'name': 'MikroTik RB5009',               'brand': 'MikroTik','category': '路由器'},
    {'name': 'ASUS GT-AX11000 Pro',           'brand': 'ASUS',    'category': '路由器'},
]


def init_sample_products():
    """初始化全品类商品数据库。

    首次启动时自动导入 ALL_PRODUCTS。
    之后新品发布时，管理员可通过网页添加商品，系统自动获取价格。
    """
    from blog.models import db, Product

    if Product.query.first() is not None:
        return

    for item in ALL_PRODUCTS:
        p = Product(name=item['name'], brand=item['brand'], category=item['category'],
                    specs=_generate_specs(item['name'], item['brand'], item['category']))
        db.session.add(p)
    db.session.commit()
    logger.info('已初始化 %d 个商品，覆盖 %d 个品类',
                len(ALL_PRODUCTS),
                len(set(p['category'] for p in ALL_PRODUCTS)))


def get_ref_price(category):
    """返回品类参考价格。"""
    ref = {
        'CPU': 3299, '显卡': 6999, '内存': 899, '固态硬盘': 999,
        '主板': 2499, '电源': 899, '散热器': 599, '机箱': 699,
        '显示器': 3999, '手机': 5999, '平板': 4999, '笔记本': 8999,
        '耳机': 1999, '手表': 3999, '相机': 15999, '鼠标': 499,
        '键盘': 799, '游戏机': 3999, '路由器': 999,
    }
    return ref.get(category, 1000)


def _generate_specs(name, brand, category):
    """根据品类自动生成关键规格参数。"""
    name_lower = name.lower()

    if category == 'CPU':
        core_count = '16C/32T' if '9' in name and 'Ultra 9' in name else \
                     '8C/16T' if '7' in name and '9700' in name else \
                     '8C/16T' if '7' in name else \
                     '6C/12T' if '5' in name else '4C/8T'
        socket = 'LGA1851' if 'Ultra' in name else \
                 'AM5' if 'Ryzen' in name else 'LGA1700'
        tdp = '125W' if '9' in name or '7' in name else '65W'
        return {'核心/线程': core_count, '接口': socket, 'TDP': tdp, '架构': 'Zen 5' if '9000' in name else 'Arrow Lake' if 'Ultra' in name else 'Raptor Lake'}

    if category == '显卡':
        vram = '24GB' if '5090' in name or '4090' in name else \
               '16GB' if '5080' in name or '4080' in name or '7900' in name else \
               '12GB' if '5070' in name or '4070' in name else '8GB'
        return {'显存': vram, '显存类型': 'GDDR7' if '50' in name else 'GDDR6X', '接口': 'PCIe 5.0'}

    if category == '内存':
        size = '32GB (2×16GB)' if '32GB' in name else '16GB (2×8GB)'
        speed = '6000MHz' if '6000' in name else '5600MHz'
        return {'容量': size, '频率': speed, '类型': 'DDR5', '散热': '铝合金散热片'}

    if category == '固态硬盘':
        size = '2TB' if '2TB' in name else '1TB'
        return {'容量': size, '接口': 'M.2 NVMe PCIe 4.0', '顺序读取': '7450MB/s' if '990' in name else '7300MB/s', '顺序写入': '6900MB/s'}

    if category == '主板':
        chipset = 'Z890' if 'Z890' in name else 'Z790' if 'Z790' in name else \
                  'X870E' if 'X870' in name else 'X670E' if 'X670' in name else \
                  'B760' if 'B760' in name else 'B650'
        socket_mb = 'LGA1851' if chipset.startswith('Z8') else \
                    'LGA1700' if chipset == 'Z790' or chipset == 'B760' else 'AM5'
        return {'芯片组': chipset, 'CPU插槽': socket_mb, '内存插槽': '4×DDR5', 'PCIe': 'PCIe 5.0'}

    if category == '电源':
        wattage = '1000W' if '1000' in name else '850W'
        return {'功率': wattage, '认证': '80+ Gold', '模组化': '全模组', '风扇': '135mm'}

    if category == '散热器':
        return {'类型': '360mm AIO' if '360' in name or 'X73' in name or 'H150' in name else '风冷', '风扇': '3×120mm' if '360' in name else '双塔', 'TDP': '280W+' if '360' in name or 'D15' in name else '260W', '兼容': 'Intel LGA1851/1700 & AMD AM5'}

    if category == '机箱':
        return {'类型': 'ATX中塔', '主板兼容': 'ATX / M-ATX / ITX', '显卡限长': '420mm', '散热器限高': '170mm'}

    if category == '显示器':
        size_disp = '27"' if '27' in name else '32"' if '32' in name else '34"'
        panel = 'OLED' if 'OLED' in name or 'OLED' in name else 'IPS'
        res = '4K UHD' if '4K' in name else '3440×1440' if '34' in name else '4K'
        return {'尺寸': size_disp, '面板': panel, '分辨率': res, '刷新率': '240Hz' if '240' in name else '144Hz'}

    if category == '手机':
        soc = 'A19 Pro' if 'iPhone 16' in name else \
              'Snapdragon 8 Elite' if 'Samsung' in name or 'OnePlus' in name or 'Xiaomi' in name else \
              'Tensor G5' if 'Pixel' in name else '麒麟9010'
        screen = '6.9"' if 'Pro Max' in name or 'Ultra' in name else '6.3"' if 'Pro' in name else '6.1"'
        return {'处理器': soc, '屏幕': screen, 'RAM': '12GB' if 'Pro' in name else '8GB', '存储': '256GB'}

    if category == '平板':
        return {'处理器': 'Apple M4' if 'M4' in name else 'Apple M3', '屏幕': '13"' if '13' in name else '11"', '存储': '256GB', '系统': 'iPadOS'}

    if category == '笔记本':
        cpu_nb = 'Apple M4' if 'MacBook' in name and 'M4' in name else 'Apple M4 Pro' if 'M4 Pro' in name else \
                 'Core Ultra 9' if 'ROG' in name else 'Core Ultra 7'
        ram_nb = '24GB统一内存' if 'MacBook' in name else '32GB DDR5'
        return {'处理器': cpu_nb, '内存': ram_nb, '存储': '512GB SSD' if 'Air' in name else '1TB SSD', '屏幕': '13.6"' if 'Air' in name else '14.2"' if 'Pro' in name else '16"'}

    if category == '耳机':
        driver = '40mm' if 'WH-1000' in name or 'Momentum' in name else 'H2芯片' if 'AirPods' in name else '35mm'
        anc = '自适应降噪' if 'Ultra' in name or '1000X' in name else '主动降噪'
        return {'驱动单元': driver, '降噪': anc, '续航': '30h' if '1000X' in name or 'Ultra' in name else '6h', '连接': '蓝牙 5.3'}

    if category == '手表':
        chip = 'Apple S9 SiP' if 'Apple' in name else 'Exynos W1000'
        screen_watch = '49mm' if 'Ultra' in name else '45mm'
        return {'芯片': chip, '表盘': screen_watch, '防水': '100m' if 'Ultra' in name else '50m', '续航': '72h' if 'Ultra' in name else '36h'}

    if category == '相机':
        sensor = '全画幅' if 'A7' in name or 'R5' in name or 'Z8' in name else 'APS-C'
        mp = '61MP' if 'R5' in name else '50MP' if 'Z8' in name else '45MP' if 'A7' in name else '40MP'
        return {'传感器': sensor, '有效像素': mp, '防抖': '机身5轴防抖', '视频': '8K 30p'}

    if category == '鼠标':
        sensor_ms = 'HERO 2' if 'Logitech' in name else 'Focus Pro 30K'
        return {'传感器': sensor_ms, '连接': '无线 2.4G / 蓝牙', '续航': '70h' if 'Logitech' in name else '90h', '重量': '60g'}

    if category == '键盘':
        return {'类型': '机械键盘', '轴体': '热插拔', '连接': '有线/无线/蓝牙', '布局': '75%'}

    if category == '游戏机':
        soc_console = '定制 AMD Ryzen Zen 2' if 'PS5' in name else '定制 NVIDIA'
        storage_console = '2TB SSD' if 'Pro' in name else '1TB SSD'
        return {'处理器': soc_console, '存储': storage_console, '光线追踪': '支持', 'HDR': '支持'}

    if category == '路由器':
        wifi = 'WiFi 7' if 'AX' not in name else 'WiFi 6'
        speed_router = '11000Mbps' if '11000' in name else '10000Mbps'
        return {'WiFi标准': wifi, '速度': speed_router, '频段': '三频', '天线': '8根'}

    return {}
