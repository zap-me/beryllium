import logging
import secrets

from flask import Blueprint, render_template, request, flash, Markup, jsonify # pyright: ignore [reportPrivateImportUsage]
from flask_security import roles_accepted # pyright: ignore [reportPrivateImportUsage]

from utils import qrcode_svg_create
from web_utils import bad_request
from app_core import app, limiter, db
from models import BtcTxIndex, Role
from ln import LnRpc, _msat_to_sat
from wallet import bitcoind_rpc, btc_txs_load
from tasks import rebalance_channels, task_manager

logger = logging.getLogger(__name__)
ln_wallet = Blueprint('ln_wallet', __name__, template_folder='templates')
limiter.limit("100/minute")(ln_wallet)
BITCOIN_EXPLORER = app.config["BITCOIN_EXPLORER"]

@ln_wallet.before_request
def before_request():
    info = LnRpc().get_info()
    if 'warning_bitcoind_sync' in info:
        flash(info['warning_bitcoind_sync'], 'danger')
    if 'warning_lightningd_sync' in info:
        flash(info['warning_lightningd_sync'], 'danger')

@ln_wallet.route('/')
@roles_accepted(Role.ROLE_ADMIN)
def ln_index():
    rpc = LnRpc()
    return render_template('lightning/index.html', funds_dict=rpc.list_funds())

@ln_wallet.route('/getinfo')
@roles_accepted(Role.ROLE_ADMIN)
def lightningd_getinfo():
    return render_template('lightning/lightningd_getinfo.html', info=LnRpc().get_info())

@ln_wallet.route('/utxos', methods=['GET'])
@roles_accepted(Role.ROLE_ADMIN)
def utxos_ep():
    return render_template("lightning/utxos.html", outputs=LnRpc().list_funds()['funds']['outputs'])

@ln_wallet.route('/new_address', methods=['GET', 'POST'])
@roles_accepted(Role.ROLE_ADMIN)
def new_address_ep():
    """ Returns template showing a new address created by our HD wallet """
    address = None
    qrcode_svg = None
    if request.method == 'POST':
        address_type = request.form.get('address_type')
        if not address_type:
            flash('invalid address type', 'danger')
        else:
            address = LnRpc().new_address(address_type)
            qrcode_svg = qrcode_svg_create(address[address_type], 10)
    return render_template("lightning/new_address.html", address=address, qrcode_svg=qrcode_svg)

@ln_wallet.route('/list_txs')
@roles_accepted(Role.ROLE_ADMIN)
def list_txs():
    """ Returns template of on-chain txs """
    return render_template("lightning/list_transactions.html", txs=btc_txs_load(), bitcoin_explorer=BITCOIN_EXPLORER)

@ln_wallet.route('/invoice', methods=['GET', 'POST'])
@roles_accepted(Role.ROLE_ADMIN)
def ln_invoice():
    """Create a lightning invoice"""
    label = None
    bolt11 = None
    qrcode_svg = None
    if request.method == 'POST':
        amount = request.form['amount']
        message = request.form['message']
        label = f"lbl-{secrets.token_urlsafe(8)}"
        rpc = LnRpc()
        bolt11 = rpc.invoice(int(amount), label, message)['bolt11']
        qrcode_svg = qrcode_svg_create(bolt11, 10)
    return render_template("lightning/invoice.html", bolt11=bolt11, label=label, qrcode_svg=qrcode_svg, funds_dict=LnRpc().list_funds())

@ln_wallet.route('/channel_management', methods=['GET', 'POST'])
@roles_accepted(Role.ROLE_ADMIN)
def channel_management():
    """ Returns a template listing all connected LN peers """
    rpc = LnRpc()
    if request.method == 'POST':
        if request.form['form-name'] == 'rebalance_channel_form':
            oscid = request.form['oscid']
            iscid = request.form['iscid']
            amount = int(request.form['amount'])
            try:
                task_manager.one_off('rebalance_channel', rebalance_channels, [oscid, iscid, amount])
                flash(Markup(f'successfully moved {amount} sats from {oscid} to {iscid}'), 'success')
            except Exception as e:
                flash(Markup(e.args[0]), 'danger')
        elif request.form['form-name'] == 'close_channel_form':
            try:
                LnRpc().close_channel(request.form['channel_id'])
                flash(Markup(f'successfully closed channel {request.form["channel_id"]}'), 'success')
            except Exception as e:
                flash(Markup(e.args[0]), 'danger')
    peers = rpc.list_peers()['peers']
    channels = []
    total_receivable = 0
    total_spendable = 0
    largest_channel_sats = 0
    for peer in peers:
        for channel in peer['channels']:
            total = channel['msatoshi_total']
            total_sats = _msat_to_sat(total)
            if total_sats > largest_channel_sats:
                largest_channel_sats = total_sats
            ours = channel['msatoshi_to_us']
            theirs = total - ours
            our_reserve = channel['our_channel_reserve_satoshis']
            their_reserve = channel['their_channel_reserve_satoshis']
            receivable = theirs - our_reserve
            spendable = ours - their_reserve

            if peer['connected'] and channel['state'] == 'CHANNELD_NORMAL':
                total_receivable += receivable
                total_spendable += spendable

            channel['total_sats'] = total
            channel['our_reserve_sats'] = our_reserve
            channel['their_reserve_sats'] = their_reserve
            channel['receivable_sats'] = _msat_to_sat(receivable)
            channel['spendable_sats'] = _msat_to_sat(spendable)
            channel['peer_id'] = peer['id']
            channel['peer_connected'] = peer['connected']

            channels.append(channel)

    return render_template('lightning/channel_management.html', channels=channels, total_spendable_sats=_msat_to_sat(total_spendable), total_receivable_sats=_msat_to_sat(total_receivable), largest_channel_sats=largest_channel_sats)

