import gevent
import logging

from app_core import app, db
import dasset
import assets
import email_utils
import depwith
import broker
from task_manager import TaskManager
import wallet
from ln import LnRpc, _msat_to_sat
from models import CryptoDeposit
import websocket

logger = logging.getLogger(__name__)

#
# Periodic task functions, !assume we have a flask app context!
#

def process_email_alerts():
    data = dasset.account_balances()
    if not data:
        logger.error('failed to get dasset account balances')
        return
    for balance in data:
        if balance.symbol == 'NZD':
            if balance.available < app.config["MIN_AVAILABLE_NZD_BALANCE"]:
                balance_format = assets.asset_dec_to_str(balance.symbol, balance.available)
                subject = f"Available {balance.symbol} Balance below the minimum threshold"
                msg = f"Available {balance.symbol} Balance needs to be replenished in the dasset account.<br/><br/>Available {balance.symbol} balance is: ${balance_format}"
                email_utils.email_notification_alert(logger, subject, msg, app.config["ADMIN_EMAIL"])

def process_depwith_and_broker_orders():
    logger.info('process deposits..')
    depwith.fiat_deposits_update(db.session)
    gevent.sleep()
    depwith.crypto_deposits_check(db.session)
    gevent.sleep()
    logger.info('process withdrawals..')
    depwith.fiat_withdrawals_update(db.session)
    gevent.sleep()
    depwith.crypto_withdrawals_update(db.session)
    gevent.sleep()
    logger.info('process broker orders..')
    broker.broker_orders_update(db.session)

def process_btc_tx_index():
    logger.info('process btc tx index..')
    wallet.btc_transactions_index()

def process_dasset_cache():
    #logger.info('process dasset cache..')
    dasset.order_book_refresh_cache(10)
    dasset.markets_refresh_cache(10)

#
# One off task functions, !assume we have a flask app context
#

def update_withdrawal(asset: str, token: str):
    if assets.asset_is_crypto(asset):
        depwith.crypto_withdrawal_update(db.session, token)
    else:
        depwith.fiat_withdrawal_update(db.session, token)
#
# Non-terminating task functions
#

def _process_ln_invoices_loop():
    gevent.sleep(10, False) # HACK: wait for the webserver to start
    lastpay_index = 0
    while True:
        try:
            if lastpay_index == 0:
                lastpay_index = LnRpc().lastpay_index()
            pay, err = wallet.ln_any_deposit_completed(lastpay_index)
            if err:
                logger.debug('wait_any_invoice failed: "%s"', err)
                gevent.sleep(2, False) # probably timeout so we wait a short time before polling again
            else:
                logger.info('wait_any_invoice: %s', pay)
                with app.app_context():
                    if pay and pay['status'] == 'paid':
                        label = pay['label']
                        payment_hash = pay['payment_hash']
                        bolt11 = pay['bolt11']
                        lastpay_index = pay['pay_index']
                        description = pay['description']
                        msat = pay['msatoshi']
                        sat = _msat_to_sat(msat)
                        deposit = CryptoDeposit.from_wallet_reference(db.session, bolt11)
                        email = None
                        if deposit:
                            email = deposit.user.email
                        # update user with websocket event
                        websocket.ln_invoice_paid_event(label, payment_hash, bolt11, email, description, sat)
                        # yield to other tasks
                        gevent.sleep()
                        # update deposits from wallet
                        depwith.crypto_wallet_deposits_check(db.session)
        except ConnectionError as e:
            logger.error('wait_any_invoice error: %s', e)
            gevent.sleep(5, False)

def rebalance_channels(oscid: str, iscid: str, amount: int):
    gevent.sleep(10, False) # HACK: wait for the webserver to start
    LnRpc().rebalance_channel(oscid, iscid, amount)
    send_email('Channel Rebalance Successful', 'Rebalanced {0} -> {1} with {2} sats'.format(oscid, iscid, amount))

def send_email(title: str, msg: str):
    gevent.sleep(10, False) # HACK: wait for the webserver to start
    email_utils.send_email(logger, title, msg)

def pay_to_invoice(invoice_str: str):
    gevent.sleep(10, False) # HACK: wait for the webserver to start
    LnRpc().pay(invoice_str)
#
# Init tasks
#

task_manager = TaskManager()
task_manager.repeated('email alerts', process_email_alerts, 30)
task_manager.repeated('deposits, withdrawals, orders', process_depwith_and_broker_orders, 5)
task_manager.repeated('btc tx index', process_btc_tx_index, 60)
task_manager.repeated('dasset cache', process_dasset_cache, 0)
task_manager.non_terminating('ln invoices', _process_ln_invoices_loop)
