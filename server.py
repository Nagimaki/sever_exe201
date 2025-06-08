import os
import time
import json
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask, request, jsonify, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS, cross_origin
from payos import PaymentData, PayOS

# Setup logging
logging.basicConfig(level=logging.INFO)

# Load environment variables
load_dotenv()

# Instantiate Flask app
app = Flask(__name__)
CORS(app)

# --- PayOS Configuration & Payment Endpoints ---
payos = None
try:
    payos = PayOS(
        client_id    = os.getenv('PAYOS_CLIENT_ID'),
        api_key      = os.getenv('PAYOS_API_KEY'),
        checksum_key = os.getenv('PAYOS_CHECKSUM_KEY')
    )
    logging.info("PayOS initialized")
except Exception as e:
    logging.warning(f"PayOS init failed: {e}")

HISTORY_FILE = 'history.json'
STATUS_LABELS = {
    'PENDING':   'Chờ thanh toán',
    'EXPIRED':   'Hết hạn',
    'SUCCESS':   'Thanh toán thành công',
    'CANCELED':  'Đã huỷ'
}

# Helpers for payment history

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def write_history(data):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/payment/create', methods=['POST'])
@cross_origin()
def create_payment():
    logging.info("create_payment called")
    body = request.get_json(force=True, silent=True) or {}
    amount = body.get('amount')
    description = body.get('description', '')
    if not amount:
        return jsonify({'error': 'Missing amount'}), 400

    order_code = f"ORDER-{int(time.time())}"
    if payos:
        pd = PaymentData(
            orderCode = order_code,
            amount    = int(amount),
            currency  = 'VND',
            extra     = {'description': description}
        )
        try:
            res = payos.create_payment_link(pd)
        except Exception as e:
            logging.error(f"PayOS error: {e}")
            return jsonify({'error': str(e)}), 500
        checkout_url = res.get('checkoutUrl')
        payment_link_id = res.get('paymentLinkId')
    else:
        # Fallback stub
        checkout_url = f"https://example.com/checkout/{order_code}"
        payment_link_id = f"LINK-{order_code}"
        logging.info("Using stub payment link")

    # Save history
    history = load_history()
    now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    history.append({
        'paymentLinkId': payment_link_id,
        'orderCode':     order_code,
        'amount':        int(amount),
        'statusCode':    'PENDING',
        'status':        STATUS_LABELS['PENDING'],
        'createdAt':     now_iso
    })
    write_history(history)

    return jsonify({
        'checkoutUrl':   checkout_url,
        'orderCode':     order_code,
        'paymentLinkId': payment_link_id
    }), 200

@app.route('/payment/history', methods=['GET'])
@cross_origin()
def payment_history():
    logging.info("payment_history called")
    history = load_history()
    now = datetime.utcnow().replace(microsecond=0)
    dirty = False
    for tx in history:
        if tx.get('statusCode') == 'PENDING':
            created = datetime.fromisoformat(tx['createdAt'].rstrip('Z'))
            if now - created > timedelta(minutes=10):
                tx['statusCode'] = 'EXPIRED'
                tx['status']     = STATUS_LABELS['EXPIRED']
                tx['updatedAt']  = now.isoformat() + 'Z'
                dirty = True
    if dirty:
        write_history(history)
    for tx in history:
        tx['statusLabel'] = STATUS_LABELS.get(tx['statusCode'], tx['statusCode'])
    return jsonify(history), 200

# Aliases without /payment prefix
app.add_url_rule('/create',  endpoint='create_payment_alias',  view_func=create_payment, methods=['POST'])
app.add_url_rule('/history', endpoint='payment_history_alias', view_func=payment_history, methods=['GET'])

# Webhook & redirect
@app.route('/payment/success', methods=['GET'])
def payment_success():
    order_code = request.args.get('orderCode')
    history = load_history()
    now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    for tx in history:
        if tx.get('orderCode') == order_code:
            tx['statusCode'] = 'SUCCESS'
            tx['status']     = STATUS_LABELS['SUCCESS']
            tx['updatedAt']  = now_iso
            break
    write_history(history)
    return redirect(os.getenv('FRONTEND_SUCCESS_URL', '/')), 302

@app.route('/payment/cancel', methods=['GET'])
def payment_cancel():
    order_code = request.args.get('orderCode')
    history = load_history()
    now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    for tx in history:
        if tx.get('orderCode') == order_code:
            tx['statusCode'] = 'CANCELED'
            tx['status']     = STATUS_LABELS['CANCELED']
            tx['updatedAt']  = now_iso
            break
    write_history(history)
    return redirect(os.getenv('FRONTEND_CANCEL_URL', '/')), 302

