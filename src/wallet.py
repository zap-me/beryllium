import os
from decimal import Decimal
import logging
import time
from dataclasses import dataclass

from pyln.client.lightning import RpcError
from bitcoin.rpc import Proxy
import requests

from app_core import app, db
import assets
from ln import LnRpc, _msat_to_sat
from models import BtcTxIndex

logger = logging.getLogger(__name__)
TESTNET = app.config['TESTNET']

@dataclass
class BtcInputBasic:
    def __init__(self, txid: str, addr: str, vout: int, amount: int, ours: bool):
        self.txid = txid
        self.addr = addr
        self.vout = vout
        self.amount = amount
        self.ours = ours

    def __repr__(self) -> str:
        return f'<txid: {self.txid}, addr: {self.addr}, vout: {self.vout}, amount: {self.amount}>'

@dataclass
class BtcOutputBasic:
    def __init__(self, addr: str, vout: int, amount: int, ours: bool):
        self.addr = addr
        self.vout = vout
        self.amount = amount
        self.ours = ours

    def __repr__(self) -> str:
        return f'<addr: {self.addr}, vout: {self.vout}, amount: {self.amount}>'

@dataclass
class BtcTxBasic:
    def __init__(self, txid: str, blockheight: int, inputs: list[BtcInputBasic], outputs: list[BtcOutputBasic], fee: int, has_output_ours: bool, has_input_ours: bool):
        self.txid = txid
        self.blockheight = blockheight
        self.inputs = inputs
        self.outputs = outputs
        self.fee = fee
        self.has_output_ours = has_output_ours
        self.has_input_ours = has_input_ours

    def ours(self):
        return self.has_output_ours or self.has_input_ours

    def is_deposit(self):
        return self.has_output_ours and not self.has_input_ours

    def amount_deposited(self):
        assert self.is_deposit()
        amount = 0
        for output in self.outputs:
            if output.ours:
                amount += output.amount
        return amount

    def __repr__(self) -> str:
        return f'<txid: {self.txid}, inputs: {self.inputs}, outputs: {self.outputs}>'

def _build_bitcoin_rpc_url(bitcoin_datadir, bitcoin_host):
    btc_conf_file = os.path.join(bitcoin_datadir, 'bitcoin.conf')
    conf = {'rpcuser': ""}
    with open(btc_conf_file, 'r', encoding='utf-8') as fd:
        for line in fd.readlines():
            if '#' in line:
                line = line[:line.index('#')]
            if '=' not in line:
                continue
            k, v = line.split('=', 1)
            conf[k.strip()] = v.strip()
    authpair = f"{conf['rpcuser']}:{conf['rpcpassword']}"
    service_url = f"http://{authpair}@{bitcoin_host}:{conf['rpcport']}"
    return service_url

def bitcoind_service_url():
    return _build_bitcoin_rpc_url(app.config['BITCOIN_DATADIR'], app.config['BITCOIN_RPCCONNECT'])

def bitcoind_rpc_url(service_url, name, *args):
    bitcoind = Proxy(service_url=service_url)
    return bitcoind._call(name, *args)

def bitcoind_rpc(name, *args):
    service_url = bitcoind_service_url()
    return bitcoind_rpc_url(service_url, name, *args)

def _is_ln(asset: str, l2_network: str | None) -> bool:
    return asset == assets.BTC.symbol and l2_network == assets.BTCLN.symbol

def _is_btc_chain(asset: str, l2_network: str | None) -> bool:
    return asset == assets.BTC.symbol and l2_network is None

def recipient_expired(asset: str, l2_network: str | None, recipient: str) -> bool:
    rpc = LnRpc()
    if _is_ln(asset, l2_network):
        result = rpc.decode_bolt11(recipient)
        if not result:
            logger.error('unable to decode invoice')
            return False
        created_at: int = result['created_at']
        expiry: int = result['expiry']
        if time.time() >= created_at + expiry:
            return True
    if _is_btc_chain(asset, l2_network):
        return False
    return False

