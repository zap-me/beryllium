from __future__ import annotations
from typing import List, TYPE_CHECKING
from datetime import datetime, timedelta
import logging
from typing_extensions import reveal_type

from flask import url_for
from flask_security.core import UserMixin, RoleMixin
from marshmallow import Schema, fields
from sqlalchemy import and_, Column, Integer, String, DateTime, Boolean, BigInteger, Float, ForeignKey, Table
from sqlalchemy.orm import relationship, backref, RelationshipProperty
from sqlalchemy.orm.session import Session

from app_core import db
from utils import generate_key
import assets

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.ext.declarative import declarative_base
    from flask_sqlalchemy.model import Model
    BaseModel = declarative_base(Model)
else:
    BaseModel = db.Model

#
# Define beryllium models
#

class WithdrawStatusMixin():
    STATUS_CREATED = 'created'
    STATUS_AUTHORIZED = 'authorized'
    STATUS_WITHDRAW = 'withdraw'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'


class FromTokenMixin():
    token: str | Column[str]

    @classmethod
    def from_token(cls, session: Session, token: str):
        return session.query(cls).filter(cls.token == token).first()

class FromUserMixin():
    id: Column[int]
    user_id: Column[int]

    @classmethod
    def from_user(cls, session: Session, user: User, offset: int, limit: int):
        return session.query(cls).filter(cls.user_id == user.id).order_by(cls.id.desc()).offset(offset).limit(limit)

    @classmethod
    def total_for_user(cls, session: Session, user: User):
        return session.query(cls).filter(cls.user_id == user.id).count()

class OfAssetMixin():
    id: Column[int]
    asset: Column[str]
    l2_network: Column[str]
    user_id: Column[int]

    @classmethod
    def of_asset(cls, session: Session, user: User, asset: str, l2_network: str | None, offset: int, limit: int):
        return session.query(cls).filter(and_(cls.user_id == user.id, and_(cls.asset == asset, cls.l2_network == l2_network))).order_by(cls.id.desc()).offset(offset).limit(limit)

    @classmethod
    def total_of_asset(cls, session: Session, user: User, asset: str, l2_network: str | None):
        return session.query(cls).filter(and_(cls.user_id == user.id, and_(cls.asset == asset, cls.l2_network == l2_network))).count()

roles_users = Table(
    'roles_users',
    BaseModel.metadata,
    Column('user_id', Integer(), ForeignKey('user.id')),
    Column('role_id', Integer(), ForeignKey('role.id'))
)

class Role(BaseModel, RoleMixin):
    ROLE_ADMIN = 'admin'
    ROLE_FINANCE = 'finance'
    ROLE_REFERRAL_CLAIMER = 'referral_claimer'

    id = Column(Integer(), primary_key=True)
    name = Column(String(80), unique=True)
    description = Column(String(255))

    @classmethod
    def from_name(cls, session, name) -> Role | None:
        return session.query(cls).filter(cls.name == name).first()

    def __str__(self):
        return f'{self.name}'

class User(BaseModel, UserMixin):
    id = Column(Integer, primary_key=True)
    token = Column(String(255), unique=True, nullable=False)
    first_name = Column(String(255))
    last_name = Column(String(255))
    email = Column(String(255), unique=True, nullable=False)
    password = Column(String(255))
    mobile_number = Column(String(255))
    address = Column(String(255))
    last_login_at = Column(DateTime())
    current_login_at = Column(DateTime())
    last_login_ip = Column(String(100))
    current_login_ip = Column(String(100))
    login_count = Column(Integer)
    active = Column(Boolean())
    fs_uniquifier = Column(String(255), unique=True, nullable=False)
    confirmed_at = Column(DateTime())
    tf_totp_secret: str | None | Column[str] = Column(String(255))
    tf_primary_method: str | None | Column[str] = Column(String(255))
    tf_phone_number = Column(String(255))
    roles: RelationshipProperty[list[Role]] = relationship('Role', secondary=roles_users, backref=backref('users', lazy='dynamic'))
    photo = Column(String())
    photo_type = Column(String(255))

    dasset_subaccount = relationship('DassetSubaccount', uselist=False, back_populates='user')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.token = generate_key()

    def kyc_validated(self):
        if self.kyc_requests:
            for req in self.kyc_requests:
                if req.validated():
                    return True
        return False

    def kyc_url(self):
        if self.kyc_requests:
            for req in self.kyc_requests:
                return req.url()
        return None

    @classmethod
    def from_email(cls, session, email) -> User | None:
        return session.query(cls).filter(cls.email == email).first()

    def __str__(self):
        return f'{self.email}'

class UserCreateRequest(BaseModel, FromTokenMixin):

    MINUTES_EXPIRY = 30

    id = Column(Integer, primary_key=True)
    token = Column(String(255), unique=True, nullable=False)
    first_name = Column(String(255))
    last_name = Column(String(255))
    email = Column(String(255))
    mobile_number = Column(String(255))
    address = Column(String(255))
    photo = Column(String())
    photo_type = Column(String(255))
    password = Column(String(255))
    expiry = Column(DateTime())

    def __init__(self, first_name, last_name, email, mobile_number, address, photo, photo_type, password):
        self.token = generate_key()
        self.first_name = first_name
        self.last_name = last_name
        self.email = email
        self.mobile_number = mobile_number
        self.address = address
        self.photo = photo
        self.photo_type = photo_type
        self.password = password
        self.expiry = datetime.now() + timedelta(minutes=self.MINUTES_EXPIRY)

    @classmethod
    def from_email(cls, session, email) -> 'UserCreateRequest' | None:
        return session.query(cls).filter(cls.email == email).first()

    def __str__(self):
        return self.email

