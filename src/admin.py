import datetime

from flask import redirect, url_for, request, has_app_context, g, abort
import flask_admin
from flask_admin import helpers as admin_helpers
from flask_admin.babel import lazy_gettext
from flask_admin.contrib import sqla
from flask_admin.contrib.sqla.filters import BaseSQLAFilter
from flask_admin.model import filters, typefmt
from flask_login.utils import current_user
from markupsafe import Markup

from app_core import app, db
from models import Role, User, ApiKey, Topic, PushNotificationLocation, Referral, BrokerOrder, ExchangeOrder, CryptoWithdrawal, CryptoDeposit, CryptoAddress, KycRequest, AplyId, FiatDbTransaction, FiatDeposit, FiatWithdrawal, WindcavePaymentRequest, PayoutRequest, CrownPayment, WithdrawalConfirmation
from security import security

# helper functions/classes

class ReloadingIterator:
    def __init__(self, iterator_factory):
        self.iterator_factory = iterator_factory

    def __iter__(self):
        return self.iterator_factory()

# flask admin formatters

def _date_format(view, value):
    return value.strftime('%Y.%m.%d %H:%M')

MY_DEFAULT_FORMATTERS = dict(typefmt.BASE_FORMATTERS)
MY_DEFAULT_FORMATTERS.update({
    datetime.date: _date_format,
})

def _format_location(view, context, model, name):
    lat = model.latitude
    lon = model.longitude
    html = f'''
    <a href="http://www.google.com/maps/place/{lat},{lon}">{lat}, {lon}</a>
    '''
    return Markup(html)

# flask admin filters

class DateBetweenFilter(BaseSQLAFilter, filters.BaseDateBetweenFilter):
    def __init__(self, column, name, options=None, data_type=None):
        super(DateBetweenFilter, self).__init__(column,
                                                name,
                                                options,
                                                data_type='daterangepicker')

    def apply(self, query, value, alias=None):
        start, end = value
        return query.filter(self.get_column(alias).between(start, end))

class FilterEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(self.get_column(alias) == value)

    def operation(self):
        return lazy_gettext('equals')

class FilterNotEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(self.get_column(alias) != value)

    def operation(self):
        return lazy_gettext('not equal')

class FilterGreater(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(self.get_column(alias) > value)

    def operation(self):
        return lazy_gettext('greater than')

class FilterSmaller(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(self.get_column(alias) < value)

    def operation(self):
        return lazy_gettext('smaller than')

class DateTimeGreaterFilter(FilterGreater, filters.BaseDateTimeFilter):
    pass

class DateSmallerFilter(FilterSmaller, filters.BaseDateFilter):
    pass

def get_users():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'users'):
            query = User.query.order_by(User.email)
            g.users = [(user.id, user.email) for user in query]
        for user_id, user_email in g.users:
            yield user_id, user_email

class FilterByUserEmail(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(User.id == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_users)

def get_broker_order_assets():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'assets'):
            query = BrokerOrder.query.with_entities(BrokerOrder.base_asset).distinct()
            g.assets = [(broker_order.base_asset, broker_order.base_asset) for broker_order in query]
        for base_asset_a, base_asset_b in g.assets:
            yield base_asset_a, base_asset_b

class FilterByBrokerOrderAsset(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(BrokerOrder.base_asset == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_broker_order_assets)

def get_brokerorder_statuses():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'brokerorder_statuses'):
            query = BrokerOrder.query.with_entities(BrokerOrder.status).distinct()
            g.brokerorder_statuses = [(broker_order.status, broker_order.status) for broker_order in query]
        for broker_order_status_a, broker_order_status_b in g.brokerorder_statuses:
            yield broker_order_status_a, broker_order_status_b

def get_brokerorder_markets():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'brokerorder_markets'):
            query = BrokerOrder.query.with_entities(BrokerOrder.market).distinct()
            g.brokerorder_markets = [(broker_order.market, broker_order.market) for broker_order in query]
        for broker_order_market_a, broker_order_market_b in g.brokerorder_markets:
            yield broker_order_market_a, broker_order_market_b

