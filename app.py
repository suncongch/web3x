from flask import (Flask, Response, abort, current_app, g, render_template, request,
                   redirect, url_for, session, jsonify, flash, send_file)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import gzip
import logging
import os
import re
import secrets
import string
import hashlib
import hmac
import time
from datetime import datetime
from pathlib import Path
from dotenv import dotenv_values, load_dotenv
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import selectinload
from clash_config import INCLUDE_PATTERN
from three_xui import DuplicateClientError, PanelError, PanelRequestError, ThreeXUI
from subscription import (SubscriptionError, build_subscription, cached_rule_config, clash_attachment_filename,
                          extra_urls, panel_subscription_base, public_url)
from urllib.parse import quote

env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(env_path)
public_base_url = dotenv_values(env_path).get('PUBLIC_BASE_URL')
if public_base_url is not None:
    os.environ['PUBLIC_BASE_URL'] = public_base_url

app = Flask(__name__)
app.logger.setLevel(logging.INFO)
for logger_name in ('subscription', 'three_xui'):
    timing_logger = logging.getLogger(logger_name)
    timing_logger.setLevel(logging.INFO)
    for handler in app.logger.handlers:
        if handler not in timing_logger.handlers:
            timing_logger.addHandler(handler)
    timing_logger.propagate = False

app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY') or 'your-secret-key-change-this'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    can_use_external_nodes = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_name = db.Column(db.String(120), nullable=False)
    price = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='completed')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


TICKET_CATEGORIES = ('技术问题', '账户问题', '计费问题', '功能请求', '其他')
TICKET_STATUSES = ('open', 'in_progress', 'resolved', 'closed')
TICKET_IMAGE_MIME_TYPES = ('image/png', 'image/jpeg', 'image/webp', 'image/gif')
DEFAULT_TICKET_CATEGORY = '其他'
DEFAULT_TICKET_SUBJECT = '在线客服会话'
TICKET_STATUS_LABELS = {
    'open': '待处理',
    'in_progress': '处理中',
    'resolved': '已解决',
    'closed': '已关闭',
}


class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    subject = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='open')
    admin_reply = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    closed_at = db.Column(db.DateTime, nullable=True)
    user = db.relationship('User')
    attachments = db.relationship('TicketAttachment', backref='ticket', lazy='select',
                                  cascade='all, delete-orphan')
    messages = db.relationship('TicketMessage', backref='ticket', lazy='select',
                               cascade='all, delete-orphan')


class TicketAttachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False, index=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(80), unique=True, nullable=False)
    mime_type = db.Column(db.String(50), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class TicketMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False, index=True)
    sender_role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    images = db.relationship('TicketMessageImage', backref='message', lazy='select',
                             cascade='all, delete-orphan')


class TicketMessageImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('ticket_message.id'), nullable=False, index=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(80), unique=True, nullable=False)
    mime_type = db.Column(db.String(50), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class SubscriptionToken(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)


class AppSetting(db.Model):
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, nullable=False)


with app.app_context():
    db.create_all()
    if 'can_use_external_nodes' not in {
            column['name'] for column in inspect(db.engine).get_columns('user')}:
        with db.engine.begin() as connection:
            connection.exec_driver_sql(
                'ALTER TABLE user ADD COLUMN can_use_external_nodes BOOLEAN NOT NULL DEFAULT 0')


def current_product(user_id):
    return (Order.query.filter_by(user_id=user_id, status='completed')
            .order_by(Order.id.desc()).first())


def random_client_email():
    return ''.join(secrets.choice(string.ascii_letters + string.digits)
                   for _ in range(8))


def start_user_session(user):
    session.clear()
    session['user_id'] = user.id
    session['username'] = user.username


def admin_configuration():
    username = os.environ.get('ADMIN_USERNAME', '').strip()
    password_hash = os.environ.get('ADMIN_PASSWORD_HASH', '').strip()
    secret = current_app.config.get('SECRET_KEY')
    valid_hash = re.fullmatch(r'pbkdf2:sha256:[1-9]\d*\$[A-Za-z0-9]+\$[0-9a-f]{64}', password_hash)
    if not username or not valid_hash or not secret or secret == 'your-secret-key-change-this':
        current_app.logger.error('管理员服务需要配置 ADMIN_USERNAME、ADMIN_PASSWORD_HASH 和独立的 FLASK_SECRET_KEY')
        abort(503, '管理员服务尚未安全配置，请联系管理员')
    return username, password_hash