class UserUpdateEmailRequest(BaseModel, FromTokenMixin):

    MINUTES_EXPIRY = 30

    id = Column(Integer, primary_key=True)
    token = Column(String(255), unique=True, nullable=False)
    email = Column(String(255))
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    user: RelationshipProperty[User] = relationship('User', backref=backref('update_email_requests', lazy='dynamic'))
    expiry = Column(DateTime())

    def __init__(self, user, email):
        self.token = generate_key()
        self.user = user
        self.email = email
        self.expiry = datetime.now() + timedelta(minutes=self.MINUTES_EXPIRY)

    @classmethod
    def from_email(cls, session, email) -> 'UserUpdateEmailRequest' | None:
        return session.query(cls).filter(cls.email == email).first()

    def __str__(self):
        return self.email

permissions_api_keys = Table(
    'permissions_api_keys',
    BaseModel.metadata,
    Column('api_key_id', Integer(), ForeignKey('api_key.id')),
    Column('permission_id', Integer(), ForeignKey('permission.id'))
)

class Permission(BaseModel):
    PERMISSION_RECIEVE = 'receive'
    PERMISSION_BALANCE = 'balance'
    PERMISSION_HISTORY = 'history'
    PERMISSION_TRANSFER = 'transfer'
    PERMISSION_ISSUE = 'issue'
    PERMS_ALL = [PERMISSION_BALANCE, PERMISSION_HISTORY, PERMISSION_ISSUE, PERMISSION_RECIEVE, PERMISSION_TRANSFER]

    id = Column(Integer(), primary_key=True)
    name = Column(String(80), unique=True)
    description = Column(String(255))

    @classmethod
    def from_name(cls, session, name) -> Permission | None:
        return session.query(cls).filter(cls.name == name).first()

    def __str__(self):
        return f'{self.name}'

class ApiKey(BaseModel, FromTokenMixin):
    MINUTES_EXPIRY = 30

    id = Column(Integer, primary_key=True)
    token = Column(String(255), unique=True, nullable=False)
    secret = Column(String(255), nullable=False)
    nonce = Column(BigInteger, nullable=False)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    user: RelationshipProperty[User] = relationship('User', backref=backref('api_keys', lazy='dynamic'))
    device_name = Column(String(255))
    expiry = Column(DateTime())
    permissions: RelationshipProperty[list[Permission]] = relationship('Permission', secondary=permissions_api_keys, backref=backref('api_keys', lazy='dynamic'))

    def __init__(self, user, device_name):
        self.user_id = user.id
        self.token = generate_key()
        self.secret = generate_key(20)
        self.nonce = 0
        self.device_name = device_name
        self.expiry = datetime.now() + timedelta(minutes=self.MINUTES_EXPIRY)

    def has_permission(self, permission_name):
        perm = Permission.from_name(db.session, permission_name)
        if perm:
            return perm in self.permissions
        return False

