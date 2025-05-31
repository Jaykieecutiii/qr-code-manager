from flask_mail import Mail, Message # Giữ lại nếu sau này dùng, hoặc xóa nếu không bao giờ dùng nữa
from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash, jsonify, make_response
from captcha.image import ImageCaptcha
import random
import string
import sqlite3
import qrcode
import os
import re
import datetime
from werkzeug.security import generate_password_hash, check_password_hash


def generate_order_code():
    now = datetime.datetime.now()
    return f"ORD-{now.strftime('%Y%m%d-%H%M%S')}-{random.randint(100, 999)}"


def generate_internal_product_id():
    return str(random.randint(100000, 999999))


app = Flask(__name__)
@app.after_request
def add_security_headers(response):
    # Cho phép truy cập camera
    response.headers['Permissions-Policy'] = 'camera=(self)'
    return response

@app.route("/")
def scan_page():
    # Trả về giao diện quét QR
    response = make_response(render_template("mobile_scan_screen.html"))
    return response


app.secret_key = 'your_very_secret_and_complex_key_here_CHANGE_ME'

conn = sqlite3.connect('sales.db', check_same_thread=False) # Nên cân nhắc chuyển 'sales.db' thành biến
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    username TEXT UNIQUE, 
    email TEXT UNIQUE, 
    phone TEXT, 
    password TEXT,
    is_verified BOOLEAN DEFAULT 0 
)
""")

# c.execute("""
# CREATE TABLE IF NOT EXISTS products (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     name TEXT NOT NULL,
#     price REAL DEFAULT 0,
#     qty INTEGER DEFAULT 0,
#     category TEXT,
#     product_id_internal TEXT UNIQUE,
#     date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
#     expiry_date DATE,
#     product_qr_code_path TEXT,
#     barcode_data TEXT,
#     volume_weight TEXT
# """)

c.execute("""
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_code TEXT UNIQUE NOT NULL,
    customer_name TEXT,
    customer_phone TEXT,
    customer_address TEXT,
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'Mới',
    total_amount REAL DEFAULT 0,
    notes TEXT,
    qr_code_path TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER,
    product_id INTEGER,
    product_name TEXT,
    quantity INTEGER,
    price_at_order REAL,
    FOREIGN KEY (order_id) REFERENCES orders (id),
    FOREIGN KEY (product_id) REFERENCES products (id)
)
""")
c.execute("""
CREATE TABLE IF NOT EXISTS scan_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_data TEXT NOT NULL,
    product_id INTEGER, 
    product_name_at_scan TEXT,
    scan_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER,
    action_type TEXT,  
    quantity_changed INTEGER,
    FOREIGN KEY (product_id) REFERENCES products (id),
    FOREIGN KEY (user_id) REFERENCES users (id)
)
""")
conn.commit()

