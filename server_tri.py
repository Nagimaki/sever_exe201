# server_tri.py
import os
import time
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from payos import PaymentData, PayOS
from flask import Blueprint, request, jsonify, redirect
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
    json.dump(data,
              open(HISTORY_FILE, 'w', encoding='utf-8'),
              ensure_ascii=False,
              indent=2)

@tri_bp.route('/create', methods=['POST'])
@cross_origin()
def create_payment():
    """
    Tạo payment link. 
    returnUrl/cancelUrl sẽ redirect về web để cập nhật lịch sử.
    """
    base = request.host_url.rstrip('/')   # https://severexe201-production.up.railway.app
    body        = request.get_json() or {}
    amount      = body.get('amount', 5000)
    description = body.get('description', 'Demo thanh toán')
    order_code  = int(time.time())

    pd = PaymentData(
        orderCode   = order_code,
        amount      = amount,
        description = description,
        # web return URLs
        returnUrl   = f"{base}/payment/success?orderCode={order_code}",
        cancelUrl   = f"{base}/payment/cancel?orderCode={order_code}"
    )
    res = payos.createPaymentLink(pd).to_json()

    # lưu PENDING
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

@tri_bp.route('/success', methods=['GET'])
def payment_success_web():
    """
    PayOS redirect về khi thành công.
    Query: ?orderCode=...
    """
    order_code = request.args.get('orderCode')
    history    = load_history()
    now_iso    = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'

    for tx in history:
        if str(tx.get("orderCode")) == str(order_code):
            tx["statusCode"] = "SUCCESS"
            tx["status"]     = STATUS_LABELS["SUCCESS"]
            tx["updatedAt"]  = now_iso
            break
    write_history(history)

    # Bạn có thể trả JSON hoặc render 1 trang nhỏ:
    return jsonify({
      "orderCode": order_code,
      "status": "Thành công"
    })

@tri_bp.route('/cancel', methods=['GET'])
def payment_cancel_web():
    """
    PayOS redirect về khi hủy.
    """
    order_code = request.args.get('orderCode')
    history    = load_history()
    now_iso    = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'

    for tx in history:
        if str(tx.get("orderCode")) == str(order_code):
            tx["statusCode"] = "CANCELED"
            tx["status"]     = STATUS_LABELS["CANCELED"]
            tx["updatedAt"]  = now_iso
            break
    write_history(history)

    return jsonify({
      "orderCode": order_code,
      "status": "Thất bại"
    })

@tri_bp.route('/webhook', methods=['POST'])
def webhook():
    """
    PayOS callback khi status thay đổi.
    Bạn có thể dùng webhook thay vì /success để update.
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
    Lấy lịch sử, expire PENDING > 10 phút.
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