def admin_fingerprint(username, password_hash):
    key = current_app.config['SECRET_KEY'].encode('utf-8')
    credentials = (username + '\0' + password_hash).encode('utf-8')
    return hmac.new(key, credentials, hashlib.sha256).hexdigest()


def admin_authenticated(username, password_hash):
    fingerprint = session.get('admin_fingerprint', '')
    expires = session.get('admin_expires', 0)
    return (isinstance(fingerprint, str) and isinstance(expires, (int, float))
            and time.time() < expires
            and secrets.compare_digest(fingerprint, admin_fingerprint(username, password_hash)))


def admin_csrf_token():
    if 'admin_csrf' not in session:
        session['admin_csrf'] = secrets.token_urlsafe(32)
    return session['admin_csrf']


def verify_admin_csrf():
    expected = session.get('admin_csrf')
    supplied = request.form.get('csrf_token', '')
    if not isinstance(expected, str) or not secrets.compare_digest(expected.encode('utf-8'), supplied.encode('utf-8')):
        abort(400, '请求验证失败，请刷新页面重试')


def admin_page_number():
    value = request.args.get('page', '1')
    if not value.isascii() or not value.isdecimal() or len(value) > 9 or int(value) < 1:
        abort(400, '页码无效')
    return int(value)


def current_node_filter_pattern():
    setting = db.session.get(AppSetting, 'node_include_pattern')
    pattern = setting.value if setting is not None else INCLUDE_PATTERN.pattern
    try:
        return re.compile(pattern)
    except re.error as exc:
        current_app.logger.error('节点筛选条件无效：%s', exc)
        raise SubscriptionError('节点筛选条件无效，请联系管理员') from exc


def render_admin_users(filter_pattern=None, filter_error=None):
    setting = db.session.get(AppSetting, 'node_include_pattern')
    if filter_pattern is None:
        filter_pattern = setting.value if setting is not None else INCLUDE_PATTERN.pattern
    users = (User.query.with_entities(User.id, User.username, User.email,
                                      User.can_use_external_nodes)
             .order_by(User.id).paginate(page=admin_page_number(), per_page=25, error_out=False))
    return render_template('admin_users.html', users=users, csrf_token=admin_csrf_token(),
                           filter_pattern=filter_pattern, filter_error=filter_error)


def ticket_upload_dir():
    directory = Path(current_app.instance_path) / 'ticket_uploads'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def validate_ticket_images(files):
    if len(files) > 3:
        return None, '最多上传 3 张图片。'
    specs = []
    for upload in files:
        if upload.mimetype not in TICKET_IMAGE_MIME_TYPES:
            return None, '仅支持 PNG/JPEG/WebP/GIF 图片。'
        upload.stream.seek(0, os.SEEK_END)
        size = upload.stream.tell()
        upload.stream.seek(0)
        if size <= 0:
            return None, '上传图片为空，请重新选择。'
        if size > 5 * 1024 * 1024:
            return None, '单张图片不能超过 5 MB。'
        extension = Path(secure_filename(upload.filename)).suffix.lower() or '.img'
        specs.append((upload, size, extension))
    return specs, None


def save_ticket_message_images(message_id, image_specs):
    saved_paths = []
    for upload, size, extension in image_specs:
        stored_name = secrets.token_hex(24) + extension
        path = ticket_upload_dir() / stored_name
        upload.save(path)
        saved_paths.append(path)
        db.session.add(TicketMessageImage(
            message_id=message_id,
            original_name=secure_filename(upload.filename) or 'image',
            stored_name=stored_name,
            mime_type=upload.mimetype,
            size=size,
        ))
    return saved_paths