def incoming_available(asset: str, l2_network: str | None, amount_dec: Decimal) -> bool:
    if _is_ln(asset, l2_network):
        funds = LnRpc().list_funds()
        sats = assets.asset_dec_to_int(asset, amount_dec)
        logger.info('required: %d sats, largest channel theirs: %d sats', sats, funds['sats_largest_channel_theirs'])
        return funds['sats_largest_channel_theirs'] >= sats
    return False

def funds_available(asset: str, l2_network: str | None, amount_dec: Decimal) -> bool:
    if _is_ln(asset, l2_network):
        funds = LnRpc().list_funds()
        sats = assets.asset_dec_to_int(asset, amount_dec * Decimal('1.01'))  # add a 1% buffer for fees
        logger.info('required: %d sats, largest channel: %d sats', sats, funds['sats_largest_channel'])
        return funds['sats_largest_channel'] >= sats
    if _is_btc_chain(asset, l2_network):
        funds = LnRpc().list_funds()
        sats = assets.asset_dec_to_int(asset, amount_dec)
        logger.info('required: %d sats, sats onchain: %d sats', sats, funds['sats_onchain'])
        return funds['sats_onchain'] >= sats
    return False

def withdrawals_supported(asset: str, l2_network: str | None):
    return _is_ln(asset, l2_network) or _is_btc_chain(asset, l2_network)

def withdrawal_l2_recipient_exists(asset: str, l2_network: str | None, recipient: str):
    if _is_ln(asset, l2_network):
        result = LnRpc().pay_status(recipient)
        return len(result['pays']) > 0
    return False

def withdrawal_create(asset: str, l2_network: str | None, amount_dec: Decimal, recipient: str):
    assert withdrawals_supported(asset, l2_network)
    rpc = LnRpc()
    if _is_ln(asset, l2_network):
        try:
            result = rpc.decode_bolt11(recipient)
            amount_sat = assets.asset_dec_to_int(asset, amount_dec)
            if amount_sat != result['amount_sat']:
                logger.error('ln pay amount does not match: %d, %d', amount_sat, result['amount_sat'])
                return None, 'pay amount does not match'
            result = rpc.pay(recipient)
            if not result:
                logger.error('ln pay failed: %s', recipient)
                return None, 'pay failed'
            logger.info('ln pay made: %s', result['payment_hash'])
            return result['payment_hash'], None
        except RpcError as e:
            logger.error('ln pay error: %s', e.error)
            return None, e.error
    if _is_btc_chain(asset, l2_network):
        try:
            amount_sat = assets.asset_dec_to_int(asset, amount_dec)
            outputs = [{recipient: f'{amount_sat}sats'}]
            result = rpc.multi_withdraw(outputs)
            return result['txid'], None
        except RpcError as e:
            logger.error('ln pay error: %s', e.error)
            return None, e.error
    return None, 'unsupported'

def withdrawal_completed(asset: str, l2_network: str | None, wallet_reference: str) -> bool:
    rpc = LnRpc()
    if _is_ln(asset, l2_network):
        result = rpc.pay_status_from_hash(wallet_reference)
        if not result and len(result['pays']) != 1:
            logger.error('ln pay not found: %s', wallet_reference)
            return False
        pay = result['pays'][0]
        complete = pay['status'] == 'complete'
        return complete
    if _is_btc_chain(asset, l2_network):
        result = rpc.list_txs()
        txs = result['transactions']
        for tx in txs:
            if tx['hash'] == wallet_reference:
                return tx['blockheight'] >= 0  # tx is in a block
        return False
    return False

def deposits_supported(asset: str, l2_network: str | None):
    return _is_ln(asset, l2_network) or _is_btc_chain(asset, l2_network)

