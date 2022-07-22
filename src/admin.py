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
from models import Role, User, ApiKey, Topic, PushNotificationLocation, Referral, BrokerOrder, ExchangeOrder, BalanceUpdate, CryptoAddress, KycRequest, AplyId, FiatDbTransaction, WindcavePaymentRequest, PayoutRequest, CrownPayment, WithdrawalConfirmation
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

def get_balanceupdate_types():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'balanceupdate_types'):
            query = BalanceUpdate.query.with_entities(BalanceUpdate.type).distinct()
            g.balanceupdate_types = [(balance_update.type, balance_update.type) for balance_update in query]
        for balance_update_type_a, balance_update_type_b in g.balanceupdate_types:
            yield balance_update_type_a, balance_update_type_b

def get_balanceupdate_statuses():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'balanceupdate_statuses'):
            query = BalanceUpdate.query.with_entities(BalanceUpdate.status).distinct()
            g.balanceupdate_statuses = [(balance_update.status, balance_update.status) for balance_update in query]
        for balance_update_status_a, balance_update_status_b in g.balanceupdate_statuses:
            yield balance_update_status_a, balance_update_status_b

def get_balanceupdate_assets():
    # prevent database access when app is not yet ready
    if has_app_context():
        if not hasattr(g, 'balanceupdate_assets'):
            query = BalanceUpdate.query.with_entities(BalanceUpdate.asset).distinct()
            g.balanceupdate_assets = [(balance_update.asset, balance_update.asset) for balance_update in query]
        for balance_update_asset_a, balance_update_asset_b in g.balanceupdate_assets:
            yield balance_update_asset_a, balance_update_asset_b

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

class FilterByBalanceUpdateTypeEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(BalanceUpdate.type == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_balanceupdate_types)

class FilterByBalanceUpdateStatusEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(BalanceUpdate.status == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_balanceupdate_statuses)

class FilterByBalanceUpdateAssetEqual(BaseSQLAFilter):
    def apply(self, query, value, alias=None):
        return query.filter(BalanceUpdate.asset == value)

    def operation(self):
        return 'equals'

    def get_options(self, view):
        # return a generator that is reloaded each time it is used
        return ReloadingIterator(get_balanceupdate_assets)

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

class BalanceUpdateModelView(RestrictedModelView):
    can_create = False
    can_delete = False
    can_edit = False

    column_filters = [DateBetweenFilter(BalanceUpdate.date, 'Search Date'),
                      FilterByBalanceUpdateTypeEqual(BalanceUpdate.type, 'Search Type'),
                      FilterByBalanceUpdateAssetEqual(BalanceUpdate.asset, 'Search Asset'),
                      FilterByBalanceUpdateStatusEqual(BalanceUpdate.status, 'Search Status')]

class PayoutRequestModelView(RestrictedModelView):
    can_create = False
    can_delete = False
    can_edit = False

    column_filters = [DateBetweenFilter(PayoutRequest.date, 'Search Date'),
                      FilterByPayoutRequestStatusEqual(PayoutRequest.status, 'Search Status'),
                      FilterByPayoutRequestAssetEqual(PayoutRequest.asset, 'Search Asset')]

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
    url='/admin/',
)

# Add model views
admin.add_view(UserModelView(User, db.session, category='Admin'))
admin.add_view(AdminUserModelView(User, db.session, category='Admin', endpoint='AdminUser'))
admin.add_view(RestrictedModelView(Role, db.session, category='Admin'))
admin.add_view(RestrictedModelView(Topic, db.session, category='Admin'))
admin.add_view(PushNotificationLocationModelView(PushNotificationLocation, db.session, category='Admin'))
admin.add_view(BrokerOrderModelView(BrokerOrder, db.session, category='Admin'))
admin.add_view(RestrictedModelView(ExchangeOrder, db.session, category='Admin'))
admin.add_view(BalanceUpdateModelView(BalanceUpdate, db.session, category='Admin'))
admin.add_view(RestrictedModelView(CryptoAddress, db.session, category='Admin'))
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