def get_cryptowithdrawal_statuses():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'cyptowithdrawal_statuses'):
            query = CryptoWithdrawal.query.with_entities(CryptoWithdrawal.status).distinct()
            g.cryptowithdrawal_statuses = [(crypto_withdrawal.status, crypto_withdrawal.status) for crypto_withdrawal in query]
        for crypto_withdrawal_status_a, crypto_withdrawal_status_b in g.cryptowithdrawal_statuses:
            yield crypto_withdrawal_status_a, crypto_withdrawal_status_b

def get_cryptowithdrawal_assets():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'cyptowithdrawal_assets'):
            query = CryptoWithdrawal.query.with_entities(CryptoWithdrawal.asset).distinct()
            g.cryptowithdrawal_assets = [(crypto_withdrawal.asset, crypto_withdrawal.asset) for crypto_withdrawal in query]
        for crypto_withdrawal_asset_a, crypto_withdrawal_asset_b in g.cryptowithdrawal_assets:
            yield crypto_withdrawal_asset_a, crypto_withdrawal_asset_b

def get_cryptodeposit_confirmed():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'cyptodeposit_confirmed'):
            query = CryptoDeposit.query.with_entities(CryptoDeposit.confirmed).distinct()
            g.cryptodeposit_confirmed = [(crypto_deposit.confirmed, crypto_deposit.confirmed) for crypto_deposit in query]
        for crypto_deposit_confirmed_a, crypto_deposit_confirmed_b in g.cryptodeposit_confirmed:
            yield crypto_deposit_confirmed_a, crypto_deposit_confirmed_b

class FilterByBrokerOrderStatusEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(BrokerOrder.status == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_brokerorder_statuses)

class FilterByBrokerOrderMarketEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(BrokerOrder.market == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_brokerorder_markets)

class FilterByCrytpoWithdrawalStatusEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(CryptoWithdrawal.status == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_cryptowithdrawal_statuses)

class FilterByCryptoWithdrawalAssetEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(CryptoWithdrawal.asset == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_cryptowithdrawal_assets)

class FilterByCryptoDepositConfirmedEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(CryptoDeposit.confirmed == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_cryptodeposit_confirmed)

def get_cryptodeposit_assets():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'cyptodeposit_assets'):
            query = CryptoDeposit.query.with_entities(CryptoDeposit.asset).distinct()
            g.cryptodeposit_assets = [(crypto_deposit.asset, crypto_deposit.asset) for crypto_deposit in query]
        for crypto_deposit_asset_a, crypto_deposit_asset_b in g.cryptodeposit_assets:
            yield crypto_deposit_asset_a, crypto_deposit_asset_b

class FilterByCryptoDepositAssetEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(CryptoDeposit.asset == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_cryptodeposit_assets)

def get_fiatwithdrawal_statuses():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'fiatwithdrawal_statuses'):
            query = FiatWithdrawal.query.with_entities(FiatWithdrawal.status).distinct()
            g.fiatwithdrawal_statuses = [(fiat_withdrawal.status, fiat_withdrawal.status) for fiat_withdrawal in query]
        for fiat_withdrawal_status_a, fiat_withdrawal_status_b in g.fiatwithdrawal_statuses:
            yield fiat_withdrawal_status_a, fiat_withdrawal_status_b

class FilterByFiatWithdrawalStatusEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(FiatWithdrawal.status == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_fiatwithdrawal_statuses)

def get_fiatwithdrawal_assets():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'fiatwithdrawal_assets'):
            query = FiatWithdrawal.query.with_entities(FiatWithdrawal.asset).distinct()
            g.fiatwithdrawal_assets = [(fiat_withdrawal.asset, fiat_withdrawal.asset) for fiat_withdrawal in query]
        for fiat_withdrawal_asset_a, fiat_withdrawal_asset_b in g.fiatwithdrawal_assets:
            yield fiat_withdrawal_asset_a, fiat_withdrawal_asset_b

class FilterByFiatWithdrawalAssetEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(FiatWithdrawal.asset == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_fiatwithdrawal_assets)

def get_fiatdeposit_statuses():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'fiatdeposit_statuses'):
            query = FiatDeposit.query.with_entities(FiatDeposit.status).distinct()
            g.fiatdeposit_statuses = [(fiat_deposit.status, fiat_deposit.status) for fiat_deposit in query]
        for fiat_deposit_status_a, fiat_deposit_status_b in g.fiatdeposit_statuses:
            yield fiat_deposit_status_a, fiat_deposit_status_b

class FilterByFiatDepositStatusEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(FiatDeposit.status == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_fiatdeposit_statuses)

def get_fiatdeposit_assets():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'fiatdeposit_assets'):
            query = FiatDeposit.query.with_entities(FiatDeposit.asset).distinct()
            g.fiatdeposit_assets = [(fiat_deposit.asset, fiat_deposit.asset) for fiat_deposit in query]
        for fiat_deposit_asset_a, fiat_deposit_asset_b in g.fiatdeposit_assets:
            yield fiat_deposit_asset_a, fiat_deposit_asset_b

class FilterByFiatDepositAssetEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(FiatDeposit.asset == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_fiatdeposit_assets)

def get_payoutrequest_statuses():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'payoutrequest_statuses'):
            query = PayoutRequest.query.with_entities(PayoutRequest.status).distinct()
            g.payoutrequest_statuses = [(payout_request.status, payout_request.status) for payout_request in query]
        for payout_request_status_a, payout_request_status_b in g.payoutrequest_statuses:
            yield payout_request_status_a, payout_request_status_b

class FilterByPayoutRequestStatusEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(PayoutRequest.status == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_payoutrequest_statuses)

def get_payoutrequest_assets():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'payoutrequest_assets'):
            query = PayoutRequest.query.with_entities(PayoutRequest.asset).distinct()
            g.payoutrequest_assets = [(payout_request.asset, payout_request.asset) for payout_request in query]
        for payout_request_asset_a, payout_request_asset_b in g.payoutrequest_assets:
            yield payout_request_asset_a, payout_request_asset_b

class FilterByPayoutRequestAssetEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(PayoutRequest.asset == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_payoutrequest_assets)

def get_fiatdbtransaction_assets():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'fiatdbtransaction_assets'):
            query = FiatDbTransaction.query.with_entities(FiatDbTransaction.asset).distinct()
            g.fiatdbtransaction_assets = [(fiat_db_transaction.asset, fiat_db_transaction.asset) for fiat_db_transaction in query]
        for fiat_db_transaction_asset_a, fiat_db_transaction_asset_b in g.fiatdbtransaction_assets:
            yield fiat_db_transaction_asset_a, fiat_db_transaction_asset_b

class FilterByFiatDbTransactionAssetEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(FiatDbTransaction.asset == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_fiatdbtransaction_assets)

def get_fiatdbtransaction_actions():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'fiatdbtransaction_actions'):
            query = FiatDbTransaction.query.with_entities(FiatDbTransaction.action).distinct()
            g.fiatdbtransaction_actions = [(fiat_db_transaction.action, fiat_db_transaction.action) for fiat_db_transaction in query]
        for fiat_db_transaction_action_a, fiat_db_transaction_action_b in g.fiatdbtransaction_actions:
            yield fiat_db_transaction_action_a, fiat_db_transaction_action_b

class FilterByFiatDbTransactionActionEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(FiatDbTransaction.action == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_fiatdbtransaction_actions)

class FilterByFiatDbTransactionUserSearch(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        result = User.query.filter(User.id == value).one()
        user_id = result.id
        return query.filter(FiatDbTransaction.user_id == user_id)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_users)

