from datetime import datetime, timedelta
import logging
from typing import Dict, Tuple

from sqlalchemy.orm.session import Session

import windcave
import dasset
import assets
from models import CryptoAddress, CryptoDeposit, CryptoWithdrawal, FiatDbTransaction, FiatDeposit, FiatWithdrawal, User, CrownPayment, WithdrawalConfirmation
import websocket
import email_utils
import fiatdb_core
import coordinator
import wallet
import tripwire
import utils
import crown_financial
import payouts_core

logger = logging.getLogger(__name__)

#
# Helper functions (public)
#

def withdrawal_authorize(withdrawal: CryptoWithdrawal | FiatWithdrawal, reason: str):
    # cancel withdrawal
    assert withdrawal.status == withdrawal.STATUS_CREATED
    withdrawal.status = withdrawal.STATUS_AUTHORIZED

def withdrawal_cancel(withdrawal: CryptoWithdrawal | FiatWithdrawal, reason: str):
    # cancel withdrawal
    assert withdrawal.status in (withdrawal.STATUS_CREATED, withdrawal.STATUS_AUTHORIZED)
    withdrawal.status = withdrawal.STATUS_CANCELLED
    # refund user
    type_ = 'crypto' if isinstance(withdrawal, CryptoWithdrawal) else 'fiat'
    asset = withdrawal.asset
    amount_int = withdrawal.amount
    return fiatdb_core.tx_create(withdrawal.user, FiatDbTransaction.ACTION_CREDIT, asset, amount_int, f'{type_} withdrawal refund - {reason}: {withdrawal.token}')

# -------------

def _fiat_deposit_update(fiat_deposit: FiatDeposit):
    logger.info('processing fiat deposit %s (%s)..', fiat_deposit.token, fiat_deposit.status)
    updated_records = []
    # check payment
    if fiat_deposit.status == fiat_deposit.STATUS_CREATED:
        if fiat_deposit.windcave_payment_request:
            payment_req = fiat_deposit.windcave_payment_request
            windcave.payment_request_status_update(payment_req)
            if payment_req.status == payment_req.STATUS_CANCELLED:
                fiat_deposit.status = fiat_deposit.STATUS_CANCELLED
                updated_records.append(payment_req)
                updated_records.append(fiat_deposit)
                return updated_records
            if payment_req.status == payment_req.STATUS_COMPLETED:
                fiat_deposit.status = fiat_deposit.STATUS_COMPLETED
                ftx = fiatdb_core.tx_create(fiat_deposit.user, FiatDbTransaction.ACTION_CREDIT, fiat_deposit.asset, fiat_deposit.amount, f'fiat deposit: {fiat_deposit.token}')
                updated_records.append(payment_req)
                updated_records.append(fiat_deposit)
                updated_records.append(ftx)
                return updated_records
        elif fiat_deposit.crown_payment:
            crown_payment = fiat_deposit.crown_payment
            tx = crown_financial.transaction_details(crown_payment.crown_txn_id)
            if tx.status == tx.STATUS_ACCEPTED:
                crown_payment.crown_status = tx.STATUS_ACCEPTED
                crown_payment.status = fiat_deposit.crown_payment.STATUS_COMPLETED
                fiat_deposit.status = fiat_deposit.STATUS_COMPLETED
                ftx = fiatdb_core.tx_create(fiat_deposit.user, FiatDbTransaction.ACTION_CREDIT, fiat_deposit.asset, fiat_deposit.amount, f'fiat deposit: {fiat_deposit.token}')
                updated_records.append(crown_payment)
                updated_records.append(fiat_deposit)
                updated_records.append(ftx)
                return updated_records
    # check expiry (for deposits via windcave)
    if fiat_deposit.status == fiat_deposit.STATUS_CREATED and fiat_deposit.windcave_payment_request:
        if datetime.now() > fiat_deposit.expiry:
            fiat_deposit.status = fiat_deposit.STATUS_EXPIRED
            updated_records.append(fiat_deposit)
            return updated_records
    return updated_records

