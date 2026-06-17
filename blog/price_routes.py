# -*- coding: utf-8 -*-
"""
HOSHINO Blog — 价格追踪路由

提供前台价格看板和图表。
"""
import datetime
import logging
from flask import render_template, request, redirect, url_for, abort, flash, jsonify, current_app
from flask_login import login_required
from . import price_bp
from .models import db, Product, ProductSource, PriceRecord
from .crawler import crawl_price, crawl_all_active_sources, init_sample_products

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════
# 价格看板首页
# ═══════════════════════════════════════════════
@price_bp.route('/')
def index():
    """价格看板：展示所有商品的最新价格。

    Template: price/dashboard.html
    """
    products = Product.query.order_by(Product.category, Product.name).all()
    return render_template('price/dashboard.html', products=products)


# ═══════════════════════════════════════════════
# 商品价格详情 + 图表
# ═══════════════════════════════════════════════
@price_bp.route('/product/<int:id>')
def detail(id):
    """商品价格历史详情。

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

    按来源分组返回，格式：
    {
      "name": "商品名",
      "sources": [
        {
          "site": "jd",
          "url": "...",
          "prices": [
            {"date": "2026-01-15", "price": 1999.00},
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
@login_required
def trigger_crawl():
    """手动触发一次价格爬取。

    供管理员通过按钮调用。
    """
    count = crawl_all_active_sources()
    flash(f'价格爬取完成，成功记录 {count} 条', 'success')
    return redirect(url_for('price.index'))


# ═══════════════════════════════════════════════
# 手动输入价格
# ═══════════════════════════════════════════════
@price_bp.route('/manual-price', methods=['POST'])
@login_required
def manual_price():
    """手动输入/更新商品价格。

    当爬虫无法自动获取价格时，用户可通过此接口手动录入。
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
@login_required
def add_product():
    """添加新产品到追踪列表。

    新品发布后，管理员可通过此接口添加。
    添加后自动触发 Baidu 搜索获取价格。
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

    # 异步尝试获取价格
    try:
        from .crawler import crawl_via_baidu
        price = crawl_via_baidu(name)
        if price is not None:
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
            db.session.commit()
            flash(f'已添加 {name}，自动获取价格 ¥{price:.0f}', 'success')
        else:
            flash(f'已添加 {name}，自动获取价格失败，请手动录入', 'warning')
    except Exception as e:
        logger.error('新品价格获取失败: %s', e)
        flash(f'已添加 {name}，价格获取异常，请手动录入', 'warning')

    return redirect(url_for('price.index'))