def deposit_create(asset: str, l2_network: str | None, label: str, msg: str, amount_dec: Decimal):
    assert deposits_supported(asset, l2_network)
    rpc = LnRpc()
    if _is_ln(asset, l2_network):
        sats = assets.asset_dec_to_int(asset, amount_dec)
        try:
            invoice = rpc.invoice(sats, label, msg)
            if not invoice:
                logger.error('ln invoice failed: %s %s', amount_dec, asset)
                return None, 'invoice failed'
            logger.info('ln invoice made: %s', invoice)
            return invoice['bolt11'], None
        except RpcError as e:
            logger.error('ln invoice error: %s', e.error)
            return None, e.error
    return None, 'unsupported'

def address_create(asset: str, l2_network: str | None):
    assert deposits_supported(asset, l2_network)
    rpc = LnRpc()
    if _is_btc_chain(asset, l2_network):
        #TODO: ensure this address is used right (ie only called once for each user and then stored in the DB)
        #TODO: this address cant be stored as 'wallet_reference' that should only be txids
        try:
            address = rpc.new_address('p2sh-segwit')
            if not address:
                logger.error('btc new address failed')
                return None, 'new address failed'
            if 'bech32' in address and address['bech32']:
                addr = address['bech32']
            else:
                addr = address['p2sh-segwit']
            logger.info('btc address created: %s', addr)
            return addr, None
        except RpcError as e:
            logger.error('btc new address error: %s', e.error)
            return None, e.error
    return None, 'unsupported'

def address_deposits(asset: str, l2_network: str | None, address: str) -> list[BtcTxBasic]:
    assert deposits_supported(asset, l2_network)
    deposit_txs = []
    if _is_btc_chain(asset, l2_network):
        txs = btc_txs_load(address)
        for tx in txs:
            if tx.is_deposit():
                deposit_txs.append(tx)
    return deposit_txs

def deposit_expired(asset: str, l2_network: str | None, wallet_reference: str | None) -> bool:
    rpc = LnRpc()
    if wallet_reference:
        if _is_ln(asset, l2_network):
            result = rpc.invoice_status(wallet_reference)
            if not result and len(result['invoices']) != 1:
                logger.error('ln invoice not found: %s', wallet_reference)
                return False
            invoice = result['invoices'][0]
            expired = invoice['status'] == 'expired'
            return expired
        if _is_btc_chain(asset, l2_network):
            return False
    return False

def deposit_completed(asset: str, l2_network: str | None, wallet_reference: str | None) -> bool:
    rpc = LnRpc()
    if wallet_reference:
        if _is_ln(asset, l2_network):
            result = rpc.invoice_status(wallet_reference)
            if not result or len(result['invoices']) != 1:
                logger.error('ln invoice not found: %s', wallet_reference)
                return False
            invoice = result['invoices'][0]
            complete = invoice['status'] == 'paid'
            return complete
        if _is_btc_chain(asset, l2_network):
            result = rpc.list_txs()
            txs = result['transactions']
            for tx in txs:
                if tx['hash'] == wallet_reference:
                    return tx['blockheight'] >= 0  # tx is in a block
            return False
    return False

def ln_any_deposit_completed(lastpay_index):
    rpc = LnRpc()
    try:
        return rpc.wait_any_invoice(lastpay_index, 0), None
    except RpcError as e:
        return None, e.error

def _get_raw_tx(service_url, txid, blockhash=None):
    try:
        if blockhash:
            return bitcoind_rpc_url(service_url, 'getrawtransaction', txid, True, blockhash)
        return bitcoind_rpc_url(service_url, 'getrawtransaction', txid, True)
    except Exception:
        return None

def _get_raw_tx_using_bitaps_blockhash(service_url, txid):
    network = 'testnet/v1' if TESTNET else 'v1'
    try:
        tx = requests.get(f'https://api.bitaps.com/btc/{network}/blockchain/transaction/{txid}').json()
        blockhash = tx['data']['blockHash']
        return _get_raw_tx(service_url, txid, blockhash)
    except Exception:
        return None

def _get_raw_tx_using_loop(service_url, txid, max_block_history):
    block_count = bitcoind_rpc_url(service_url, 'getblockcount')
    current_block = block_count
    while current_block + max_block_history > block_count and current_block > 0:
        blockhash = bitcoind_rpc_url(service_url, 'getblockhash', current_block)
        input_tx = _get_raw_tx(service_url, txid, blockhash)
        if input_tx:
            logger.info('found input tx in block %s', current_block)
            return input_tx
        current_block -= 1
    return None

