# server.py

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime
import os

app = Flask(__name__)
CORS(app)

# --- Cấu hình DB ---
base_dir = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(base_dir, 'app.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# --- Models ---
class User(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role     = db.Column(db.String(20), nullable=False)  # 'admin' hoặc 'employee'

class Employee(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name         = db.Column(db.String(100), nullable=False)
    title        = db.Column(db.String(100), nullable=False)
    total_shifts = db.Column(db.Integer, default=0)
    done_shifts  = db.Column(db.Integer, default=0)
    rating       = db.Column(db.Float,   default=0.0)
    on_time      = db.Column(db.Boolean, default=False)

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

# Tạo các bảng nếu chưa có
with app.app_context():
    db.create_all()

# --- Các decorator xác thực (ví dụ) ---
def require_admin(fn):
    def wrapper(*args, **kwargs):
        uid  = request.headers.get('X-User-Id')
        user = User.query.get(int(uid)) if uid and uid.isdigit() else None
        if not user or user.role != 'admin':
            return jsonify({'error': 'Forbidden'}), 403
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper

# --- User / Employee CRUD (giữ nguyên) ---
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    user = User.query.filter_by(
        username=data.get("username"),
        password=data.get("password")
    ).first()
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401
    return jsonify({
        "userId":  user.id,
        "userName": user.username,
        "role":    user.role,
        "success": True
    }), 200

@app.route("/employees", methods=["GET"])
@require_admin
def list_employees():
    emps = Employee.query.all()
    return jsonify([{
        "id":         e.id,
        "userId":     e.user_id,
        "name":       e.name,
        "title":      e.title,
        "totalShifts": e.total_shifts,
        "doneShifts": e.done_shifts,
        "rating":     e.rating,
        "onTime":     e.on_time
    } for e in emps]), 200

@app.route("/employees", methods=["POST"])
@require_admin
def create_employee():
    data = request.get_json() or {}
    # ... tương tự create user + employee
    # Giữ nguyên code cũ của bạn
    return jsonify({"success": True}), 200

# ... các route PUT/Delete employee giữ nguyên

# --- Appointment endpoints (đã chỉnh để khớp testapp.html) ---
@app.route("/appointments", methods=["GET"])
def get_appointments():
    """
    GET /appointments
    Nếu client có header X-User-Id: trả về chỉ của user đó
    Kết quả: [ { id, userId, datetime, description } ]
    """
    uid = request.headers.get("X-User-Id") or request.args.get("userId")
    query = Appointment.query
    if uid and uid.isdigit():
        query = query.filter_by(user_id=int(uid))
    apps = query.order_by(Appointment.id.asc()).all()

    return jsonify([{
        "id":          a.id,
        "userId":      a.user_id,
        "datetime":    f"{a.date}T{a.time}",
        "description": a.service
    } for a in apps]), 200

@app.route("/appointments", methods=["POST"])
def create_appointment():
    """
    POST /appointments
    Body JSON: { datetime: "YYYY-MM-DDTHH:MM", description: "..." }
    Hoặc fallback nhận date, time, service (giữ backward)
    """
    data = request.get_json() or {}
    uid  = request.headers.get("X-User-Id") or data.get("userId")
    dt   = data.get("datetime")
    desc = data.get("description") or data.get("service")

    if not uid or not uid.isdigit() or not desc or not dt:
        return jsonify({"error": "Missing fields"}), 400

    try:
        parsed = datetime.fromisoformat(dt)
    except ValueError:
        return jsonify({"error": "Invalid datetime format"}), 400

    date_str = parsed.strftime("%Y-%m-%d")
    time_str = parsed.strftime("%H:%M")

    new_app = Appointment(
        user_id = int(uid),
        date    = date_str,
        time    = time_str,
        service = desc
    )
    db.session.add(new_app)
    db.session.commit()

    return jsonify({
        "id":          new_app.id,
        "userId":      new_app.user_id,
        "datetime":    f"{new_app.date}T{new_app.time}",
        "description": new_app.service
    }), 201

@app.route("/appointments/<int:app_id>", methods=["PUT"])
def update_appointment(app_id):
    a = Appointment.query.get(app_id)
    if not a:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json() or {}
    a.service = data.get("description", data.get("service", a.service))
    # bạn có thể cho cập nhật datetime tương tự
    db.session.commit()
    return jsonify({"success": True}), 200

@app.route("/appointments/<int:app_id>", methods=["DELETE"])
def delete_appointment(app_id):
    a = Appointment.query.get(app_id)
    if not a:
        return jsonify({"error": "Not found"}), 404
    db.session.delete(a)
    db.session.commit()
    return jsonify({"success": True}), 200

# --- Message endpoints (giữ nguyên) ---
@app.route("/messages", methods=["GET"])
def get_messages():
    msgs = Message.query.order_by(Message.timestamp.asc()).all()
    return jsonify([{
        "id":        m.id,
        "senderId":  m.sender_id,
        "content":   m.content,
        "timestamp": m.timestamp.isoformat()
    } for m in msgs]), 200

@app.route("/messages", methods=["POST"])
def create_message():
    data      = request.get_json() or {}
    sender_id = data.get("senderId")
    content   = data.get("content")
    if not sender_id or not content:
        return jsonify({"error": "Missing fields"}), 400

    new_msg = Message(sender_id=sender_id, content=content)
    db.session.add(new_msg)
    db.session.commit()
    return jsonify({
        "id":        new_msg.id,
        "senderId":  new_msg.sender_id,
        "content":   new_msg.content,
        "timestamp": new_msg.timestamp.isoformat()
    }), 201

# --- Predict endpoint (giữ nguyên) ---
@app.route("/predict", methods=["POST"])
def predict():
    data = request.get_json()
    if not data:
        return jsonify({"result": "no image"}), 200
    return jsonify({"result": "anomaly"}), 200

if __name__ == "__main__":
    port = int(os.getenv('PORT', 8080))
    app.run(host="0.0.0.0", port=port)
