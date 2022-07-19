import os
import decimal

from flask import Flask
import flask.json
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_mail_sendgrid import MailSendGrid
from flask_mail import Mail
from flask_socketio import SocketIO
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from flask_talisman import Talisman
from dotenv import load_dotenv

SERVER_VERSION = 10
CLIENT_VERSION_DEPLOYED = 8

MISSING_VITAL_SETTING = False

class MyJSONEncoder(flask.json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            # Convert decimal instances to strings.
            return str(o)
        return super().default(o)

def boolify(val):
    if isinstance(val, str):
        return val.lower() in ('true', 't', '1', 'yes', 'y')
    return bool(val)

def strdef(name, default):
    value = os.getenv(name)
    if not value:
        return default
    return value

# take environment variables from .env file if present
load_dotenv()

# Create Flask application
app = Flask(__name__)
app.json_encoder = MyJSONEncoder
app.wsgi_app = ProxyFix(app.wsgi_app)  # type: ignore
all_origins = {"origins": "*"}
cors = CORS(app, resources={r"/apiv1/*": all_origins})
csp = {
    'default-src': "'self'",
    'img-src': "'self'",
    'object-src': "'none'",
    'style-src': "'self' 'unsafe-hashes' 'sha256-aLM6kCMKBszYlopfUKTtpYd6xHtlR3jUaa4HNP1LLmI=' 'sha256-ZdHxw9eWtnxUb3mk6tBS+gIiVUPE3pGM470keHPDFlE=' 'sha256-0EZqoz+oBhx7gF4nvY2bSqoGyy4zLjNF+SDQXGp/ZrY='",
    'script-src': "'self' 'unsafe-hashes' 'sha256-rRMdkshZyJlCmDX27XnL7g3zXaxv7ei6Sg+yt4R3svU=' 'sha256-ftmTNsdfRKq6ZNyHL+p7dI9xRqueDTpseN1IaUUgQW4=' 'sha256-gikCNhEl+fhjSb8779qEr3zNPPm8nyTyg8MPyBYs+Tw=' 'sha256-2rvfFrggTCtyF5WOiTri1gDS8Boibj4Njn0e+VCBmDI='",
    'font-src': "'self'",
    'frame-ancestors': "'none'",
    'form-action': "'self'"
}
talisman = Talisman(app, content_security_policy=csp, force_https=False)

if os.getenv("DEBUG"):
    app.config["DEBUG"] = True

app.config.from_pyfile("flask_config.py")

app.config["JSONIFY_PRETTYPRINT_REGULAR"] = True

app.config["DEBUG"] = boolify(os.getenv("DEBUG"))
app.config["TESTNET"] = boolify(os.getenv("TESTNET"))
app.config["MAIL_SENDGRID_API_KEY"] = os.getenv("SENDGRID_API_KEY")
app.config["USE_SENDGRID"] = bool(app.config["MAIL_SENDGRID_API_KEY"])
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")

app.config["LOGO_URL_SRC"] = strdef("LOGO_URL_SRC", "/static/assets/img/logo.png")
app.config["LOGO_EMAIL_SRC"] = strdef("LOGO_EMAIL_SRC", f"http://{os.getenv('SERVER_NAME', 'error')}/static/assets/img/logo.png")

app.config["APPLE_APP_STORE_URL"] = strdef("APPLE_APP_STORE_URL", "https://apps.apple.com/nz/app/zap/XXX")
app.config["GOOGLE_PLAY_STORE_URL"] = strdef("GOOGLE_PLAY_STORE_URL", "https://play.google.com/store/apps/details?id=XXX")

app.config["USE_REFERRALS"] = boolify(os.getenv("USE_REFERRALS"))
app.config["REFERRAL_REWARD_TYPE_SENDER"] = strdef("REFERRAL_REWARD_TYPE_SENDER", "fixed")
app.config["REFERRAL_REWARD_SENDER"] = int(os.getenv("REFERRAL_REWARD_SENDER", 1000))
app.config["REFERRAL_REWARD_TYPE_RECIPIENT"] = strdef("REFERRAL_REWARD_TYPE_RECIPIENT", "fixed")
app.config["REFERRAL_REWARD_RECIPIENT"] = int(os.getenv("REFERRAL_REWARD_RECIPIENT", 1000))
app.config["REFERRAL_RECIPIENT_MIN_SPEND"] = int(os.getenv("REFERRAL_RECIPIENT_MIN_SPEND", 5000))
app.config["REFERRAL_ECOMMERCE_URL"] = strdef("REFERRAL_ECOMMERCE_URL", None)
app.config["REFERRAL_STORE_NAME"] = strdef("REFERRAL_STORE_NAME", "Change My Name Inc")
app.config["REFERRAL_SPEND_ASSET"] = strdef("REFERRAL_SPEND_ASSET", "NZD")

app.config["BROKER_ORDER_FEE"] = strdef("BROKER_ORDER_FEE", "2.5")

app.config['EXCHANGE_ACCOUNT_MOCK'] = boolify(os.getenv('EXCHANGE_ACCOUNT_MOCK'))

app.config['SECURITY_REGISTERABLE'] = not boolify(os.getenv('REGISTRATION_DISABLE'))

app.config["FLASK_ADMIN_SWATCH"] = strdef("FLASK_ADMIN_SWATCH", "default")
if os.getenv("FLASK_ADMIN_SWATCH") == "slate":
    app.config["CSS_THEME"] = "css/custom_reporting_dark.css"
    app.config["CSS_THEME_INTENSITY"] = "dark"
else:
    app.config["CSS_THEME_INTENSITY"] = "light"

app.config["MIN_AVAILABLE_NZD_BALANCE"] = decimal.Decimal(os.getenv("MIN_AVAILABLE_NZD_BALANCE", 2000))

if app.config["TESTNET"]:
    app.config["BITCOIN_EXPLORER"] = "https://blockstream.info/testnet/"
else:
    app.config["BITCOIN_EXPLORER"] = "https://blockstream.info/"

app.config["MAIL_SERVER"] = "mail"
app.config["MAIL_PORT"] = 587

def set_vital_setting(env_name, setting_name=None, acceptable_values=None, custom_handler=None):
    global MISSING_VITAL_SETTING
    if not setting_name:
        setting_name = env_name
    if os.getenv(env_name):
        value = app.config[setting_name] = os.getenv(env_name)
        app.config[env_name] = os.getenv(env_name)
        if acceptable_values and value not in acceptable_values:
            print(env_name + " not in range of acceptable values: " + str(acceptable_values))
            MISSING_VITAL_SETTING = True
        if custom_handler:
            custom_handler(env_name, value)
    else:
        print("no " + env_name)
        MISSING_VITAL_SETTING = True

set_vital_setting("ADMIN_EMAIL", "SECURITY_TWO_FACTOR_RESCUE_MAIL")
set_vital_setting("FROM_EMAIL", "SECURITY_EMAIL_SENDER")
set_vital_setting("FROM_NAME")

set_vital_setting("SESSION_KEY", "SECRET_KEY")
def set_totp_secret(name, val):
    app.config["SECURITY_TOTP_SECRETS"] = {'1': val}
set_vital_setting("PASSWORD_SALT", "SECURITY_PASSWORD_SALT", custom_handler=set_totp_secret)
set_vital_setting("SERVER_NAME")
set_vital_setting("FIREBASE_CREDENTIALS")
set_vital_setting("DASSET_API_SECRET")
set_vital_setting("DASSET_ACCOUNT_ID")
set_vital_setting("DASSET_TOTP_KEY")
set_vital_setting("PAYOUT_GROUP_EMAIL")
set_vital_setting("APLYID_BASE_URL")
set_vital_setting("APLYID_API_KEY")
set_vital_setting("APLYID_API_SECRET")
set_vital_setting("APLYID_WEBHOOK_BEARER_TOKEN")
set_vital_setting("B2_ACCOUNT_ID")
set_vital_setting("B2_APPLICATION_KEY")
set_vital_setting("KYC_BUCKET")
set_vital_setting("CROWN_ACCOUNT_EMAIL")
set_vital_setting("CROWN_ACCOUNT_NUMBER")
set_vital_setting("CROWN_ACCOUNT_CODE")
set_vital_setting("CROWN_API_KEY")
set_vital_setting("CROWN_API_SECRET")
set_vital_setting("CROWN_WITHDRAW_FEE_INT")
set_vital_setting("CROWN_WITHDRAW_NAME")
set_vital_setting("KYC_BUCKET")
set_vital_setting("BITCOIN_DATADIR")
set_vital_setting("BITCOIN_RPCCONNECT")

db = SQLAlchemy(app)
migrate = Migrate(app, db)
if app.config["USE_SENDGRID"]:
    mail = MailSendGrid(app)
else:
    mail = Mail(app)
socketio = SocketIO(app, cors_allowed_origins='*')
limiter = Limiter(app, key_func=get_remote_address, headers_enabled=True, default_limits=["3000 per minute"])
csrf = CSRFProtect(app)
