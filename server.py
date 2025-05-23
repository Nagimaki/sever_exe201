import os
import datetime
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from server_tri import tri_bp  
# --- App & DB setup ---
app = Flask(__name__)
CORS(app)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.register_blueprint(tri_bp, url_prefix='/payment')
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
    rating       = db.Column(db.Float, default=0.0)
    on_time      = db.Column(db.Boolean, default=True)

class Appointment(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    user_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date      = db.Column(db.Date, nullable=False)
    time      = db.Column(db.String(10), nullable=False)
    service   = db.Column(db.String(120), nullable=False)

class Message(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    sender_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content    = db.Column(db.Text, nullable=False)
    timestamp  = db.Column(db.DateTime, default=datetime.datetime.utcnow)

# --- Create tables at import time ---
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
    db.session.add(u); db.session.commit()
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
        return jsonify([{
            'id': e.id, 'name': e.name, 'title': e.title,
            'total_shifts': e.total_shifts, 'done_shifts': e.done_shifts,
            'rating': e.rating, 'on_time': e.on_time
        } for e in emps])
    data = request.get_json() or {}
    e = Employee(**{k: data[k] for k in ('name','title') if k in data})
    db.session.add(e); db.session.commit()
    return jsonify({'id': e.id}), 201

@app.route('/employees/<int:emp_id>', methods=['PUT','DELETE'])
def modify_employee(emp_id):
    e = Employee.query.get_or_404(emp_id)
    if request.method == 'DELETE':
        db.session.delete(e); db.session.commit()
        return '', 204
    data = request.get_json() or {}
    for f in ('name','title','total_shifts','done_shifts','rating','on_time'):
        if f in data:
            setattr(e, f, data[f])
    db.session.commit()
    return jsonify({'success': True})

# --- Appointment CRUD ---
@app.route('/appointments', methods=['GET','POST'])
def appointments():
    if request.method == 'GET':
        appts = Appointment.query.all()
        return jsonify([{
            'id': a.id, 'user_id': a.user_id,
            'date': a.date.isoformat(), 'time': a.time, 'service': a.service
        } for a in appts])
    data = request.get_json() or {}
    a = Appointment(
        user_id = data['user_id'],
        date    = datetime.date.fromisoformat(data['date']),
        time    = data['time'],
        service = data['service']
    )
    db.session.add(a); db.session.commit()
    return jsonify({'id': a.id}), 201

@app.route('/appointments/<int:app_id>', methods=['PUT','DELETE'])
def modify_appointment(app_id):
    a = Appointment.query.get_or_404(app_id)
    if request.method == 'DELETE':
        db.session.delete(a); db.session.commit()
        return '', 204
    data = request.get_json() or {}
    if 'date' in data:
        a.date = datetime.date.fromisoformat(data['date'])
    for f in ('time','service'):
        if f in data:
            setattr(a, f, data[f])
    db.session.commit()
    return jsonify({'success': True})

# --- Chat ---
@app.route('/messages', methods=['GET','POST'])
def messages():
    if request.method == 'GET':
        msgs = Message.query.order_by(Message.timestamp).all()
        return jsonify([{
            'id': m.id, 'sender_id': m.sender_id,
            'content': m.content, 'timestamp': m.timestamp.isoformat()
        } for m in msgs])
    data = request.get_json() or {}
    m = Message(sender_id=data['sender_id'], content=data['content'])
    db.session.add(m); db.session.commit()
    return jsonify({'id': m.id}), 201

# --- Image analysis stub ---
@app.route('/predict', methods=['POST'])
def predict():
    data = request.get_json() or {}
    # TODO: integrate real model here
    result = 'anomaly' if 'image' in data else 'no image'
    return jsonify({'result': result})

# --- Run ---
if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
