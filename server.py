from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import datetime

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
CORS(app)

db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(100))
    total_shifts = db.Column(db.Integer, default=0)
    done_shifts = db.Column(db.Integer, default=0)
    rating = db.Column(db.Float, default=0.0)
    on_time = db.Column(db.Boolean, default=True)

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.String(10), nullable=False)
    service = db.Column(db.String(100), nullable=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)

# Routes
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    user = User.query.filter_by(email=data.get('email')).first()
    if user and user.check_password(data.get('password')):
        return jsonify({'success': True, 'user_id': user.id}), 200
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if User.query.filter_by(email=data.get('email')).first():
        return jsonify({'success': False, 'message': 'Email already registered'}), 400
    user = User(email=data.get('email'))
    user.set_password(data.get('password'))
    db.session.add(user)
    db.session.commit()
    return jsonify({'success': True, 'user_id': user.id}), 201

@app.route('/employees', methods=['GET', 'POST'])
def employees():
    if request.method == 'GET':
        emps = Employee.query.all()
        return jsonify([
            {'id': e.id, 'name': e.name, 'title': e.title,
             'total_shifts': e.total_shifts, 'done_shifts': e.done_shifts,
             'rating': e.rating, 'on_time': e.on_time}
            for e in emps
        ])
    data = request.get_json()
    emp = Employee(name=data.get('name'), title=data.get('title'))
    db.session.add(emp)
    db.session.commit()
    return jsonify({'success': True, 'id': emp.id}), 201

@app.route('/employees/<int:emp_id>', methods=['PUT', 'DELETE'])
def modify_employee(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    if request.method == 'PUT':
        data = request.get_json()
        for field in ['name', 'title', 'total_shifts', 'done_shifts', 'rating', 'on_time']:
            if field in data:
                setattr(emp, field, data[field])
        db.session.commit()
        return jsonify({'success': True}), 200
    db.session.delete(emp)
    db.session.commit()
    return jsonify({'success': True}), 200

@app.route('/appointments', methods=['GET', 'POST'])
def appointments():
    if request.method == 'GET':
        appts = Appointment.query.all()
        return jsonify([
            {'id': a.id, 'user_id': a.user_id,
             'date': a.date.isoformat(), 'time': a.time, 'service': a.service}
            for a in appts
        ])
    data = request.get_json()
    appt = Appointment(
        user_id=data.get('user_id'),
        date=datetime.date.fromisoformat(data.get('date')),
        time=data.get('time'),
        service=data.get('service')
    )
    db.session.add(appt)
    db.session.commit()
    return jsonify({'success': True, 'id': appt.id}), 201

@app.route('/appointments/<int:appt_id>', methods=['PUT', 'DELETE'])
def modify_appointment(appt_id):
    appt = Appointment.query.get_or_404(appt_id)
    if request.method == 'PUT':
        data = request.get_json()
        if 'date' in data:
            appt.date = datetime.date.fromisoformat(data['date'])
        if 'time' in data:
            appt.time = data['time']
        if 'service' in data:
            appt.service = data['service']
        db.session.commit()
        return jsonify({'success': True}), 200
    db.session.delete(appt)
    db.session.commit()
    return jsonify({'success': True}), 200

@app.route('/messages', methods=['GET', 'POST'])
def messages():
    if request.method == 'GET':
        msgs = Message.query.order_by(Message.timestamp).all()
        return jsonify([
            {'id': m.id, 'sender_id': m.sender_id,
             'content': m.content, 'timestamp': m.timestamp.isoformat()}
            for m in msgs
        ])
    data = request.get_json()
    msg = Message(sender_id=data.get('sender_id'), content=data.get('content'))
    db.session.add(msg)
    db.session.commit()
    return jsonify({'success': True, 'id': msg.id}), 201

if __name__ == '__main__':
    # Create tables within app context
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