@ln_wallet.route('/list_forwards')
@roles_accepted(Role.ROLE_ADMIN)
def list_forwards():
    rpc = LnRpc()
    return rpc.list_forwards()

@ln_wallet.route('/pay_invoice', methods=['GET', 'POST'])
@roles_accepted(Role.ROLE_ADMIN)
def pay_invoice():
    """Returns template for paying LN invoices"""
    invoice = ''
    if request.method == 'POST':
        invoice = request.form['invoice']
        try:
            result = LnRpc().pay(invoice)
            flash(f'Invoice paid: {result}', 'success')
        except Exception as e:
            flash(f'Error paying invoice: {e}', 'danger')
    return render_template("lightning/pay_invoice.html", invoice=invoice, funds_dict=LnRpc().list_funds())

@ln_wallet.route('/lightning_transactions', methods=['GET'])
@roles_accepted(Role.ROLE_ADMIN)
def lightning_transactions():
    """ Returns received transactions """
    dict_txs = []
    unsorted_list_dict = []
    rpc = LnRpc()
    received_txs = rpc.list_invoices()
    send_txs = rpc.list_sendpays()
    funds_dict = rpc.list_funds()
    dict_txs.append(received_txs)
    dict_txs.append(send_txs)
    for unsorted_dict in dict_txs[0]:
        unsorted_list_dict.append(unsorted_dict)
    for unsorted_dict in dict_txs[1]:
        unsorted_list_dict.append(unsorted_dict)
    sorted_txs = sorted(unsorted_list_dict, key=lambda d: d["paid_at"], reverse=True)
    record_no = str(len(sorted_txs))
    return render_template("lightning/lightning_transactions.html", funds_dict=funds_dict, sorted_txs=sorted_txs, record_no=record_no)

@ln_wallet.route('/decode_bolt11/<bolt11>', strict_slashes=False)
@roles_accepted(Role.ROLE_ADMIN)
def decode_bolt11(bolt11=None):
    if not bolt11:
        return bad_request('please enter a non-empty bolt11 string')
    try:
        rpc = LnRpc()
        return rpc.decode_bolt11(str(bolt11))
    except Exception as e:
        return bad_request(str(e))

@ln_wallet.route('/channel_opener', methods=['GET', 'POST'])
@roles_accepted(Role.ROLE_ADMIN)
def channel_opener():
    if request.method == 'POST':
        amount = request.form["amount"]
        nodeid = request.form["nodeid"]
        try:
            rpc = LnRpc()
            rpc.connect_node(nodeid)
            node_id = nodeid.split("@")
            rpc.fund_channel(node_id[0], amount)
            flash(Markup(f'successfully added node id: {node_id[0]} with the amount: {amount}'), 'success')
        except Exception as e:
            flash(Markup(e.args[0]), 'danger')
    return render_template('lightning/channel_opener.html', funds_dict=LnRpc().list_funds())