def _fiat_deposit_email_msg(fiat_deposit: FiatDeposit, msg: str):
    amount = assets.asset_int_to_dec(fiat_deposit.asset, fiat_deposit.amount)
    amount_str = assets.asset_dec_to_str(fiat_deposit.asset, amount)
    return f'Your deposit {fiat_deposit.token} ({amount_str} {fiat_deposit.asset}) is now {fiat_deposit.status}. \n\n{msg}'

def _fiat_deposit_email(fiat_deposit: FiatDeposit):
    if fiat_deposit.status == fiat_deposit.STATUS_COMPLETED:
        email_utils.send_email(logger, 'Deposit Completed', _fiat_deposit_email_msg(fiat_deposit, ''), fiat_deposit.user.email)
    if fiat_deposit.status == fiat_deposit.STATUS_EXPIRED:
        email_utils.send_email(logger, 'Deposit Expired', _fiat_deposit_email_msg(fiat_deposit, ''), fiat_deposit.user.email)

def _crown_check_new_desposits(db_session: Session):
    if not utils.is_email(crown_financial.EMAIL):
        logger.error('invalid crown_financial.EMAIL %s', crown_financial.EMAIL)
        return
    txs = crown_financial.transactions_filtered_type(crown_financial.CrownTx.TYPE_DEPOSIT, datetime.now() - timedelta(days=7), datetime.now())
    for tx in txs:
        if tx.currency == crown_financial.CURRENCY and not CrownPayment.from_crown_txn_id(db_session, tx.crown_txn_id):
            payment = CrownPayment(utils.generate_key(), tx.currency, tx.amount, tx.crown_txn_id, tx.status)
            user = crown_financial.user_from_deposit(db_session, tx)
            if user:
                deposit = FiatDeposit(user, crown_financial.CURRENCY, tx.amount)
                deposit.crown_payment = payment
                db_session.add(payment)
                db_session.add(deposit)
                db_session.commit()

def _fiat_deposit_update_and_commit(db_session: Session, deposit: FiatDeposit):
    if deposit.asset not in assets.ASSETS:
        logger.error('fiat deposit (%s) asset (%s) is not valid', deposit.token, deposit.asset)
        return
    while True:
        updated_records = _fiat_deposit_update(deposit)
        # commit db if records updated
        if not updated_records:
            return
        for rec in updated_records:
            db_session.add(rec)
        db_session.commit()
        # send updates
        _fiat_deposit_email(deposit)
        websocket.fiat_deposit_update_event(deposit)

def fiat_deposit_update(db_session: Session, token: str):
    with coordinator.lock:
        deposit = FiatDeposit.from_token(db_session, token)
        if deposit:
            _fiat_deposit_update_and_commit(db_session, deposit)

def fiat_deposits_update(db_session: Session):
    with coordinator.lock:
        deposits = FiatDeposit.all_active(db_session)
        logger.info('num deposits: %d', len(deposits))
        for deposit in deposits:
            _fiat_deposit_update_and_commit(db_session, deposit)
        _crown_check_new_desposits(db_session)

def _fiat_withdrawal_update(fiat_withdrawal: FiatWithdrawal):
    logger.info('processing fiat withdrawal %s (%s)..', fiat_withdrawal.token, fiat_withdrawal.status)
    updated_records: list = []
    # check withdrawals enabled
    if not tripwire.WITHDRAWAL.ok:
        return updated_records
    # check status
    if fiat_withdrawal.status == fiat_withdrawal.STATUS_CREATED:
        conf = fiat_withdrawal.withdrawal_confirmation
        if not conf:
            logger.error('fiat withdrawal (%s) does not have a confirmation record', fiat_withdrawal.token)
            return updated_records
        if not conf.confirmed:
            if conf.expired():
                ftx = withdrawal_cancel(fiat_withdrawal, 'confirmation expiry')
                updated_records.append(fiat_withdrawal)
                updated_records.append(ftx)
            return updated_records
    if fiat_withdrawal.status == fiat_withdrawal.STATUS_AUTHORIZED:
        if not fiat_withdrawal.payout_request:
            assert fiat_withdrawal.withdrawal_confirmation
            address_book = fiat_withdrawal.withdrawal_confirmation.address_book
            assert address_book
            payout_request = payouts_core.payout_create(fiat_withdrawal.amount, crown_financial.CROWN_WITHDRAW_NAME, fiat_withdrawal.token, address_book)
            if not payout_request:
                logger.error('payouts_core.payout_create failed')
                return updated_records
            fiat_withdrawal.payout_request = payout_request
            updated_records.append(payout_request)
            fiat_withdrawal.status = fiat_withdrawal.STATUS_WITHDRAW
            updated_records.append(fiat_withdrawal)
            return updated_records
    if fiat_withdrawal.status == fiat_withdrawal.STATUS_WITHDRAW:
        if fiat_withdrawal.payout_request:
            payout_request = fiat_withdrawal.payout_request
            if payout_request.status == payout_request.STATUS_COMPLETED:
                fiat_withdrawal.status = fiat_withdrawal.STATUS_COMPLETED
                updated_records.append(fiat_withdrawal)
    return updated_records

