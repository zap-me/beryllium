import logging
import json

from flask import request
from flask_socketio import Namespace, emit, join_room, leave_room

from app_core import SERVER_VERSION, CLIENT_VERSION_DEPLOYED, db, socketio
from web_utils import check_auth
from security import tf_enabled_check
from models import BrokerOrder, CryptoDeposit, CryptoWithdrawal, FiatDeposit, FiatWithdrawal, User, ApiKey

logger = logging.getLogger(__name__)
ws_sids = {}

NS = '/events'

#
# Helper functions
#

def user_info_dict(api_key: ApiKey, all_info: bool) -> dict:
    user = api_key.user
    roles = []
    perms = []
    kyc_validated = None
    kyc_url = None
    aplyid_req_exists = False
    tf_enabled = tf_enabled_check(user)
    if list(user.kyc_requests):
        req = api_key.user.kyc_requests[0]
        aplyid_req_exists = req.aplyid is not None
    if all_info:
        roles = [role.name for role in user.roles]
        perms = [perm.name for perm in api_key.permissions]
        kyc_validated = user.kyc_validated()
        kyc_url = user.kyc_url()
    return dict(first_name=user.first_name, last_name=user.last_name, mobile_number=user.mobile_number, address=user.address, email=user.email, photo=user.photo, photo_type=user.photo_type, roles=roles, permissions=perms, kyc_validated=kyc_validated, kyc_url=kyc_url, aplyid_req_exists=aplyid_req_exists, tf_enabled=tf_enabled)

def user_info_dict_ws(user: User) -> dict:
    roles = [role.name for role in user.roles]
    kyc_validated = user.kyc_validated()
    kyc_url = user.kyc_url()
    aplyid_req_exists = False
    tf_enabled = tf_enabled_check(user)
    if list(user.kyc_requests):
        req = user.kyc_requests[0]
        aplyid_req_exists = req.aplyid is not None
    return dict(first_name=user.first_name, last_name=user.last_name, mobile_number=user.mobile_number, address=user.address, email=user.email, photo=user.photo, photo_type=user.photo_type, roles=roles, kyc_validated=kyc_validated, kyc_url=kyc_url, aplyid_req_exists=aplyid_req_exists, tf_enabled=tf_enabled)

#
# Websocket events
#

def user_info_event(user: User, old_email: str | None = None):
    email = user.email
    if old_email:
        email = old_email
    data = json.dumps(user_info_dict_ws(user))
    socketio.emit('user_info_update', data, json=True, room=email, namespace=NS)
    logger.info('user_info_update: %s (%s)', user.email, old_email)

def broker_order_update_event(broker_order: BrokerOrder):
    data = json.dumps(broker_order.to_json())
    socketio.emit('broker_order_update', data, json=True, room=broker_order.user.email, namespace=NS)
    logger.info('broker_order_update: %s', broker_order.token)

def broker_order_new_event(broker_order: BrokerOrder):
    data = json.dumps(broker_order.to_json())
    socketio.emit('broker_order_new', data, json=True, room=broker_order.user.email, namespace=NS)
    logger.info('broker_order_new: %s', broker_order.token)

def crypto_deposit_update_event(crypto_deposit: CryptoDeposit):
    data = json.dumps(crypto_deposit.to_json())
    socketio.emit('crypto_deposit_update', data, json=True, room=crypto_deposit.user.email, namespace=NS)
    logger.info('crypto_deposit_update: %s', crypto_deposit.token)

def crypto_deposit_new_event(crypto_deposit: CryptoDeposit):
    data = json.dumps(crypto_deposit.to_json())
    socketio.emit('crypto_deposit_new', data, json=True, room=crypto_deposit.user.email, namespace=NS)
    logger.info('crypto_deposit_new: %s', crypto_deposit.token)

def crypto_withdrawal_update_event(crypto_withdrawal: CryptoWithdrawal):
    data = json.dumps(crypto_withdrawal.to_json())
    socketio.emit('crypto_withdrawal_update', data, json=True, room=crypto_withdrawal.user.email, namespace=NS)
    logger.info('crypto_withdrawal_update: %s', crypto_withdrawal.token)

def crypto_withdrawal_new_event(crypto_withdrawal: CryptoWithdrawal):
    data = json.dumps(crypto_withdrawal.to_json())
    socketio.emit('crypto_withdrawal_new', data, json=True, room=crypto_withdrawal.user.email, namespace=NS)
    logger.info('crypto_withdrawal_new: %s', crypto_withdrawal.token)

