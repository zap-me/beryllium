import logging
from decimal import Decimal as Dec
from enum import Enum
from dataclasses import dataclass
from typing import Optional

import bitcoin
import bitcoin.wallet
import base58
import web3
from stdnum.nz import bankaccount

from app_core import app
from ln import LnRpc

logger = logging.getLogger(__name__)

@dataclass
class Asset:
    symbol: str
    name: str
    decimals: int
    withdraw_fee: Dec
    withdraw_fee_fixed: bool
    min_withdraw: Dec
    is_crypto: bool
    l2_network: Optional['Asset']
    deposit_instr: str | None
    withdraw_instr: str | None

@dataclass
class Market:
    base_asset: Asset
    quote_asset: Asset

TESTNET = app.config['TESTNET']
NZD = Asset(symbol='NZD', name='New Zealand Dollar', decimals=2, withdraw_fee=Dec(7), withdraw_fee_fixed=True, min_withdraw=Dec(20), is_crypto=False, l2_network=None,
            deposit_instr=None, withdraw_instr=None)
BTCLN = Asset(symbol='BTC-LN', name='Bitcoin Lightning', decimals=8, withdraw_fee=Dec('0.005'), withdraw_fee_fixed=False, min_withdraw=Dec('0.00000001'), is_crypto=True, l2_network=None,
              deposit_instr=None, withdraw_instr=None)
BTC = Asset(symbol='BTC', name='Bitcoin', decimals=8, withdraw_fee=Dec('0.0001'), withdraw_fee_fixed=True, min_withdraw=Dec('0.001'), is_crypto=True, l2_network=BTCLN,
            deposit_instr=None, withdraw_instr=None)
USDT = Asset(symbol='USDT', name='Tether USD', decimals=2, withdraw_fee=Dec(20), withdraw_fee_fixed=True, min_withdraw=Dec(50), is_crypto=True, l2_network=None,
             deposit_instr='This is an ethereum network address. Only deposit from the ethereum network.', withdraw_instr='Only withdraw to an ethereum address on the ethereum network.')
USDC = Asset(symbol='USDC', name='USD Coin', decimals=2, withdraw_fee=Dec(20), withdraw_fee_fixed=True, min_withdraw=Dec(50), is_crypto=True, l2_network=None,
             deposit_instr='This is an ethereum network address. Only deposit from the ethereum network.', withdraw_instr='Only withdraw to an ethereum address on the ethereum network.')
ETH = Asset(symbol='ETH', name='Ethereum', decimals=18, withdraw_fee=Dec('0.0052'), withdraw_fee_fixed=True, min_withdraw=Dec('0.01'), is_crypto=True, l2_network=None,
            deposit_instr=None, withdraw_instr=None)
DOGE = Asset(symbol='DOGE', name='Dogecoin', decimals=8, withdraw_fee=Dec(5), withdraw_fee_fixed=True, min_withdraw=Dec(20), is_crypto=True, l2_network=None,
             deposit_instr=None, withdraw_instr=None)
LTC = Asset(symbol='LTC', name='Litecoin', decimals=8, withdraw_fee=Dec('0.01'), withdraw_fee_fixed=True, min_withdraw=Dec('0.03'), is_crypto=True, l2_network=None,
            deposit_instr=None, withdraw_instr=None)
WAVES = Asset(symbol='WAVES', name='Waves', decimals=8, withdraw_fee=Dec('0.001'), withdraw_fee_fixed=True, min_withdraw=Dec('0.003'), is_crypto=True, l2_network=None,
              deposit_instr=None, withdraw_instr=None)
ASSETS_HISTORICAL = dict(NZD=NZD, BTC=BTC, USDT=USDT, USDC=USDC, ETH=ETH, DOGE=DOGE, LTC=LTC, WAVES=WAVES)
ASSETS = dict(NZD=NZD, BTC=BTC)
MARKETS_HISTORICAL = {'BTC-NZD': Market(base_asset=BTC, quote_asset=NZD),
                      'BTC-USDT': Market(base_asset=BTC, quote_asset=USDT),
                      'BTC-USDC': Market(base_asset=BTC, quote_asset=USDC),
                      'ETH-NZD': Market(base_asset=ETH, quote_asset=NZD),
                      'DOGE-NZD': Market(base_asset=DOGE, quote_asset=NZD),
                      'LTC-NZD': Market(base_asset=LTC, quote_asset=NZD),
                      'WAVES-BTC': Market(base_asset=WAVES, quote_asset=BTC)}
MARKETS = {'BTC-NZD': Market(base_asset=BTC, quote_asset=NZD)}

class MarketSide(Enum):
    BID = 'bid'
    ASK = 'ask'

    @classmethod
    def parse(cls, val: str):
        try:
            return cls(val)
        except Exception:
            return None