def _fiat_withdrawal_email_msg(fiat_withdrawal: FiatWithdrawal, msg: str):
    amount = assets.asset_int_to_dec(fiat_withdrawal.asset, fiat_withdrawal.amount)
    amount_str = assets.asset_dec_to_str(fiat_withdrawal.asset, amount)
    return f'Your withdrawal {fiat_withdrawal.token} ({amount_str} {fiat_withdrawal.asset}) is now {fiat_withdrawal.status}. \n\n{msg}'

def _fiat_withdrawal_email(fiat_withdrawal: FiatWithdrawal):
    if fiat_withdrawal.status == fiat_withdrawal.STATUS_COMPLETED:
        email_utils.send_email(logger, 'Withdrawal Completed', _fiat_withdrawal_email_msg(fiat_withdrawal, ''), fiat_withdrawal.user.email)

def _fiat_withdrawal_update_and_commit(db_session: Session, withdrawal: FiatWithdrawal):
    if withdrawal.asset not in assets.ASSETS:
        logger.error('fiat withdrawal (%s) asset (%s) is not valid', withdrawal.token, withdrawal.asset)
        return
    while True:
        updated_records = _fiat_withdrawal_update(withdrawal)
        # commit db if record updated
        if not updated_records:
            return
        for updated_record in updated_records:
            db_session.add(updated_record)
        db_session.commit()
        # send updates
        _fiat_withdrawal_email(withdrawal)
        websocket.fiat_withdrawal_update_event(withdrawal)

def fiat_withdrawal_update(db_session: Session, token: str):
    with coordinator.lock:
        withdrawal = FiatWithdrawal.from_token(db_session, token)
        if withdrawal:
            _fiat_withdrawal_update_and_commit(db_session, withdrawal)

def fiat_withdrawals_update(db_session: Session):
    with coordinator.lock:
        withdrawals = FiatWithdrawal.all_active(db_session)
        logger.info('num withdrawals: %d', len(withdrawals))
        for withdrawal in withdrawals:
            _fiat_withdrawal_update_and_commit(db_session, withdrawal)

def _crypto_deposit_email_msg(deposit: CryptoDeposit, verb: str, msg: str):
    amount = assets.asset_int_to_dec(deposit.asset, deposit.amount)
    amount_str = assets.asset_dec_to_str(deposit.asset, amount)
    deposit_id = deposit.txid if deposit.txid else deposit.wallet_reference
    deposit_id = utils.shorten(deposit_id)
    return f'Your deposit {deposit_id} ({amount_str} {deposit.asset}) is now {verb}. \n\n{msg}'

def _crypto_deposit_email(deposit: CryptoDeposit):
    if deposit.confirmed:
        email_utils.send_email(logger, 'Deposit Confirmed', _crypto_deposit_email_msg(deposit, 'confirmed', ''), deposit.user.email)
    else:
        email_utils.send_email(logger, 'Deposit Incoming', _crypto_deposit_email_msg(deposit, 'incoming', ''), deposit.user.email)