@app.route('/payment/webhook', methods=['POST'])
def payment_webhook():
    payload = request.get_json(force=True, silent=True) or {}
    link_id = payload.get('paymentLinkId')
    status  = payload.get('status')
    if not link_id or not status:
        return jsonify({'error': 'Invalid payload'}), 400
    history = load_history()
    for tx in history:
        if tx.get('paymentLinkId') == link_id:
            tx['statusCode'] = status
            tx['status']     = STATUS_LABELS.get(status, status)
            tx['updatedAt']  = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
            break
    write_history(history)
    return jsonify({'success': True}), 200

# --- Database setup ---
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Models ---
class User(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role     = db.Column(db.String(20), nullable=False)

class Employee(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name         = db.Column(db.String(100), nullable=False)
    title        = db.Column(db.String(100), nullable=False)
    total_shifts = db.Column(db.Integer, default=0)
    done_shifts  = db.Column(db.Integer, default=0)
    rating       = db.Column(db.Float, default=0.0)
    on_time      = db.Column(db.Boolean, default=True)
    def to_dict(self):
        return {
            'id': self.id,
            'userId': self.user_id,
            'name': self.name,
            'title': self.title,
            'totalShifts': self.total_shifts,
            'doneShifts': self.done_shifts,
            'rating': self.rating,
            'onTime': self.on_time
        }

class Appointment(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    user_id  = db.Column(db.Integer, nullable=False)
    date     = db.Column(db.String(20), nullable=False)
    time     = db.Column(db.String(20), nullable=False)
    service  = db.Column(db.String(200), nullable=False)

class Message(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    sender_id  = db.Column(db.Integer, nullable=False)
    content    = db.Column(db.String(500), nullable=False)
    timestamp  = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

# --- Decorator: Admin only ---
def require_admin(fn):
    def wrapper(*args, **kwargs):
        uid = request.headers.get('X-User-Id')
        if not uid or not uid.isdigit():
            return jsonify({'error': 'Unauthorized'}), 401
        user = User.query.get(int(uid))
        if not user or user.role != 'admin':
            return jsonify({'error': 'Forbidden'}), 403
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper

# --- Auth Endpoints ---
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json(force=True, silent=True) or {}
    u = data.get('username','').strip()
    p = data.get('password','').strip()
    if not u or not p:
        return jsonify({'error': 'Username and password required'}), 400
    if User.query.filter_by(username=u).first():
        return jsonify({'error': 'Username exists'}), 409
    user = User(username=u, password=p, role='admin')
    db.session.add(user)
    db.session.commit()
    return jsonify({'success': True, 'userId': user.id, 'userName': user.username, 'role': user.role}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(force=True, silent=True) or {}
    u = data.get('username','')
    p = data.get('password','')
    if not u or not p:
        return jsonify({'error': 'Username and password required'}), 400
    user = User.query.filter_by(username=u, password=p).first()
    if not user:
        return jsonify({'error': 'Invalid credentials'}), 401
    return jsonify({'success': True, 'userId': user.id, 'userName': user.username, 'role': user.role}), 200

# --- Employee CRUD ---
@app.route('/employees', methods=['POST'])
@require_admin
def create_employee():
    data = request.get_json(force=True, silent=True) or {}
    u = data.get('username','').strip()
    p = data.get('password','').strip()
    name = data.get('name','').strip()
    t = data.get('title','').strip()
    if not u or not p or not name or not t:
        return jsonify({'error': 'Missing fields'}), 400
    if User.query.filter_by(username=u).first():
        return jsonify({'error': 'Username exists'}), 409
    user = User(username=u, password=p, role='employee')
    db.session.add(user)
    db.session.commit()
    emp = Employee(user_id=user.id, name=name, title=t)
    db.session.add(emp)
    db.session.commit()
    return jsonify(emp.to_dict()), 201

@app.route('/employees', methods=['GET'])
@require_admin
def list_employees():
    return jsonify([e.to_dict() for e in Employee.query.all()]), 200

@app.route('/employees/<int:user_id>', methods=['GET'])
def get_employee(user_id):
    emp = Employee.query.filter_by(user_id=user_id).first()
    if not emp:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(emp.to_dict()), 200

@app.route('/employees/<int:emp_id>', methods=['PUT'])
@require_admin
def update_employee(emp_id):
    emp = Employee.query.get(emp_id)
    if not emp:
        return jsonify({'error': 'Not found'}), 404
    data = request.get_json(force=True, silent=True) or {}
    emp.name = data.get('name', emp.name)
    emp.title = data.get('title', emp.title)
    emp.total_shifts = data.get('totalShifts', emp.total_shifts)
    emp.done_shifts = data.get('doneShifts', emp.done_shifts)
    emp.rating = data.get('rating', emp.rating)
    emp.on_time = data.get('onTime', emp.on_time)
    db.session.commit()
    return jsonify(emp.to_dict()), 200

@app.route('/employees/<int:emp_id>', methods=['DELETE'])
@require_admin
def delete_employee(emp_id):
    emp = Employee.query.get(emp_id)
    if not emp:
        return jsonify({'error': 'Not found'}), 404
    user = User.query.get(emp.user_id)
    db.session.delete(emp)
    if user:
        db.session.delete(user)
    db.session.commit()
    return jsonify({'success': True}), 200

# --- Appointments ---
@app.route('/appointments', methods=['GET'])
def get_appointments():
    qry = Appointment.query
    apps = qry.order_by(Appointment.id).all()
    return jsonify([{ 'id': a.id, 'userId': a.user_id, 'datetime': f"{a.date}T{a.time}", 'description': a.service } for a in apps]), 200

@app.route('/appointments', methods=['POST'])
def create_appointment():
    data = request.get_json(force=True, silent=True) or {}
    dt = data.get('datetime')
    desc = data.get('description') or data.get('service')
    if not dt or not desc:
        return jsonify({'error': 'Missing fields'}), 200  # return 200 to let client parse JSON

    # Determine user_id (fallback to first user)
    uid_hdr = request.headers.get('X-User-Id')
    if uid_hdr and uid_hdr.isdigit():
        uid = int(uid_hdr)
    else:
        first = User.query.first()
        if first:
            uid = first.id
        else:
            # create default user if none exist
            default = User(username='guest', password='', role='employee')
            db.session.add(default)
            db.session.commit()
            uid = default.id
    try:
        parsed = datetime.fromisoformat(dt)
    except Exception:
        return jsonify({'error': 'Invalid datetime format'}), 400
    date_str = parsed.strftime('%Y-%m-%d')
    time_str = parsed.strftime('%H:%M')
    appo = Appointment(user_id=uid, date=date_str, time=time_str, service=desc)
    db.session.add(appo)
    db.session.commit()
    return jsonify({'id': appo.id, 'userId': appo.user_id, 'datetime': f"{appo.date}T{appo.time}", 'description': appo.service}), 201

@app.route('/appointments/<int:app_id>', methods=['PUT','DELETE'])
def modify_appointment(app_id):
    if request.method == 'DELETE':
        a = Appointment.query.get(app_id)
        if not a: return jsonify({'error': 'Not found'}), 404
        db.session.delete(a); db.session.commit()
        return jsonify({'success': True}), 200
    # PUT
    a = Appointment.query.get(app_id)
    if not a: return jsonify({'error': 'Not found'}), 404
    data = request.get_json(force=True, silent=True) or {}
    if 'datetime' in data:
        try:
            p = datetime.fromisoformat(data['datetime'])
            a.date = p.strftime('%Y-%m-%d'); a.time = p.strftime('%H:%M')
        except: pass
    a.service = data.get('description', data.get('service', a.service))
    db.session.commit()
    return jsonify({'id': a.id, 'userId': a.user_id, 'datetime': f"{a.date}T{a.time}", 'description': a.service}), 200

# --- Messages ---
@app.route('/messages', methods=['GET','POST'])
def handle_messages():
    if request.method == 'GET':
        msgs = Message.query.order_by(Message.timestamp).all()
        return jsonify([{'id': m.id, 'senderId': m.sender_id, 'content': m.content, 'timestamp': m.timestamp.isoformat()} for m in msgs]), 200
    # POST
    data = request.get_json(force=True, silent=True) or {}
    sid = data.get('senderId'); cnt = data.get('content')
    if not sid or not cnt: return jsonify({'error': 'Missing fields'}), 400
    m = Message(sender_id=sid, content=cnt)
    db.session.add(m); db.session.commit()
    return jsonify({'id': m.id, 'senderId': m.sender_id, 'content': m.content, 'timestamp': m.timestamp.isoformat()}), 201

# --- Predict ---
@app.route('/predict', methods=['POST'])
def predict():
    data = request.get_json(force=True, silent=True)
    return jsonify({'result': 'no image'} if not data else {'result': 'anomaly'})

# --- Run server ---
if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
