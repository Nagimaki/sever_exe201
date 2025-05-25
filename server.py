import os
import datetime
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

# Import Blueprint thanh toán
from server_tri import tri_bp

# --- App & DB setup ---
app = Flask(__name__)
CORS(app)
app.config['SQLALCHEMY_DATABASE_URI']        = os.getenv('DATABASE_URL', 'sqlite:///app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Models ---
class User(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

class Employee(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(120), nullable=False)
    title        = db.Column(db.String(120), nullable=False)
    total_shifts = db.Column(db.Integer, default=0)
    done_shifts  = db.Column(db.Integer, default=0)
    rating       = db.Column(db.Float,   default=0.0)
    on_time      = db.Column(db.Boolean, default=True)

class Appointment(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    user_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date      = db.Column(db.Date,    nullable=False)
    time      = db.Column(db.String(10), nullable=False)
    service   = db.Column(db.String(120), nullable=False)

class Message(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    sender_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content    = db.Column(db.Text,    nullable=False)
    timestamp  = db.Column(db.DateTime, default=datetime.datetime.utcnow)

# --- Create tables if not exist ---
with app.app_context():
    db.create_all()

# --- Auth routes ---
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    email, pwd = data.get('email'), data.get('password')
    if not email or not pwd:
        return jsonify({'success': False, 'message': 'Email & password required'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': 'Email already registered'}), 400
    u = User(email=email, password_hash=generate_password_hash(pwd))
    db.session.add(u)
    db.session.commit()
    return jsonify({'success': True, 'user_id': u.id}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email, pwd = data.get('email'), data.get('password')
    u = User.query.filter_by(email=email).first()
    if u and check_password_hash(u.password_hash, pwd):
        return jsonify({'success': True, 'user_id': u.id}), 200
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

# --- Employee CRUD ---
@app.route('/employees', methods=['GET', 'POST'])
def employees():
    if request.method == 'GET':
        emps = Employee.query.all()
        result = []
        for e in emps:
            percentage = (e.done_shifts / e.total_shifts * 100) if e.total_shifts > 0 else 0
            result.append({
                'id': e.id,
                'name': e.name,
                'title': e.title,
                'totalShifts': e.total_shifts,
                'doneShifts': e.done_shifts,
                'rating': e.rating,
                'onTime': e.on_time,
                'percentage': round(percentage, 1),
            })
        return jsonify(result)

    # POST: create new employee with optional fields
    data = request.get_json() or {}
    e = Employee(
        name         = data.get('name', ''),
        title        = data.get('title', ''),
        total_shifts = data.get('totalShifts', 0),
        done_shifts  = data.get('doneShifts', 0),
        rating       = data.get('rating', 0.0),
        on_time      = data.get('onTime', True),
    )
    db.session.add(e)
    db.session.commit()
    return jsonify({'id': e.id}), 201

@app.route('/employees/<int:emp_id>', methods=['PUT', 'DELETE'])
def modify_employee(emp_id):
    e = Employee.query.get_or_404(emp_id)
    if request.method == 'DELETE':
        db.session.delete(e)
        db.session.commit()
        return '', 204

    # PUT: update allowed fields
    data = request.get_json() or {}
    if 'name' in data:        e.name         = data['name']
    if 'title' in data:       e.title        = data['title']
    if 'totalShifts' in data: e.total_shifts = data['totalShifts']
    if 'doneShifts' in data:  e.done_shifts  = data['doneShifts']
    if 'rating' in data:      e.rating       = data['rating']
    if 'onTime' in data:      e.on_time      = data['onTime']
    db.session.commit()
    return jsonify({'success': True})

# --- Appointment CRUD ---
@app.route('/appointments', methods=['GET', 'POST'])
def appointments():
    if request.method == 'GET':
        appts = Appointment.query.all()
        return jsonify([{
            'id': a.id,
            'user_id': a.user_id,
            'date': a.date.isoformat(),
            'time': a.time,
            'service': a.service
        } for a in appts])
    data = request.get_json() or {}
    a = Appointment(
        user_id = data['user_id'],
        date    = datetime.date.fromisoformat(data['date']),
        time    = data['time'],
        service = data['service']
    )
    db.session.add(a)
    db.session.commit()
    return jsonify({'id': a.id}), 201

@app.route('/appointments/<int:app_id>', methods=['PUT', 'DELETE'])
def modify_appointment(app_id):
    a = Appointment.query.get_or_404(app_id)
    if request.method == 'DELETE':
        db.session.delete(a)
        db.session.commit()
        return '', 204
    data = request.get_json() or {}
    if 'date' in data:
        a.date = datetime.date.fromisoformat(data['date'])
    for f in ('time', 'service'):
        if f in data:
            setattr(a, f, data[f])
    db.session.commit()
    return jsonify({'success': True})

# --- Chat Messages ---
@app.route('/messages', methods=['GET', 'POST'])
def messages():
    if request.method == 'GET':
        msgs = Message.query.order_by(Message.timestamp).all()
        return jsonify([{
            'id': m.id,
            'sender_id': m.sender_id,
            'content': m.content,
            'timestamp': m.timestamp.isoformat()
        } for m in msgs])
    data = request.get_json() or {}
    m = Message(sender_id=data['sender_id'], content=data['content'])
    db.session.add(m)
    db.session.commit()
    return jsonify({'id': m.id}), 201

# --- Image analysis stub ---
@app.route('/predict', methods=['POST'])
def predict():
    data = request.get_json() or {}
    # TODO: integrate real model here
    result = 'anomaly' if 'image' in data else 'no image'
    return jsonify({'result': result})

# --- Đăng ký Blueprint thanh toán ---
# Tất cả route định nghĩa trong server_tri.py sẽ nằm dưới /payment
app.register_blueprint(tri_bp, url_prefix='/payment')

# --- Run ---
if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