@app.route('/captcha')
def captcha():
    image = ImageCaptcha(width=180, height=70)
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    session['captcha_code'] = code
    data = image.generate(code)
    return send_file(data, mimetype='image/png')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    error = None
    username_value = ''
    if 'username' in session:
        return redirect(url_for('product_dashboard_overview'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        username_value = username

        c.execute("SELECT id, username, password, is_verified FROM users WHERE username=?", (username,))
        user_data = c.fetchone()

        if user_data and check_password_hash(user_data[2], password):
            if user_data[3] == 1:
                session['username'] = user_data[1]
                flash('Đăng nhập thành công!', 'success')
                return redirect(url_for('product_dashboard_overview'))
            else: # Trường hợp is_verified = 0 (nếu bạn dùng lại OTP sau này)
                error = 'Tài khoản của bạn chưa được xác thực.'
        else:
            error = 'Tên tài khoản hoặc mật khẩu không đúng.'
    return render_template('login.html', error=error, username_value=username_value)


def generate_otp(length=6):
    return "".join(random.choices(string.digits, k=length))


@app.route('/register', methods=['GET', 'POST'])
def register():
    error = ''
    if request.method == 'POST':
        form_data = {
            'username': request.form.get('username', ''),
            'email': request.form.get('email', ''),
            'phone': request.form.get('phone', '')
        }
        username = form_data['username']
        email = form_data['email']
        phone = form_data['phone']
        password = request.form.get('password', '')  # Dùng .get để tránh lỗi nếu thiếu
        confirm_password = request.form.get('confirm_password', '')
        captcha_input = request.form.get('captcha', '')
        captcha_session = session.get('captcha_code', '')
    else:
        form_data = {'username': '', 'email': '', 'phone': ''}

    if request.method == 'POST':
        if not username or not email or not password or not confirm_password or not captcha_input:
            error = 'Vui lòng điền đầy đủ các trường bắt buộc.'
        elif password != confirm_password:
            error = 'Mật khẩu không khớp.'
        elif len(password) < 8:
            error = 'Mật khẩu phải có ít nhất 8 ký tự.'
        elif not re.search(r'[A-Z]', password):
            error = 'Mật khẩu phải chứa ít nhất một chữ cái viết hoa.'
        elif not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            error = 'Mật khẩu phải chứa ít nhất một ký tự đặc biệt.'
        elif captcha_input.upper() != captcha_session.upper():
            error = 'Mã captcha không đúng.'

        if not error:
            c.execute("SELECT id FROM users WHERE username=? OR email=?", (username, email))
            existing_user = c.fetchone()
            if existing_user:
                error = 'Tên người dùng hoặc email đã tồn tại.'
            else:
                try:
                    hashed_password = generate_password_hash(password)
                    c.execute(
                        "INSERT INTO users (username, email, phone, password, is_verified) VALUES (?, ?, ?, ?, ?)",
                        (username, email, phone, hashed_password, 1)  # is_verified = 1
                    )
                    conn.commit()

                    session['username'] = username

                    flash('Đăng ký thành công! Bạn đã được đăng nhập.', 'success')

                    return redirect(url_for('product_dashboard_overview'))

                except sqlite3.IntegrityError:
                    error = 'Tên người dùng hoặc email đã tồn tại (lỗi ràng buộc CSDL).'
                    conn.rollback()
                except Exception as e:
                    error = f'Lỗi không xác định trong quá trình đăng ký: {str(e)}'
                    app.logger.error(f"Registration error: {e}")
                    conn.rollback()

    new_captcha_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    session['captcha_code'] = new_captcha_code

    return render_template('register.html', error=error, form_data=form_data)

@app.route('/logout')
def logout():
    session.pop('username', None)
    flash("Bạn đã đăng xuất.", "info")
    return redirect(url_for('index'))

@app.route('/qr-generator-tool', methods=['GET', 'POST'])
def qr_generator_tool():
    # ... (code của bạn)
    if 'username' not in session: return redirect(url_for('login_page'))
    qr_image_path_display = None
    data_generated = None
    if request.method == 'POST':
        data = request.form['data']
        if data:
            img = qrcode.make(data)

            static_dir = os.path.join(os.path.dirname(__file__), 'static')
            if not os.path.exists(static_dir): os.makedirs(static_dir)
            img_path_on_disk = os.path.join(static_dir, 'qr_tool_generated.png')
            img.save(img_path_on_disk)
            qr_image_path_display = 'qr_tool_generated.png' # Sẽ dùng với url_for('static', filename=...)
            data_generated = data
            flash("Mã QR đã được tạo.", "success")
        else:
            flash("Vui lòng nhập dữ liệu để tạo mã QR.", "warning")
    return render_template('qr_tool.html', qr_image_path=qr_image_path_display, data_generated=data_generated)


@app.route('/rename-files-tool', methods=['GET', 'POST'])
def rename_files_tool():
    # ... (code của bạn)
    if 'username' not in session: return redirect(url_for('login_page'))
    # ... (phần còn lại của hàm)
    return render_template('rename_tool.html')


@app.route('/password-generator-tool', methods=['GET', 'POST'])
def password_generator_tool():
    # ... (code của bạn)
    if 'username' not in session: return redirect(url_for('login_page'))
    # ... (phần còn lại của hàm)
    return render_template('password_tool.html')


@app.route('/sales-management-tool', methods=['GET', 'POST'])
def sales_management_tool():
    # ... (code của bạn)
    if 'username' not in session: return redirect(url_for('login_page'))
    # ... (phần còn lại của hàm)
    c.execute("SELECT id, name, price, qty, category FROM products ORDER BY name")
    products_data = c.fetchall()
    products_list = [{'id': p[0], 'name': p[1], 'price': p[2], 'qty': p[3], 'category': p[4]} for p in products_data]
    return render_template('sales_tool.html', products=products_list)

@app.route('/quan-ly-san-pham/')
@app.route('/quan-ly-san-pham/tong-quan')
def product_dashboard_overview():
    if 'username' not in session:
        return redirect(url_for('login_page'))

    return render_template(
        'product_dashboard_content_tongquan.html',
        mobile_nav_type='main_dashboard_nav' # Nav dưới cho trang chính mobile
    )
CATEGORY_DETAILS = {
    "thuc-pham": {
        "display_name": "Hàng Thực phẩm",
        "image_url": "https://png.pngtree.com/thumb_back/fw800/background/20250408/pngtree-aisle-full-of-packaged-food-products-in-supermarket-image_17172476.jpg",
        "description": "Quản lý các mặt hàng thực phẩm..."
    },
    "gia-dung": {
        "display_name": "Đồ gia dụng",
        "image_url": "https://blog.dktcdn.net/files/nguon-hang-do-gia-dung-gia-re-1-e1507186249781.jpg",
        "description": "Quản lý các thiết bị, dụng cụ..."
    },
    "thoi-trang": {
        "display_name": "Thời trang",
        "image_url": "https://spacet-release.s3.ap-southeast-1.amazonaws.com/img/blog/2023-10-03/anh-sang-hop-ly-tao-su-dang-cap-651beab8c9649b0ef5ad95c2.webp",
        "description": "Quản lý các sản phẩm quần áo..."
    },
    "may-tinh-linh-kien": {
        "display_name": "Máy tính & Linh kiện",
        "image_url": "https://maytinhgiaredanang.com/wp-content/uploads/2024/04/ve-sinh-may-tinh-pc-tai-da-nang.jpg",
        "description": "Quản lý máy tính, laptop..."
    }
}


@app.route('/quan-ly-san-pham/danh-muc/<string:category_slug>')
def manage_category_placeholder(category_slug):
    if 'username' not in session:
        return redirect(url_for('login_page'))

    category_info = CATEGORY_DETAILS.get(category_slug)  # Lấy thông tin dựa trên slug

    if not category_info:
        flash("Danh mục không tồn tại.", "danger")
        return redirect(url_for('product_dashboard_overview'))
    print(f"DEBUG: Category Slug: {category_slug}")
    print(f"DEBUG: Category Info: {category_info}")
    print(f"DEBUG: Mobile Nav Type for this page: category_detail_nav")

    return render_template(
        'category_management_page.html',
        category_slug=category_slug,
        category_display_name=category_info["display_name"],
        category_bg_image=category_info["image_url"],
        category_description=category_info["description"],
        page_specific_title=f'{category_info["display_name"]}',

        mobile_nav_type='category_detail_nav'
    )

@app.route('/quan-ly-san-pham/tong-quan/chi-tiet')
def product_dashboard_overview_detail():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    try:
        c.execute("SELECT COUNT(id) FROM products")
        total_products = c.fetchone()[0] or 0
        c.execute("SELECT SUM(qty) FROM products")
        total_items_in_stock = c.fetchone()[0] or 0
        today_str = datetime.date.today().strftime('%Y-%m-%d')
        c.execute("SELECT COUNT(id) FROM orders WHERE DATE(order_date) = ?", (today_str,))
        orders_today = c.fetchone()[0] or 0
        LOW_STOCK_THRESHOLD = 5
        c.execute("SELECT name, qty FROM products WHERE qty > 0 AND qty <= ? ORDER BY qty ASC LIMIT 5", (LOW_STOCK_THRESHOLD,))
        low_stock_products = c.fetchall()
        EXPIRY_ALERT_DAYS = 30
        c.execute(f"""
            SELECT name, expiry_date FROM products 
            WHERE expiry_date IS NOT NULL AND DATE(expiry_date) BETWEEN DATE('now') AND DATE('now', '+{EXPIRY_ALERT_DAYS} days') 
            ORDER BY expiry_date ASC
        """)
        expiring_products = c.fetchall()
        overview_data = {
            'total_products': total_products,
            'total_items_in_stock': total_items_in_stock,
            'orders_today': orders_today,
            'low_stock_products': low_stock_products,
            'expiring_products': expiring_products
        }
        return render_template('product_dashboard_content_tongquan_chitiet.html', overview_data=overview_data)
    except Exception as e:
        app.logger.error(f"Error loading overview detail: {e}")
        flash("Có lỗi xảy ra khi tải trang chi tiết.", "danger")
        return redirect(url_for('product_dashboard_overview'))

@app.route('/quan-ly-san-pham/don-hang/xu-ly')
def pd_don_hang_xu_ly():

    if 'username' not in session: return redirect(url_for('login_page'))

    return render_template('product_dashboard_content_donhang_xuly.html', orders=[])


@app.route('/quan-ly-san-pham/don-hang/nhap', methods=['GET', 'POST'])
def pd_don_hang_nhap():

    if 'username' not in session: return redirect(url_for('login_page'))

    return render_template('product_dashboard_content_donhang_nhap.html')


@app.route('/quan-ly-san-pham/don-hang/gan-qr', methods=['GET', 'POST'])
def pd_don_hang_gan_qr():

    if 'username' not in session: return redirect(url_for('login_page'))

    return render_template('product_dashboard_content_donhang_ganqr.html')


@app.route('/quan-ly-san-pham/ton-kho')
def pd_ton_kho_quan_ly():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    c.execute("""
        SELECT id, name, price, qty, category, product_id_internal, date_added, expiry_date, product_qr_code_path 
        FROM products ORDER BY date_added DESC, name
    """)

    products_list = []
    for p_row in c.fetchall():

        products_list.append({
            'id': p_row[0], 'name': p_row[1], 'price': p_row[2], 'qty': p_row[3], 'category': p_row[4],
            'product_id_internal': p_row[5], 'date_added': p_row[6], 'expiry_date': p_row[7],
            'product_qr_code_path': p_row[8]
        })
    return render_template(
        'product_dashboard_content_tonkho.html',
        products=products_list,
        contextual_sidebar=None,
        mobile_nav_type='main_dashboard_nav'
    )

@app.route('/quan-ly-san-pham/bao-cao')
def pd_bao_cao_xem():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    return render_template(
        'product_dashboard_content_baocao.html',
        mobile_nav_type='main_dashboard_nav'
    )


@app.route('/quan-ly-san-pham/thong-tin-ca-nhan')
def pd_user_profile():

    if 'username' not in session: return redirect(url_for('login_page'))

    return render_template('product_dashboard_content_user_profile.html', user_info=None)


@app.route('/quan-ly-san-pham/nhap-san-pham-moi', methods=['GET', 'POST'])
def pd_nhap_san_pham_moi():

    if 'username' not in session: return redirect(url_for('login_page'))

    if request.method == 'POST':

        product_name = request.form.get('product_name')
        if product_name:

            qr_folder_sp = os.path.join(os.path.dirname(__file__), 'static', 'product_qrcodes')
            if not os.path.exists(qr_folder_sp):
                os.makedirs(qr_folder_sp)

    return render_template('product_dashboard_content_nhap_sanpham.html')


@app.route('/quan-ly-san-pham/nhap-kho-qua-quet')
def pd_nhap_kho_quet_page():
    if 'username' not in session:
        return redirect(url_for('login_page'))

    context_slug_from_url = request.args.get('context_slug')
    nav_type_to_use = 'category_context_nav' if context_slug_from_url else 'main_dashboard_nav'


    return render_template(
        'product_dashboard_content_scan_and_input.html',
        contextual_sidebar='category_management',
        mobile_nav_type=nav_type_to_use,
        category_slug=context_slug_from_url
    )

@app.route('/quan-ly-san-pham/xuat-kho-qua-quet') # Route mới bạn yêu cầu
def pd_xuat_kho_quet_page():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    return render_template('product_dashboard_content_xuatkho_scan.html')


@app.route('/process-scanned-product-barcode', methods=['POST'])
def process_scanned_product_barcode():

    if 'username' not in session: return jsonify({'error': 'Unauthorized'}), 401
    # ... (phần còn lại của hàm)
    return jsonify({'exists_in_db': False})


@app.route('/save-scanned-product-to-inventory', methods=['POST'])
def save_scanned_product_to_inventory():

    if 'username' not in session: return jsonify({'error': 'Unauthorized'}), 401

    if request.method == 'POST':

            qr_folder_sys = os.path.join(os.path.dirname(__file__), 'static', 'product_qrcodes')
            if not os.path.exists(qr_folder_sys): os.makedirs(qr_folder_sys)
        # ...
    # ... (phần còn lại của hàm)
    return jsonify({'error': 'Lỗi không xác định'}), 500


@app.route('/san-pham/qr-info/<product_internal_id>')
def view_product_details_by_qr(product_internal_id):

    return render_template('view_product_by_qr.html', product=None)


@app.route('/api/process-and-log-scan', methods=['POST'])
def process_and_log_scan():
    if 'username' not in session:
        return jsonify({'error': 'Chưa đăng nhập'}), 401

    try:
        data = request.get_json()
        scanned_data = data.get('scanned_data')

        if not scanned_data:
            return jsonify({'error': 'Không có dữ liệu mã quét'}), 400

        c.execute("""
            SELECT id, name, product_id_internal, barcode_data 
            FROM products 
            WHERE product_id_internal = ? OR barcode_data = ?
        """, (scanned_data, scanned_data))
        product = c.fetchone()

        product_id_db = None
        product_name_db = "Không tìm thấy sản phẩm"

        if product:
            product_id_db = product[0]
            product_name_db = product[1]

        user_id = None
        if 'username' in session:
            c.execute("SELECT id FROM users WHERE username = ?", (session['username'],))
            user_obj = c.fetchone()
            if user_obj:
                user_id = user_obj[0]

        c.execute("""
            INSERT INTO scan_log (scanned_data, product_id, product_name_at_scan, user_id)
            VALUES (?, ?, ?, ?)
        """, (scanned_data, product_id_db, product_name_db, user_id))
        conn.commit()

        return jsonify({
            'success': True,
            'scanned_data': scanned_data,
            'product_id': product_id_db,
            'product_name': product_name_db,
            'log_message': 'Đã lưu vào lịch sử quét.'
        }), 200

    except Exception as e:
        app.logger.error(f"Error processing scan: {e}")
        conn.rollback()
        return jsonify({'error': f'Lỗi server: {str(e)}'}), 500


# Trong app.py
@app.route('/api/get-product-info-from-scan', methods=['POST'])
def get_product_info_from_scan():
    if 'username' not in session:  # Đảm bảo người dùng đã đăng nhập
        return jsonify({'error': 'Chưa đăng nhập hoặc phiên hết hạn'}), 401

    data = request.get_json()
    scanned_data = data.get('scanned_data')

    if not scanned_data:
        return jsonify({'error': 'Không nhận được dữ liệu mã quét'}), 400

    app.logger.info(f"API: Yêu cầu thông tin sản phẩm cho mã quét: {scanned_data}")

    # Tra cứu sản phẩm trong bảng products
    # Ưu tiên tìm theo product_id_internal, sau đó là barcode_data, cuối cùng có thể thử tìm theo name
    # (Thứ tự này quan trọng nếu scanned_data có thể là nhiều loại)
    c.execute("""
        SELECT id, name, product_id_internal, barcode_data, price, qty, category, expiry_date 
        FROM products 
        WHERE product_id_internal = ? OR barcode_data = ?
    """, (scanned_data, scanned_data))
    product = c.fetchone()

    if product:
        product_details = {
            'product_id': product[0],
            'product_name': product[1],
            'product_id_internal': product[2],
            'barcode_data': product[3],
            'price': product[4],
            'qty': product[5],
            'category': product[6],
            'expiry_date': product[7].strftime('%Y-%m-%d') if product[7] else None
            # Thêm các trường khác nếu bạn muốn hiển thị
        }
        app.logger.info(f"API: Sản phẩm được tìm thấy: {product_details}")
        return jsonify(product_details), 200  # Trả về toàn bộ thông tin sản phẩm
    else:
        # Nếu không tìm thấy bằng ID hoặc barcode, thử tìm theo tên (nếu mã QR chứa tên)
        c.execute("""
            SELECT id, name, product_id_internal, barcode_data, price, qty, category, expiry_date 
            FROM products 
            WHERE name = ?
        """, (scanned_data,))
        product_by_name = c.fetchone()
        if product_by_name:
            product_details = {
                'product_id': product_by_name[0],
                'product_name': product_by_name[1],
                # ... các trường khác ...
            }
            app.logger.info(f"API: Sản phẩm được tìm thấy theo tên: {product_details}")
            return jsonify(product_details), 200
        else:
            app.logger.warning(f"API: Không tìm thấy sản phẩm cho mã quét: {scanned_data}")
            return jsonify({'error': 'Sản phẩm không tồn tại trong hệ thống'}), 404


@app.route('/api/update-inventory-and-log', methods=['POST'])
def update_inventory_and_log():
    if 'username' not in session:
        return jsonify({'error': 'Chưa đăng nhập'}), 401

    try:
        data = request.get_json()
        app.logger.info(f"API: Update inventory data: {data}")

        scanned_data = data.get('scanned_data')
        product_id = data.get('product_id')
        product_name_at_scan = data.get('product_name')
        action = data.get('action')
        quantity = int(data.get('quantity', 0))

        if not scanned_data or not action or quantity <= 0:
            return jsonify({'error': 'Dữ liệu không hợp lệ (thiếu mã quét, hành động hoặc số lượng <=0)'}), 400

        if not product_id and action == 'xuat':
            return jsonify({'error': 'Sản phẩm không xác định, không thể xuất kho.'}), 400

        if not product_id and action == 'nhap':

            app.logger.warning(f"API: Attempting to stock in an unknown product with scanned_data: {scanned_data}")

            pass

        user_id = None
        c.execute("SELECT id FROM users WHERE username = ?", (session['username'],))
        user_obj = c.fetchone()
        if user_obj: user_id = user_obj[0]

        log_message = ""

        if action == 'nhap' and product_id:
            c.execute("UPDATE products SET qty = qty + ? WHERE id = ?", (quantity, product_id))
            log_message = f"Đã nhập {quantity} sản phẩm '{product_name_at_scan or 'Không rõ'}'."
            app.logger.info(f"API: Stocked in {quantity} for product_id {product_id}")
        elif action == 'xuat' and product_id:  # product_id chắc chắn có ở đây
            c.execute("SELECT qty, name FROM products WHERE id = ?", (product_id,))
            product_in_db = c.fetchone()
            if not product_in_db:
                return jsonify({'error': 'Sản phẩm không tồn tại trong kho để xuất.'}), 404

            current_qty = product_in_db[0]
            actual_product_name = product_in_db[1]
            product_name_at_scan = actual_product_name

            if current_qty < quantity:
                return jsonify(
                    {'error': f"Không đủ số lượng '{product_name_at_scan}' để xuất. Tồn kho: {current_qty}"}), 400

            c.execute("UPDATE products SET qty = qty - ? WHERE id = ?", (quantity, product_id))
            log_message = f"Đã xuất {quantity} sản phẩm '{product_name_at_scan}'."
            app.logger.info(f"API: Stocked out {quantity} for product_id {product_id}")
        elif action == 'nhap' and not product_id:
            log_message = f"Ghi nhận quét nhập cho mã '{scanned_data}' (sản phẩm mới), số lượng {quantity}."


        else:
            return jsonify({'error': 'Hành động hoặc thông tin sản phẩm không hợp lệ.'}), 400

        c.execute("""
            INSERT INTO scan_log (scanned_data, product_id, product_name_at_scan, user_id, action_type, quantity_changed) 
            VALUES (?, ?, ?, ?, ?, ?) 
        """, (scanned_data, product_id, product_name_at_scan, user_id, action, quantity))

        conn.commit()
        return jsonify({'success': True, 'message': log_message}), 200

    except Exception as e:
        app.logger.error(f"API: Error updating inventory: {e}")
        conn.rollback()
        return jsonify({'error': f'Lỗi server: {str(e)}'}), 500


@app.route('/mobile-scan-product')
def render_mobile_scan_page():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    category_slug = request.args.get('category_slug')
    return render_template('mobile_scan_screen.html', category_slug=category_slug)
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)