def btc_transactions_index():
    max_block_history = 128  # 1 day
    service_url = bitcoind_service_url()
    rpc = LnRpc()
    try:
        txs = rpc.list_txs()['transactions']
        for tx in txs:
            for input_ in tx["inputs"]:
                input_txid = input_['txid']
                input_tx = BtcTxIndex.from_txid(db.session, input_txid)
                if input_tx:
                    continue
                logger.info('searching for input tx %s', input_txid)
                # try mempool
                input_tx = _get_raw_tx(service_url, input_txid)
                if not input_tx:
                    # try looping back though blocks
                    input_tx = _get_raw_tx_using_loop(service_url, input_txid, max_block_history)
                if not input_tx:
                    logger.error('failed to find input tx after searching top %d blocks, trying bitaps.com', max_block_history)
                    input_tx = _get_raw_tx_using_bitaps_blockhash(service_url, input_txid)
                if not input_tx:
                    logger.error('failed to find input tx after searching bitaps.com')
                    continue
                # make db input tx
                input_tx = BtcTxIndex(input_txid, input_tx['hex'], None, input_tx['blockhash'])
                db.session.add(input_tx)
                db.session.commit()
    except RpcError as e:
        logger.error('btc transactions index failed: %s', e.error)

def btc_input_transaction_get(txid: str):
    tx = BtcTxIndex.from_txid(db.session, txid)
    if tx:
        return tx.hex
    return None

def btc_txs_load(addr=None) -> list[BtcTxBasic]:
    btc_transactions_index()
    rpc = LnRpc()
    txs = []
    addresses = rpc.list_addrs()['addresses']
    transactions = rpc.list_txs()
    for tx in transactions['transactions']:
        input_sum = 0
        output_sum = 0
        has_output_ours = False
        has_input_ours = False
        tx_bitcoind = bitcoind_rpc('decoderawtransaction', tx['rawtx'])
        outputs = []
        inputs = []
        for output in tx['outputs']:
            vout = tx_bitcoind['vout'][output['index']]
            output_address = vout['scriptPubKey']['address']
            output_sats = _msat_to_sat(output['msat'])
            output_sum += output_sats
            ours = False
            if addr:
                if output_address == addr:
                    ours = True
                    has_output_ours = True
            else:
                for address in addresses:
                    if output_address in (address['bech32'], address['p2sh']):
                        ours = True
                        has_output_ours = True
            outputs.append(BtcOutputBasic(output_address, output['index'], output_sats, ours))
        for input_ in tx['inputs']:
            input_tx_hex = btc_input_transaction_get(input_['txid'])
            if not input_tx_hex:
                logger.error('could not get input tx hex for %s', input_['txid'])
                continue
            input_tx_bitcoind = bitcoind_rpc('decoderawtransaction', input_tx_hex)
            ours = False
            vout = input_tx_bitcoind['vout'][input_['index']]
            input_address = vout['scriptPubKey']['address']
            input_sats = int(float(vout['value']) * 100000000)
            input_sum += input_sats
            if addr:
                if input_address == addr:
                    ours = True
                    has_input_ours = True
            else:
                for address in addresses:
                    if input_address in (address['bech32'], address['p2sh']):
                        ours = True
                        has_input_ours = True
            inputs.append(BtcInputBasic(input_['txid'], input_address, input_['index'], input_sats, ours))
        if not addr or has_input_ours or has_output_ours:
            txs.append(BtcTxBasic(tx['hash'], tx['blockheight'], inputs, outputs, input_sum - output_sum, has_output_ours, has_input_ours))

    def zero_first(txn: BtcTxBasic):
        if txn.blockheight == 0:
            return 99999999999999
        return txn.blockheight
    return sorted(txs, key=zero_first, reverse=True)
