import datetime
import logging

from sqlalchemy.orm.session import Session

import fiatdb_core
import dasset
import assets
from assets import MarketSide
from models import BrokerOrder, ExchangeOrder, FiatDbTransaction
import websocket
import email_utils
import web_utils
import coordinator
import utils

logger = logging.getLogger(__name__)

#
# Helper functions (public)
#

def order_refund(order: BrokerOrder):
    side = MarketSide.parse(order.side)
    # refund users account
    if side is MarketSide.BID:
        asset = order.quote_asset
        amount_int = order.quote_amount
    else:
        asset = order.base_asset
        amount_int = order.base_amount
    return fiatdb_core.tx_create(order.user, FiatDbTransaction.ACTION_CREDIT, asset, amount_int, f'broker order refund: {order.token}')

def order_required_asset(order: BrokerOrder, side: MarketSide):
    assert isinstance(side, MarketSide)
    if side is MarketSide.BID:
        return order.quote_asset, order.quote_amount
    return order.base_asset, order.base_amount

def order_check_funds(db_session: Session, order: BrokerOrder, check_user: bool = True):
    side = MarketSide.parse(order.side)
    if not side:
        return web_utils.INVALID_SIDE
    asset, amount_int = order_required_asset(order, side)
    amount_dec = assets.asset_int_to_dec(asset, amount_int)
    # check funds on dasset
    if not dasset.funds_available_us(asset, amount_dec):
        return web_utils.INSUFFICIENT_LIQUIDITY
    # and funds user has with us
    if check_user and not fiatdb_core.funds_available_user(db_session, order.user, asset, amount_dec):
        return web_utils.INSUFFICIENT_BALANCE
    return None

#
# Helper functions (private)
#

def _broker_order_action(db_session: Session, broker_order: BrokerOrder):
    logger.info('processing broker order %s (%s)..', broker_order.token, broker_order.status)
    updated_records = []
    base_amount_dec = assets.asset_int_to_dec(broker_order.base_asset, broker_order.base_amount)
    quote_amount_dec = assets.asset_int_to_dec(broker_order.quote_asset, broker_order.quote_amount)
    price = quote_amount_dec / base_amount_dec
    price = utils.round_dec(price, assets.asset_decimals(broker_order.quote_asset))
    side = MarketSide.parse(broker_order.side)
    # check side
    if not side:
        logger.error('invalid side "%s" for broker order %s', broker_order.side, broker_order.token)
        broker_order.status = broker_order.STATUS_FAILED
        updated_records.append(broker_order)
        return updated_records
    # check balance
    if broker_order.status == broker_order.STATUS_READY:
        err_msg = order_check_funds(db_session, broker_order, check_user=False)
        if err_msg:
            logger.error('"%s" for broker order %s', err_msg, broker_order.token)
            broker_order.status = broker_order.STATUS_FAILED
            updated_records.append(broker_order)
            ftx = order_refund(broker_order)
            if not ftx:
                logger.error('failed to create fiatdb transaction for broker order %s', broker_order.token)
                return updated_records
            updated_records.append(ftx)
            return updated_records
        # create exchange order
        exchange_order_id = dasset.order_create(broker_order.market, side, base_amount_dec, price)
        if not exchange_order_id:
            msg = f'{broker_order.token}, {broker_order.market}, {broker_order.side}, {base_amount_dec}, {quote_amount_dec}, {price}'
            logger.error('failed to create exchange order - %s', msg)
            email_utils.send_email(logger, 'failed to create exchange order', msg)
            return updated_records
        exchange_order = ExchangeOrder(exchange_order_id)
        broker_order.exchange_order = exchange_order
        broker_order.status = broker_order.STATUS_EXCHANGE
        updated_records.append(exchange_order)
        updated_records.append(broker_order)
        return updated_records
    # finalize
    if broker_order.status == broker_order.STATUS_EXCHANGE:
        # check exchange order
        if broker_order.exchange_order:
            if dasset.order_status_check(broker_order.exchange_order.exchange_reference, broker_order.market):
                if side is MarketSide.ASK:
                    asset = broker_order.quote_asset
                    amount_int = broker_order.quote_amount
                else:
                    asset = broker_order.base_asset
                    amount_int = broker_order.base_amount
                ftx = fiatdb_core.tx_create(broker_order.user, FiatDbTransaction.ACTION_CREDIT, asset, amount_int, f'broker order completed: {broker_order.token}')
                updated_records.append(ftx)
                broker_order.status = broker_order.STATUS_COMPLETED
                updated_records.append(broker_order)
            else:
                msg = f'{broker_order.token}, {broker_order.exchange_order.exchange_reference}'
                logger.error('failed to complete exchange order - %s', msg)
                email_utils.send_email(logger, 'failed to complete exchange order', msg)
        return updated_records
    # check expiry
    if broker_order.status == broker_order.STATUS_CREATED:
        if datetime.datetime.now() > broker_order.expiry:
            broker_order.status = broker_order.STATUS_EXPIRED
            updated_records.append(broker_order)
            return updated_records
    return updated_records

def _email_msg(broker_order: BrokerOrder, msg: str):
    side = assets.market_side_nice(broker_order.side)
    amount_dec = assets.asset_int_to_dec(broker_order.base_asset, broker_order.base_amount)
    amount_str = assets.asset_dec_to_str(broker_order.base_asset, amount_dec)
    return f'Your order {broker_order.token} ({side} {amount_str} {broker_order.base_asset}) is now {broker_order.status}. \n\n{msg}'

def _broker_order_email(broker_order: BrokerOrder):
    if broker_order.status == broker_order.STATUS_FAILED:
        email_utils.send_email(logger, 'Order Failed', _email_msg(broker_order, ''), broker_order.user.email)
    if broker_order.status == broker_order.STATUS_CANCELLED:
        email_utils.send_email(logger, 'Order Cancelled', _email_msg(broker_order, ''), broker_order.user.email)
    if broker_order.status == broker_order.STATUS_COMPLETED:
        email_utils.send_email(logger, 'Order Completed', _email_msg(broker_order, ''), broker_order.user.email)
    if broker_order.status == broker_order.STATUS_EXPIRED:
        email_utils.send_email(logger, 'Order Expired', _email_msg(broker_order, ''), broker_order.user.email)

#
# Public functions
#

def _broker_order_update_and_commit(db_session: Session, broker_order: BrokerOrder):
    if broker_order.market not in assets.MARKETS:
        logger.error('broker order (%s) market (%s) is not valid', broker_order.token, broker_order.market)
        return
    while True:
        updated_records = _broker_order_action(db_session, broker_order)
        # commit db if records updated
        if not updated_records:
            return
        for rec in updated_records:
            db_session.add(rec)
        db_session.commit()
        # send updates
        _broker_order_email(broker_order)
        websocket.broker_order_update_event(broker_order)

def broker_orders_update(db_session: Session):
    with coordinator.lock:
        orders = BrokerOrder.all_active(db_session)
        logger.info('num orders: %d', len(orders))
        for broker_order in orders:
            _broker_order_update_and_commit(db_session, broker_order)