def admin_session_active():
    username = os.environ.get('ADMIN_USERNAME', '').strip()
    password_hash = os.environ.get('ADMIN_PASSWORD_HASH', '').strip()
    valid_hash = re.fullmatch(r'pbkdf2:sha256:[1-9]\d*\$[A-Za-z0-9]+\$[0-9a-f]{64}', password_hash)
    if not username or not valid_hash:
        return False
    return admin_authenticated(username, password_hash)


def support_status_label(status):
    return TICKET_STATUS_LABELS.get(status, status)


def current_user_ticket(user_id):
    return (Ticket.query.options(selectinload(Ticket.messages).selectinload(TicketMessage.images),
                                 selectinload(Ticket.attachments))
            .filter_by(user_id=user_id).order_by(Ticket.id.desc()).first())


def render_support_page(status_code=200):
    ticket = current_user_ticket(session['user_id'])
    return render_template(
        'support.html',
        username=session.get('username'),
        ticket=ticket,
        status_labels=TICKET_STATUS_LABELS,
        image_mime_types=TICKET_IMAGE_MIME_TYPES,
    ), status_code


@app.before_request
def start_subscription_timing():
    if request.endpoint in ('subscription_links', 'subscription_content'):
        g.subscription_request_started = time.perf_counter()


@app.after_request
def protect_admin_responses(response):
    if request.path == '/admin' or request.path.startswith('/admin/'):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
    started = getattr(g, 'subscription_request_started', None)
    if started is not None:
        app.logger.info('subscription_timing endpoint=%s stage=request_total elapsed_ms=%.1f status=%s',
                        request.endpoint, (time.perf_counter() - started) * 1000,
                        response.status_code)
    return response


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    username, password_hash = admin_configuration()
    if request.method == 'POST':
        verify_admin_csrf()
        supplied_username = request.form.get('username', '')
        supplied_password = request.form.get('password', '')
        if len(supplied_username) > 128 or len(supplied_password) > 1024:
            abort(400, '用户名或密码过长')
        try:
            password_matches = check_password_hash(password_hash, supplied_password)
        except (ValueError, TypeError):
            current_app.logger.error('ADMIN_PASSWORD_HASH 配置无效')
            abort(503, '管理员服务尚未安全配置，请联系管理员')
        username_matches = secrets.compare_digest(username.encode('utf-8'), supplied_username.encode('utf-8'))
        if username_matches and password_matches:
            session.clear()
            session['admin_fingerprint'] = admin_fingerprint(username, password_hash)
            session['admin_expires'] = time.time() + 1800
            return redirect(url_for('admin_users'))
        return render_template('admin_login.html', csrf_token=admin_csrf_token(),
                               error='用户名或密码错误'), 401
    if admin_authenticated(username, password_hash):
        return redirect(url_for('admin_users'))
    return render_template('admin_login.html', csrf_token=admin_csrf_token())


@app.route('/admin')
def admin_users():
    username, password_hash = admin_configuration()
    if not admin_authenticated(username, password_hash):
        return redirect(url_for('admin_login'))
    return render_admin_users()


