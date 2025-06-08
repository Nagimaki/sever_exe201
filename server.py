import os
import time
import json
import logging
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, request, jsonify, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS, cross_origin
import jwt
from werkzeug.security import generate_password_hash, check_password_hash
from payos import PaymentData, PayOS

# --- Setup ---
logging.basicConfig(level=logging.INFO)
load_dotenv()
app = Flask(__name__)
CORS(app)

# JWT Secret Key
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'super-secret-key')

# --- PayOS Configuration & Payment History Utils ---
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

HISTORY_FILE  = 'history.json'
STATUS_LABELS = {
    'PENDING': 'Chờ thanh toán',
    'SUCCESS': 'Thanh toán thành công',
    'FAILED':  'Thanh toán thất bại'
}

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def write_history(data):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- Authentication Decorators ---
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', None)
        if not auth or not auth.startswith('Bearer '):
            return jsonify({'error': 'Token is missing'}), 401
        token = auth.split()[1]
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            request.user = data
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except Exception:
            return jsonify({'error': 'Invalid token'}), 401
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    @wraps(f)
    @token_required
    def decorated(*args, **kwargs):
        if request.user.get('role') != 'admin':
            return jsonify({'error': 'Admin privilege required'}), 403
        return f(*args, **kwargs)
    return decorated

# --- Database setup & Models ---
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class User(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role     = db.Column(db.String(20), nullable=False)

class Employee(db.Model):
    id      = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name    = db.Column(db.String(100), nullable=False)
    title   = db.Column(db.String(100), nullable=False)

class Appointment(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    user_id  = db.Column(db.Integer, nullable=False)
    date     = db.Column(db.String(20), nullable=False)  # 'YYYY-MM-DD'
    time     = db.Column(db.String(20), nullable=False)  # 'HH:MM'
    service  = db.Column(db.String(200), nullable=False)

class Message(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, nullable=False)
    content   = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# --- User Endpoints ---
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json(force=True, silent=True) or {}
    username = data.get('username')
    password = data.get('password')
    role     = data.get('role', 'user')
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already exists'}), 409
    hashed = generate_password_hash(password)
    user = User(username=username, password=hashed, role=role)
    db.session.add(user)
    db.session.commit()
    return jsonify({'message': 'User registered'}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(force=True, silent=True) or {}
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({'error': 'Invalid credentials'}), 401
    payload = {
        'id': user.id,
        'username': user.username,
        'role': user.role,
        'exp': datetime.utcnow() + timedelta(hours=24)
    }
    token = jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')
    return jsonify({'token': token}), 200

# --- Employee Endpoints ---
@app.route('/employees', methods=['GET'])
@require_admin
def list_employees():
    emps = Employee.query.all()
    return jsonify([{'id': e.id, 'user_id': e.user_id, 'name': e.name, 'title': e.title} for e in emps]), 200

@app.route('/employees', methods=['POST'])
@require_admin
def create_employee():
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get('user_id')
    name    = data.get('name')
    title   = data.get('title')
    if not user_id or not name or not title:
        return jsonify({'error': 'Missing fields'}), 400
    emp = Employee(user_id=user_id, name=name, title=title)
    db.session.add(emp)
    db.session.commit()
    return jsonify({'id': emp.id, 'user_id': emp.user_id, 'name': emp.name, 'title': emp.title}), 201

@app.route('/employees/<int:emp_id>', methods=['DELETE'])
@require_admin
def delete_employee(emp_id):
    emp = Employee.query.get(emp_id)
    if not emp:
        return jsonify({'error': 'Not found'}), 404
    db.session.delete(emp)
    db.session.commit()
    return jsonify({'success': True}), 200

# --- Appointment Endpoints ---
@app.route('/appointments', methods=['GET'])
@cross_origin()
def get_appointments():
    apps = Appointment.query.order_by(Appointment.id).all()
    return jsonify([
        {'id': a.id, 'user_id': a.user_id, 'date': a.date, 'time': a.time, 'service': a.service}
        for a in apps
    ]), 200

@app.route('/appointments', methods=['POST'])
@cross_origin()
def create_appointment():
    data    = request.get_json(force=True, silent=True) or {}
    user_id = data.get('user_id')
    date    = data.get('date')
    time_   = data.get('time')
    service = data.get('service')
    if not user_id or not date or not time_ or not service:
        return jsonify({'error': 'Missing fields'}), 400
    try:
        datetime.strptime(date, '%Y-%m-%
