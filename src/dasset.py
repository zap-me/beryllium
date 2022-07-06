from dataclasses import dataclass
import logging
import decimal
import json
from enum import Enum
import time
from typing import Any, Tuple

import requests
import pyotp

import utils
from app_core import app
import assets

logger = logging.getLogger(__name__)

DASSET_API_SECRET = app.config['DASSET_API_SECRET']
DASSET_ACCOUNT_ID = app.config['DASSET_ACCOUNT_ID']
BROKER_ORDER_FEE = decimal.Decimal(app.config['BROKER_ORDER_FEE'])

URL_BASE = 'https://api.dassetx.com/api'
URL_BASE_NOAPI = 'https://api.dassetx.com'
URL_BASE_SUBACCOUNT = 'https://api.dassetx.com/prod/api'

CRYPTO_WITHDRAWAL_STATUS_COMPLETED = 'completed'
CRYPTO_WITHDRAWAL_STATUS_2FA = '2fa'
CRYPTO_WITHDRAWAL_STATUS_UNKNOWN = 'unknown'

class QuoteResult(Enum):
    OK = 0
    AMOUNT_TOO_LOW = 1
    INSUFFICIENT_LIQUIDITY = 2
    MARKET_API_FAIL = 3

@dataclass
class DassetBalance:
    symbol: str
    name: str
    total: decimal.Decimal
    available: decimal.Decimal
    decimals: int

@dataclass
class DassetAsset:
    symbol: str
    name: str
    coin_type: str
    status: str
    min_confs: int
    message: str
    decimals: int

@dataclass
class DassetMarket:
    symbol: str
    base_asset: str
    quote_asset: str
    precision: str
    status: str
    min_trade: str
    message: str

@dataclass
class DassetOrderbook:
    bids: Any
    asks: Any

@dataclass
class DassetOrder:
    id: Any
    base_asset: str
    quote_asset: str
    date: str
    side: assets.MarketSide
    status: str
    base_amount: str
    quote_amount: str
    filled: str

@dataclass
class DassetDeposit:
    id: Any
    symbol: str
    address: str
    amount: decimal.Decimal
    date: str
    status: str
    txid: str | None

@dataclass
class DassetWithdrawal:
    id: Any
    symbol: str
    amount: str
    date: str
    status: str
    address: str

_orderbook_cache: dict[str, Tuple[float, DassetOrderbook]] = {}
_markets_cache: Tuple[float, list[DassetMarket]] | None = None
CACHE_EXPIRY = 30

#
# Helper functions
#

def _account_mock():
    return app.config['EXCHANGE_ACCOUNT_MOCK']

def _parse_balance(item):
    symbol = item['currencySymbol']
    return DassetBalance(symbol=symbol, name=item['currencyName'], total=decimal.Decimal(item['total']), available=decimal.Decimal(item['available']), decimals=assets.asset_decimals(symbol))

def _parse_asset(item):
    symbol = item['symbol']
    message = ''
    if 'notice' in item:
        message = item['notice']
    return DassetAsset(symbol=symbol, name=item['name'], coin_type=item['coinType'], status=item['status'], min_confs=item['minConfirmations'], message=message, decimals=assets.asset_decimals(symbol))

def _parse_market(item):
    message = ''
    if 'notice' in item:
        message = item['notice']
    return DassetMarket(symbol=item['symbol'], base_asset=item['baseCurrencySymbol'], quote_asset=item['quoteCurrencySymbol'], precision=item['precision'], status=item['status'], min_trade=item['minTradeSize'], message=message)

def _parse_order_book(item):
    return DassetOrderbook(bids=item['bid'], asks=item['ask'])

def _parse_order(item):
    side = assets.MarketSide.BID if item['type'] == 'BUY' else assets.MarketSide.ASK
    return DassetOrder(id=item['id'], base_asset=item['baseSymbol'], quote_asset=item['quoteSymbol'], date=item['timestamp'], side=side, status=item['status'],
                       base_amount=item['baseAmount'], quote_amount=item['quoteAmount'], filled=item['details']['filled'])

def _parse_deposit(item):
    return DassetDeposit(id=item['id'], symbol=item['currencySymbol'], address=item['cryptoAddress'], amount=decimal.Decimal(item['quantity']), date=item['updatedAt'], status=item['status'], txid=item['txId'])

def _parse_withdrawal_full(item):
    id_ = item['id'] if 'id' in item else item['transactionId']
    amount = item['amount'] if 'amount' in item else item['quantity']
    return DassetWithdrawal(id=id_, symbol=item['currencySymbol'], amount=amount, date=item['createdAt'], status=item['status'], address=item['cryptoAddress'])

