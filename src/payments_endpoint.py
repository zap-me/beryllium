import logging

from flask import Blueprint, request, render_template, flash, redirect, url_for
from flask_security.decorators import roles_accepted

from app_core import db, limiter
from models import PayoutRequest, PayoutGroup, WindcavePaymentRequest, Role
import web_utils
import payouts_core
import windcave
import crown_financial
import depwith

logger = logging.getLogger(__name__)
payments = Blueprint('payments', __name__, template_folder='templates')
limiter.limit("100/minute")(payments)

#
# Public payments endpoints
#

@payments.route('/payment/<token>', methods=['GET'])
def payment_interstitial(token=None):
    if not token:
        flash('Sorry payment request', category='danger')
        return redirect('/')
    req = WindcavePaymentRequest.from_token(db.session, token)
    if not req:
        flash('Sorry payment request not found', category='danger')
        return redirect('/')
    if req.status != req.STATUS_CREATED:
        return redirect(url_for('payments.payment', token=token))
    if req.fiat_deposit:
        depwith.fiat_deposit_update(db.session, req.fiat_deposit.token)
    if req.status != req.STATUS_CREATED:
        return redirect(url_for('payments.payment', token=token))
    return render_template('payments/payment_request.html', token=token, interstitial=True, mock=windcave.mock())

@payments.route('/payment/mock/<token>', methods=['GET'])
def payment_mock_confirm(token=None):
    if not token:
        flash('Sorry invalid payment request', category='danger')
        return redirect('/')
    if not windcave.mock():
        return web_utils.bad_request('not found', code=404)
    req = WindcavePaymentRequest.from_token(db.session, token)
    if not req:
        flash('Sorry payment request not found', category='danger')
        return redirect('/')
    windcave.payment_request_mock_confirm(req)
    if req.fiat_deposit:
        depwith.fiat_deposit_update(db.session, req.fiat_deposit.token)
    return redirect(url_for('payments.payment', token=token))

@payments.route('/payment/x/<token>', methods=['GET'])
def payment(token=None):
    if not token:
        flash('Sorry invalid payment request', category='danger')
        return redirect('/')
    req = WindcavePaymentRequest.from_token(db.session, token)
    if not req:
        flash('Sorry payment request not found', category='danger')
        return redirect('/')
    windcave.payment_request_status_update(req)
    completed = req.status == req.STATUS_COMPLETED
    cancelled = req.status == req.STATUS_CANCELLED
    return render_template('payments/payment_request.html', token=token, completed=completed, cancelled=cancelled, req=req)

@payments.route('/payouts')
@roles_accepted(Role.ROLE_ADMIN, Role.ROLE_FINANCE)
def payouts():
    suspended = request.args.get('suspended') == 'true'
    if suspended:
        reqs = PayoutRequest.where_status_suspended(db.session)
    else:
        reqs = PayoutRequest.where_status_created(db.session)
    return render_template('payments/payouts.html', payout_requests=reqs, suspended=suspended)

@payments.route('/payout_group/<token>', methods=['GET'])
@roles_accepted(Role.ROLE_ADMIN, Role.ROLE_FINANCE)
def payout_group(token=None):
    if not token:
        flash('Sorry invalid group', category='danger')
        return redirect('/')
    group = PayoutGroup.from_token(db.session, token)
    if not group:
        flash('Sorry group not found', category='danger')
        return redirect('/')
    if group.expired:
        flash('Sorry group is expired', category='danger')
        return redirect('/')
    return render_template('payments/payout_group.html', token=token, group=group, payout_requests=group.requests)

@payments.route('/payout_group_create', methods=['POST'])
@roles_accepted(Role.ROLE_ADMIN, Role.ROLE_FINANCE)
def payout_group_create():
    group = payouts_core.payout_group_create()
    if group:
        db.session.commit()
        return redirect(f'/payments/payout_group/{group.token}')
    flash('Sorry group not created', category='danger')
    return redirect('/')

@payments.route('/payout_group_process_all', methods=['POST'])
@roles_accepted(Role.ROLE_ADMIN, Role.ROLE_FINANCE)
def payout_group_process_all():
    content = request.form
    token = content['token']
    logger.info('looking for %s', token)
    group = PayoutGroup.from_token(db.session, token)
    if group:
        asset, total, count = group.total_payout()
        assert asset == crown_financial.CURRENCY
        balance = crown_financial.balance()
        total += crown_financial.CROWN_WITHDRAW_FEE_INT * count
        if balance < total:
            flash('Sorry, crown balance is not sufficient', category='danger')
        else:
            for req in group.requests:
                # ignore suspended or completed
                if req.status in (req.STATUS_SUSPENDED, req.STATUS_COMPLETED):
                    continue
                address_book = req.address_book
                if not address_book:
                    logger.error('unable to create withdrawal for payout without address_book (%s)', req.token)
                    continue
                crown_txn_id = crown_financial.withdrawal(req.amount, req.reference, req.code, address_book.recipient, address_book.account_name, address_book.account_addr_01, address_book.account_addr_02, address_book.account_addr_country)
                if crown_txn_id:
                    payouts_core.set_payout_request_complete(req)
                    db.session.commit()
        return redirect(f'/payments/payout_group/{token}')
    flash('Sorry, group not found', category='danger')
    return redirect('/')

@payments.route('/payout_request_suspend', methods=['POST'])
@roles_accepted(Role.ROLE_ADMIN, Role.ROLE_FINANCE)
def payout_suspend():
    content = request.form
    token = content['token']
    logger.info('looking for %s', token)
    req = PayoutRequest.from_token(db.session, token)
    if req:
        payouts_core.set_payout_request_suspended(req)
        db.session.commit()
        return redirect('/payments/payouts')
    flash('Sorry payout not found', category='danger')
    return redirect('/')

@payments.route('/payout_request_unsuspend', methods=['POST'])
@roles_accepted(Role.ROLE_ADMIN, Role.ROLE_FINANCE)
def payout_unsuspend():
    content = request.form
    token = content['token']
    logger.info('looking for %s', token)
    req = PayoutRequest.from_token(db.session, token)
    if req:
        payouts_core.set_payout_request_created(req)
        db.session.commit()
        return redirect('/payments/payouts')
    flash('Sorry payout not found', category='danger')
    return redirect('/')
