# server.py

from flask import Flask, request, jsonify, Blueprint
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
CORS(app)

# --- Cấu hình database ---
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"  # (ví dụ)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


# --- Model User (thêm trường role) ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="employee")
    # Nếu muốn, có thể định nghĩa thêm quan hệ tới Employee
    # employee = db.relationship("Employee", backref="user", uselist=False)


# --- Model Employee (giữ nguyên, nhưng nên có user_id) ---
class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    total_shifts = db.Column(db.Integer, default=0)
    done_shifts = db.Column(db.Integer, default=0)
    rating = db.Column(db.Float, default=0.0)
    on_time = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "userId": self.user_id,
            "name": self.name,
            "title": self.title,
            "totalShifts": self.total_shifts,
            "doneShifts": self.done_shifts,
            "rating": self.rating,
            "onTime": self.on_time
        }


# --- Model Appointment ---
class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    date = db.Column(db.String(20), nullable=False)
    time = db.Column(db.String(20), nullable=False)
    service = db.Column(db.String(100), nullable=False)


# --- Model Message ---
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, nullable=False)
    content = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


# --- Khởi tạo database (nếu cần) ---
with app.app_context():
    db.create_all()


# --- Helper: kiểm tra role (chỉ ví dụ) ---
def require_manager(f):
    def wrapper(*args, **kwargs):
        user_id = request.headers.get("X-User-Id")
        if not user_id:
            return jsonify({"error": "Missing user ID"}), 401
        user = User.query.get(int(user_id))
        if not user or user.role != "manager":
            return jsonify({"error": "Unauthorized"}), 403
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper


# --- Route: Đăng ký (POST /register) ---
@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    # Nếu muốn, có thể cho phép truyền role từ client (nhưng chỉ admin có thể tạo manager)
    # role = data.get("role", "employee")
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Username already exists"}), 409

    new_user = User(
        username=username,
        password=password,
        role="employee"  # mặc định tạo user với role employee
    )
    db.session.add(new_user)
    db.session.commit()

    # Tạo luôn bản ghi Employee (liên kết qua user_id)
    new_emp = Employee(
        user_id=new_user.id,
        name=username,
        title="Nhân viên",  # mặc định title, có thể chỉnh sau
        total_shifts=0,
        done_shifts=0,
        rating=0.0,
        on_time=True
    )
    db.session.add(new_emp)
    db.session.commit()

    return jsonify({
        "success": True,
        "userId": new_user.id,
        "userName": new_user.username,
        "role": new_user.role
    }), 201


# --- Route: Đăng nhập (POST /login) ---
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    user = User.query.filter_by(username=username, password=password).first()
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401

    # Trả về role để frontend phân quyền
    return jsonify({
        "success": True,
        "userId": user.id,
        "userName": user.username,
        "role": user.role
    }), 200


# --- Route: Lấy tất cả nhân viên (GET /employees) ---
@app.route("/employees", methods=["GET"])
@require_manager
def get_all_employees():
    emps = Employee.query.all()
    return jsonify([e.to_dict() for e in emps]), 200


# --- Route: Lấy thông tin nhân viên theo user_id (GET /employees/<user_id>) ---
@app.route("/employees/<int:user_id>", methods=["GET"])
def get_employee_by_user(user_id):
    emp = Employee.query.filter_by(user_id=user_id).first()
    if not emp:
        return jsonify({"error": "Employee not found"}), 404
    return jsonify(emp.to_dict()), 200


# --- Route: Tạo nhân viên mới (POST /employees) ---
@app.route("/employees", methods=["POST"])
@require_manager
def create_employee():
    data = request.get_json()
    name = data.get("name")
    title = data.get("title")
    total_shifts = data.get("totalShifts", 0)
    done_shifts = data.get("doneShifts", 0)
    rating = data.get("rating", 0.0)
    on_time = data.get("onTime", True)
    user_id = data.get("userId", None)  # nếu muốn liên kết với User

    if not name or not title:
        return jsonify({"error": "Name and title required"}), 400

    new_emp = Employee(
        user_id=user_id,
        name=name,
        title=title,
        total_shifts=total_shifts,
        done_shifts=done_shifts,
        rating=rating,
        on_time=on_time
    )
    db.session.add(new_emp)
    db.session.commit()
    return jsonify(new_emp.to_dict()), 201


