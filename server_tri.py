import os
import time
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from payos import PaymentData, PayOS
from flask import Flask, Blueprint, request, jsonify, redirect
from flask_cors import CORS, cross_origin

# Load environment variables
load_dotenv()

# PayOS client setup
pos_client = PayOS(
    client_id=os.getenv('PAYOS_CLIENT_ID'),
    api_key=os.getenv('PAYOS_API_KEY'),
    checksum_key=os.getenv('PAYOS_CHECKSUM_KEY')
)

# History storage
HISTORY_FILE = 'history.json'
STATUS_LABELS = {
    'PENDING':  'Đang thanh toán',
    'SUCCESS':  'Thành công',
    'CANCELED': 'Thất bại',
    'FAILED':   'Thất bại',
    'EXPIRED':  'Thất bại'
}

def load_history():
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def write_history(data):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Blueprint for payment routes
payment_bp = Blueprint('payment', __name__)

@payment_bp.route('/create', methods=['POST'])
@cross_origin()
def create_payment():
    # Build base URL for return/cancel links
    base = request.host_url.rstrip('/')
    body = request.get_json() or {}
    amount = body.get('amount', 5000)
    description = body.get('description', 'Demo thanh toán')
    order_code = int(time.time())

    pd = PaymentData(
        orderCode=order_code,
        amount=amount,
        description=description,
        returnUrl=f"{base}/payment/success?orderCode={order_code}",
        cancelUrl=f"{base}/payment/cancel?orderCode={order_code}"
    )
    res = pos_client.createPaymentLink(pd).to_json()

    # Save initial PENDING status
    now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    history = load_history()
    history.append({
        'paymentLinkId': res['paymentLinkId'],
        'orderCode': res['orderCode'],
        'amount': res['amount'],
        'statusCode': 'PENDING',
        'status': STATUS_LABELS['PENDING'],
        'createdAt': now_iso
    })
    write_history(history)

    return jsonify({
        'checkoutUrl': res['checkoutUrl'],
        'orderCode': order_code,
        'paymentLinkId': res['paymentLinkId']
    })

@payment_bp.route('/success', methods=['GET'])
@cross_origin()
def payment_success():
    # Callback when payment succeeds
    order_code = request.args.get('orderCode')
    history = load_history()
    now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    for tx in history:
        if str(tx.get('orderCode')) == str(order_code):
            tx['statusCode'] = 'SUCCESS'
            tx['status'] = STATUS_LABELS['SUCCESS']
            tx['updatedAt'] = now_iso
            break
    write_history(history)
    return jsonify({'orderCode': order_code, 'status': STATUS_LABELS['SUCCESS']})

@payment_bp.route('/cancel', methods=['GET'])
@cross_origin()
def payment_cancel():
    # Callback when payment is cancelled
    order_code = request.args.get('orderCode')
    history = load_history()
    now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    for tx in history:
        if str(tx.get('orderCode')) == str(order_code):
            tx['statusCode'] = 'CANCELED'
            tx['status'] = STATUS_LABELS['CANCELED']
            tx['updatedAt'] = now_iso
            break
    write_history(history)
    return jsonify({'orderCode': order_code, 'status': STATUS_LABELS['CANCELED']})

@payment_bp.route('/webhook', methods=['POST'])
@cross_origin()
def payment_webhook():
    # Webhook from PayOS when status updates
    data = request.get_json(force=True)
    history = load_history()
    now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    for tx in history:
        if tx.get('paymentLinkId') == data.get('paymentLinkId'):
            code = data.get('status')
            tx['statusCode'] = code
            tx['status'] = STATUS_LABELS.get(code, code)
            tx['updatedAt'] = now_iso
            break
    write_history(history)
    return ('', 200)

@payment_bp.route('/history', methods=['GET'])
@cross_origin()
def payment_history():
    # Return transaction history and expire old PENDING
    history = load_history()
    now = datetime.utcnow().replace(microsecond=0)
    dirty = False
    for tx in history:
        if tx.get('statusCode') == 'PENDING':
            created = datetime.fromisoformat(tx['createdAt'].rstrip('Z'))
            if now - created > timedelta(minutes=10):
                tx['statusCode'] = 'EXPIRED'
                tx['status'] = STATUS_LABELS['EXPIRED']
                tx['updatedAt'] = now.isoformat() + 'Z'
                dirty = True
    if dirty:
        write_history(history)
    return jsonify(history)


def create_app():
    app = Flask(__name__)
    CORS(app)
    app.register_blueprint(payment_bp, url_prefix='/payment')
    return app

# Application entry point
a
app = create_app()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