def fiat_deposit_update_event(fiat_deposit: FiatDeposit):
    data = json.dumps(fiat_deposit.to_json())
    socketio.emit('fiat_deposit_update', data, json=True, room=fiat_deposit.user.email, namespace=NS)
    logger.info('fiat_deposit_update: %s', fiat_deposit.token)

def fiat_deposit_new_event(fiat_deposit: FiatDeposit):
    data = json.dumps(fiat_deposit.to_json())
    socketio.emit('fiat_deposit_new', data, json=True, room=fiat_deposit.user.email, namespace=NS)
    logger.info('fiat_deposit_new: %s', fiat_deposit.token)

def fiat_withdrawal_update_event(fiat_withdrawal: FiatWithdrawal):
    data = json.dumps(fiat_withdrawal.to_json())
    socketio.emit('fiat_withdrawal_update', data, json=True, room=fiat_withdrawal.user.email, namespace=NS)
    logger.info('fiat_withdrawal_update: %s', fiat_withdrawal.token)

def fiat_withdrawal_new_event(fiat_withdrawal: FiatWithdrawal):
    data = json.dumps(fiat_withdrawal.to_json())
    socketio.emit('fiat_withdrawal_new', data, json=True, room=fiat_withdrawal.user.email, namespace=NS)
    logger.info('fiat_withdrawal_new: %s', fiat_withdrawal.token)

def ln_invoice_paid_event(label: str, payment_hash: str, bolt11: str, email: str | None, description: str, amount_sat: int):
    data = json.dumps(dict(label=label, payment_hash=payment_hash, bolt11=bolt11, description=description, amount_sat=amount_sat))
    socketio.emit('ln_invoice_paid', data, json=True, room=f'ln-{label}', namespace=NS)
    if email:
        socketio.emit('ln_invoice_paid', data, json=True, room=email, namespace=NS)
    logger.info('ln_invoice_paid: %s, %s, %s, %s', label, email, description, amount_sat)

class EventsNamespace(Namespace):

    def on_error(self, err):
        logger.error(err)

    def on_connect(self):
        logger.info("connect sid: %s", request.sid)  # pyright: ignore [reportGeneralTypeIssues]
        emit('version', json.dumps(dict(server_version=SERVER_VERSION, client_version_deployed=CLIENT_VERSION_DEPLOYED)), json=True, namespace=NS)

    def on_auth(self, auth: dict | str):
        if not isinstance(auth, dict):
            try:
                auth = json.loads(auth)
                assert isinstance(auth, dict)
            except Exception:
                emit("info", "invalid json", namespace=NS)
                return
        if "api_key" not in auth:
            emit("info", "'api_key' param missing", namespace=NS)
            return
        if "nonce" not in auth:
            emit("info", "'nonce' param missing", namespace=NS)
            return
        if "signature" not in auth:
            emit("info", "'signature' param missing", namespace=NS)
            return
        # check auth
        res, reason, api_key = check_auth(db.session, auth["api_key"], auth["nonce"], auth["signature"], str(auth["nonce"]))
        if res and api_key:
            emit("info", "authenticated!", namespace=NS)
            # join room and store user
            logger.info("join room for email: %s", api_key.user.email)
            join_room(api_key.user.email)
            # store sid -> email map
            ws_sids[request.sid] = api_key.user.email  # type: ignore
        else:
            api_key_token = auth["api_key"]
            emit("info", f"failed authentication ({api_key_token}): {reason}", namespace=NS)
            logger.info("failed authentication (%s): %s", api_key_token, reason)

    def on_ln_invoice(self, label: str):
        logger.info("ln_invoice: %s", label)
        # join room for invoice label
        join_room(f"ln-{label}")
        emit("info", f"joined room for invoice label ({label})", namespace=NS)

    def on_disconnect(self):
        sid = request.sid  # pyright: ignore [reportGeneralTypeIssues]
        logger.info("disconnect sid: %s", sid)
        if sid in ws_sids:
            # remove sid -> email map
            email = ws_sids[sid]
            logger.info("leave room for email: %s", email)
            leave_room(email)
            del ws_sids[sid]

socketio.on_namespace(EventsNamespace(NS))
