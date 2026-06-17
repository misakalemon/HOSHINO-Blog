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