def _crypto_deposits_wallet_check(db_session: Session, new_crypto_deposits: list[CryptoDeposit], updated_crypto_deposits: list[CryptoDeposit], user: User, asset: str, addr_list: list[str]):
    for addr in addr_list:
        wallet_deposits = wallet.address_deposits(asset, None, addr)
        for wallet_deposit in wallet_deposits:
            completed = wallet.deposit_completed(asset, None, wallet_deposit.txid)
            crypto_deposit = CryptoDeposit.from_txid(db_session, wallet_deposit.txid)
            if not crypto_deposit:
                crypto_deposit = CryptoDeposit(user, asset, None, wallet_deposit.amount_deposited(), None, wallet_deposit.txid, wallet_deposit.txid, completed, False)
                new_crypto_deposits.append(crypto_deposit)
            if (crypto_deposit in new_crypto_deposits or not crypto_deposit.confirmed) and completed:
                # credit the users account
                ftx = fiatdb_core.tx_create(user, FiatDbTransaction.ACTION_CREDIT, asset, wallet_deposit.amount_deposited(), f'crypto deposit: {crypto_deposit.token}')
                db_session.add(ftx)
                # update crypto deposit
                crypto_deposit.confirmed = completed
                updated_crypto_deposits.append(crypto_deposit)
            if not crypto_deposit.crypto_address:
                addr_db = CryptoAddress.from_addr(db_session, addr)
                if addr_db:
                    crypto_deposit.crypto_address = addr_db
            db_session.add(crypto_deposit)
            db_session.commit()

def _crypto_deposits_dasset_check(db_session: Session, new_crypto_deposits: list[CryptoDeposit], updated_crypto_deposits: list[CryptoDeposit], user: User, asset: str):
    if asset not in assets.ASSETS:
        logger.error('dasset crypto deposit asset (%s) is not valid', asset)
        return
    if not user.dasset_subaccount:
        logger.error('user %s dasset subaccount does not exist', user.email)
        return
    dasset_deposits = dasset.crypto_deposits(asset, user.dasset_subaccount.subaccount_id)
    for dasset_deposit in dasset_deposits:
        completed = dasset.crypto_deposit_completed(dasset_deposit)
        crypto_deposit = CryptoDeposit.from_txid(db_session, dasset_deposit.txid)
        if not crypto_deposit:
            amount_int = assets.asset_dec_to_int(asset, dasset_deposit.amount)
            crypto_deposit = CryptoDeposit(user, asset, None, amount_int, dasset_deposit.id, None, dasset_deposit.txid, completed, False)
            new_crypto_deposits.append(crypto_deposit)
        if (crypto_deposit in new_crypto_deposits or not crypto_deposit.confirmed) and completed:
            # if deposit now completed transfer the funds to the master account
            if not dasset.transfer(None, user.dasset_subaccount.subaccount_id, asset, dasset_deposit.amount):
                logger.error('failed to transfer funds from subaccount to master %s', dasset_deposit.id)
                continue
            # and credit the users account
            ftx = fiatdb_core.tx_create(user, FiatDbTransaction.ACTION_CREDIT, asset, crypto_deposit.amount, f'crypto deposit: {crypto_deposit.token}')
            db_session.add(ftx)
            # update crypto deposit
            crypto_deposit.confirmed = completed
            updated_crypto_deposits.append(crypto_deposit)
        if not crypto_deposit.crypto_address:
            addr = CryptoAddress.from_addr(db_session, dasset_deposit.address)
            if addr:
                crypto_deposit.crypto_address = addr
        db_session.add(crypto_deposit)
        db_session.commit()

def _crypto_deposits_address_check(db_session: Session, new_crypto_deposits: list[CryptoDeposit], updated_crypto_deposits: list[CryptoDeposit]):
    # query for list of addresses that need to be checked
    addrs = CryptoAddress.need_to_be_checked(db_session)
    # sort in groups of assets for each user
    user_assets: Dict[str, Tuple[User, dict]] = {}
    for addr in addrs:
        if addr.user.email not in user_assets:
            user_assets[addr.user.email] = addr.user, {}
        _, asset_dict = user_assets[addr.user.email]
        if addr.asset not in asset_dict:
            asset_dict[addr.asset] = [addr.address]
        # update checked at time of CryptoAddress
        addr.checked_at = int(datetime.timestamp(datetime.now()))
        db_session.add(addr)
    db_session.commit()
    # check for new deposits, update existing deposits
    for user, asset_dict in user_assets.values():
        for asset, addr_list in asset_dict.items():
            if wallet.deposits_supported(asset, None):
                _crypto_deposits_wallet_check(db_session, new_crypto_deposits, updated_crypto_deposits, user, asset, addr_list)
            else:
                _crypto_deposits_dasset_check(db_session, new_crypto_deposits, updated_crypto_deposits, user, asset)