@ln_wallet.route('/create_psbt', methods=['GET', 'POST'])
@roles_accepted(Role.ROLE_ADMIN)
def create_psbt():
    """ Returns template for creating a PSBT """
    rpc = LnRpc()
    onchain_sats = int(rpc.list_funds()["sats_onchain"])
    onchain = onchain_sats / 100000000
    addrs = []
    amounts = []
    mode = 'psbt'
    psbt = None
    if request.method == 'POST':
        addrs = request.form.getlist('address')
        amounts = request.form.getlist('amount')
        mode = request.form['mode']
        unit = request.form['unit']
        outputs: list[dict[str, str]] = []
        for addr, amount in zip(addrs, amounts):
            outputs.append({addr: f'{amount}{unit}'})
        if mode == 'psbt':
            logger.info('preparing psbt with outputs: %s', outputs)
            try:
                res = rpc.prepare_psbt(outputs)
                psbt = res['psbt']
                flash('PSBT created', 'success')
            except Exception as e:
                flash(f'Failed to create PSBT: {e}', 'danger')
        elif mode == 'withdraw':
            logger.info('preparing withdrawal with outputs: %s', outputs)
            try:
                res = rpc.multi_withdraw(outputs)
                txid = res['txid']
                flash(f'Withdrawal transaction created: {txid}', 'success')
            except Exception as e:
                flash(f'Failed to create withdrawal transaction: {e}', 'danger')
        else:
            flash(f'Unknown mode: {mode}', 'danger')
    return render_template(
        'lightning/create_psbt.html', onchain=onchain, addrs=addrs, amounts=amounts, mode=mode, psbt=psbt, onchain_sats=onchain_sats)

@ln_wallet.route('/sign_psbt', methods=['GET', 'POST'])
@roles_accepted(Role.ROLE_ADMIN)
def sign_psbt():
    rpc = LnRpc()
    onchain_sats = int(rpc.list_funds()["sats_onchain"])
    onchain = onchain_sats / 100000000
    signed_psbt = None
    if request.method == 'POST':
        psbt = request.form["psbt"]
        try:
            rpc = LnRpc()
            res = rpc.sign_psbt(psbt)
            signed_psbt = res['signed_psbt']
            flash('Sign successful', 'success')
        except Exception as e:
            flash(f'Sign failed: {e}', 'danger')
    return render_template('lightning/sign_psbt.html', signed_psbt=signed_psbt, onchain=onchain, onchain_sats=onchain_sats)

@ln_wallet.route('/broadcast_psbt', methods=['GET', 'POST'])
@roles_accepted(Role.ROLE_ADMIN)
def broadcast():
    rpc = LnRpc()
    onchain_sats = int(rpc.list_funds()["sats_onchain"])
    onchain = onchain_sats / 100000000
    if request.method == 'POST':
        psbt = request.form["psbt"]
        try:
            rpc = LnRpc()
            res = rpc.send_psbt(psbt)
            txid = res['txid']
            flash(f'Broadcast successful, TXID: {txid}', 'success')
        except Exception as e:
            flash(f'Broadcast failed: {e}', 'danger')
    return render_template('lightning/broadcast_psbt.html', onchain=onchain, onchain_sats=onchain_sats)

@ln_wallet.route('/decode_psbt')
@roles_accepted(Role.ROLE_ADMIN)
def decode_psbt():
    psbt = request.args['psbt']
    if not psbt:
        return bad_request('empty psbt string')
    try:
        psbt_json = bitcoind_rpc('decodepsbt', psbt)
        logger.info('psbt json: %s', psbt_json)
        return jsonify(psbt_json)
    except Exception as e:
        return bad_request(str(e))

@ln_wallet.route('/address', methods=['GET'])
@roles_accepted(Role.ROLE_ADMIN)
def address_ep():
    address = request.args.get('address', '')
    if address:
        txs = btc_txs_load(address)
    else:
        txs = []
    return render_template("lightning/address.html", address=address, txs=txs, bitcoin_explorer=BITCOIN_EXPLORER)

@ln_wallet.route('/addr_raw/<addr>', methods=['GET'])
@roles_accepted(Role.ROLE_ADMIN)
def addr_raw(addr):
    for a in LnRpc().list_addrs()['addresses']:
        if addr in (a['bech32'], a['p2sh']):
            return jsonify(a)
        if addr in (a['bech32_redeemscript'], a['p2sh_redeemscript']):
            return jsonify(a)
        if addr == a['pubkey']:
            return jsonify(a)
    return jsonify(dict(msg='address not found'))

@ln_wallet.route('/tx_raw/<txid>', methods=['GET'])
@roles_accepted(Role.ROLE_ADMIN)
def tx_raw(txid):
    tx = BtcTxIndex.from_txid(db.session, txid)
    if tx:
        tx = bitcoind_rpc('decoderawtransaction', tx.hex)
        return jsonify(tx)
    for tx in LnRpc().list_txs()['transactions']:
        if tx['hash'] == txid:
            tx = bitcoind_rpc('decoderawtransaction', tx['rawtx'])
            return jsonify(tx)
    return jsonify(dict(msg='tx not found'))

@ln_wallet.route('/btc_tx_index_clear', methods=['GET'])
@roles_accepted(Role.ROLE_ADMIN)
def btc_tx_index_clear():
    BtcTxIndex.clear(db.session)
    db.session.commit()
    return 'ok'