def _parse_withdrawal_2fa(item):
    id_ = item['transactionId']
    if 'status' in item:
        status = item['status']
    else:
        status = item['mfaStatus']
    return DassetWithdrawal(id=id_, symbol='', amount='0', date='', status=status, address='')

def _parse_withdrawal(item):
    try:
        return _parse_withdrawal_full(item)
    except:
        return _parse_withdrawal_2fa(item)

#
# Dasset API Requests
#

def _req_get(endpoint: str, params=None, subaccount_id: str | None = None, noapi_in_path=False, quiet=False):
    url = URL_BASE + endpoint
    if noapi_in_path:
        url = URL_BASE_NOAPI + endpoint
    headers = {}
    headers['x-api-key'] = DASSET_API_SECRET
    headers['x-account-id'] = DASSET_ACCOUNT_ID
    if subaccount_id:
        headers['x-subaccount-id'] = subaccount_id
    r = requests.get(url, headers=headers, params=params)
    if not quiet:
        logger.info('GET - %s', url)
        headers['x-api-key'] = 'xxxxx'
        logger.info('HEADERS - %s', headers)
    return r

def _req_post(endpoint: str, params, subaccount_id: str | None = None, noapi_in_path=False):
    url = URL_BASE + endpoint
    if noapi_in_path:
        url = URL_BASE_NOAPI + endpoint
    headers = {}
    headers['x-api-key'] = DASSET_API_SECRET
    headers['x-account-id'] = DASSET_ACCOUNT_ID
    if subaccount_id:
        headers['x-subaccount-id'] = subaccount_id
    r = requests.post(url, headers=headers, data=json.dumps(params))
    logger.info('POST - %s', url)
    headers['x-api-key'] = 'xxxxx'
    logger.info('HEADERS - %s', headers)
    logger.info('PARAMS - %s', params)
    return r

def _req_put(endpoint, params):
    url = URL_BASE + endpoint
    headers = {}
    headers['x-api-key'] = DASSET_API_SECRET
    headers['x-account-id'] = DASSET_ACCOUNT_ID
    logger.info('   POST - %s', url)
    r = requests.put(url, headers=headers, data=json.dumps(params))
    return r

def assets_req(asset=None):
    endpoint = '/currencies'
    if asset:
        endpoint = f'/currencies/{asset}'
    r = _req_get(endpoint)
    if r.status_code == 200:
        return [_parse_asset(a) for a in r.json() if a['symbol'] in assets.ASSETS]
    logger.error('request failed: %d, %s', r.status_code, r.content)
    return None

def markets_refresh_cache(margin: int):
    if _markets_cache:
        timestamp, _ = _markets_cache
        if timestamp + CACHE_EXPIRY - margin > time.time():
            return
    #logger.info('refresh cache for %s', MARKETS_KEY)
    markets_req(quiet=True)

def markets_req(use_cache=False, quiet=False):
    global _markets_cache
    if use_cache:
        # see if we have a cached version to return
        if _markets_cache:
            timestamp, markets = _markets_cache
            # if timestamp + cache expiry is greater then current timestamp then cache still valid
            if timestamp + CACHE_EXPIRY > time.time():
                return markets
            logger.error('cache hit failed, ts: %f, time: %f', timestamp, time.time())
    endpoint = '/markets'
    r = _req_get(endpoint, quiet=quiet)
    if r.status_code == 200:
        # save to the cache with timestamp
        markets = r.json()
        markets = [_parse_market(m) for m in markets if m['symbol'] in assets.MARKETS]
        _markets_cache = time.time(), markets
        # return result to caller
        return markets
    logger.error('request failed: %d, %s', r.status_code, r.content)
    return None

def market_req(name, use_cache=False):
    markets = markets_req(use_cache)
    if markets:
        for market in markets:
            if market.symbol == name:
                return market
    return None

def order_book_refresh_cache(margin: int):
    for symbol in assets.MARKETS:
        if symbol in _orderbook_cache:
            timestamp, _ = _orderbook_cache[symbol]
            if timestamp + CACHE_EXPIRY - margin > time.time():
                continue
        #logger.info('refresh cache for %s', symbol)
        order_book_req(symbol, quiet=True)