def _crypto_deposits_updated_wallet_check(db_session: Session, updated_crypto_deposits: list[CryptoDeposit]):
    for deposit in CryptoDeposit.of_wallet(db_session, False, False):
        logger.info('processing crypto deposit %s (confirmed: %s)..', deposit.token, deposit.confirmed)
        if wallet.deposit_expired(deposit.asset, deposit.l2_network, deposit.wallet_reference):
            deposit.expired = True
            updated_crypto_deposits.append(deposit)
        elif wallet.deposit_completed(deposit.asset, deposit.l2_network, deposit.wallet_reference):
            deposit.confirmed = True
            # credit the users account
            ftx = fiatdb_core.tx_create(deposit.user, FiatDbTransaction.ACTION_CREDIT, deposit.asset, deposit.amount, f'crypto deposit: {deposit.token}')
            db_session.add(ftx)
            updated_crypto_deposits.append(deposit)
        db_session.add(deposit)
        db_session.commit()

def crypto_wallet_deposits_check(db_session: Session):
    updated_crypto_deposits: list[CryptoDeposit] = []
    with coordinator.lock:
        # check crypto deposits in our wallet
        _crypto_deposits_updated_wallet_check(db_session, updated_crypto_deposits)
    # send updates
    for deposit in updated_crypto_deposits:
        _crypto_deposit_email(deposit)
        websocket.crypto_deposit_update_event(deposit)

def crypto_deposits_check(db_session: Session):
    new_crypto_deposits: list[CryptoDeposit] = []
    updated_crypto_deposits: list[CryptoDeposit] = []
    with coordinator.lock:
        # check crypto deposits from addresses that are due to be checked (from dasset or our wallet)
        _crypto_deposits_address_check(db_session, new_crypto_deposits, updated_crypto_deposits)
        # check crypto deposits in our wallet
        _crypto_deposits_updated_wallet_check(db_session, updated_crypto_deposits)
    # send updates
    for deposit in new_crypto_deposits:
        _crypto_deposit_email(deposit)
        websocket.crypto_deposit_new_event(deposit)
    for deposit in updated_crypto_deposits:
        _crypto_deposit_email(deposit)
        websocket.crypto_deposit_update_event(deposit)

