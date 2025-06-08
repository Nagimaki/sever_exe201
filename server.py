# server.py

import os
import time
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask, request, jsonify, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS, cross_origin
from payos import PaymentData, PayOS

# Load environment variables
load_dotenv()

# Instantiate Flask app
app = Flask(__name__)
# Enable CORS for all routes
CORS(app)

# --- PayOS Configuration & Payment Endpoints ---
payos = PayOS(
    client_id    = os.getenv('PAYOS_CLIENT_ID'),
    api_key      = os.getenv('PAYOS_API_KEY'),
    checksum_key = os.getenv('PAYOS_CHECKSUM_KEY')
)

HISTORY_FILE = 'history.json'
STATUS_LABELS = {
    'PENDING':   'Chờ thanh toán',
    'EXPIRED':   'Hết hạn',
    'SUCCESS':   'Thanh toán thành công',
    'CANCELED':  'Đã huỷ'
}

# Helper functions for payment history
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
    body        = request.get_json() or {}
    amount      = body.get('amount')
    description = body.get('description', '')
    if not amount:
        return jsonify({'error': 'Missing amount'}), 400

    # Generate unique order code
    order_code = f"ORDER-{int(time.time())}"
    pd = PaymentData(
        orderCode   = order_code,
        amount      = int(amount),
        currency    = 'VND',
        extra       = {'description': description}
    )
    try:
        res = payos.create_payment_link(pd)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    # Save to local history
    history = load_history()
    now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    history.append({
        'paymentLinkId': res['paymentLinkId'],
        'orderCode':     order_code,
        'amount':        pd.amount,
        'statusCode':    'PENDING',
        'status':        STATUS_LABELS['PENDING'],
        'createdAt':     now_iso
    })
    write_history(history)

    return jsonify({
        'checkoutUrl':   res['checkoutUrl'],
        'orderCode':     order_code,
        'paymentLinkId': res['paymentLinkId']
    }), 200

@app.route('/payment/history', methods=['GET'])
@cross_origin()
def payment_history():
    history = load_history()
    now     = datetime.utcnow().replace(microsecond=0)
    dirty   = False

    # Expire stale payments
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

    # Attach friendly label
    for tx in history:
        tx['statusLabel'] = STATUS_LABELS.get(tx['statusCode'], tx['statusCode'])

    return jsonify(history), 200

# Webhook and redirect endpoints
@app.route('/payment/success', methods=['GET'])
def payment_success():
    order_code = request.args.get('orderCode')
    history    = load_history()
    now_iso    = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
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
    history    = load_history()
    now_iso    = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
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
    payload = request.get_json() or {}
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
    role     = db.Column(db.String(20), nullable=False)  # 'admin' or 'employee'

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

# Create tables
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
    data = request.get_json() or {}
    u = data.get('username','').strip()
    p = data.get('password','').strip()
    if not u or not p:
        return jsonify({'error':'Username and password required'}),400
    if User.query.filter_by(username=u).first():
        return jsonify({'error':'Username exists'}),409
    user = User(username=u,password=p,role='admin')
    db.session.add(user)
    db.session.commit()
    return jsonify({'success':True,'userId':user.id,'userName':user.username,'role':user.role}),201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    u = data.get('username','')
    p = data.get('password','')
    if not u or not p:
        return jsonify({'error':'Required'}),400
    user = User.query.filter_by(username=u,password=p).first()
    if not user:
        return jsonify({'error':'Invalid credentials'}),401
    return jsonify({'success':True,'userId':user.id,'userName':user.username,'role':user.role}),200

# --- Employee CRUD ---
@app.route('/employees', methods=['POST'])
@require_admin
def create_employee():
    data = request.get_json() or {}
    u   = data.get('username','').strip()
    p   = data.get('password','').strip()
    name= data.get('name','').strip()
    t   = data.get('title','').strip()
    if not u or not p or not name or not t:
        return jsonify({'error':'Missing fields'}),400
    if User.query.filter_by(username=u).first():
        return jsonify({'error':'Username exists'}),409
    user= User(username=u,password=p,role='employee')
    db.session.add(user)
    db.session.commit()
    emp=Employee(user_id=user.id,name=name,title=t)
    db.session.add(emp)
    db.session.commit()
    return jsonify(emp.to_dict()),201

@app.route('/employees', methods=['GET'])
@require_admin
def list_employees():
    return jsonify([e.to_dict() for e in Employee.query.all()]),200

@app.route('/employees/<int:user_id>', methods=['GET'])
def get_employee(user_id):
    emp=Employee.query.filter_by(user_id=user_id).first()
    if not emp: return jsonify({'error':'Not found'}),404
    return jsonify(emp.to_dict()),200

