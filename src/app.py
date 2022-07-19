#!/usr/bin/python3

import sys
import logging
import signal
import traceback

import gevent
import gevent.pool
from flask_security.utils import encrypt_password

import payouts_core
import web
import email_utils
import log_utils
from app_core import MISSING_VITAL_SETTING, app, db
from models import User, Role, Permission, Topic
from security import user_datastore

logger = logging.getLogger()  # root log handler

def teardown_logging():
    # fix this bug: https://bugs.python.org/issue21149
    logger.handlers.clear()

def add_user(email, password):
    email = email.lower()
    with app.app_context():
        user = User.from_email(db.session, email)
        if user:
            logger.info('user already exists, updating password...')
            user.password = encrypt_password(password)
        else:
            user = user_datastore.create_user(email=email, password=encrypt_password(password))
        db.session.commit()

def create_role(name, desc):
    role = Role.from_name(db.session, name)
    if not role:
        role = Role(name=name, description=desc)  # pyright: ignore [reportGeneralTypeIssues]
    else:
        role.description = desc
    db.session.add(role)
    return role

def create_permission(name, desc):
    permission = Permission.from_name(db.session, name)
    if not permission:
        permission = Permission(name=name, description=desc)
    else:
        permission.description = desc
    db.session.add(permission)
    return permission

def create_topic(name):
    topic = Topic.from_name(db.session, name)
    if not topic:
        topic = Topic(topic=name)
    db.session.add(topic)
    return topic

def add_role(email, role_name):
    with app.app_context():
        user = User.from_email(db.session, email)
        if not user:
            logger.error("user does not exist")
            return
        role = create_role(role_name, None)
        if role not in user.roles:
            user.roles.append(role)
        else:
            logger.info("user already has role")
        db.session.commit()

def payouts_notification_create():
    with app.app_context():
        payouts_core.payouts_notification_create()

def sigint_handler(signum, frame):
    global KEEP_RUNNING
    logger.warning("SIGINT caught, attempting to exit gracefully")
    KEEP_RUNNING = False

def g_exception(greenlet):
    try:
        greenlet.get()
    except Exception as e:
        stack_trace = traceback.format_exc()
        msg = f"{e}\n---\n{stack_trace}"
        email_utils.email_exception(logger, msg)

KEEP_RUNNING = True
if __name__ == "__main__":
    ch = log_utils.setup_logging(logger, logging.INFO)
    log_utils.log_socketio_version(logger)

    # process commands
    if len(sys.argv) > 1:
        if sys.argv[1] == "seed_db":
            create_role(Role.ROLE_ADMIN, "super user")
            create_role(Role.ROLE_FINANCE, "Can view all records, can authorize rewards")
            create_role(Role.ROLE_REFERRAL_CLAIMER, "Can claim referrals")
            create_permission(Permission.PERMISSION_RECIEVE, "view account name")
            create_permission(Permission.PERMISSION_BALANCE, "view account balance")
            create_permission(Permission.PERMISSION_HISTORY, "view account history")
            create_permission(Permission.PERMISSION_TRANSFER, "transfer funds")
            create_permission(Permission.PERMISSION_ISSUE, "issue funds")
            create_topic("test")
            create_topic("general")
            db.session.commit()
        if sys.argv[1] == "add_user":
            add_user(sys.argv[2], sys.argv[3])
        if sys.argv[1] == "add_role":
            add_role(sys.argv[2], sys.argv[3])
        if sys.argv[1] == 'payouts_notification_create':
            payouts_notification_create()
    else:
        if MISSING_VITAL_SETTING:
            logger.error('missing vital setting')
            sys.exit(1)
        else:
            logger.info('got all vital settings')

        signal.signal(signal.SIGINT, sigint_handler)

        logger.info("starting greenlets")
        web_greenlet = web.WebGreenlet(g_exception)  # pyright: ignore [reportGeneralTypeIssues]
        web_greenlet.start()
        while KEEP_RUNNING:
            gevent.sleep(1)
        logger.info("stopping greenlets")
        web_greenlet.stop()
        logger.info("teardown logging")
        teardown_logging()
