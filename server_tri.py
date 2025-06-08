# server_tri.py

import os
import time
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from payos import PaymentData, PayOS
from flask import Flask, request, jsonify, redirect
from flask_cors import CORS, cross_origin

load_dotenv()

app = Flask(__name__)
CORS(app)  # cho phép tất cả các route bên dưới cross-origin

# Khởi tạo PayOS SDK
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

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def write_history(data):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/create', methods=['POST'])
@cross_origin()
def create_payment():
    """
    Tạo payment link qua PayOS.
    Trả về JSON: { checkoutUrl, orderCode, paymentLinkId }
    """
    body        = request.get_json() or {}
    amount      = body.get('amount', 5000)
    description = body.get('description', 'Demo thanh toán')
    order_code  = f"ORDER-{int(time.time())}"

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

    # Lưu lịch sử
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

@app.route('/history', methods=['GET'])
@cross_origin()
def payment_history():
    """
    Trả về toàn bộ lịch sử payments (cập nhật trạng thái EXPIRED nếu PENDING >10′).
    """
    history = load_history()
    now     = datetime.utcnow().replace(microsecond=0)
    dirty   = False

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

    # gán thêm label cho mỗi đối tượng
    for tx in history:
        tx['statusLabel'] = STATUS_LABELS.get(tx['statusCode'], tx['statusCode'])

    return jsonify(history), 200

@app.route('/success', methods=['GET'])
def payment_success_web():
    """
    PayOS redirect khi thành công: ?orderCode=...
    """
    order_code = request.args.get('orderCode')
    history    = load_history()
    now_iso    = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    for tx in history:
        if str(tx.get('orderCode')) == str(order_code):
            tx['statusCode'] = 'SUCCESS'
            tx['status']     = STATUS_LABELS['SUCCESS']
            tx['updatedAt']  = now_iso
            break
    write_history(history)
    # Bạn có thể redirect về frontend success page
    return redirect(os.getenv('FRONTEND_SUCCESS_URL', '/')), 302

@app.route('/cancel', methods=['GET'])
def payment_cancel_web():
    """
    PayOS redirect khi huỷ: ?orderCode=...
    """
    order_code = request.args.get('orderCode')
    history    = load_history()
    now_iso    = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    for tx in history:
        if str(tx.get('orderCode')) == str(order_code):
            tx['statusCode'] = 'CANCELED'
            tx['status']     = STATUS_LABELS['CANCELED']
            tx['updatedAt']  = now_iso
            break
    write_history(history)
    return redirect(os.getenv('FRONTEND_CANCEL_URL', '/')), 302

@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Webhook từ PayOS cập nhật status.
    """
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

if __name__ == '__main__':
    # Chạy độc lập nếu cần
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
