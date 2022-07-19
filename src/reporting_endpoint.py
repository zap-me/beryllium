import logging
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from sqlalchemy import func, and_

from flask import Blueprint, render_template, redirect
from flask_security.decorators import roles_accepted

from models import Role, User, BrokerOrder
import dasset
import assets

logger = logging.getLogger(__name__)
reporting = Blueprint('reporting', __name__, template_folder='templates/reporting')

# FREQUENTLY USED DATES
def TODAY():
    return date.today()
def YESTERDAY():
    return date.today() - timedelta(days=1)
def TOMORROW():
    return date.today() + timedelta(days=1)
def WEEKDAY():
    return date.today().weekday()
def MONDAY():
    return date.today() - timedelta(days=date.today().weekday())
def NEXT_MONDAY():
    return date.today() + timedelta(days=-date.today().weekday(), weeks=1)
def FIRST_DAY_CURRENT_MONTH():
    return date.today().replace(day=1)
def FIRST_DAY_NEXT_MONTH():
    return date.today().replace(day=1) + relativedelta(months=+1)
def FIRST_DAY_CURRENT_YEAR():
    return date.today().replace(day=1) + relativedelta(month=1)
def FIRST_DAY_NEXT_YEAR():
    return date.today().replace(day=1) + relativedelta(month=1, years=+1)

def user_counting(table, start_date, end_date):
    result = table.query.filter(and_(table.confirmed_at >= str(start_date), table.confirmed_at <= str(end_date))).count()
    if not result:
        result = 0
    return result

def broker_order_amount(table, start_date, end_date, market):
    result = table.query.filter(table.market == market) \
        .filter(and_(table.date >= str(start_date), table.date < str(end_date))) \
        .with_entities(func.sum(table.base_amount)).scalar()
    if not result:
        result = 0
    asset_symbol = market.split('-')[0]
    result = assets.asset_int_to_dec(asset_symbol, result)
    result = '{0:.4f}'.format(result)
    return result

def broker_order_amount_lifetime(table, market):
    result = table.query.filter(table.market == market) \
        .with_entities(func.sum(table.base_amount)).scalar()
    if not result:
        result = 0
    asset_symbol = market.split('-')[0]
    result = assets.asset_int_to_dec(asset_symbol, result)
    result = '{0:.4f}'.format(result)
    return result

def broker_order_count(table, start_date, end_date, market):
    result = table.query.filter(table.market == market) \
        .filter(and_(table.date >= str(start_date), table.date < str(end_date))) \
        .count()
    if not result:
        result = 0
    return result

def broker_order_count_lifetime(table, market):
    result = table.query.filter(table.market == market) \
        .count()
    if not result:
        result = 0
    return result

@reporting.route("/dashboard")
@roles_accepted(Role.ROLE_ADMIN, Role.ROLE_FINANCE)
def dashboard():
    return redirect('dashboard_general')

@reporting.route("/dashboard_general")
@roles_accepted(Role.ROLE_ADMIN, Role.ROLE_FINANCE)
def dashboard_general():
    balances = dasset.account_balances()
    balances_formatted = []
    if balances:
        for balance in balances:
            balance_formatted = dict(symbol=balance.symbol, available=assets.asset_dec_to_str(balance.symbol, balance.available), total=assets.asset_dec_to_str(balance.symbol, balance.total))
            balances_formatted.append(balance_formatted)
    return render_template('reporting/dashboard_general.html', dasset_balances=balances_formatted)

@reporting.route("/dashboard_user")
@roles_accepted(Role.ROLE_ADMIN, Role.ROLE_FINANCE)
def dashboard_user():
    user_count = User.query.count()
    user_count_today = user_counting(User, TODAY(), TOMORROW())
    user_count_yesterday = user_counting(User, YESTERDAY(), TODAY())
    user_count_weekly = user_counting(User, MONDAY(), NEXT_MONDAY())
    user_count_monthly = user_counting(User, FIRST_DAY_CURRENT_MONTH(), FIRST_DAY_NEXT_MONTH())
    user_count_yearly = user_counting(User, FIRST_DAY_CURRENT_YEAR(), FIRST_DAY_NEXT_YEAR())
    return render_template("reporting/dashboard_user.html", user_count_today=user_count_today, user_count_yesterday=user_count_yesterday, user_count_weekly=user_count_weekly, user_count_monthly=user_count_monthly, user_count_yearly=user_count_yearly, user_count_lifetime=user_count)

@reporting.route("/dashboard_report_broker_order")
@roles_accepted(Role.ROLE_ADMIN, Role.ROLE_FINANCE)
def dashboard_report_broker_order():
    orders_data = {}
    for market in assets.MARKETS:
        asset_symbol = market.split('-')[0]
        today = str(TODAY())
        yesterday = str(YESTERDAY())
        tomorrow = str(TOMORROW())
        monday = str(MONDAY())
        next_monday = str(NEXT_MONDAY())
        first_day_current_month = str(FIRST_DAY_CURRENT_MONTH())
        first_day_next_month = str(FIRST_DAY_NEXT_MONTH())
        first_day_current_year = str(FIRST_DAY_CURRENT_YEAR())
        first_day_next_year = str(FIRST_DAY_NEXT_YEAR())
        order_count_today = broker_order_count(BrokerOrder, TODAY(), TOMORROW(), market)
        order_count_yesterday = broker_order_count(BrokerOrder, YESTERDAY(), TODAY(), market)
        order_count_week = broker_order_count(BrokerOrder, MONDAY(), NEXT_MONDAY(), market)
        order_count_month = broker_order_count(BrokerOrder, FIRST_DAY_CURRENT_MONTH(), FIRST_DAY_NEXT_MONTH(), market)
        order_count_year = broker_order_count(BrokerOrder, FIRST_DAY_CURRENT_YEAR(), FIRST_DAY_NEXT_YEAR(), market)
        order_count_lifetime = broker_order_count_lifetime(BrokerOrder, market)
        order_amount_today = broker_order_amount(BrokerOrder, TODAY(), TOMORROW(), market)
        order_amount_yesterday = broker_order_amount(BrokerOrder, YESTERDAY(), TODAY(), market)
        order_amount_week = broker_order_amount(BrokerOrder, MONDAY(), NEXT_MONDAY(), market)
        order_amount_month = broker_order_amount(BrokerOrder, FIRST_DAY_CURRENT_MONTH(), FIRST_DAY_NEXT_MONTH(), market)
        order_amount_year = broker_order_amount(BrokerOrder, FIRST_DAY_CURRENT_YEAR(), FIRST_DAY_NEXT_YEAR(), market)
        order_amount_lifetime = broker_order_amount_lifetime(BrokerOrder, market)
        orders_data[market] = dict(asset_symbol=asset_symbol, today=today, yesterday=yesterday, tomorrow=tomorrow, monday=monday, next_monday=next_monday, first_day_current_month=first_day_current_month, first_day_next_month=first_day_next_month, first_day_current_year=first_day_current_year, first_day_next_year=first_day_next_year, order_count_today=order_count_today, order_count_yesterday=order_count_yesterday, order_count_week=order_count_week, order_count_month=order_count_month, order_count_year=order_count_year, order_count_lifetime=order_count_lifetime, order_amount_today=order_amount_today, order_amount_yesterday=order_amount_yesterday, order_amount_week=order_amount_week, order_amount_month=order_amount_month, order_amount_year=order_amount_year, order_amount_lifetime=order_amount_lifetime)
    return render_template('reporting/dashboard_broker_orders.html', orders_data=orders_data)