def order_book_req(symbol, use_cache=False, quiet=False):
    if use_cache:
        # see if we have a cached version to return
        if symbol in _orderbook_cache:
            timestamp, book = _orderbook_cache[symbol]
            # if timestamp + cache expiry is greater then current timestamp then cache still valid
            if timestamp + CACHE_EXPIRY > time.time():
                return book, BROKER_ORDER_FEE
            logger.error('cache hit failed, ts: %f, time: %f', timestamp, time.time())
    # request the current data from dasset
    endpoint = f'/markets/{symbol}/orderbook'
    r = _req_get(endpoint, quiet=quiet)
    if r.status_code == 200:
        # save to the cache with timestamp
        book = _parse_order_book(r.json()[0])
        _orderbook_cache[symbol] = time.time(), book
        # return result to caller
        return book, BROKER_ORDER_FEE
    logger.error('request failed: %d, %s', r.status_code, r.content)
    return None

def _balances_req(asset: str | None, subaccount_id: str | None):
    endpoint = '/balances'
    if asset:
        endpoint = f'/balances/{asset}'
    r = _req_get(endpoint, subaccount_id=subaccount_id)
    if r.status_code == 200:
        balances = r.json()
        balances = [_parse_balance(b) for b in balances if b['currencySymbol'] in assets.ASSETS]
        return balances
    logger.error('request failed: %d, %s', r.status_code, r.content)
    return None

def _order_create_req(market: str, side: assets.MarketSide, amount: decimal.Decimal, price: decimal.Decimal):
    assert isinstance(side, assets.MarketSide)
    assert isinstance(amount, decimal.Decimal)
    assert isinstance(price, decimal.Decimal)
    endpoint = '/orders'
    if side is assets.MarketSide.BID:
        dasset_side = 'BUY'
    else:
        dasset_side = 'SELL'
    r = _req_post(endpoint, params=dict(amount=float(amount), tradingPair=market, side=dasset_side, orderType='LIMIT', timeInForce='FILL_OR_KILL', limit=float(price)))
    if r.status_code == 200:
        return r.json()[0]['order']['orderId']
    logger.error('request failed: %d, %s', r.status_code, r.content)
    return None

def _orders_req(market, offset, limit):
    endpoint = '/orders'
    page = int(offset / limit) + 1
    r = _req_get(endpoint, params=dict(marketSymbol=market, limit=limit, page=page))
    if r.status_code == 200:
        return r.json()[0]
    logger.error('request failed: %d, %s', r.status_code, r.content)
    return None

def _order_status_req(order_id: str, market: str):
    offset = 0
    limit = 1000
    while True:
        orders = _orders_req(market, offset, limit)
        if orders:
            for item in orders['results']:
                if item['id'] == order_id:
                    return _parse_order(item)
            offset += limit
            if offset > orders['total']:
                break
        else:
            break
    logger.error('exchange order %s not found for market %s', order_id, market)
    return None

def _crypto_withdrawal_create_req(asset: str, amount: decimal.Decimal, address: str):
    assert isinstance(amount, decimal.Decimal)
    endpoint = '/crypto/withdrawals'
    r = _req_post(endpoint, params=dict(currencySymbol=asset, quantity=float(amount), cryptoAddress=address))
    if r.status_code == 200:
        withdrawal = _parse_withdrawal(r.json()[0])
        return withdrawal.id
    logger.error('request failed: %d, %s', r.status_code, r.content)
    return None

def _crypto_withdrawal_status_req(withdrawal_id: str):
    endpoint = f'/crypto/withdrawals/{withdrawal_id}'
    r = _req_get(endpoint)
    if r.status_code == 200:
        return _parse_withdrawal(r.json()[0])
    logger.error('request failed: %d, %s', r.status_code, r.content)
    return None

def _crypto_withdrawal_confirm_req(withdrawal_id: str, totp_code: str):
    endpoint = '/crypto/withdrawals/confirm'
    r = _req_post(endpoint, params=dict(txId=withdrawal_id, token=totp_code), noapi_in_path=True)
    if r.status_code == 200:
        return True
    logger.error('request failed: %d, %s', r.status_code, r.content)
    return False

def _addresses_req(asset: str, subaccount_id: str):
    endpoint = f'/addresses/{asset}'
    r = _req_get(endpoint, subaccount_id=subaccount_id)
    if r.status_code == 200:
        addrs: list[str] = []
        for item in r.json():
            if item['status'] == 'PROVISIONED':
                addrs.append(item['cryptoAddress'])
        return addrs
    logger.error('request failed: %d, %s', r.status_code, r.content)
    return None

def _addresses_create_req(asset: str, subaccount_id: str):
    endpoint = '/addresses'
    r = _req_post(endpoint, params=dict(currencySymbol=asset), subaccount_id=subaccount_id)
    if r.status_code == 200:
        return r.json()[0]['status'] == 'REQUESTED'
    logger.error('request failed: %d, %s', r.status_code, r.content)
    return False

