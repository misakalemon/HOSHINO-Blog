"""
HOSHINO Blog — 价格追踪路由

提供前台价格看板和图表，包括：
  - 价格看板首页（分页商品列表 + 分类筛选）
  - 商品价格历史详情页面（带 ECharts 图表）
  - 价格历史 JSON API（供前端图表异步加载）
  - 手动触发爬取（管理员）
  - 手动录入价格
  - 添加新产品到追踪列表
  - 汇率走势页面 + JSON API

所有路由挂在 price_bp（Blueprint）上，URL 前缀为 /price。

函数列表：
  index()             — 价格看板首页
  detail(id)          — 商品价格历史详情
  api_history(id)     — 价格历史 JSON API
  trigger_crawl()     — 手动触发价格爬取
  manual_price()      — 手动录入价格
  add_product()       — 添加新产品
  rates_page()        — 汇率走势页面
  api_rates()         — 汇率历史 JSON API
"""
import datetime
import logging

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required

from . import price_bp
from .admin import editor_required
from .crawler import crawl_all_active_sources
from .models import ExchangeRate, PriceRecord, Product, ProductSource, db

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════
# 价格看板首页
# ═══════════════════════════════════════════════
@price_bp.route('/')
def index():
    """价格看板：展示所有商品的最新价格（分页 + 侧边栏）。

    URL 参数：
      page      — 页码（默认 1）
      per_page  — 每页条数（默认 24）
      category  — 按品类筛选（可选）

    Template: price/dashboard.html
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 24, type=int)
    cat_filter = request.args.get('category', '')

    query = Product.query
    if cat_filter:
        query = query.filter_by(category=cat_filter)

    products = query.order_by(Product.category, Product.name).paginate(
        page=page, per_page=per_page, error_out=False
    )
    categories = db.session.query(Product.category).distinct().order_by(Product.category).all()
    categories = [c[0] for c in categories]

    return render_template('price/dashboard.html',
        products=products, categories=categories,
        current_category=cat_filter,
        current_per_page=per_page,
        per_page_options=[12, 24, 48, 96],
    )


# ═══════════════════════════════════════════════
# 商品价格详情 + 图表
# ═══════════════════════════════════════════════
@price_bp.route('/product/<int:id>')
def detail(id):
    """商品价格历史详情。

    展示商品的基本信息、各来源最新价格、以及历史价格走势图表。
    图表数据通过 ajax 异步加载 api_history。

    Args:
        id: 商品 ID

    URL 参数：
      days — 显示最近 N 天的数据（默认 30）

    Template: price/detail.html
    """
    product = Product.query.get_or_404(id)
    days = request.args.get('days', 30, type=int)
    records = product.price_history(days=days)
    return render_template('price/detail.html',
        product=product, records=records, days=days
    )


# ═══════════════════════════════════════════════
# 价格数据 JSON API（供 ECharts 调用）
# ═══════════════════════════════════════════════
@price_bp.route('/api/product/<int:id>/history')
def api_history(id):
    """返回商品价格历史 JSON 数据。

    按来源分组返回，供前端 ECharts 折线图使用。

    Args:
        id: 商品 ID

    URL 参数：
      days — 最近 N 天（默认 30）

    返回格式：
    {
      "name": "商品名",
      "sources": [
        {
          "site": "jd",
          "url": "...",
          "latest_price": 1999.00,
          "prices": [
            {"date": "2026-01-15 12:00", "price": 1999.00},
            ...
          ]
        }
      ]
    }
    """
    product = Product.query.get_or_404(id)
    days = request.args.get('days', 30, type=int)
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    sources_data = []
    for source in product.sources:
        records = PriceRecord.query.filter(
            PriceRecord.source_id == source.id,
            PriceRecord.recorded_at >= since
        ).order_by(PriceRecord.recorded_at.asc()).all()

        prices = [
            {
                'date': r.recorded_at.strftime('%Y-%m-%d %H:%M'),
                'price': r.price,
            }
            for r in records
        ]
        sources_data.append({
            'site': source.site,
            'url': source.url,
            'latest_price': source.latest_price,
            'prices': prices,
        })

    return jsonify({
        'name': product.name,
        'sources': sources_data,
    })


# ═══════════════════════════════════════════════
# 手动触发爬取（仅管理员）
# ═══════════════════════════════════════════════
@price_bp.route('/crawl', methods=['POST'])
@editor_required
def trigger_crawl():
    """手动触发一次价格爬取。

    供管理员通过按钮调用，调用 crawl_all_active_sources()
    遍历所有商品的所有数据源获取最新价格。

    爬取完成后刷新价格看板页面并显示统计结果。
    """
    count = crawl_all_active_sources()
    flash(f'价格爬取完成，成功记录 {count} 条', 'success')
    return redirect(url_for('price.index'))


# ═══════════════════════════════════════════════
# 手动输入价格
# ═══════════════════════════════════════════════
@price_bp.route('/manual-price', methods=['POST'])
@editor_required
def manual_price():
    """手动输入/更新商品价格。

    当爬虫无法自动获取价格时，用户可通过此接口手动录入。
    录入的价格会被保存到 manual 来源的历史记录中。

    表单字段：
      product_id — 商品 ID
      price      — 价格（浮点数）
    """
    product_id = request.form.get('product_id', type=int)
    price = request.form.get('price', type=float)

    if not product_id or not price:
        flash('请填写完整信息', 'error')
        return redirect(url_for('price.index'))

    product = Product.query.get_or_404(product_id)

    # 查找或创建默认的 manual 来源
    source = ProductSource.query.filter_by(
        product_id=product_id, site='manual'
    ).first()
    if not source:
        source = ProductSource(
            product_id=product_id,
            site='manual',
            url='',
            is_active=True,
        )
        db.session.add(source)
        db.session.flush()

    # 创建价格记录
    record = PriceRecord(
        source_id=source.id,
        product_id=product_id,
        price=price,
    )
    db.session.add(record)
    source.latest_price = price
    flash(f'已录入 {product.name} 价格 ¥{price:.2f}', 'success')
    return redirect(url_for('price.index'))


# ═══════════════════════════════════════════════
# 添加新产品
# ═══════════════════════════════════════════════
@price_bp.route('/add-product', methods=['POST'])
@editor_required
def add_product():
    """添加新产品到追踪列表。

    新品发布后，管理员可通过此接口添加。
    添加后自动尝试 Amazon 直爬获取价格。
    若自动获取失败，可稍后手动录入。

    表单字段：
      name     — 商品名称（必填）
      brand    — 品牌（可选）
      category — 品类（必填）
    """
    name = request.form.get('name', '').strip()
    brand = request.form.get('brand', '').strip()
    category = request.form.get('category', '').strip()

    if not name or not category:
        flash('请填写商品名称和品类', 'error')
        return redirect(url_for('price.index'))

    # 检查是否已存在
    existing = Product.query.filter_by(name=name).first()
    if existing:
        flash(f'商品 "{name}" 已存在', 'error')
        return redirect(url_for('price.index'))

    product = Product(name=name, brand=brand, category=category)
    db.session.add(product)
    db.session.commit()

    price = None
    site = ''

    # Amazon 直爬（curl_cffi）
    try:
        from .apify_client import scraper
        price = scraper.fetch_amazon_price(name)
        site = 'amazon'
    except Exception as e:
        logger.error('Amazon 直爬查询失败: %s', e)

    if price and site:
        source = ProductSource(
            product_id=product.id, site=site, url='', is_active=True,
        )
        db.session.add(source)
        db.session.flush()
        record = PriceRecord(
            source_id=source.id, product_id=product.id, price=price,
        )
        db.session.add(record)
        source.latest_price = price
        db.session.commit()
        flash(f'已添加 {name}，{site} 价格 ¥{price:.0f}', 'success')
    else:
        flash(f'已添加 {name}，自动获取价格失败，请手动录入', 'warning')

    return redirect(url_for('price.index'))


# ═══════════════════════════════════════════════
# 汇率走势
# ═══════════════════════════════════════════════
@price_bp.route('/rates')
def rates_page():
    """汇率走势页面。

    展示 USD/CNY、EUR/CNY、GBP/CNY 的历史汇率走势图表。
    图表数据通过 ajax 异步加载 api_rates。

    URL 参数：
      days — 显示最近 N 天（默认 90）

    Template: price/rates.html
    """
    days = request.args.get('days', 90, type=int)
    return render_template('price/rates.html', days=days)


@price_bp.route('/api/rates')
def api_rates():
    """返回汇率历史 JSON 数据。

    按币种分组返回，供前端 ECharts 折线图使用。

    URL 参数：
      days — 最近 N 天（默认 90）

    返回格式：
    {
      "rates": [
        { "currency": "USD", "history": [{"date": "01-15", "rate": 7.2}, ...] },
        ...
      ]
    }
    """
    days = request.args.get('days', 90, type=int)
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    records = ExchangeRate.query.filter(
        ExchangeRate.recorded_at >= since
    ).order_by(ExchangeRate.recorded_at.asc()).all()

    grouped = {}
    for r in records:
        grouped.setdefault(r.currency, []).append({
            'date': r.recorded_at.strftime('%m-%d'),
            'rate': r.rate,
        })

    rates_data = [
        {'currency': c, 'history': h}
        for c, h in sorted(grouped.items())
    ]

    return jsonify({'rates': rates_data})