# --- Route: Cập nhật nhân viên (PUT /employees/<id>) ---
@app.route("/employees/<int:emp_id>", methods=["PUT"])
@require_manager
def update_employee(emp_id):
    emp = Employee.query.get(emp_id)
    if not emp:
        return jsonify({"error": "Employee not found"}), 404

    data = request.get_json()
    emp.name = data.get("name", emp.name)
    emp.title = data.get("title", emp.title)
    emp.total_shifts = data.get("totalShifts", emp.total_shifts)
    emp.done_shifts = data.get("doneShifts", emp.done_shifts)
    emp.rating = data.get("rating", emp.rating)
    emp.on_time = data.get("onTime", emp.on_time)
    db.session.commit()
    return jsonify(emp.to_dict()), 200


# --- Route: Xóa nhân viên (DELETE /employees/<id>) ---
@app.route("/employees/<int:emp_id>", methods=["DELETE"])
@require_manager
def delete_employee(emp_id):
    emp = Employee.query.get(emp_id)
    if not emp:
        return jsonify({"error": "Employee not found"}), 404
    db.session.delete(emp)
    db.session.commit()
    return jsonify({"success": True}), 200


# --- Routes Appointment CRUD (giữ nguyên) ---
@app.route("/appointments", methods=["GET"])
def get_appointments():
    apps = Appointment.query.all()
    return jsonify([{
        "id": a.id,
        "userId": a.user_id,
        "date": a.date,
        "time": a.time,
        "service": a.service
    } for a in apps]), 200


@app.route("/appointments", methods=["POST"])
def create_appointment():
    data = request.get_json()
    user_id = data.get("userId")
    date = data.get("date")
    time = data.get("time")
    service = data.get("service")
    if not user_id or not date or not time or not service:
        return jsonify({"error": "Missing fields"}), 400
    new_app = Appointment(
        user_id=user_id,
        date=date,
        time=time,
        service=service
    )
    db.session.add(new_app)
    db.session.commit()
    return jsonify({
        "id": new_app.id,
        "userId": new_app.user_id,
        "date": new_app.date,
        "time": new_app.time,
        "service": new_app.service
    }), 201


@app.route("/appointments/<int:app_id>", methods=["PUT"])
def update_appointment(app_id):
    a = Appointment.query.get(app_id)
    if not a:
        return jsonify({"error": "Appointment not found"}), 404
    data = request.get_json()
    a.date = data.get("date", a.date)
    a.time = data.get("time", a.time)
    a.service = data.get("service", a.service)
    db.session.commit()
    return jsonify({
        "id": a.id,
        "userId": a.user_id,
        "date": a.date,
        "time": a.time,
        "service": a.service
    }), 200


@app.route("/appointments/<int:app_id>", methods=["DELETE"])
def delete_appointment(app_id):
    a = Appointment.query.get(app_id)
    if not a:
        return jsonify({"error": "Appointment not found"}), 404
    db.session.delete(a)
    db.session.commit()
    return jsonify({"success": True}), 200


# --- Routes Message (giữ nguyên) ---
@app.route("/messages", methods=["GET"])
def get_messages():
    msgs = Message.query.order_by(Message.timestamp.asc()).all()
    return jsonify([{
        "id": m.id,
        "senderId": m.sender_id,
        "content": m.content,
        "timestamp": m.timestamp.isoformat()
    } for m in msgs]), 200


@app.route("/messages", methods=["POST"])
def create_message():
    data = request.get_json()
    sender_id = data.get("senderId")
    content = data.get("content")
    if not sender_id or not content:
        return jsonify({"error": "Missing fields"}), 400
    new_msg = Message(sender_id=sender_id, content=content)
    db.session.add(new_msg)
    db.session.commit()
    return jsonify({
        "id": new_msg.id,
        "senderId": new_msg.sender_id,
        "content": new_msg.content,
        "timestamp": new_msg.timestamp.isoformat()
    }), 201


# --- Route Predict (giữ nguyên stub) ---
@app.route("/predict", methods=["POST"])
def predict():
    # Đây là stub; giả sử nhận {"content": "..."} hoặc ảnh base64
    data = request.get_json()
    if not data:
        return jsonify({"result": "no image"}), 200
    # Luồng xử lý phân tích ảnh, text... ở đây (hiện tại trả dummy)
    return jsonify({"result": "anomaly"}), 200


# --- Chạy app (chỉ cho dev) ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