def _crypto_deposits_pending_req(asset: str, subaccount_id: str):
    endpoint = '/crypto/deposits/open'
    r = _req_get(endpoint, params=dict(currencySymbol=asset, status='PENDING'), subaccount_id=subaccount_id, noapi_in_path=True)
    if r.status_code == 200:
        deposits = r.json()
        deposits = [_parse_deposit(d) for d in deposits]
        return deposits
    logger.error('request failed: %d, %s', r.status_code, r.content)
    return None

def _crypto_deposits_closed_req(asset: str, subaccount_id: str):
    endpoint = '/crypto/deposits/closed'
    r = _req_get(endpoint, params=dict(currencySymbol=asset), subaccount_id=subaccount_id, noapi_in_path=True)
    if r.status_code == 200:
        deposits = r.json()
        deposits = [_parse_deposit(d) for d in deposits if d['currencySymbol'] == asset]
        return deposits
    logger.error('request failed: %d, %s', r.status_code, r.content)
    return None

def _crypto_deposit_status_req(deposit_id: str):
    endpoint = f'/crypto/deposits/{deposit_id}'
    r = _req_get(endpoint)
    if r.status_code == 200:
        return _parse_deposit(r.json()[0])
    logger.error('request failed: %d, %s', r.status_code, r.content)
    return None

def _subaccount_req(reference: str):
    endpoint = '/subaccount'
    r = _req_put(endpoint, params=dict(reference=reference))
    if r.status_code == 200:
        return r.json()[0]
    logger.error('request failed: %d, %s', r.status_code, r.content)
    return None

def _transfer_req(to_master: bool, from_subaccount_id: str | None, to_subaccount_id: str | None, asset: str, amount: decimal.Decimal):
    endpoint = '/transfer'
    r = _req_put(endpoint, params=dict(toMasterAccount=to_master, fromSubaccountId=from_subaccount_id, toSubaccountId=to_subaccount_id, symbol=asset, quantity=str(amount)))
    if r.status_code == 200:
        return True
    logger.error('request failed: %d, %s', r.status_code, r.content)
    return False

#
# Public functions
#

def crypto_deposit_completed(deposit: DassetDeposit):
    return deposit and deposit.status == 'COMPLETED'

#
# Public functions that rely on an exchange request
#

def bid_quote_amount(market: str, amount: decimal.Decimal, use_cache=False):
    assert isinstance(amount, decimal.Decimal)
    dasset_market = market_req(market, use_cache=use_cache)
    if not dasset_market:
        return decimal.Decimal(-1), QuoteResult.MARKET_API_FAIL
    min_trade = decimal.Decimal(dasset_market.min_trade)
    if amount < min_trade:
        return decimal.Decimal(-1), QuoteResult.AMOUNT_TOO_LOW

    order_book_result = order_book_req(market, use_cache=use_cache)
    if not order_book_result:
        return decimal.Decimal(-1), QuoteResult.MARKET_API_FAIL
    order_book, broker_fee = order_book_result

    filled = decimal.Decimal(0)
    total_price = decimal.Decimal(0)
    n = 0
    while amount > filled:
        if n >= len(order_book.asks):
            break
        rate = decimal.Decimal(order_book.asks[n]['rate'])
        quantity = decimal.Decimal(order_book.asks[n]['quantity'])
        quantity_to_use = quantity
        if quantity_to_use > amount - filled:
            quantity_to_use = amount - filled
        filled += quantity_to_use
        total_price += quantity_to_use * rate
        if filled == amount:
            return total_price * (decimal.Decimal(1) + broker_fee / decimal.Decimal(100)), QuoteResult.OK
        n += 1

    return decimal.Decimal(-1), QuoteResult.INSUFFICIENT_LIQUIDITY

def ask_quote_amount(market: str, amount: decimal.Decimal, use_cache=False):
    assert isinstance(amount, decimal.Decimal)
    dasset_market = market_req(market, use_cache=use_cache)
    if not dasset_market:
        return decimal.Decimal(-1), QuoteResult.MARKET_API_FAIL
    min_trade = decimal.Decimal(dasset_market.min_trade)
    if amount < min_trade:
        return decimal.Decimal(-1), QuoteResult.AMOUNT_TOO_LOW

    order_book_result = order_book_req(market, use_cache=use_cache)
    if not order_book_result:
        return decimal.Decimal(-1), QuoteResult.MARKET_API_FAIL
    order_book, broker_fee = order_book_result

    filled = decimal.Decimal(0)
    total_price = decimal.Decimal(0)
    n = 0
    while amount > filled:
        if n >= len(order_book.bids):
            break
        rate = decimal.Decimal(order_book.bids[n]['rate'])
        quantity = decimal.Decimal(order_book.bids[n]['quantity'])
        quantity_to_use = quantity
        if quantity_to_use > amount - filled:
            quantity_to_use = amount - filled
        filled += quantity_to_use
        total_price += quantity_to_use * rate
        if filled == amount:
            return total_price * (decimal.Decimal(1) - broker_fee / decimal.Decimal(100)), QuoteResult.OK
        n += 1

    return decimal.Decimal(-1), QuoteResult.INSUFFICIENT_LIQUIDITY

