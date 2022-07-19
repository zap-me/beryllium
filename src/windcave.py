import os
import sys
import logging
import base64
import json
import decimal

from flask import url_for
import requests
from dateutil import tz

import utils
from app_core import db
from models import WindcavePaymentRequest

logger = logging.getLogger(__name__)

WINDCAVE_API_URL = 'https://sec.windcave.com/api/v1'
WINDCAVE_MOCK = os.environ.get('WINDCAVE_MOCK', '')
WINDCAVE_API_USER = os.environ.get('WINDCAVE_API_USER', '')
WINDCAVE_API_KEY = os.environ.get('WINDCAVE_API_KEY', '')
if not WINDCAVE_API_USER:
    logger.error('ERROR: no WINDCAVE_API_USER')
    sys.exit(1)
if not WINDCAVE_API_KEY:
    logger.error('ERROR: no WINDCAVE_API_KEY')
    sys.exit(1)

def mock():
    return WINDCAVE_MOCK

def moneyfmt(value, places=2, curr='', sep=',', dpi='.',
             pos='', neg='-', trailneg=''):
    """Convert Decimal to a money formatted string.

    places:  required number of places after the decimal point
    curr:    optional currency symbol before the sign (may be blank)
    sep:     optional grouping separator (comma, period, space, or blank)
    dpi:     decimal point indicator (comma or period)
             only specify as blank when places is zero
    pos:     optional sign for positive numbers: '+', space or blank
    neg:     optional sign for negative numbers: '-', '(', space or blank
    trailneg:optional trailing minus indicator:  '-', ')', space or blank

    >>> d = Decimal('-1234567.8901')
    >>> moneyfmt(d, curr='$')
    '-$1,234,567.89'
    >>> moneyfmt(d, places=0, sep='.', dpi='', neg='', trailneg='-')
    '1.234.568-'
    >>> moneyfmt(d, curr='$', neg='(', trailneg=')')
    '($1,234,567.89)'
    >>> moneyfmt(Decimal(123456789), sep=' ')
    '123 456 789.00'
    >>> moneyfmt(Decimal('-0.02'), neg='<', trailneg='>')
    '<0.02>'

    """
    q = decimal.Decimal(10) ** -places      # 2 places --> '0.01'
    sign, digits, _ = value.quantize(q).as_tuple()
    result = []
    digits = list(map(str, digits))
    build, next_ = result.append, digits.pop
    if sign:
        build(trailneg)
    for i in range(places):
        build(next_() if digits else '0')
    if places:
        build(dpi)
    if not digits:
        build('0')
    i = 0
    while digits:
        build(next_())
        i += 1
        if i == 3 and digits:
            i = 0
            build(sep)
    build(curr)
    build(neg if sign else pos)
    return ''.join(reversed(result))

def auth_header():
    raw = bytearray(WINDCAVE_API_USER + ':' + WINDCAVE_API_KEY, 'utf-8')
    data = base64.b64encode(raw).decode('utf-8')
    return 'Basic ' + data

def windcave_create_session(amount_cents, token, expiry):
    body = {'type': 'purchase', 'amount': moneyfmt(decimal.Decimal(amount_cents) / decimal.Decimal(100), sep=''), 'currency': 'NZD', 'merchantReference': token}
    body['methods'] = ['account2account']
    expiry = expiry.replace(tzinfo=tz.tzlocal())  # set time zone to local (datetime objects are 'naive' by default)
    expiry = expiry.astimezone(tz.tzutc())  # convert to UTC
    expiry = expiry.replace(microsecond=0)  # strip microsecond to placate windcave (RFC 3339)
    body['expires'] = expiry.isoformat()
    callback_url = url_for('payments.payment', token=token, _external=True)
    body['callbackUrls'] = {'approved': callback_url, 'declined': callback_url, 'cancelled': callback_url}
    body['notificationUrl'] = callback_url
    logger.info(json.dumps(body))
    headers = {'Content-Type': 'application/json', 'Authorization': auth_header()}
    r = requests.post(WINDCAVE_API_URL + '/sessions', headers=headers, json=body)
    logger.info(r.text)
    r.raise_for_status()
    if r.status_code == 202:
        jsn = r.json()
        return jsn['id'], jsn['state']
    return None, None

def windcave_get_session_status(windcave_session_id):
    headers = {'Authorization': auth_header()}
    r = requests.get(WINDCAVE_API_URL + '/sessions/' + windcave_session_id, headers=headers)
    logger.info(r.text)
    r.raise_for_status()
    jsn = r.json()
    state = jsn['state']
    link = ""
    for ln_data in jsn['links']:
        if ln_data['method'] == 'REDIRECT':
            link = ln_data['href']
            break
    tx_state = None
    if 'transactions' in jsn:
        txs = jsn['transactions']
        if len(txs) > 0:
            tx_state = txs[0]['authorised'], txs[0]['allowRetry']
    return state, link, tx_state

def payment_create(amount_cents, expiry):
    token = utils.generate_key()
    req = WindcavePaymentRequest.from_token(db.session, token)
    if req:
        raise Exception('payment already exists')
    logger.info("creating session with windcave")
    if mock():
        windcave_session_id = token
        windcave_status = 'created (mock)'
    else:
        windcave_session_id, windcave_status = windcave_create_session(amount_cents, token, expiry)
    if not windcave_session_id:
        raise Exception('failed to create windcave session')
    logger.info("creating payment request object for %s", token)
    req = WindcavePaymentRequest(token, 'NZD', amount_cents, windcave_session_id, windcave_status)
    return req

def payment_request_mock_confirm(req):
    assert mock()
    req.windcave_status = 'confirmed (mock)'
    req.windcave_authorised = True

def payment_request_status_update(req):
    if mock():
        if req.windcave_status == 'confirmed (mock)':
            req.status = req.STATUS_COMPLETED
        return
    # get status from windcave
    state, windcave_url, tx_state = windcave_get_session_status(req.windcave_session_id)
    req.windcave_status = state
    req.windcave_url = windcave_url
    if tx_state:
        if tx_state[0]:
            req.status = req.STATUS_COMPLETED
        elif not tx_state[1]:
            req.status = req.STATUS_CANCELLED
        req.windcave_authorised = tx_state[0]
        req.windcave_allow_retry = tx_state[1]
