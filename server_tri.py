from flask import Blueprint, request, jsonify
import os, time, json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from payos import PaymentData, PayOS

load_dotenv()
tri_bp = Blueprint('tri', __name__)

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
    json.dump(data, open(HISTORY_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

# --- Tạo Payment Link ---
@app.route('/payment/create', methods=['POST'])
def create_payment():
    """
    Body JSON: { "amount": 5000, "description": "..." }
    Response JSON: { "checkoutUrl": "...", "orderCode": 1234567890, "paymentLinkId": "..." }
    """
    body = request.get_json() or {}
    amount      = body.get('amount', 5000)
    description = body.get('description', 'Flutter Demo')
    order_code  = int(time.time())  # mã duy nhất

    # Tạo PaymentData, embed deep-link scheme vào returnUrl/cancelUrl
    pd = PaymentData(
        orderCode   = order_code,
        amount      = amount,
        description = description,
        returnUrl   = f"myapp://payment-success?orderCode={order_code}",
        cancelUrl   = f"myapp://payment-cancel?orderCode={order_code}"
    )
    res = payos.createPaymentLink(pd).to_json()

    # Lưu lịch sử mới với trạng thái PENDING
    now = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    history = load_history()
    history.append({
        "paymentLinkId": res["paymentLinkId"],
        "orderCode":      res["orderCode"],
        "amount":         res["amount"],
        "statusCode":     "PENDING",
        "status":         STATUS_LABELS["PENDING"],
        "createdAt":      now
    })
    write_history(history)

    return jsonify({
        "checkoutUrl":   res["checkoutUrl"],
        "orderCode":     order_code,
        "paymentLinkId": res["paymentLinkId"]
    })


# --- Webhook từ PayOS ---
@app.route('/payment/webhook', methods=['POST'])
def webhook():
    """
    Khi PayOS có event SUCCESS/CANCELED sẽ POST về đây.
    """
    data = request.get_json(force=True)
    history = load_history()
    now = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'

    for tx in history:
        if tx.get("paymentLinkId") == data.get("paymentLinkId"):
            code = data.get("status")
            tx["statusCode"] = code
            tx["status"]     = STATUS_LABELS.get(code, code)
            tx["updatedAt"]  = now
            break

    write_history(history)
    return '', 200


# --- Lấy lịch sử giao dịch ---
@app.route('/payment/history', methods=['GET'])
def payment_history():
    """
    Trước khi trả về, expire mọi PENDING > 10 phút thành EXPIRED.
    """
    history = load_history()
    now = datetime.utcnow().replace(microsecond=0)
    dirty = False

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


if __name__ == '__main__':
    # Cho phép override port qua env var PORT nếu cần
    port = int(os.getenv('PORT', 4242))
    app.run(host='0.0.0.0', port=port, debug=True)