class FilterGreaterFiatDbTransactionAmount(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(self.get_column(alias) > value)

    def operation(self):
        return lazy_gettext('greater than')

class FilterSmallerFiatDbTransactionAmount(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(self.get_column(alias) < value)

    def operation(self):
        return lazy_gettext('smaller than')

class FilterEqualFiatDbTransactionAmount(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(self.get_column(alias) == value)

    def operation(self):
        return lazy_gettext('equals')

# model view classes

class BaseModelView(sqla.ModelView):
    def _handle_view(self, name, **kwargs):
        """
        Override builtin _handle_view in order to redirect users when a view is not accessible.
        """
        if not self.is_accessible():
            if current_user.is_authenticated:
                # permission denied
                return abort(403)
            # login
            return redirect(url_for('security.login', next=request.url))
        return None

class RestrictedModelView(BaseModelView):
    can_create = False
    can_delete = False
    can_edit = False
    column_exclude_list = ['password', 'secret']

    def is_accessible(self):
        return (current_user.is_active and
                current_user.is_authenticated and
                (current_user.has_role(Role.ROLE_ADMIN) or
                 current_user.has_role(Role.ROLE_FINANCE)))

class BaseOnlyUserOwnedModelView(BaseModelView):
    can_create = False
    can_delete = False
    can_edit = False
    column_exclude_list = ['password', 'secret']

    def is_accessible(self):
        return (current_user.is_active and
                current_user.is_authenticated)

    def get_query(self):
        return self.session.query(self.model).filter(self.model.user == current_user)

    def get_count_query(self):
        return self.session.query(db.func.count('*')).filter(self.model.user == current_user)

class UserModelView(BaseModelView):
    can_export = True
    can_create = False
    can_delete = False
    can_edit = False
    column_list = ['token', 'email', 'roles', 'active', 'confirmed_at']
    column_filters = [FilterByUserEmail(User.email, 'Search email'),
                      DateBetweenFilter(User.confirmed_at, 'Search Date')]

    def is_accessible(self):
        if not (current_user.is_active and current_user.is_authenticated):
            return False
        if current_user.has_role(Role.ROLE_FINANCE) and not current_user.has_role(Role.ROLE_ADMIN):
            return True
        return False

class AdminUserModelView(UserModelView):
    column_editable_list = ['roles', 'active']

    def is_accessible(self):
        if not (current_user.is_active and current_user.is_authenticated):
            return False
        if current_user.has_role(Role.ROLE_ADMIN):
            return True
        return False

class ApiKeyModelView(BaseOnlyUserOwnedModelView):
    can_create = False
    can_delete = True
    can_edit = False
    column_list = ('token', 'device_name', 'expiry', 'permissions')
    column_labels = dict(token='API Key')

class PushNotificationLocationModelView(RestrictedModelView):
    can_create = False
    can_delete = False
    can_edit = False

    column_list = ['date', 'location', 'fcm_registration_token']
    column_formatters = {'location': _format_location}

class BrokerOrderModelView(RestrictedModelView):
    can_create = False
    can_delete = False
    can_edit = False

    column_filters = [DateBetweenFilter(BrokerOrder.date, 'Search Date'),
                      FilterByBrokerOrderAsset(BrokerOrder.base_asset, 'Search Asset'),
                      FilterByBrokerOrderStatusEqual(BrokerOrder.status, 'Search Status'),
                      FilterByBrokerOrderMarketEqual(BrokerOrder.market, 'Search Market')]

class CryptoWithdrawalModelView(RestrictedModelView):
    can_create = False
    can_delete = False
    can_edit = False

    column_filters = [DateBetweenFilter(CryptoWithdrawal.date, 'Search Date'),
                      FilterByCrytpoWithdrawalStatusEqual(CryptoWithdrawal.status, 'Search Status'),
                      FilterByCryptoWithdrawalAssetEqual(CryptoWithdrawal.asset, 'Search Asset')]

class CryptoDepositModelView(RestrictedModelView):
    can_create = False
    can_delete = False
    can_edit = False

    column_filters = [DateBetweenFilter(CryptoDeposit.date, 'Search Date'),
                      FilterByCryptoDepositConfirmedEqual(CryptoDeposit.confirmed, 'Search Confirmed'),
                      FilterByCryptoDepositAssetEqual(CryptoDeposit.asset, 'Search Asset')]

class FiatWithdrawalModelView(RestrictedModelView):
    can_create = False
    can_delete = False
    can_edit = False

    column_filters = [DateBetweenFilter(FiatWithdrawal.date, 'Search Date'),
                      FilterByFiatWithdrawalStatusEqual(FiatWithdrawal.status, 'Search Status'),
                      FilterByFiatWithdrawalAssetEqual(FiatWithdrawal.asset, 'Search Asset')]

class FiatDepositModelView(RestrictedModelView):
    can_create = False
    can_delete = False
    can_edit = False

    column_filters = [DateBetweenFilter(FiatDeposit.date, 'Search Date'),
                      FilterByFiatDepositStatusEqual(FiatDeposit.status, 'Search Status'),
                      FilterByFiatDepositAssetEqual(FiatDeposit.asset, 'Search Asset')]

class PayoutRequestModelView(RestrictedModelView):
    can_create = False
    can_delete = False
    can_edit = False

    column_filters = [DateBetweenFilter(PayoutRequest.date, 'Search Date'),
                      FilterByPayoutRequestStatusEqual(PayoutRequest.status, 'Search Status'),
                      FilterByPayoutRequestAssetEqual(FiatDeposit.asset, 'Search Asset')]

class FiatDbTransactionModelView(RestrictedModelView):
    can_create = False
    can_delete = False
    can_edit = False

    column_filters = [DateBetweenFilter(FiatDbTransaction.date, 'Search Date'),
                      FilterByFiatDbTransactionAssetEqual(FiatDbTransaction.asset, 'Search Asset'),
                      FilterByFiatDbTransactionActionEqual(FiatDbTransaction.action, 'Search Action'),
                      FilterEqualFiatDbTransactionAmount(FiatDbTransaction.amount, 'Search Amount'),
                      FilterGreaterFiatDbTransactionAmount(FiatDbTransaction.amount, 'Search Amount'),
                      FilterSmallerFiatDbTransactionAmount(FiatDbTransaction.amount, 'Search Amount'),
                      FilterByFiatDbTransactionUserSearch(FiatDbTransaction.user_id, 'Search User')]

class WithdrawalConfirmationView(RestrictedModelView):
    can_create = False
    can_delete = False
    can_edit = False

    column_filters = [DateBetweenFilter(WithdrawalConfirmation.date, 'Search Date')]

#
# Create admin
#

admin = flask_admin.Admin(
    app,
    'Beryllium Admin',
    base_template='my_master.html',
    template_mode='bootstrap3',
)

# Add model views
admin.add_view(UserModelView(User, db.session, category='Admin'))
admin.add_view(AdminUserModelView(User, db.session, category='Admin', endpoint='AdminUser'))
admin.add_view(RestrictedModelView(Role, db.session, category='Admin'))
admin.add_view(RestrictedModelView(Topic, db.session, category='Admin'))
admin.add_view(PushNotificationLocationModelView(PushNotificationLocation, db.session, category='Admin'))
admin.add_view(BrokerOrderModelView(BrokerOrder, db.session, category='Admin'))
admin.add_view(RestrictedModelView(ExchangeOrder, db.session, category='Admin'))
admin.add_view(CryptoWithdrawalModelView(CryptoWithdrawal, db.session, category='Admin'))
admin.add_view(CryptoDepositModelView(CryptoDeposit, db.session, category='Admin'))
admin.add_view(RestrictedModelView(CryptoAddress, db.session, category='Admin'))
admin.add_view(FiatWithdrawalModelView(FiatWithdrawal, db.session, category='Admin'))
admin.add_view(FiatDepositModelView(FiatDeposit, db.session, category='Admin'))
admin.add_view(RestrictedModelView(WindcavePaymentRequest, db.session, category='Admin'))
admin.add_view(RestrictedModelView(CrownPayment, db.session, category='Admin'))
admin.add_view(PayoutRequestModelView(PayoutRequest, db.session, category='Admin'))
admin.add_view(FiatDbTransactionModelView(FiatDbTransaction, db.session, category='Admin'))
admin.add_view(WithdrawalConfirmationView(WithdrawalConfirmation, db.session, category='Admin'))
admin.add_view(RestrictedModelView(KycRequest, db.session, category='Admin'))
admin.add_view(RestrictedModelView(AplyId, db.session, category='Admin'))
admin.add_view(ApiKeyModelView(ApiKey, db.session, category='User'))
if app.config["USE_REFERRALS"]:
    admin.add_view(RestrictedModelView(Referral, db.session, category='Admin', name='Referrals'))
    admin.add_view(BaseOnlyUserOwnedModelView(Referral, db.session, category='User', name='Referrals', endpoint='UserReferrals'))

# define a context processor for merging flask-admin's template context into the
# flask-security views.
@security.context_processor
def security_context_processor():
    return dict(
        admin_base_template=admin.base_template,
        admin_view=admin.index_view,
        h=admin_helpers,
        get_url=url_for
    )