@app.route('/admin/node-filter', methods=['POST'])
def admin_update_node_filter():
    username, password_hash = admin_configuration()
    if not admin_authenticated(username, password_hash):
        return redirect(url_for('admin_login'))
    verify_admin_csrf()
    pattern = request.form.get('include_pattern', '')
    if not pattern.strip():
        return render_admin_users(pattern, '筛选条件不能为空。'), 400
    if len(pattern) > 2000:
        return render_admin_users(pattern, '筛选条件不能超过 2000 个字符。'), 400
    try:
        re.compile(pattern)
    except re.error as exc:
        return render_admin_users(pattern, f'正则表达式无效：{exc}'), 400
    setting = db.session.get(AppSetting, 'node_include_pattern')
    if setting is None:
        setting = AppSetting(key='node_include_pattern', value=pattern)
        db.session.add(setting)
    else:
        setting.value = pattern
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('保存节点筛选条件失败')
        return render_admin_users(pattern, '筛选条件保存失败，请稍后重试。'), 500
    flash('节点筛选条件已更新。', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:user_id>/external-nodes', methods=['POST'])
def admin_update_external_nodes(user_id):
    username, password_hash = admin_configuration()
    if not admin_authenticated(username, password_hash):
        return redirect(url_for('admin_login'))
    verify_admin_csrf()
    enabled = request.form.get('enabled')
    if enabled not in (None, 'true'):
        abort(400, '外部节点权限值无效')
    user = User.query.filter_by(id=user_id).first_or_404()
    user.can_use_external_nodes = enabled == 'true'
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('更新用户外部节点权限失败')
        flash('外部节点权限保存失败，请稍后重试。', 'error')
    else:
        flash('外部节点权限已更新。', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:user_id>/orders')
def admin_user_orders(user_id):
    username, password_hash = admin_configuration()
    if not admin_authenticated(username, password_hash):
        return redirect(url_for('admin_login'))
    user = User.query.with_entities(User.id, User.username, User.email).filter_by(id=user_id).first_or_404()
    orders = (Order.query.with_entities(Order.id, Order.product_name, Order.price, Order.status, Order.created_at)
              .filter_by(user_id=user_id).order_by(Order.id.desc())
              .paginate(page=admin_page_number(), per_page=25, error_out=False))
    return render_template('admin_orders.html', user=user, orders=orders, csrf_token=admin_csrf_token())


@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    username, password_hash = admin_configuration()
    if not admin_authenticated(username, password_hash):
        return redirect(url_for('admin_login'))
    verify_admin_csrf()
    session.clear()
    return redirect(url_for('admin_login'))


@app.route('/admin/refresh-rules', methods=['POST'])
def admin_refresh_rules():
    username, password_hash = admin_configuration()
    if not admin_authenticated(username, password_hash):
        return redirect(url_for('admin_login'))
    verify_admin_csrf()
    try:
        cached_rule_config(force=True)
    except SubscriptionError as exc:
        current_app.logger.error('管理员刷新分流规则缓存失败：%s', exc)
        flash('分流规则缓存刷新失败，原缓存未改变。请检查服务器日志。', 'error')
    else:
        flash('分流规则缓存刷新成功。', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/tickets')
def admin_tickets():
    username, password_hash = admin_configuration()
    if not admin_authenticated(username, password_hash):
        return redirect(url_for('admin_login'))
    tickets = (Ticket.query.options(selectinload(Ticket.user), selectinload(Ticket.attachments),
                                    selectinload(Ticket.messages).selectinload(TicketMessage.images))
               .order_by(Ticket.updated_at.desc(), Ticket.id.desc()).all())
    selected = None
    ticket_id = request.args.get('ticket_id', '')
    if ticket_id.isdecimal():
        selected = next((ticket for ticket in tickets if ticket.id == int(ticket_id)), None)
    if selected is None and tickets:
        selected = tickets[0]
    return render_template('admin_tickets.html', tickets=tickets, selected_ticket=selected,
                           csrf_token=admin_csrf_token(), status_labels=TICKET_STATUS_LABELS,
                           status_options=TICKET_STATUSES)


@app.route('/admin/tickets/<int:ticket_id>', methods=['POST'])
def admin_update_ticket(ticket_id):
    username, password_hash = admin_configuration()
    if not admin_authenticated(username, password_hash):
        return redirect(url_for('admin_login'))
    verify_admin_csrf()
    status = request.form.get('status', '').strip()
    if status not in TICKET_STATUSES:
        abort(400, '工单状态无效')
    ticket = Ticket.query.filter_by(id=ticket_id).first_or_404()
    ticket.status = status
    ticket.updated_at = datetime.utcnow()
    if status in ('resolved', 'closed'):
        ticket.closed_at = datetime.utcnow()
    else:
        ticket.closed_at = None
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('更新工单失败')
        flash('工单更新失败，请稍后重试。', 'error')
    else:
        flash(f'工单 #{ticket.id} 已更新为“{support_status_label(status)}”。', 'success')
    return redirect(url_for('admin_tickets', ticket_id=ticket.id))


@app.route('/admin/tickets/<int:ticket_id>/messages', methods=['POST'])
def admin_add_ticket_message(ticket_id):
    username, password_hash = admin_configuration()
    if not admin_authenticated(username, password_hash):
        return redirect(url_for('admin_login'))
    verify_admin_csrf()
    content = request.form.get('content', '').strip()
    files = [item for item in request.files.getlist('images') if item and item.filename]
    if not content and not files:
        abort(400, '回复内容不能为空')
    if len(content) > 5000:
        abort(400, '回复内容不能超过 5000 个字符')
    image_specs, image_error = validate_ticket_images(files)
    if image_error:
        flash(image_error, 'error')
        return redirect(url_for('admin_tickets', ticket_id=ticket_id))
    ticket = Ticket.query.filter_by(id=ticket_id).first_or_404()
    message_text = content or '[图片]'
    saved_paths = []
    message = TicketMessage(sender_role='admin', content=message_text)
    ticket.messages.append(message)
    ticket.updated_at = datetime.utcnow()
    if ticket.status == 'open':
        ticket.status = 'in_progress'
    if ticket.status in ('resolved', 'closed'):
        ticket.closed_at = datetime.utcnow()
    try:
        db.session.flush()
        saved_paths = save_ticket_message_images(message.id, image_specs)
        db.session.commit()
    except OSError:
        db.session.rollback()
        for path in saved_paths:
            if path.exists():
                path.unlink()
        current_app.logger.exception('保存管理员工单图片失败')
        flash('图片发送失败，请稍后重试。', 'error')
    except SQLAlchemyError:
        db.session.rollback()
        for path in saved_paths:
            if path.exists():
                path.unlink()
        current_app.logger.exception('保存工单回复失败')
        flash('工单回复失败，请稍后重试。', 'error')
    else:
        flash(f'已回复工单 #{ticket.id}。', 'success')
    return redirect(url_for('admin_tickets', ticket_id=ticket.id))


@app.route('/ticket-attachments/<int:attachment_id>')
def ticket_attachment(attachment_id):
    attachment = TicketAttachment.query.filter_by(id=attachment_id).first_or_404()
    user_id = session.get('user_id')
    allowed = isinstance(user_id, int) and user_id == attachment.ticket.user_id
    if not allowed:
        allowed = admin_session_active()
    if not allowed:
        abort(403, '无权访问该附件')
    path = ticket_upload_dir() / attachment.stored_name
    if not path.is_file():
        current_app.logger.error('工单附件不存在：id=%s stored_name=%s', attachment.id, attachment.stored_name)
        abort(404, '附件不存在')
    return send_file(path, mimetype=attachment.mime_type, as_attachment=False,
                     download_name=attachment.original_name)


@app.route('/ticket-message-images/<int:image_id>')
def ticket_message_image(image_id):
    image = TicketMessageImage.query.filter_by(id=image_id).first_or_404()
    user_id = session.get('user_id')
    allowed = isinstance(user_id, int) and user_id == image.message.ticket.user_id
    if not allowed:
        allowed = admin_session_active()
    if not allowed:
        abort(403, '无权访问该图片')
    path = ticket_upload_dir() / image.stored_name
    if not path.is_file():
        current_app.logger.error('工单消息图片不存在：id=%s stored_name=%s', image.id, image.stored_name)
        abort(404, '图片不存在')
    return send_file(path, mimetype=image.mime_type, as_attachment=False,
                     download_name=image.original_name)


@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('home'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email', '').strip()
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if not username or not password:
            return render_template('register.html', error='请填写用户名和密码')

        if password != confirm_password:
            return render_template('register.html', error='密码不匹配')

        if email and (len(email) > 120 or not re.fullmatch(
                r'[^@\s/\\]+@[^@\s/\\]+', email)):
            return render_template('register.html', error='请输入有效的邮箱地址')

        if User.query.filter_by(username=username).first():
            return render_template('register.html', error='用户名已存在')

        if email and User.query.filter_by(email=email).first():
            return render_template('register.html', error='邮箱已注册')

        generated_email = not email
        if generated_email:
            for _ in range(10):
                email = random_client_email()
                if not User.query.filter_by(email=email).first():
                    break
            else:
                app.logger.error('生成客户端邮箱失败：随机值重复次数过多')
                return render_template('register.html', error='生成客户端邮箱失败，请稍后重试')

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            return render_template('register.html', error='用户名或邮箱已存在')
        panel = ThreeXUI()
        try:
            client_email = panel.create_client(username, email, generated_email)
        except DuplicateClientError as exc:
            db.session.rollback()
            return render_template('register.html', error=str(exc))
        except PanelError as exc:
            db.session.rollback()
            app.logger.error('客户端创建失败：%s', exc)
            return render_template('register.html', error='客户端创建失败，注册未完成；请联系管理员检查面板')
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception('用户注册保存失败，正在清理已创建的客户端')
            try:
                panel.delete_client(client_email)
            except PanelError:
                app.logger.exception('客户端清理失败，请检查面板')
            return render_template('register.html', error='注册保存失败，请联系管理员检查面板')

        start_user_session(user)
        if panel.failed_inbounds:
            flash('注册成功，但部分入站未能分配，请联系客服。', 'warning')
        return redirect(url_for('home'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            return render_template('login.html', error='请填写用户名和密码')

        user = User.query.filter_by(username=username).first()

        if not user or not user.check_password(password):
            return render_template('login.html', error='用户名或密码错误')

        start_user_session(user)
        return redirect(url_for('home'))

    return render_template('login.html')

@app.route('/home')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('home.html', username=session.get('username'),
                           current_order=current_product(session['user_id']))


@app.route('/api/subscription-links', methods=['POST'])
def subscription_links():
    if 'user_id' not in session:
        return jsonify(error='请先登录'), 401
    if current_app.config['SECRET_KEY'] == 'your-secret-key-change-this':
        current_app.logger.error('订阅链接需要配置独立的 FLASK_SECRET_KEY')
        return jsonify(error='订阅服务安全配置未完成，请联系管理员'), 503
    user = db.session.get(User, session['user_id'])
    if user is None:
        return jsonify(error='用户不存在，请重新登录'), 401
    try:
        base = public_url()
    except SubscriptionError:
        app.logger.error('订阅链接配置无效：PUBLIC_BASE_URL')
        return jsonify(error='订阅服务尚未配置，请联系管理员'), 503
    try:
        panel_subscription_base('clash')
        panel_subscription_base('shadowrocket')
        if user.can_use_external_nodes:
            extra_urls()
    except SubscriptionError as exc:
        app.logger.error('订阅源配置无效：%s', exc)
        return jsonify(error='订阅服务配置无效，请联系管理员'), 503
    token = db.session.get(SubscriptionToken, user.id)
    if token is None:
        token = SubscriptionToken(user_id=user.id, token=secrets.token_urlsafe(32))
        db.session.add(token)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            token = db.session.get(SubscriptionToken, user.id)
            if token is None:
                app.logger.exception('创建订阅链接失败')
                return jsonify(error='创建订阅链接失败，请稍后重试'), 500
    clash = base + url_for('subscription_content', kind='clash', token=token.token)
    shadow = base + url_for('subscription_content', kind='shadowrocket', token=token.token)
    response = jsonify(clash=clash, shadowrocket=shadow,
                       shadowrocket_import='shadowrocket://add/' + quote(shadow, safe=''),
                       flclash_import='clash://install-config?url=' + quote(clash, safe=''))
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/subscription/<kind>/<token>')
def subscription_content(kind, token):
    if kind not in ('clash', 'shadowrocket'):
        return Response('未知订阅类型', status=404)
    entry = SubscriptionToken.query.filter_by(token=token).first()
    user = db.session.get(User, entry.user_id) if entry else None
    if user is None:
        return Response('订阅链接无效', status=404, headers={'Cache-Control': 'no-store'})
    try:
        filename = quote(clash_attachment_filename(), safe='') if kind == 'clash' else ''
        include_pattern = current_node_filter_pattern()
        result = build_subscription(ThreeXUI(), user.email, user.username, kind,
                                    include_external_nodes=user.can_use_external_nodes,
                                    include_pattern=include_pattern)
    except (SubscriptionError, PanelError, SQLAlchemyError) as exc:
        db.session.rollback()
        app.logger.error('生成订阅失败：%s', exc)
        return Response('订阅生成失败，请联系管理员', status=503,
                        headers={'Cache-Control': 'no-store'})
    if kind == 'clash':
        data = result.content.encode('utf-8')
        chunks = (data[offset:offset + 8192] for offset in range(0, len(data), 8192))
        response = Response(chunks, content_type='text/plain; charset=utf-8')
        response.headers['Content-Disposition'] = "attachment; filename*=UTF-8''" + filename
        userinfo = (f'upload={result.upload}; download={result.download}; total={result.total}; '
                    'update=' + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        if result.expiry_ms > 0:
            userinfo += f'; expire={result.expiry_ms // 1000}'
        response.headers['subscription-userinfo'] = userinfo
    else:
        response = Response(result.content, content_type='text/plain; charset=utf-8')
    response.vary.add('Accept-Encoding')
    if request.accept_encodings.best_match(['gzip']) == 'gzip':
        response.set_data(gzip.compress(response.get_data(), mtime=0))
        response.headers['Content-Encoding'] = 'gzip'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@app.route('/purchase')
def purchase():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('purchase.html', username=session.get('username'))

@app.route('/tutorial')
def tutorial():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('tutorial.html', username=session.get('username'))

@app.route('/support')
def support():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_support_page()


@app.route('/support/messages', methods=['POST'])
def support_add_ticket_message():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    content = request.form.get('content', '').strip()
    files = [item for item in request.files.getlist('images') if item and item.filename]
    if not content and not files:
        flash('消息内容不能为空。', 'error')
        return redirect(url_for('support'))
    if len(content) > 5000:
        flash('消息内容不能超过 5000 个字符。', 'error')
        return redirect(url_for('support'))
    image_specs, image_error = validate_ticket_images(files)
    if image_error:
        flash(image_error, 'error')
        return redirect(url_for('support'))
    ticket = current_user_ticket(session['user_id'])
    if ticket is None:
        initial_content = content or '用户发送了图片'
        ticket = Ticket(user_id=session['user_id'], subject=DEFAULT_TICKET_SUBJECT,
                        category=DEFAULT_TICKET_CATEGORY, content=initial_content)
        db.session.add(ticket)
    message_text = content or '[图片]'
    saved_paths = []
    ticket.updated_at = datetime.utcnow()
    if ticket.status in ('resolved', 'closed'):
        ticket.status = 'open'
        ticket.closed_at = None
    try:
        db.session.flush()
        message = TicketMessage(ticket_id=ticket.id, sender_role='user', content=message_text)
        db.session.add(message)
        db.session.flush()
        saved_paths = save_ticket_message_images(message.id, image_specs)
        db.session.commit()
    except OSError:
        db.session.rollback()
        for path in saved_paths:
            if path.exists():
                path.unlink()
        current_app.logger.exception('保存工单消息图片失败')
        flash('图片发送失败，请稍后重试。', 'error')
    except SQLAlchemyError:
        db.session.rollback()
        for path in saved_paths:
            if path.exists():
                path.unlink()
        current_app.logger.exception('追加工单消息失败')
        flash('发送失败，请稍后重试。', 'error')
    else:
        flash('消息已发送。', 'success')
    return redirect(url_for('support'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/api/purchase', methods=['POST'])
def api_purchase():
    """
    处理购买请求的 API 接口
    
    请求参数：
        product_name: 产品名称
        price: 产品价格
    
    返回值：
        success: 是否成功
        message: 返回信息
        order_id: 订单 ID（成功时）
    """
    if 'user_id' not in session:
        return jsonify({
            'success': False,
            'message': '请先登录'
        }), 401
    
    data = request.get_json()
    
    if not data:
        return jsonify({
            'success': False,
            'message': '请提供正确的数据'
        }), 400
    
    product_name = data.get('product_name')
    price = data.get('price')
    
    if not product_name or price is None:
        return jsonify({
            'success': False,
            'message': '产品名称和价格不能为空'
        }), 400
    
    try:
        # 创建订单
        order = Order(
            user_id=session.get('user_id'),
            product_name=product_name,
            price=float(price),
            status='completed'
        )
        db.session.add(order)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': '购买成功',
            'order_id': order.id
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': '购买失败: ' + str(e)
        }), 500

if __name__ == '__main__':
    app.run(host='192.168.2.17', debug=False, port=8000)
