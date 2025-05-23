# entrypoint.py
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from server import app as main_app       # flask app trong server.py
from server_tri import app as tri_app     # flask app trong server_tri.py

# Gắn tri_app vào đường dẫn /payment
# - Mọi route của server.py vẫn như cũ (ở gốc /)
# - Mọi route trong server_tri.py sẽ có tiền tố /payment, ví dụ /payment/create
app = DispatcherMiddleware(main_app, {
    '/payment': tri_app
})