@app.route('/employees/<int:emp_id>', methods=['PUT'])
@require_admin
def update_employee(emp_id):
    emp=Employee.query.get(emp_id)
    if not emp: return jsonify({'error':'Not found'}),404
    data=request.get_json() or {}
    emp.name=data.get('name',emp.name)
    emp.title=data.get('title',emp.title)
    emp.total_shifts=data.get('totalShifts',emp.total_shifts)
    emp.done_shifts=data.get('doneShifts',emp.done_shifts)
    emp.rating=data.get('rating',emp.rating)
    emp.on_time=data.get('onTime',emp.on_time)
    db.session.commit()
    return jsonify(emp.to_dict()),200

@app.route('/employees/<int:emp_id>', methods=['DELETE'])
@require_admin
def delete_employee(emp_id):
    emp=Employee.query.get(emp_id)
    if not emp: return jsonify({'error':'Not found'}),404
    user=User.query.get(emp.user_id)
    db.session.delete(emp)
    if user: db.session.delete(user)
    db.session.commit()
    return jsonify({'success':True}),200

# --- Appointments ---
@app.route('/appointments', methods=['GET'])
def get_appointments():
    uid=request.headers.get('X-User-Id') or request.args.get('userId')
    qry=Appointment.query
    if uid and uid.isdigit(): qry=qry.filter_by(user_id=int(uid))
    apps=qry.order_by(Appointment.id).all()
    return jsonify([{ 'id':a.id, 'userId':a.user_id, 'datetime':f"{a.date}T{a.time}", 'description':a.service } for a in apps]),200

@app.route('/appointments', methods=['POST'])
def create_appointment():
    data=request.get_json() or {}
    uid = request.headers.get('X-User-Id') or data.get('userId')
    dt  = data.get('datetime')
    desc= data.get('description') or data.get('service')
    if not uid or not uid.isdigit() or not dt or not desc:
        return jsonify({'error':'Missing fields'}),400
    try:
        p=datetime.fromisoformat(dt)
    except:
        return jsonify({'error':'Invalid datetime format'}),400
    date_str=p.strftime('%Y-%m-%d')
    time_str=p.strftime('%H:%M')
    appo=Appointment(user_id=int(uid), date=date_str, time=time_str, service=desc)
    db.session.add(appo); db.session.commit()
    return jsonify({'id':appo.id,'userId':appo.user_id,'datetime':f"{appo.date}T{appo.time}",'description':appo.service}),201

@app.route('/appointments/<int:app_id>', methods=['PUT'])
def update_appointment(app_id):
    a=Appointment.query.get(app_id)
    if not a: return jsonify({'error':'Not found'}),404
    data=request.get_json() or {}
    if data.get('datetime'):
        try:
            p=datetime.fromisoformat(data['datetime'])
            a.date=p.strftime('%Y-%m-%d'); a.time=p.strftime('%H:%M')
        except: pass
    a.service=data.get('description',data.get('service',a.service))
    db.session.commit()
    return jsonify({'id':a.id,'userId':a.user_id,'datetime':f"{a.date}T{a.time}",'description':a.service}),200

@app.route('/appointments/<int:app_id>', methods=['DELETE'])
def delete_appointment(app_id):
    a=Appointment.query.get(app_id)
    if not a: return jsonify({'error':'Not found'}),404
    db.session.delete(a); db.session.commit()
    return jsonify({'success':True}),200

# --- Messages ---
@app.route('/messages', methods=['GET'])
def get_messages():
    msgs=Message.query.order_by(Message.timestamp).all()
    return jsonify([{'id':m.id,'senderId':m.sender_id,'content':m.content,'timestamp':m.timestamp.isoformat()} for m in msgs]),200

@app.route('/messages', methods=['POST'])
def create_message():
    data=request.get_json() or {}
    sid=data.get('senderId'); cnt=data.get('content')
    if not sid or not cnt: return jsonify({'error':'Missing fields'}),400
    m=Message(sender_id=sid, content=cnt)
    db.session.add(m); db.session.commit()
    return jsonify({'id':m.id,'senderId':m.sender_id,'content':m.content,'timestamp':m.timestamp.isoformat()}),201

# --- Predict ---
@app.route('/predict', methods=['POST'])
def predict():
    data=request.get_json()
    return jsonify({'result':'no image'} if not data else {'result':'anomaly'})

# --- Run server ---
if __name__ == '__main__':
    port=int(os.getenv('PORT',8080))
    app.run(host='0.0.0.0', port=port)