def _crypto_withdrawal_update(crypto_withdrawal: CryptoWithdrawal):
    logger.info('processing crypto withdrawal %s (%s)..', crypto_withdrawal.token, crypto_withdrawal.status)
    updated_records: list[CryptoDeposit] = []
    # check withdrawals enabled
    if not tripwire.WITHDRAWAL.ok:
        return updated_records
    # check status
    if crypto_withdrawal.status == crypto_withdrawal.STATUS_CREATED:
        conf: WithdrawalConfirmation = crypto_withdrawal.withdrawal_confirmation
        if not conf:
            logger.error('crypto withdrawal (%s) does not have a confirmation record', crypto_withdrawal.token)
            return updated_records
        if not conf.confirmed:
            if conf.expired():
                ftx = withdrawal_cancel(crypto_withdrawal, 'confirmation expiry')
                updated_records.append(crypto_withdrawal)
                updated_records.append(ftx)
            return updated_records
    if crypto_withdrawal.status == crypto_withdrawal.STATUS_AUTHORIZED:
        if not crypto_withdrawal.wallet_reference and not crypto_withdrawal.exchange_reference:
            asset = crypto_withdrawal.asset
            l2_network = crypto_withdrawal.l2_network
            amount_dec = assets.asset_int_to_dec(asset, crypto_withdrawal.amount)
            recipient = crypto_withdrawal.recipient
            # create wallet/exchange withdrawal
            exchange_reference = None
            wallet_reference = None
            if wallet.withdrawals_supported(asset, l2_network):
                logger.info('check local wallet has funds available')
                if not wallet.funds_available(asset, l2_network, amount_dec):
                    logger.error('wallet.funds_available failed')
                    return updated_records
                logger.info('create local wallet withdrawal')
                wallet_reference, err_msg = wallet.withdrawal_create(asset, l2_network, amount_dec, recipient)
                if err_msg:
                    logger.error('wallet.withdrawal_create failed - %s', err_msg)
                    return updated_records
            else:
                if not dasset.funds_available_us(asset, amount_dec):
                    logger.error('dasset.funds_available_us failed')
                    return updated_records
                exchange_reference = dasset.crypto_withdrawal_create(asset, amount_dec, recipient)
                if not exchange_reference:
                    logger.error('dasset.crypto_withdrawal_create failed')
                    return updated_records
            crypto_withdrawal.wallet_reference = wallet_reference
            crypto_withdrawal.exchange_reference = exchange_reference
        crypto_withdrawal.status = crypto_withdrawal.STATUS_WITHDRAW
        updated_records.append(crypto_withdrawal)
        return updated_records
    if crypto_withdrawal.status == crypto_withdrawal.STATUS_WITHDRAW:
        if crypto_withdrawal.wallet_reference:
            # check wallet withdrawal
            if wallet.withdrawal_completed(crypto_withdrawal.asset, crypto_withdrawal.l2_network, crypto_withdrawal.wallet_reference):
                crypto_withdrawal.status = crypto_withdrawal.STATUS_COMPLETED
                updated_records.append(crypto_withdrawal)
        elif crypto_withdrawal.exchange_reference:
            # check exchange withdrawal
            status = dasset.crypto_withdrawal_status_check(crypto_withdrawal.exchange_reference)
            if status == dasset.CRYPTO_WITHDRAWAL_STATUS_COMPLETED:
                crypto_withdrawal.status = crypto_withdrawal.STATUS_COMPLETED
                updated_records.append(crypto_withdrawal)
            elif status == dasset.CRYPTO_WITHDRAWAL_STATUS_2FA:
                if not dasset.crypto_withdrawal_confirm(crypto_withdrawal.exchange_reference):
                    logger.error('failed to confirm crypto withdrawal %s', crypto_withdrawal.token)
            elif status == dasset.CRYPTO_WITHDRAWAL_STATUS_UNKNOWN:
                logger.error('failed to get crypto withdrawal %s status', crypto_withdrawal.token)
        return updated_records
    return updated_records

def _crypto_withdrawal_email_msg(crypto_withdrawal: CryptoWithdrawal, msg: str):
    amount = assets.asset_int_to_dec(crypto_withdrawal.asset, crypto_withdrawal.amount)
    amount_str = assets.asset_dec_to_str(crypto_withdrawal.asset, amount)
    return f'Your withdrawal {crypto_withdrawal.token} ({amount_str} {crypto_withdrawal.asset}) is now {crypto_withdrawal.status}. \n\n{msg}'

def _crypto_withdrawal_email(crypto_withdrawal: CryptoWithdrawal):
    if crypto_withdrawal.status == crypto_withdrawal.STATUS_COMPLETED:
        email_utils.send_email(logger, 'Withdrawal Completed', _crypto_withdrawal_email_msg(crypto_withdrawal, ''), crypto_withdrawal.user.email)

def _crypto_withdrawal_update_and_commit(db_session: Session, withdrawal: CryptoWithdrawal):
    if withdrawal.asset not in assets.ASSETS:
        logger.error('crypto withdrawal (%s) asset (%s) is not valid', withdrawal.token, withdrawal.asset)
        return
    while True:
        updated_records = _crypto_withdrawal_update(withdrawal)
        # commit db if records updated
        if not updated_records:
            return
        for rec in updated_records:
            db_session.add(rec)
        db_session.commit()
        # send updates
        _crypto_withdrawal_email(withdrawal)
        websocket.crypto_withdrawal_update_event(withdrawal)

def crypto_withdrawal_update(db_session: Session, token: str):
    with coordinator.lock:
        withdrawal = CryptoWithdrawal.from_token(db_session, token)
        if withdrawal:
            _crypto_withdrawal_update_and_commit(db_session, withdrawal)

def crypto_withdrawals_update(db_session: Session):
    with coordinator.lock:
        withdrawals = CryptoWithdrawal.all_active(db_session)
        logger.info('num withdrawals: %d', len(withdrawals))
        for withdrawal in withdrawals:
            _crypto_withdrawal_update_and_commit(db_session, withdrawal)