class ApiKeyRequest(BaseModel, FromTokenMixin):
    MINUTES_EXPIRY = 30

    id = Column(Integer, primary_key=True)
    token = Column(String(255), unique=True, nullable=False)
    secret = Column(String(255), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    user: RelationshipProperty[User] = relationship('User', backref=backref('api_key_requests', lazy='dynamic'))
    device_name = Column(String(255))
    expiry = Column(DateTime())
    created_api_key_id = Column(Integer, ForeignKey('api_key.id'))
    created_api_key: RelationshipProperty[ApiKey | None] = relationship('ApiKey')

    def __init__(self, user, device_name):
        self.token = generate_key()
        self.secret = generate_key(20)
        self.user = user
        self.device_name = device_name
        self.expiry = datetime.now() + timedelta(minutes=self.MINUTES_EXPIRY)

    def __str__(self):
        return self.token

class Topic(BaseModel):
    __tablename__ = 'topics'
    id = Column(Integer, primary_key=True)
    topic = Column(String, nullable=False, unique=True)

    def __init__(self, topic):
        self.topic = topic

    @classmethod
    def topic_list(cls, session) -> list[str]:
        return [row.topic for row in session.query(cls.topic)]

    @classmethod
    def from_name(cls, session, name) -> 'Topic' | None:
        return session.query(cls).filter(cls.topic == name).first()

    def __repr__(self):
        return f'<Topic {self.topic}>'

class PushNotificationLocation(BaseModel, FromTokenMixin):
    id = Column(Integer, primary_key=True)
    fcm_registration_token = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    date = Column(DateTime(), nullable=False)

    def __init__(self, registration_token, latitude, longitude):
        self.fcm_registration_token = registration_token
        self.update(latitude, longitude)

    def update(self, latitude, longitude):
        self.latitude = latitude
        self.longitude = longitude
        self.date = datetime.now()

    @classmethod
    def tokens_at_location(cls, session, latitude, max_lat_delta, longitude, max_long_delta, max_age_minutes) -> list['PushNotificationLocation']:
        since = datetime.now() - timedelta(minutes=max_age_minutes)
        return session.query(cls).filter(and_(cls.date >= since, and_(and_(cls.latitude <= latitude + max_lat_delta, cls.latitude >= latitude - max_lat_delta), and_(cls.longitude <= longitude + max_long_delta, cls.longitude >= longitude - max_long_delta)))).all()

class Setting(BaseModel):
    __tablename__ = 'settings'
    id = Column(Integer, primary_key=True)
    key = Column(String, nullable=False, unique=True)
    value = Column(String, unique=False)

    def __init__(self, key, value):
        self.key = key
        self.value = value

    def __repr__(self):
        return f'<Setting {self.key} {self.value}>'

class ReferralSchema(Schema):
    token = fields.String()
    date = fields.Date()
    recipient = fields.String()
    reward_sender_type = fields.String()
    reward_sender = fields.Integer()
    reward_recipient_type = fields.String()
    reward_recipient = fields.Integer()
    recipient_min_spend = fields.Integer()
    status = fields.String()

class Referral(BaseModel, FromTokenMixin, FromUserMixin):
    STATUS_CREATED = 'created'
    STATUS_CLAIMED = 'claimed'
    STATUS_DELETED = 'deleted'

    REWARD_TYPE_PERCENT = 'percent'
    REWARD_TYPE_FIXED = 'fixed'
    REWARD_TYPES_ALL = [REWARD_TYPE_PERCENT, REWARD_TYPE_FIXED]

    id = Column(Integer, primary_key=True)

    token = Column(String(255), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    user: RelationshipProperty[User] = relationship('User', backref=backref('referrals', lazy='dynamic'))
    date = Column(DateTime(), nullable=False)
    recipient = Column(String, nullable=False)
    reward_sender_type = Column(String(255), nullable=False)
    reward_sender = Column(Integer, nullable=False)
    reward_recipient_type = Column(String(255), nullable=False)
    reward_recipient = Column(Integer, nullable=False)
    recipient_min_spend = Column(Integer, nullable=False)
    status = Column(String, nullable=False)

    def __init__(self, user, recipient, reward_sender_type, reward_sender, reward_recipient_type, reward_recipient, recipient_min_spend):
        assert reward_sender_type == self.REWARD_TYPE_FIXED
        assert reward_recipient_type in self.REWARD_TYPES_ALL
        self.token = generate_key()
        self.user = user
        self.date = datetime.now()
        self.recipient = recipient
        self.reward_sender_type = reward_sender_type
        self.reward_sender = reward_sender
        self.reward_recipient_type = reward_recipient_type
        self.reward_recipient = reward_recipient
        self.recipient_min_spend = recipient_min_spend
        self.status = self.STATUS_CREATED

    def to_json(self):
        ref_schema = ReferralSchema()
        return ref_schema.dump(self)

    @classmethod
    def from_token_user(cls, session, token, user) -> Referral | None:
        return session.query(cls).filter(and_(cls.token == token, cls.user_id == user.id)).first()

class BrokerOrderSchema(Schema):
    token = fields.String()
    date = fields.DateTime()
    expiry = fields.DateTime()
    market = fields.String()
    side = fields.String()
    base_asset = fields.String()
    base_amount = fields.Integer()
    base_amount_dec = fields.Method('get_base_amount_dec')
    quote_asset = fields.String()
    quote_amount = fields.Integer()
    quote_amount_dec = fields.Method('get_quote_amount_dec')
    status = fields.String()

    def get_base_amount_dec(self, obj):
        return str(assets.asset_int_to_dec(obj.base_asset, obj.base_amount))

    def get_quote_amount_dec(self, obj):
        return str(assets.asset_int_to_dec(obj.quote_asset, obj.quote_amount))

class BrokerOrder(BaseModel, FromUserMixin, FromTokenMixin):
    STATUS_CREATED = 'created'
    STATUS_READY = 'ready'
    STATUS_EXCHANGE = 'exchanging'
    STATUS_COMPLETED = 'completed'
    STATUS_EXPIRED = 'expired'
    STATUS_FAILED = 'failed'
    STATUS_CANCELLED = 'cancelled'

    MINUTES_EXPIRY = 15

    id = Column(Integer, primary_key=True)

    token = Column(String(255), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    user: RelationshipProperty[User] = relationship('User', backref=backref('orders', lazy='dynamic'))
    date = Column(DateTime(), nullable=False)
    expiry = Column(DateTime(), nullable=False)
    market = Column(String, nullable=False)
    side = Column(String, nullable=False)
    base_asset = Column(String, nullable=False)
    quote_asset = Column(String, nullable=False)
    base_amount = Column(BigInteger, nullable=False)
    quote_amount = Column(BigInteger, nullable=False)
    exchange_order_id = Column(Integer, ForeignKey('exchange_order.id'))
    exchange_order: RelationshipProperty['ExchangeOrder' | None] = relationship('ExchangeOrder')

    status = Column(String, nullable=False)

    def __init__(self, user, market, side, base_asset, quote_asset, base_amount, quote_amount):
        self.token = generate_key()
        self.user = user
        self.date = datetime.now()
        self.expiry = datetime.now() + timedelta(minutes=self.MINUTES_EXPIRY)
        self.market = market
        self.side = side
        self.base_asset = base_asset
        self.quote_asset = quote_asset
        self.base_amount = base_amount
        self.quote_amount = quote_amount
        self.status = self.STATUS_CREATED

    def to_json(self):
        ref_schema = BrokerOrderSchema()
        return ref_schema.dump(self)

    @classmethod
    def all_active(cls, session) -> list[BrokerOrder]:
        return session.query(cls).filter(and_(cls.status != cls.STATUS_COMPLETED, and_(cls.status != cls.STATUS_EXPIRED, and_(cls.status != cls.STATUS_FAILED, cls.status != cls.STATUS_CANCELLED)))).all()

class DassetSubaccount(BaseModel):
    id = Column(Integer, primary_key=True)
    date = Column(DateTime(), nullable=False, unique=False)
    subaccount_id = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    user: RelationshipProperty[User] = relationship('User', uselist=False, back_populates='dasset_subaccount')

    def __init__(self, user, subaccount_id):
        self.user = user
        self.date = datetime.now()
        self.subaccount_id = subaccount_id

    @classmethod
    def count(cls, session) -> int:
        return session.query(cls).count()

    @classmethod
    def from_subaccount_id(cls, session, subaccount_id) -> DassetSubaccount | None:
        return session.query(cls).filter(cls.subaccount_id == subaccount_id).first()

    def __repr__(self):
        return f'<DassetSubaccount {self.subaccount_id}>'

class ExchangeOrder(BaseModel):
    id = Column(Integer, primary_key=True)
    token = Column(String(255), unique=True, nullable=False)
    date = Column(DateTime(), nullable=False)
    exchange_reference = Column(String, nullable=False)

    def __init__(self, exchange_reference):
        self.token = generate_key()
        self.date = datetime.now()
        self.exchange_reference = exchange_reference

class CryptoWithdrawalSchema(Schema):
    token = fields.String()
    date = fields.DateTime()
    asset = fields.String()
    l2_network = fields.String()
    amount = fields.Integer()
    amount_dec = fields.Method('get_amount_dec')
    recipient = fields.String()
    txid = fields.String()
    status = fields.String()

    def get_amount_dec(self, obj):
        return str(assets.asset_int_to_dec(obj.asset, obj.amount))

class CryptoWithdrawal(BaseModel, FromUserMixin, FromTokenMixin, OfAssetMixin, WithdrawStatusMixin):
    id = Column(Integer, primary_key=True)
    token = Column(String(255), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    user: RelationshipProperty[User] = relationship('User', backref=backref('crypto_withdrawals', lazy='dynamic'))
    date = Column(DateTime(), nullable=False)
    asset = Column(String, nullable=False)
    l2_network = Column(String)
    amount = Column(BigInteger, nullable=False)
    recipient = Column(String, nullable=False)
    exchange_reference: str | None | Column[str] = Column(String)
    wallet_reference = Column(String)
    txid = Column(String)
    status = Column(String, nullable=False)

    def __init__(self, user, asset, l2_network, amount, recipient):
        self.token = generate_key()
        self.user = user
        self.date = datetime.now()
        self.asset = asset
        self.l2_network = l2_network
        self.amount = amount
        self.recipient = recipient
        self.exchange_reference = None
        self.wallet_reference = None
        self.status = self.STATUS_CREATED

    def to_json(self):
        ref_schema = CryptoWithdrawalSchema()
        return ref_schema.dump(self)

    @classmethod
    def all_active(cls, session) -> list[CryptoWithdrawal]:
        return session.query(cls).filter(and_(cls.status != cls.STATUS_COMPLETED, cls.status != cls.STATUS_CANCELLED)).all()

    @classmethod
    def where_active_with_recipient(cls, session, recipient: str) -> list[CryptoWithdrawal]:
        return session.query(cls).filter(and_(and_(cls.status != cls.STATUS_COMPLETED, cls.status != cls.STATUS_CANCELLED), cls.recipient == recipient)).all()

class CryptoDepositSchema(Schema):
    token = fields.String()
    date = fields.DateTime()
    asset = fields.String()
    l2_network = fields.String()
    amount = fields.Integer()
    amount_dec = fields.Method('get_amount_dec')
    recipient = fields.Method('get_recipient')
    txid = fields.String()
    confirmed = fields.Boolean()

    def get_amount_dec(self, obj):
        return str(assets.asset_int_to_dec(obj.asset, obj.amount))

    def get_recipient(self, obj):
        if obj.crypto_address:
            return obj.crypto_address.address
        if obj.wallet_reference:
            return obj.wallet_reference
        return None

class CryptoDeposit(BaseModel, FromUserMixin, OfAssetMixin):
    id = Column(Integer, primary_key=True)
    token = Column(String(255), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    user: RelationshipProperty[User] = relationship('User', backref=backref('crypto_deposits', lazy='dynamic'))
    crypto_address_id = Column(Integer, ForeignKey('crypto_address.id'))
    crypto_address: RelationshipProperty['CryptoAddress' | None] = relationship('CryptoAddress', backref=backref('crypto_deposits', lazy='dynamic'))
    date = Column(DateTime(), nullable=False)
    asset = Column(String, nullable=False)
    l2_network = Column(String)
    amount = Column(BigInteger, nullable=False)
    exchange_reference = Column(String)
    wallet_reference = Column(String)
    txid = Column(String(255), unique=True)
    confirmed = Column(Boolean, nullable=False)
    expired = Column(Boolean, nullable=False)

    def __init__(self, user, asset, l2_network, amount, exchange_reference, wallet_reference, txid, confirmed, expired):
        self.token = generate_key()
        self.user = user
        self.date = datetime.now()
        self.asset = asset
        self.l2_network = l2_network
        self.amount = amount
        self.exchange_reference = exchange_reference
        self.wallet_reference = wallet_reference
        self.txid = txid
        self.confirmed = confirmed
        self.expired = expired

    def to_json(self):
        ref_schema = CryptoDepositSchema()
        return ref_schema.dump(self)

    @classmethod
    def from_txid(cls, session, txid) -> CryptoDeposit | None:
        return session.query(cls).filter(cls.txid == txid).first()

    @classmethod
    def of_wallet(cls, session, confirmed, expired) -> list[CryptoDeposit]:
        return session.query(cls).filter(cls.wallet_reference is not None).filter(cls.confirmed == confirmed).filter(cls.expired == expired).all()

    @classmethod
    def from_wallet_reference(cls, session, wallet_reference) -> CryptoDeposit | None:
        return session.query(cls).filter(cls.wallet_reference == wallet_reference).first()

class WindcavePaymentRequestSchema(Schema):
    date = fields.DateTime()
    token = fields.String()
    asset = fields.String()
    amount = fields.Integer()
    windcave_session_id = fields.String()
    windcave_status = fields.String()
    windcave_authorised = fields.Boolean()
    windcave_allow_retry = fields.Boolean()
    status = fields.String()

class WindcavePaymentRequest(BaseModel, FromTokenMixin):
    STATUS_CREATED = 'created'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'

    id = Column(Integer, primary_key=True)
    date = Column(DateTime(), nullable=False, unique=False)
    token = Column(String, nullable=False, unique=True)
    asset = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)
    windcave_session_id = Column(String)
    windcave_status = Column(String)
    windcave_authorised = Column(Boolean)
    windcave_allow_retry = Column(Boolean)
    status = Column(String)

    def __init__(self, token, asset, amount, windcave_session_id, windcave_status):
        self.date = datetime.now()
        self.token = token
        self.asset = asset
        self.amount = amount
        self.windcave_session_id = windcave_session_id
        self.windcave_status = windcave_status
        self.status = self.STATUS_CREATED

    @classmethod
    def count(cls, session) -> int:
        return session.query(cls).count()

    def __repr__(self):
        return f'<WindcavePaymentRequest {self.token}>'

    def to_json(self):
        schema = WindcavePaymentRequestSchema()
        return schema.dump(self)

class CrownPayment(BaseModel, FromTokenMixin):
    STATUS_CREATED = 'created'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'

    id = Column(Integer, primary_key=True)
    date = Column(DateTime(), nullable=False, unique=False)
    token = Column(String, nullable=False, unique=True)
    asset = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)
    crown_txn_id = Column(String, nullable=False, unique=True)
    crown_status = Column(String)
    status = Column(String)

    def __init__(self, token, asset, amount, crown_txn_id, crown_status):
        self.date = datetime.now()
        self.token = token
        self.asset = asset
        self.amount = amount
        self.crown_txn_id = crown_txn_id
        self.crown_status = crown_status
        self.status = self.STATUS_CREATED

    @classmethod
    def count(cls, session: Session):
        return session.query(cls).count()

    @classmethod
    def from_crown_txn_id(cls, session: Session, crown_txn_id: str):
        return session.query(cls).filter(cls.crown_txn_id == crown_txn_id).first()

    def __repr__(self):
        return f'<CrownPayment {self.token}>'

class FiatDepositCode(BaseModel, FromTokenMixin):
    id = Column(Integer, primary_key=True)
    date = Column(DateTime(), nullable=False, unique=False)
    token = Column(String, nullable=False, unique=True)
    autobuy_asset = Column(String)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    user: RelationshipProperty[User] = relationship('User', backref=backref('fiat_deposit_codes', lazy='dynamic'))

    def __init__(self, user: User, autobuy_asset: str | None):
        self.date = datetime.now()
        self.user = user
        self.token = generate_key(8, True)
        self.autobuy_asset = autobuy_asset

class PayoutGroupRequest(BaseModel):
    payout_group_id = Column(Integer, ForeignKey('payout_group.id'), primary_key=True)
    payout_request_id = Column(Integer, ForeignKey('payout_request.id'), primary_key=True)

    def __init__(self, group, req):
        self.payout_group_id = group.id
        self.payout_request_id = req.id

class PayoutRequestSchema(Schema):
    date = fields.DateTime()
    token = fields.String()
    asset = fields.String()
    amount = fields.Integer()
    sender = fields.String()
    sender_account = fields.String()
    sender_reference = fields.String()
    sender_code = fields.String()
    receiver = fields.String()
    receiver_account = fields.String()
    receiver_reference = fields.String()
    receiver_code = fields.String()
    receiver_particulars = fields.String()
    email = fields.String()
    email_sent = fields.Boolean()
    status = fields.String()

class PayoutRequest(BaseModel, FromTokenMixin):
    STATUS_CREATED = 'created'
    STATUS_COMPLETED = 'completed'
    STATUS_SUSPENDED = 'suspended'

    id = Column(Integer, primary_key=True)
    date = Column(DateTime(), nullable=False, unique=False)
    token = Column(String, nullable=False, unique=True)
    asset = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)
    reference = Column(String, nullable=False)
    code = Column(String, nullable=False)
    email = Column(String, nullable=False)
    email_sent = Column(Boolean)
    status = Column(String)
    groups: RelationshipProperty[list['PayoutGroup']] = relationship('PayoutGroup', secondary='payout_group_request', back_populates='requests')
    address_book_id = Column(Integer, ForeignKey('address_book.id'))
    address_book: RelationshipProperty['AddressBook' | None] = relationship("AddressBook")

    def __init__(self, asset, amount, reference, code, email, email_sent, address_book):
        self.date = datetime.now()
        self.token = generate_key()
        self.asset = asset
        self.amount = amount
        self.reference = reference
        self.code = code
        self.email = email
        self.email_sent = email_sent
        self.status = self.STATUS_CREATED
        self.address_book = address_book

    @classmethod
    def count(cls, session) -> int:
        return session.query(cls).count()

    @classmethod
    def where_status_created(cls, session) -> list[PayoutRequest]:
        return session.query(cls).filter(cls.status == cls.STATUS_CREATED).all()

    @classmethod
    def where_status_suspended(cls, session) -> list[PayoutRequest]:
        return session.query(cls).filter(cls.status == cls.STATUS_SUSPENDED).all()

    @classmethod
    def not_completed(cls, session) -> list[PayoutRequest]:
        return session.query(cls).filter(cls.status != cls.STATUS_COMPLETED).all()

    def __repr__(self):
        return f'<PayoutRequest {self.token}>'

    def to_json(self):
        schema = PayoutRequestSchema()
        return schema.dump(self)

class PayoutGroup(BaseModel, FromTokenMixin):
    id = Column(Integer, primary_key=True)
    token = Column(String, nullable=False, unique=True)
    expired = Column(Boolean, nullable=False)
    requests: RelationshipProperty[list[PayoutRequest]] = relationship('PayoutRequest', secondary='payout_group_request', back_populates='groups')

    def __init__(self):
        self.token = generate_key()
        self.expired = False

    def total_payout(self):
        asset = None
        total = 0
        n = 0
        for req in self.requests:
            if not asset:
                asset = req.asset
            assert asset == req.asset
            if req.status != req.STATUS_CREATED:
                continue
            total += req.amount
            n += 1
        return asset, total, n

    @classmethod
    def expire_all_but(cls, session, group):
        session.query(cls).filter(cls.id != group.id).update({"expired": True})

class AplyId(BaseModel):
    id = Column(Integer, primary_key=True)
    transaction_id = Column(String, nullable=False, unique=True)
    kyc_request_id = Column(Integer, ForeignKey('kyc_request.id'))
    kyc_request: RelationshipProperty['KycRequest' | None] = relationship("KycRequest", back_populates="aplyid")

    def __init__(self, kyc_request, transaction_id):
        self.kyc_request = kyc_request
        self.transaction_id = transaction_id

class KycRequestSchema(Schema):
    date = fields.DateTime()
    token = fields.String()
    status = fields.String()

class KycRequest(BaseModel, FromTokenMixin):
    STATUS_CREATED = 'created'
    STATUS_COMPLETED = 'completed'

    id = Column(Integer, primary_key=True)
    date = Column(DateTime(), nullable=False, unique=False)
    token = Column(String, nullable=False, unique=True)
    status = Column(String)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    user: RelationshipProperty[User] = relationship('User', backref=backref('kyc_requests', lazy='dynamic'))
    aplyid: RelationshipProperty[AplyId | None] = relationship("AplyId", uselist=False, back_populates="kyc_request")

    def __init__(self, user):
        self.user = user
        self.date = datetime.now()
        self.token = generate_key()
        self.status = self.STATUS_CREATED

    def validated(self):
        return self.status == self.STATUS_COMPLETED

    def url(self):
        return url_for('kyc.request_start', token=self.token, _external=True)

    @classmethod
    def count(cls, session) -> int:
        return session.query(cls).count()

    @classmethod
    def from_user(cls, session, user) -> KycRequest | None:
        return session.query(cls).filter(cls.user_id == user.id).first()

    def __repr__(self):
        return f'<KycRequest {self.token}>'

    def to_json(self):
        schema = KycRequestSchema()
        return schema.dump(self)

class AddressBookSchema(Schema):
    date = fields.DateTime()
    token = fields.String()
    asset = fields.String()
    recipient = fields.String()
    description = fields.String()
    account_name = fields.String()
    account_addr_01 = fields.String()
    account_addr_02 = fields.String()
    account_addr_country = fields.String()

class AddressBook(BaseModel, FromTokenMixin):
    id = Column(Integer, primary_key=True)
    date = Column(DateTime(), nullable=False, unique=False)
    token = Column(String, nullable=False, unique=True)
    asset = Column(String, nullable=False)
    recipient = Column(String, nullable=False)
    description = Column(String)
    account_name = Column(String)
    account_addr_01 = Column(String)
    account_addr_02 = Column(String)
    account_addr_country = Column(String)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    user: RelationshipProperty[User] = relationship('User', backref=backref('address_book_entries', lazy='dynamic'))

    def __init__(self, user, asset, recipient, description, account_name, account_addr_01, account_addr_02, account_addr_country):
        self.user = user
        self.date = datetime.now()
        self.token = generate_key()
        self.asset = asset
        self.recipient = recipient
        self.description = description
        self.account_name = account_name
        self.account_addr_01 = account_addr_01
        self.account_addr_02 = account_addr_02
        self.account_addr_country = account_addr_country

    @classmethod
    def count(cls, session) -> int:
        return session.query(cls).count()

    @classmethod
    def from_recipient(cls, session, user, asset, recipient) -> AddressBook | None:
        return session.query(cls).filter(and_(cls.user_id == user.id, and_(cls.asset == asset, cls.recipient == recipient))).first()

    @classmethod
    def of_asset(cls, session, user, asset) -> list[AddressBook]:
        return session.query(cls).filter(and_(cls.user_id == user.id, cls.asset == asset)).all()

    def to_json(self):
        schema = AddressBookSchema()
        return schema.dump(self)

class FiatDbTransactionSchema(Schema):
    user = fields.String()
    token = fields.String()
    date = fields.String()
    timestamp = fields.Integer()
    action = fields.String()
    asset = fields.String()
    amount = fields.Integer()
    attachment = fields.String()

class FiatDbTransaction(BaseModel, FromTokenMixin):
    ACTION_CREDIT = 'credit'
    ACTION_DEBIT = 'debit'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    user: RelationshipProperty[User] = relationship('User', backref=backref('fiatdb_transactions', lazy='dynamic'))
    token = Column(String(255), unique=True, nullable=False)
    date = Column(DateTime())
    action = Column(String(255), nullable=False)
    asset = Column(String(255), nullable=False)
    amount = Column(BigInteger())
    attachment = Column(String(255))

    def __init__(self, user, action, asset, amount, attachment):
        self.user = user
        self.token = generate_key()
        self.date = datetime.now()
        self.action = action
        self.asset = asset
        self.amount = amount
        self.attachment = attachment

    @classmethod
    def all(cls, session) -> list[FiatDbTransaction]:
        return session.query(cls).all()

    def __str__(self):
        return self.token

    def to_json(self):
        tx_schema = FiatDbTransactionSchema()
        return tx_schema.dump(self)

class FiatDepositSchema(Schema):
    token = fields.String()
    date = fields.DateTime()
    expiry = fields.DateTime()
    asset = fields.String()
    amount = fields.Integer()
    amount_dec = fields.Method('get_amount_dec')
    status = fields.String()
    payment_url = fields.Method('get_payment_url')

    def get_amount_dec(self, obj):
        return str(assets.asset_int_to_dec(obj.asset, obj.amount))

    def get_payment_url(self, obj):
        payment_url = None
        if obj.windcave_payment_request:
            payment_url = url_for('payments.payment_interstitial', token=obj.windcave_payment_request.token, _external=True)
        return payment_url

class FiatDeposit(BaseModel, FromUserMixin, FromTokenMixin):
    STATUS_CREATED = 'created'
    STATUS_COMPLETED = 'completed'
    STATUS_EXPIRED = 'expired'
    STATUS_CANCELLED = 'cancelled'

    MINUTES_EXPIRY = 15

    id = Column(Integer, primary_key=True)

    token = Column(String(255), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    user: RelationshipProperty[User] = relationship('User', backref=backref('fiat_deposits', lazy='dynamic'))
    date = Column(DateTime(), nullable=False)
    expiry = Column(DateTime(), nullable=False)
    asset = Column(String, nullable=False)
    amount = Column(BigInteger, nullable=False)
    windcave_payment_request_id = Column(Integer, ForeignKey('windcave_payment_request.id'))
    windcave_payment_request: RelationshipProperty[WindcavePaymentRequest | None] = relationship('WindcavePaymentRequest', backref=backref('fiat_deposit', uselist=False))
    crown_payment_id = Column(Integer, ForeignKey('crown_payment.id'))
    crown_payment: RelationshipProperty[CrownPayment | None] = relationship('CrownPayment', backref=backref('fiat_deposit', uselist=False))

    status = Column(String, nullable=False)

    def __init__(self, user, asset, amount):
        self.token = generate_key()
        self.user = user
        self.date = datetime.now()
        self.expiry = datetime.now() + timedelta(minutes=self.MINUTES_EXPIRY)
        self.asset = asset
        self.amount = amount
        self.status = self.STATUS_CREATED

    def to_json(self):
        ref_schema = FiatDepositSchema()
        return ref_schema.dump(self)

    @classmethod
    def all_active(cls, session) -> list[FiatDeposit]:
        return session.query(cls).filter(and_(cls.status != cls.STATUS_COMPLETED, and_(cls.status != cls.STATUS_EXPIRED, cls.status != cls.STATUS_CANCELLED))).all()

class FiatWithdrawalSchema(Schema):
    token = fields.String()
    date = fields.DateTime()
    asset = fields.String()
    amount = fields.Integer()
    amount_dec = fields.Method('get_amount_dec')
    recipient = fields.String()
    status = fields.String()

    def get_amount_dec(self, obj):
        return str(assets.asset_int_to_dec(obj.asset, obj.amount))

class FiatWithdrawal(BaseModel, FromUserMixin, FromTokenMixin, WithdrawStatusMixin):
    id = Column(Integer, primary_key=True)
    token = Column(String(255), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    user: RelationshipProperty[User] = relationship('User', backref=backref('fiat_withdrawals', lazy='dynamic'))
    date = Column(DateTime(), nullable=False)
    asset = Column(String, nullable=False)
    amount = Column(BigInteger, nullable=False)
    recipient = Column(String, nullable=False)
    payout_request_id = Column(Integer, ForeignKey('payout_request.id'))
    payout_request: RelationshipProperty[PayoutRequest | None] = relationship('PayoutRequest', backref=backref('fiat_withdrawal', uselist=False))

    status = Column(String, nullable=False)

    def __init__(self, user, asset, amount, recipient):
        self.token = generate_key()
        self.user = user
        self.date = datetime.now()
        self.asset = asset
        self.amount = amount
        self.recipient = recipient
        self.status = self.STATUS_CREATED

    def to_json(self):
        ref_schema = FiatWithdrawalSchema()
        return ref_schema.dump(self)

    @classmethod
    def all_active(cls, session) -> list[FiatWithdrawal]:
        return session.query(cls).filter(and_(cls.status != cls.STATUS_COMPLETED, cls.status != cls.STATUS_CANCELLED)).all()

class CryptoAddress(BaseModel, FromUserMixin):

    id = Column(Integer, primary_key=True)

    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    user: RelationshipProperty[User] = relationship('User', backref=backref('crypto_addresses', lazy='dynamic'))
    asset = Column(String(255), nullable=False)
    address = Column(String(255), unique=True, nullable=False)
    date = Column(DateTime(), nullable=False)
    # we make these integer timestamps so we dont have any issues with any comparisons in DB
    viewed_at = Column(BigInteger(), nullable=False)
    checked_at = Column(BigInteger(), nullable=False)

    def __init__(self, user, asset, address):
        self.user = user
        self.asset = asset
        self.address = address
        self.date = datetime.now()
        self.viewed_at = 0
        self.checked_at = 0

    @classmethod
    def from_asset(cls, session, user, asset) -> CryptoAddress | None:
        return session.query(cls).filter(and_(cls.user_id == user.id, cls.asset == asset)).first()

    @classmethod
    def from_addr(cls, session, addr) -> CryptoAddress | None:
        return session.query(cls).filter(cls.address == addr).first()

    @classmethod
    def need_to_be_checked(cls, session) -> list[CryptoAddress]:
        now = datetime.timestamp(datetime.now())
        return session.query(cls).filter(now - cls.checked_at > (cls.checked_at - cls.viewed_at) * 2).all()

class WithdrawalConfirmation(BaseModel, FromTokenMixin):
    MINUTES_EXPIRY = 30

    id = Column(Integer, primary_key=True)
    token = Column(String(255), unique=True, nullable=False)
    secret = Column(String(255), unique=True, nullable=False)
    date = Column(DateTime(), nullable=False)
    expiry = Column(DateTime(), nullable=False)
    confirmed: bool | None | Column[bool] = Column(Boolean)
    user_id = Column(Integer, ForeignKey('user.id'))
    user: RelationshipProperty[User] = relationship('User')
    crypto_withdrawal_id = Column(Integer, ForeignKey('crypto_withdrawal.id'))
    crypto_withdrawal: RelationshipProperty[CryptoWithdrawal | None] = relationship('CryptoWithdrawal', backref=backref('withdrawal_confirmation', uselist=False))
    fiat_withdrawal_id = Column(Integer, ForeignKey('fiat_withdrawal.id'))
    fiat_withdrawal: RelationshipProperty[FiatWithdrawal | None] = relationship('FiatWithdrawal', backref=backref('withdrawal_confirmation', uselist=False))
    address_book_id = Column(Integer, ForeignKey('address_book.id'))
    address_book: RelationshipProperty[AddressBook | None] = relationship('AddressBook')

    def __init__(self, user: User, crypto_withdrawal: CryptoWithdrawal | None = None, fiat_withdrawal: FiatWithdrawal | None = None, address_book: AddressBook | None = None):
        assert crypto_withdrawal is not None or fiat_withdrawal is not None
        assert crypto_withdrawal is None or fiat_withdrawal is None
        if fiat_withdrawal:
            assert address_book
        self.token = generate_key()
        self.secret = generate_key(20)
        self.date = datetime.now()
        self.expiry = self.date + timedelta(minutes=self.MINUTES_EXPIRY)
        self.confirmed = None
        self.user = user
        if crypto_withdrawal:
            self.crypto_withdrawal = crypto_withdrawal
        if fiat_withdrawal:
            self.fiat_withdrawal = fiat_withdrawal
        if address_book:
            self.address_book = address_book

    def expired(self):
        return datetime.now() > self.expiry

    def withdrawal(self):
        if self.crypto_withdrawal:
            return self.crypto_withdrawal
        assert self.fiat_withdrawal
        return self.fiat_withdrawal

    def recipient(self):
        return self.withdrawal().recipient

    def asset(self):
        return self.withdrawal().asset

    def amount(self):
        return self.withdrawal().amount

    def status_is_created(self):
        return self.withdrawal().status == self.withdrawal().STATUS_CREATED

class BtcTxIndex(BaseModel):
    id = Column(Integer, primary_key=True)
    txid = Column(String(255), nullable=False)
    hex = Column(String(), nullable=False)
    blockheight = Column(Integer)
    blockhash = Column(String(255))

    def __init__(self, txid: str, hex: str, blockheight: int | None, blockhash: str | None):
        self.txid = txid
        self.hex = hex
        self.blockheight = blockheight
        self.blockhash = blockhash

    @classmethod
    def from_txid(cls, session, txid) -> BtcTxIndex | None:
        return session.query(cls).filter(cls.txid == txid).first()

    @classmethod
    def clear(cls, session):
        session.query(cls).delete()
