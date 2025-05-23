# server_tri.py
import os
import time
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from payos import PaymentData, PayOS
from flask import Blueprint, request, jsonify
from flask_cors import cross_origin

load_dotenv()

tri_bp = Blueprint('payment', __name__)
payos = PayOS(
    client_id=os.getenv('PAYOS_CLIENT_ID'),
    api_key=os.getenv('PAYOS_API_KEY'),
    checksum_key=os.getenv('PAYOS_CHECKSUM_KEY')
)

HISTORY_FILE = 'history.json'
STATUS_LABELS = {
    'PENDING':  'Đang thanh toán',
    'SUCCESS':  'Thành công',
    'CANCELED': 'Thất bại',
    'FAILED':   'Thất bại',
    'EXPIRED':  'Thất bại'
}

def load_history():
    if os.path.exists(HISTORY_FILE):
        return json.load(open(HISTORY_FILE, 'r', encoding='utf-8'))
    return []

def write_history(data):
    json.dump(data, open(HISTORY_FILE, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

@tri_bp.route('/create', methods=['POST'])
@cross_origin()  # cho phép gọi từ Flutter hoặc web
def create_payment():
    """
    POST /payment/create
    Body JSON: { "amount":5000, "description":"..." }
    Response JSON: { "checkoutUrl":..., "orderCode":..., "paymentLinkId":... }
    """
    body        = request.get_json() or {}
    amount      = body.get('amount', 5000)
    description = body.get('description', 'Demo thanh toán')
    order_code  = int(time.time())

    # Tạo link PayOS, dùng deep-link scheme myapp://…
    pd = PaymentData(
        orderCode   = order_code,
        amount      = amount,
        description = description,
        returnUrl   = f"myapp://payment-success?orderCode={order_code}",
        cancelUrl   = f"myapp://payment-cancel?orderCode={order_code}"
    )
    res = payos.createPaymentLink(pd).to_json()

    # Lưu lịch sử trạng thái PENDING
    now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    history = load_history()
    history.append({
        "paymentLinkId": res["paymentLinkId"],
        "orderCode":      res["orderCode"],
        "amount":         res["amount"],
        "statusCode":     "PENDING",
        "status":         STATUS_LABELS["PENDING"],
        "createdAt":      now_iso
    })
    write_history(history)

    return jsonify({
        "checkoutUrl":   res["checkoutUrl"],
        "orderCode":     order_code,
        "paymentLinkId": res["paymentLinkId"]
    })

@tri_bp.route('/webhook', methods=['POST'])
def webhook():
    """
    POST /payment/webhook
    PayOS sẽ gửi callback khi trạng thái thay đổi
    """
    data    = request.get_json(force=True)
    history = load_history()
    now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'

    for tx in history:
        if tx.get("paymentLinkId") == data.get("paymentLinkId"):
            code = data.get("status")
            tx["statusCode"] = code
            tx["status"]     = STATUS_LABELS.get(code, code)
            tx["updatedAt"]  = now_iso
            break

    write_history(history)
    return '', 200

@tri_bp.route('/history', methods=['GET'])
@cross_origin()
def payment_history():
    """
    GET /payment/history
    Trả về lịch sử, trước đó:
     - expire mọi PENDING >10 phút thành EXPIRED
    """
    history = load_history()
    now     = datetime.utcnow().replace(microsecond=0)
    dirty   = False

    for tx in history:
        created = datetime.fromisoformat(tx["createdAt"].rstrip('Z'))
        if tx["statusCode"] == "PENDING" and now - created > timedelta(minutes=10):
            tx["statusCode"] = "EXPIRED"
            tx["status"]     = STATUS_LABELS["EXPIRED"]
            tx["updatedAt"]  = now.isoformat() + 'Z'
            dirty = True

    if dirty:
        write_history(history)

    return jsonify(history)