#
# Helper functions
#

def _base58_validate(address: str, mainnet_prefixes: list[int], testnet_prefixes: list[int]) -> bool:
    try:
        raw = base58.b58decode_check(address)
        prefix = raw[0]
        return not TESTNET and prefix in mainnet_prefixes or TESTNET and prefix in testnet_prefixes
    except ValueError:
        return False

#
# Public functions
#

def market_side_is(have: MarketSide | str, should_have: MarketSide) -> bool:
    assert isinstance(should_have, MarketSide)
    assert isinstance(have, (MarketSide, str))
    if isinstance(have, str):
        return have == should_have.value
    return have is should_have

def market_side_nice(side: MarketSide | str) -> str:
    if isinstance(side, str):
        if side == MarketSide.ASK.value:
            return 'sell'
        if side == MarketSide.BID.value:
            return 'buy'
    if isinstance(side, MarketSide):
        if side is MarketSide.ASK:
            return 'sell'
        if side is MarketSide.BID:
            return 'buy'
    return 'n/a'

def assets_from_market(market: str) -> list[str]:
    return market.split('-')

def asset_decimals(asset: str) -> int:
    return ASSETS_HISTORICAL[asset].decimals

def _withdraw_fee(asset: Asset, amount: Dec | None):
    if asset.withdraw_fee_fixed:
        return asset.withdraw_fee
    # withdraw fee is a ratio, we need the amount to calculate it
    assert amount
    return amount * asset.withdraw_fee

def asset_withdraw_fee(asset: str, l2_network: str | None, amount: Dec | None = None) -> Dec:
    asset_ = ASSETS_HISTORICAL[asset]
    if not l2_network:
        return _withdraw_fee(asset_, amount)
    assert asset_.l2_network is not None and asset_.l2_network.symbol == l2_network
    return _withdraw_fee(asset_.l2_network, amount)

def asset_min_withdraw(asset: str, l2_network: str | None) -> Dec:
    ass = ASSETS_HISTORICAL[asset]
    if l2_network:
        assert ass.l2_network is not None and ass.l2_network.symbol == l2_network
        return ass.l2_network.min_withdraw
    return ass.min_withdraw

def asset_int_to_dec(asset: str, value: int) -> Dec:
    decimals = asset_decimals(asset)
    return Dec(value) / Dec(10**decimals)

def asset_dec_to_int(asset: str, value: Dec) -> int:
    decimals = asset_decimals(asset)
    return int(value * Dec(10**decimals))

def asset_dec_to_str(asset: str, value: Dec) -> str:
    decimals = asset_decimals(asset)
    return format(value, f'.{decimals}f')

def asset_is_crypto(asset: str) -> bool:
    for item in ASSETS_HISTORICAL.values():
        if item.symbol == asset and item.is_crypto:
            return True
    return False

def asset_has_l2(asset: str, l2_network: str | None) -> bool:
    if not l2_network:
        return True
    for item in ASSETS.values():
        if item.symbol == asset and item.l2_network is not None and item.l2_network.symbol == l2_network:
            return True
    return False

def asset_is_fiat(asset: str) -> bool:
    for item in ASSETS_HISTORICAL.values():
        if item.symbol == asset and not item.is_crypto:
            return True
    return False

def asset_recipient_extract_amount(asset: str, l2_network: str | None, recipient: str) -> Dec:
    if asset == BTC.symbol and l2_network == BTCLN.symbol:
        rpc = LnRpc()
        result = rpc.decode_bolt11(recipient)
        if not result:
            return Dec(0)
        return asset_int_to_dec(asset, result['amount_sat'])
    return Dec(0)

def asset_recipient_validate(asset: str, l2_network: str | None, recipient: str) -> bool:
    result = False
    if asset == NZD.symbol:
        result = bankaccount.is_valid(recipient)
    elif asset == BTC.symbol:
        if l2_network == BTCLN.symbol:
            # if a valid lightning invoice it should have a positive amount to send
            return asset_recipient_extract_amount(asset, l2_network, recipient) > 0
        bitcoin.SelectParams('testnet' if TESTNET else 'mainnet')
        try:
            bitcoin.wallet.CBitcoinAddress(recipient)
            result = True
        except Exception:
            pass
    elif asset in (USDT.symbol, USDC.symbol, ETH.symbol):
        result = web3.Web3.isAddress(recipient)
    elif asset == DOGE.symbol:
        result = _base58_validate(recipient, [0x1E], [0x71])
    elif asset == LTC.symbol:
        result = _base58_validate(recipient, [0x30], [0x6F])
    if not result:
        logger.error('failed to validate recipient "%s" (%s)', recipient, asset)
    return result