def account_balances(asset: str | None = None, subaccount_id: str | None = None):
    if _account_mock():
        balances = []
        for item in assets.ASSETS.values():
            if subaccount_id and assets.asset_is_fiat(item.symbol):
                continue
            balance = DassetBalance(symbol=item.symbol, name=item.name, total=decimal.Decimal(9999), available=decimal.Decimal(9999), decimals=item.decimals)
            balances.append(balance)
        return balances
    return _balances_req(asset, subaccount_id)

def order_create(market: str, side: assets.MarketSide, amount: decimal.Decimal, price: decimal.Decimal):
    if _account_mock():
        return utils.generate_key()
    return _order_create_req(market, side, amount, price)

def order_status(order_id: str, market: str):
    if _account_mock():
        return DassetOrder(id=order_id, status='Completed', base_asset='', quote_asset='', date='', side=assets.MarketSide.ASK, base_amount='', quote_amount='', filled='')
    return _order_status_req(order_id, market)

def order_status_check(order_id: str, market: str):
    order = order_status(order_id, market)
    if not order:
        return False
    return order.status == 'Completed'

def address_get_or_create(asset: str, subaccount_id: str):
    if _account_mock():
        return asset + '-XXX'
    addrs = _addresses_req(asset, subaccount_id)
    if addrs:
        return addrs[0]
    if _addresses_create_req(asset, subaccount_id):
        addrs = _addresses_req(asset, subaccount_id)
        if addrs:
            return addrs[0]
    return None

def crypto_withdrawal_create(asset: str, amount: decimal.Decimal, address: str):
    if _account_mock():
        return utils.generate_key()
    return _crypto_withdrawal_create_req(asset, amount, address)

def crypto_withdrawal_status_check(withdrawal_id: str):
    if _account_mock():
        return CRYPTO_WITHDRAWAL_STATUS_COMPLETED
    withdrawal = _crypto_withdrawal_status_req(withdrawal_id)
    if not withdrawal:
        return CRYPTO_WITHDRAWAL_STATUS_UNKNOWN
    if withdrawal.status == 'Completed':
        return CRYPTO_WITHDRAWAL_STATUS_COMPLETED
    if withdrawal.status == 'awaiting_mfa_confirmation':
        return CRYPTO_WITHDRAWAL_STATUS_2FA
    return CRYPTO_WITHDRAWAL_STATUS_UNKNOWN

def crypto_withdrawal_confirm(withdrawal_id: str):
    key = app.config['DASSET_TOTP_KEY']
    totp = pyotp.TOTP(key)
    code = totp.now()
    return _crypto_withdrawal_confirm_req(withdrawal_id, code)

def crypto_deposits(asset: str, subaccount_id: str):
    deposits = []
    deps = _crypto_deposits_pending_req(asset, subaccount_id)
    if deps:
        for dep in deps:
            deposits.append(dep)
    deps = _crypto_deposits_closed_req(asset, subaccount_id)
    if deps:
        for dep in deps:
            deposits.append(dep)
    return deposits

def crypto_deposit_status_check(deposit_id: str):
    if _account_mock():
        return True
    deposit = _crypto_deposit_status_req(deposit_id)
    if not deposit:
        logger.error('unable to get dasset deposit status (%s)', deposit_id)
        return False
    return crypto_deposit_completed(deposit)

def subaccount_create(reference: str):
    if _account_mock():
        return utils.generate_key()
    return _subaccount_req(reference)

def transfer(to_subaccount_id: str | None, from_subaccount_id: str | None, asset: str, amount: decimal.Decimal):
    assert to_subaccount_id is None or from_subaccount_id is None
    assert isinstance(amount, decimal.Decimal)
    to_master = not to_subaccount_id
    return _transfer_req(to_master, from_subaccount_id, to_subaccount_id, asset, amount)

def funds_available_us(asset: str, amount: decimal.Decimal):
    assert isinstance(amount, decimal.Decimal)
    balances = account_balances(asset)
    if balances:
        for balance in balances:
            if balance.symbol == asset:
                return balance.available >= amount
    return False
