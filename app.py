from flask_mail import Mail, Message
from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash, jsonify
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
app.secret_key = 'your_very_secret_and_complex_key_here_CHANGE_ME'

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('GMAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('GMAIL_APP_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = ('Quản lý QR', app.config['MAIL_USERNAME'])

print(f"--- INFO: Mail username set to: {os.environ.get('GMAIL_USERNAME')} ---")

mail = Mail(app)

conn = sqlite3.connect('sales.db', check_same_thread=False)
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

c.execute("""
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    name TEXT NOT NULL, 
    price REAL DEFAULT 0, 
    qty INTEGER DEFAULT 0,
    category TEXT,
    product_id_internal TEXT UNIQUE,
    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expiry_date DATE,
    product_qr_code_path TEXT
)
""")

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
    username_value = '' # Khai báo để tránh lỗi nếu là GET request
    if 'username' in session:
        return redirect(url_for('product_dashboard_overview'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        username_value = username # Giữ lại giá trị username đã nhập

        c.execute("SELECT id, username, password, is_verified FROM users WHERE username=?", (username,))
        user_data = c.fetchone()

        # SỬA Ở ĐÂY: Dùng check_password_hash và kiểm tra is_verified
        if user_data and check_password_hash(user_data[2], password):
            if user_data[3] == 1: # Kiểm tra is_verified
                session['username'] = user_data[1]
                flash('Đăng nhập thành công!', 'success')
                return redirect(url_for('product_dashboard_overview'))
            else:
                error = 'Tài khoản của bạn chưa được xác thực. Vui lòng kiểm tra email để lấy mã OTP hoặc đăng ký lại.'
                # Có thể chuyển hướng đến trang nhập OTP nếu muốn
                # Hoặc tạo cơ chế gửi lại OTP cho tài khoản chưa xác thực
        else:
            error = 'Tên tài khoản hoặc mật khẩu không đúng.'

    return render_template('login.html', error=error, username_value=username_value)


def generate_otp(length=6):
    return "".join(random.choices(string.digits, k=length))

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = ''
    form_data = {
        'username': request.form.get('username', ''),
        'email': request.form.get('email', ''),
        'phone': request.form.get('phone', '')
    }

    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        phone = request.form['phone']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        captcha_input = request.form['captcha']
        captcha_session = session.get('captcha_code', '')

        if password != confirm_password: error = 'Mật khẩu không khớp.'
        elif len(password) < 8: error = 'Mật khẩu phải có ít nhất 8 ký tự.'

        elif captcha_input.upper() != captcha_session.upper(): error = 'Mã captcha không đúng.'
        else:
            c.execute("SELECT id FROM users WHERE username=? OR email=?", (username, email))
            existing_user = c.fetchone()
            if existing_user:
                error = 'Tên người dùng hoặc email đã tồn tại.'
            else:
                try:
                    hashed_password = generate_password_hash(password)
                    otp = generate_otp()

                    session['registration_data'] = {
                        'username': username,
                        'email': email,
                        'phone': phone,
                        'password': hashed_password
                    }
                    session['otp'] = otp
                    session['otp_email'] = email

                    msg = Message('Mã Xác Thực Tài Khoản - Quản lý QR',
                                  recipients=[email])
                    msg.body = f'Chào {username},\n\nMã OTP để xác thực tài khoản của bạn là: {otp}\n\nMã này sẽ có hiệu lực trong 10 phút.\n\nTrân trọng,\nĐội ngũ Quản lý QR'
                    msg.html = f'''
                        <p>Chào {username},</p>
                        <p>Cảm ơn bạn đã đăng ký tài khoản tại Quản lý QR.</p>
                        <p>Mã OTP để xác thực tài khoản của bạn là: <strong>{otp}</strong></p>
                        <p>Mã này sẽ có hiệu lực trong 10 phút.</p>
                        <p>Nếu bạn không thực hiện yêu cầu này, vui lòng bỏ qua email này.</p>
                        <p>Trân trọng,<br>Đội ngũ Quản lý QR</p>
                    '''
                    mail.send(msg)

                    flash('Mã OTP đã được gửi đến email của bạn. Vui lòng kiểm tra và nhập mã để hoàn tất đăng ký.', 'info')
                    return redirect(url_for('verify_otp_page')) # Chuyển đến trang nhập OTP

                except Exception as e:
                    app.logger.error(f"Registration/OTP Send error: {e}")
                    error = f'Lỗi trong quá trình đăng ký hoặc gửi email: {str(e)}'


        if error:
            new_captcha_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            session['captcha_code'] = new_captcha_code
            return render_template('register.html', error=error, form_data=form_data)

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
    if 'username' not in session:
        return redirect(url_for('login_page'))
    qr_image_path_display = None
    data_generated = None
    if request.method == 'POST':
        data = request.form['data']
        if data:
            img = qrcode.make(data)
            img_filename = 'qr_tool_generated.png'
            img_path_on_disk = os.path.join(app.static_folder, img_filename)
            img.save(img_path_on_disk)
            qr_image_path_display = img_filename
            data_generated = data
            flash("Mã QR đã được tạo.", "success")
        else:
            flash("Vui lòng nhập dữ liệu để tạo mã QR.", "warning")
    return render_template('qr_tool.html', qr_image_path=qr_image_path_display, data_generated=data_generated)


@app.route('/rename-files-tool', methods=['GET', 'POST'])
def rename_files_tool():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    if request.method == 'POST':
        folder = request.form['folder']
        prefix = request.form['prefix']
        try:
            if not os.path.isdir(folder):
                flash(f"Thư mục không tồn tại: {folder}", "danger")
                return render_template('rename_tool.html', error=f"Thư mục không tồn tại: {folder}", folder=folder,
                                       prefix=prefix)
            files = os.listdir(folder)
            renamed_count = 0
            for file_item in files:
                if os.path.isfile(os.path.join(folder, file_item)):
                    try:
                        os.rename(os.path.join(folder, file_item), os.path.join(folder, prefix + file_item))
                        renamed_count += 1
                    except Exception as e_rename:
                        flash(f"Không thể đổi tên tệp {file_item}: {e_rename}", "warning")
            new_files = os.listdir(folder)
            if renamed_count > 0:
                flash(f"Đã đổi tên {renamed_count} tệp trong thư mục: {folder}", "success")
            else:
                flash(f"Không có tệp nào được đổi tên trong thư mục: {folder}", "info")
            return render_template('rename_tool.html', new_files=new_files, folder=folder, prefix=prefix)
        except Exception as e:
            flash(f"Lỗi xử lý đổi tên tệp: {e}", "danger")
            return render_template('rename_tool.html', error=str(e), folder=folder, prefix=prefix)
    return render_template('rename_tool.html')


@app.route('/password-generator-tool', methods=['GET', 'POST'])
def password_generator_tool():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    generated_password = None
    if request.method == 'POST':
        try:
            length = int(request.form.get('length', 0))
            if length <= 0:
                flash("Độ dài mật khẩu phải là số dương lớn hơn 0.", "warning")
            else:
                use_lowercase = 'use_lowercase' in request.form
                use_uppercase = 'use_uppercase' in request.form
                use_digits = 'use_digits' in request.form
                use_special = 'use_special' in request.form
                character_pool = ""
                if use_lowercase: character_pool += string.ascii_lowercase
                if use_uppercase: character_pool += string.ascii_uppercase
                if use_digits: character_pool += string.digits
                if use_special: character_pool += string.punctuation
                if not character_pool:
                    flash("Bạn phải chọn ít nhất một loại ký tự.", "warning")
                else:
                    password_list = [random.choice(character_pool) for i in range(length)]
                    random.shuffle(password_list)
                    generated_password = "".join(password_list)
                    flash("Mật khẩu đã được tạo.", "success")
        except ValueError:
            flash("Vui lòng nhập một số hợp lệ cho độ dài.", "danger")
    return render_template('password_tool.html', generated_password=generated_password)


@app.route('/sales-management-tool', methods=['GET', 'POST'])
def sales_management_tool():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    if request.method == 'POST':
        try:
            action = request.form.get('action')
            if action == 'add_product':
                name = request.form['name']
                price = float(request.form['price'])
                qty = int(request.form['qty'])
                category = request.form.get('category', '')
                if not name or price < 0 or qty < 0:
                    flash("Thông tin sản phẩm không hợp lệ.", "danger")
                else:
                    # Cần thêm các cột mới của bảng products nếu dùng form này
                    c.execute("INSERT INTO products (name, price, qty, category) VALUES (?, ?, ?, ?)",
                              (name, price, qty, category))
                    conn.commit()
                    flash(f"Đã thêm sản phẩm '{name}' thành công!", "success")
            elif action == 'delete_product':
                product_id = request.form.get('product_id')
                if product_id:
                    c.execute("DELETE FROM products WHERE id = ?", (product_id,))
                    conn.commit()
                    flash(f"Đã xóa sản phẩm ID {product_id}.", "info")
        except ValueError:
            flash("Giá hoặc số lượng không hợp lệ.", "danger")
        except Exception as e:
            flash(f"Lỗi khi xử lý sản phẩm: {e}", "danger")
        return redirect(url_for('sales_management_tool'))
    c.execute("SELECT id, name, price, qty, category FROM products ORDER BY name")
    products_data = c.fetchall()
    products_list = [{'id': p[0], 'name': p[1], 'price': p[2], 'qty': p[3], 'category': p[4]} for p in products_data]
    return render_template('sales_tool.html', products=products_list)


@app.route('/quan-ly-san-pham/')
@app.route('/quan-ly-san-pham/tong-quan')
def product_dashboard_overview():
    if 'username' not in session:
        return redirect(url_for('login_page'))

    try:
        # 1. Lấy các số liệu chính
        c.execute("SELECT COUNT(id) FROM products")
        total_products = c.fetchone()[0] or 0

        c.execute("SELECT SUM(qty) FROM products")
        total_items_in_stock = c.fetchone()[0] or 0

        # Lấy đơn hàng mới trong ngày hôm nay (Lưu ý: Cú pháp date có thể khác nhau giữa các CSDL)
        today_str = datetime.date.today().strftime('%Y-%m-%d')
        c.execute("SELECT COUNT(id) FROM orders WHERE DATE(order_date) = ?", (today_str,))
        orders_today = c.fetchone()[0] or 0

        # 2. Lấy các cảnh báo
        # Sản phẩm sắp hết hàng (số lượng <= 5)
        LOW_STOCK_THRESHOLD = 5
        c.execute("SELECT name, qty FROM products WHERE qty > 0 AND qty <= ? ORDER BY qty ASC LIMIT 5",
                  (LOW_STOCK_THRESHOLD,))
        low_stock_products = c.fetchall()

        # Sản phẩm sắp hết hạn (trong vòng 30 ngày tới)
        EXPIRY_ALERT_DAYS = 30
        c.execute("""
            SELECT name, expiry_date FROM products 
            WHERE expiry_date IS NOT NULL AND DATE(expiry_date) BETWEEN DATE('now') AND DATE('now', '+{} days') 
            ORDER BY expiry_date ASC
        """.format(EXPIRY_ALERT_DAYS))
        expiring_products = c.fetchall()

        overview_data = {
            'total_products': total_products,
            'total_items_in_stock': total_items_in_stock,
            'orders_today': orders_today,
            'low_stock_products': low_stock_products,
            'expiring_products': expiring_products
        }

        return render_template('product_dashboard_content_tongquan.html', overview_data=overview_data)

    except Exception as e:
        app.logger.error(f"Error loading overview dashboard: {e}")
        flash("Có lỗi xảy ra khi tải trang tổng quan.", "danger")
        # Trả về trang với dữ liệu rỗng để tránh crash
        return render_template('product_dashboard_content_tongquan.html', overview_data={})


# Đặt đoạn code này vào file app.py của bạn

@app.route('/quan-ly-san-pham/tong-quan/chi-tiet')
def product_dashboard_overview_detail():
    if 'username' not in session:
        return redirect(url_for('login_page'))

    try:
        # 1. Lấy các số liệu chính
        c.execute("SELECT COUNT(id) FROM products")
        total_products = c.fetchone()[0] or 0

        c.execute("SELECT SUM(qty) FROM products")
        total_items_in_stock = c.fetchone()[0] or 0

        today_str = datetime.date.today().strftime('%Y-%m-%d')
        c.execute("SELECT COUNT(id) FROM orders WHERE DATE(order_date) = ?", (today_str,))
        orders_today = c.fetchone()[0] or 0

        # 2. Lấy các cảnh báo
        LOW_STOCK_THRESHOLD = 5
        c.execute("SELECT name, qty FROM products WHERE qty > 0 AND qty <= ? ORDER BY qty ASC LIMIT 5",
                  (LOW_STOCK_THRESHOLD,))
        low_stock_products = c.fetchall()

        EXPIRY_ALERT_DAYS = 30
        c.execute("""
            SELECT name, expiry_date FROM products 
            WHERE expiry_date IS NOT NULL AND DATE(expiry_date) BETWEEN DATE('now') AND DATE('now', '+{} days') 
            ORDER BY expiry_date ASC
        """.format(EXPIRY_ALERT_DAYS))
        expiring_products = c.fetchall()

        overview_data = {
            'total_products': total_products,
            'total_items_in_stock': total_items_in_stock,
            'orders_today': orders_today,
            'low_stock_products': low_stock_products,
            'expiring_products': expiring_products
        }

        # Render một template MỚI
        return render_template('product_dashboard_content_tongquan_chitiet.html', overview_data=overview_data)

    except Exception as e:
        app.logger.error(f"Error loading overview detail: {e}")
        flash("Có lỗi xảy ra khi tải trang chi tiết.", "danger")
        return redirect(url_for('product_dashboard_overview'))


@app.route('/quan-ly-san-pham/don-hang/xu-ly')
def pd_don_hang_xu_ly():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    try:
        c.execute(
            "SELECT id, order_code, customer_name, order_date, status, total_amount FROM orders ORDER BY order_date DESC")
        orders_data = c.fetchall()
        orders_list = []
        if orders_data:
            for row in orders_data:
                order_date_val = None
                if row[3]:
                    try:
                        if isinstance(row[3], str):
                            order_date_val = datetime.datetime.strptime(row[3].split('.')[0], '%Y-%m-%d %H:%M:%S')
                        elif isinstance(row[3], datetime.datetime):
                            order_date_val = row[3]
                    except ValueError:
                        try:
                            order_date_val = datetime.datetime.fromisoformat(row[3])
                        except:
                            pass
                order_dict = {
                    'id': row[0], 'order_code': row[1], 'customer_name': row[2],
                    'order_date': order_date_val, 'status': row[4], 'total_amount': row[5]
                }
                orders_list.append(order_dict)
        return render_template('product_dashboard_content_donhang_xuly.html', orders=orders_list)
    except Exception as e:
        flash(f"Lỗi tải đơn hàng: {e}", "danger")
        return render_template('product_dashboard_content_donhang_xuly.html', orders=[])


@app.route('/quan-ly-san-pham/don-hang/nhap', methods=['GET', 'POST'])
def pd_don_hang_nhap():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    if request.method == 'POST':
        try:
            order_code = generate_order_code()
            customer_name = request.form.get('customer_name')
            customer_phone = request.form.get('customer_phone')
            customer_address = request.form.get('customer_address')
            notes = request.form.get('notes')
            total_amount = request.form.get('total_amount', 0, type=float)
            if not customer_name:
                flash("Tên khách hàng không được để trống.", "danger")
            else:
                c.execute("""
                    INSERT INTO orders (order_code, customer_name, customer_phone, customer_address, notes, total_amount, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (order_code, customer_name, customer_phone, customer_address, notes, total_amount, 'Mới'))
                conn.commit()
                flash(f"Đã tạo đơn hàng bán '{order_code}' thành công!", "success")
                return redirect(url_for('pd_don_hang_xu_ly'))
        except Exception as e:
            conn.rollback()
            flash(f"Lỗi khi tạo đơn hàng bán: {e}", "danger")
    return render_template('product_dashboard_content_donhang_nhap.html')


@app.route('/quan-ly-san-pham/don-hang/gan-qr', methods=['GET', 'POST'])
def pd_don_hang_gan_qr():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    qr_image_path_display = None
    order_id_processed = None
    message = None
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'generate_qr':
            order_id_str = request.form.get('order_id_for_qr')
            if not order_id_str:
                message = "Vui lòng nhập ID đơn hàng."
            else:
                try:
                    order_id = int(order_id_str)
                    c.execute("SELECT id, order_code FROM orders WHERE id = ?", (order_id,))
                    order = c.fetchone()
                    if order:
                        order_id_db, order_code_db = order
                        qr_data = f"OrderCode:{order_code_db}, OrderID:{order_id_db}"
                        qr_folder = os.path.join(app.static_folder, 'qrcodes')
                        if not os.path.exists(qr_folder):
                            os.makedirs(qr_folder)
                        img_filename = f"order_{order_id_db}_qr.png"
                        img_path_on_disk = os.path.join(qr_folder, img_filename)
                        qr_img_obj = qrcode.make(qr_data)
                        qr_img_obj.save(img_path_on_disk)
                        qr_image_path_display = os.path.join('qrcodes', img_filename)
                        order_id_processed = order_id_db
                        flash(f"Đã tạo QR cho đơn hàng {order_code_db}", "success")
                    else:
                        message = f"Không tìm thấy đơn hàng với ID {order_id}."
                except ValueError:
                    message = "ID đơn hàng không hợp lệ. Vui lòng nhập một số."
                except Exception as e:
                    message = f"Lỗi tạo QR: {str(e)}"
    return render_template('product_dashboard_content_donhang_ganqr.html', qr_image_path=qr_image_path_display,
                           order_id_processed=order_id_processed, message=message)


@app.route('/quan-ly-san-pham/ton-kho')
def pd_ton_kho_quan_ly():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    c.execute("""
        SELECT id, name, price, qty, category, product_id_internal, date_added, expiry_date, product_qr_code_path 
        FROM products ORDER BY date_added DESC, name
    """)
    products_data = c.fetchall()
    products_list = []
    for p_row in products_data:
        date_added_val = None
        if p_row[6]:
            try:
                date_added_val = datetime.datetime.strptime(p_row[6].split('.')[0], '%Y-%m-%d %H:%M:%S')
            except:
                pass

        expiry_date_val = None
        if p_row[7]:
            try:
                expiry_date_val = datetime.datetime.strptime(p_row[7], '%Y-%m-%d').date()
            except:
                pass

        products_list.append({
            'id': p_row[0], 'name': p_row[1], 'price': p_row[2], 'qty': p_row[3], 'category': p_row[4],
            'product_id_internal': p_row[5], 'date_added': date_added_val, 'expiry_date': expiry_date_val,
            'product_qr_code_path': p_row[8]
        })
    return render_template('product_dashboard_content_tonkho.html', products=products_list)


@app.route('/quan-ly-san-pham/bao-cao')
def pd_bao_cao_xem():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    return render_template('product_dashboard_content_baocao.html')


@app.route('/quan-ly-san-pham/thong-tin-ca-nhan')
def pd_user_profile():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    c.execute("SELECT username, email, phone FROM users WHERE username = ?", (session['username'],))
    user_info = c.fetchone()
    return render_template('product_dashboard_content_user_profile.html', user_info=user_info)


@app.route('/quan-ly-san-pham/nhap-san-pham-moi', methods=['GET', 'POST'])
def pd_nhap_san_pham_moi():
    if 'username' not in session:
        return redirect(url_for('login_page'))

    form_data = {}
    generated_qr_path = None
    generated_product_id_internal = None  # Sửa tên biến này
    product_name_processed = None
    today_date_str = datetime.date.today().strftime('%Y-%m-%d')

    if request.method == 'POST':
        product_name = request.form.get('product_name')
        date_added_str = request.form.get('date_added', today_date_str)
        expiry_date_str = request.form.get('expiry_date')
        price_str = request.form.get('price', '0')  # Lấy giá
        qty_str = request.form.get('qty', '0')  # Lấy số lượng
        category = request.form.get('category', '')  # Lấy danh mục

        form_data = request.form
        product_name_processed = product_name

        if not product_name:
            flash("Tên sản phẩm không được để trống.", "danger")
        else:
            internal_id = generate_internal_product_id()

            date_added_db_format = None
            if date_added_str:
                try:
                    date_added_db_format = datetime.datetime.strptime(date_added_str, '%Y-%m-%d').strftime(
                        '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    flash("Định dạng Ngày nhập không hợp lệ. Sử dụng YYYY-MM-DD.", "danger")
                    return render_template('product_dashboard_content_nhap_sanpham.html', form_data=form_data,
                                           generated_qr_path=None, generated_product_id_internal=None,
                                           product_name_processed=product_name, today_date=today_date_str)
            else:
                date_added_db_format = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            expiry_date_db_format = None
            if expiry_date_str:
                try:
                    expiry_date_db_format = datetime.datetime.strptime(expiry_date_str, '%Y-%m-%d').strftime('%Y-%m-%d')
                except ValueError:
                    flash("Định dạng Ngày hết hạn không hợp lệ. Sử dụng YYYY-MM-DD.", "danger")
                    return render_template('product_dashboard_content_nhap_sanpham.html', form_data=form_data,
                                           generated_qr_path=None, generated_product_id_internal=None,
                                           product_name_processed=product_name, today_date=today_date_str)

            try:  # Thêm try-except cho việc chuyển đổi price và qty
                price = float(price_str) if price_str else 0.0
                qty = int(qty_str) if qty_str else 0
            except ValueError:
                flash("Giá hoặc số lượng nhập không hợp lệ.", "danger")
                return render_template('product_dashboard_content_nhap_sanpham.html', form_data=form_data,
                                       generated_qr_path=None, generated_product_id_internal=None,
                                       product_name_processed=product_name, today_date=today_date_str)

            qr_data_sp = url_for('view_product_details_by_qr', product_internal_id=internal_id, _external=True)
            qr_folder_sp = os.path.join(app.static_folder, 'product_qrcodes')
            if not os.path.exists(qr_folder_sp):
                os.makedirs(qr_folder_sp)
            qr_filename_sp = f"product_{internal_id}.png"
            qr_path_on_disk_sp = os.path.join(qr_folder_sp, qr_filename_sp)

            try:
                qr_img_sp = qrcode.make(qr_data_sp)
                qr_img_sp.save(qr_path_on_disk_sp)
                product_qr_code_path_for_template = os.path.join('product_qrcodes', qr_filename_sp)

                generated_qr_path = product_qr_code_path_for_template
                generated_product_id_internal = internal_id  # Sửa ở đây

                c.execute("""
                    INSERT INTO products (name, product_id_internal, date_added, expiry_date, product_qr_code_path, price, qty, category) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (product_name, internal_id, date_added_db_format, expiry_date_db_format,
                      product_qr_code_path_for_template, price, qty, category))
                conn.commit()
                flash(f"Đã nhập sản phẩm '{product_name}' (ID nội bộ: {internal_id}) và tạo QR thành công!", "success")

                form_data = {}
                product_name_processed = product_name

            except Exception as e:
                conn.rollback()
                flash(f"Lỗi khi lưu sản phẩm hoặc tạo QR: {e}", "danger")
                app.logger.error(f"Error adding product/QR: {e}")

    return render_template('product_dashboard_content_nhap_sanpham.html',
                           form_data=form_data,
                           generated_qr_path=generated_qr_path,
                           generated_product_id_internal=generated_product_id_internal,  # Sửa ở đây
                           product_name_processed=product_name_processed,
                           today_date=today_date_str)



@app.route('/quan-ly-san-pham/nhap-kho-qua-quet')
def pd_nhap_kho_quet_page():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    return render_template('product_dashboard_content_scan_and_input.html')


@app.route('/process-scanned-product-barcode', methods=['POST'])
def process_scanned_product_barcode():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    scanned_barcode_data = data.get('barcode_data')

    if not scanned_barcode_data:
        return jsonify({'error': 'No barcode data received'}), 400

    app.logger.info(f"Received Scanned Barcode Data: {scanned_barcode_data}")

    c.execute("SELECT name, volume_weight, expiry_date, product_id_internal FROM products WHERE barcode_data = ?",
              (scanned_barcode_data,))
    product = c.fetchone()

    if product:

        product_info = {
            'exists_in_db': True,
            'name': product[0],
            'volume_weight': product[1],
            'expiry_date': product[2].strftime('%Y-%m-%d') if product[2] else None,
            'product_id_internal': product[3],
            'barcode_data': scanned_barcode_data
        }
        return jsonify(product_info), 200
    else:

        product_info = {
            'exists_in_db': False,
            'name': '',
            'volume_weight': '',
            'expiry_date': None,
            'barcode_data': scanned_barcode_data
        }
        return jsonify(product_info), 200



@app.route('/save-scanned-product-to-inventory', methods=['POST'])
def save_scanned_product_to_inventory():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    product_name = data.get('name')
    barcode_data_original = data.get('barcode_data')  # Mã vạch gốc đã quét
    volume_weight = data.get('volume_weight')
    expiry_date_str = data.get('expiry_date')
    quantity_added = data.get('quantity', 0, type=int)  # Số lượng nhập mới

    product_id_internal_existing = data.get('product_id_internal')  # ID nội bộ nếu sản phẩm đã tồn tại

    if not product_name or quantity_added <= 0:
        return jsonify({'error': 'Tên sản phẩm và số lượng nhập phải hợp lệ.'}), 400

    date_added_db_format = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    expiry_date_db_format = None
    if expiry_date_str:
        try:
            expiry_date_db_format = datetime.datetime.strptime(expiry_date_str, '%Y-%m-%d').strftime('%Y-%m-%d')
        except ValueError:
            return jsonify({'error': 'Định dạng Ngày hết hạn không hợp lệ (YYYY-MM-DD).'}), 400

    new_product_qr_path = None
    final_product_id_internal = None

    try:
        if product_id_internal_existing:
            final_product_id_internal = product_id_internal_existing
            c.execute(
                "UPDATE products SET qty = qty + ?, name = ?, volume_weight = ?, expiry_date = ?, date_added = ? WHERE product_id_internal = ?",
                (quantity_added, product_name, volume_weight, expiry_date_db_format, date_added_db_format,
                 final_product_id_internal))
            flash_message = f"Đã cập nhật số lượng cho sản phẩm '{product_name}' (ID: {final_product_id_internal})."
        else:
            final_product_id_internal = generate_internal_product_id()

            qr_data_sys = url_for('view_product_details_by_qr', product_internal_id=final_product_id_internal,
                                  _external=True)
            qr_folder_sys = os.path.join(app.static_folder, 'product_qrcodes')
            if not os.path.exists(qr_folder_sys): os.makedirs(qr_folder_sys)
            qr_filename_sys = f"product_{final_product_id_internal}.png"
            qr_path_on_disk_sys = os.path.join(qr_folder_sys, qr_filename_sys)
            qr_img_sys = qrcode.make(qr_data_sys)
            qr_img_sys.save(qr_path_on_disk_sys)
            new_product_qr_path = os.path.join('product_qrcodes', qr_filename_sys)

            c.execute("""
                INSERT INTO products (name, product_id_internal, barcode_data, volume_weight, date_added, expiry_date, product_qr_code_path, qty, price) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (product_name, final_product_id_internal, barcode_data_original, volume_weight,
                  date_added_db_format, expiry_date_db_format, new_product_qr_path, quantity_added, 0))  # Giá tạm = 0
            flash_message = f"Đã thêm sản phẩm mới '{product_name}' (ID: {final_product_id_internal}) với số lượng {quantity_added} và tạo QR hệ thống."

        conn.commit()
        return jsonify({
            'message': flash_message,
            'product_name': product_name,
            'product_id_internal': final_product_id_internal,
            'new_quantity': quantity_added,  # Số lượng vừa nhập
            'system_qr_image_path': url_for('static', filename=new_product_qr_path) if new_product_qr_path else None
        }), 200

    except Exception as e:
        conn.rollback()
        app.logger.error(f"Error saving product to inventory: {e}")
        return jsonify({'error': f'Lỗi khi lưu sản phẩm: {str(e)}'}), 500

@app.route('/san-pham/qr-info/<product_internal_id>')
def view_product_details_by_qr(product_internal_id):

    c.execute("""
        SELECT name, price, qty, category, date_added, expiry_date, product_id_internal, barcode_data, volume_weight 
        FROM products WHERE product_id_internal = ?
    """, (product_internal_id,))
    product_data = c.fetchone()
    if product_data:
        product_info = {
            'name': product_data[0], 'price': product_data[1], 'qty': product_data[2],
            'category': product_data[3], 'date_added': None, 'expiry_date': None,
            'product_id_internal': product_data[6],
            'barcode_data': product_data[7],
            'volume_weight': product_data[8]
        }

        return render_template('view_product_by_qr.html', product=product_info)
    else:
        flash("Không tìm thấy thông tin sản phẩm cho mã QR này.", "danger")
        return render_template('view_product_by_qr.html', product=None)


@app.route('/verify-otp', methods=['GET'])
def verify_otp_page():
    if 'registration_data' not in session or 'otp' not in session or 'otp_email' not in session:
        flash('Dữ liệu đăng ký không hợp lệ hoặc phiên đã hết hạn. Vui lòng thử đăng ký lại.', 'danger')
        return redirect(url_for('register'))
    return render_template('verify_otp.html')


@app.route('/verify-otp', methods=['POST'])
def verify_otp_submit():
    if 'registration_data' not in session or 'otp' not in session or 'otp_email' not in session:
        flash('Phiên làm việc hết hạn hoặc dữ liệu không hợp lệ. Vui lòng thử đăng ký lại.', 'danger')
        return redirect(url_for('register'))

    user_otp = request.form.get('otp_code')
    stored_otp = session.get('otp')
    registration_data = session.get('registration_data')


    if user_otp == stored_otp:
        try:
            c.execute("SELECT id FROM users WHERE username=? OR email=?",
                      (registration_data['username'], registration_data['email']))
            if c.fetchone():
                flash(
                    'Tên người dùng hoặc email đã được sử dụng bởi một tài khoản đã xác thực khác trong lúc bạn xác thực OTP.',
                    'danger')
                # Xóa session để tránh lỗi
                session.pop('registration_data', None)
                session.pop('otp', None)
                session.pop('otp_email', None)
                return redirect(url_for('register'))

            c.execute(
                "INSERT INTO users (username, email, phone, password, is_verified) VALUES (?, ?, ?, ?, ?)",
                (registration_data['username'], registration_data['email'],
                 registration_data['phone'], registration_data['password'], 1)  # is_verified = 1
            )
            conn.commit()

            session.pop('registration_data', None)
            session.pop('otp', None)
            session.pop('otp_email', None)

            session['username'] = registration_data['username']
            flash('Đăng ký và xác thực tài khoản thành công! Bạn đã được đăng nhập.', 'success')
            return redirect(url_for('product_dashboard_overview'))
        except sqlite3.IntegrityError:
            flash('Lỗi CSDL: Tên người dùng hoặc email đã tồn tại.', 'danger')
            return redirect(url_for('register'))
        except Exception as e:
            app.logger.error(f"OTP Verification error: {e}")
            flash(f'Lỗi không xác định trong quá trình xác thực: {str(e)}', 'danger')
            return redirect(url_for('register'))
    else:
        flash('Mã OTP không chính xác. Vui lòng thử lại.', 'danger')
        return render_template('verify_otp.html')


@app.route('/resend-otp')
def resend_otp():
    if 'registration_data' not in session or 'otp_email' not in session:
        flash('Không thể gửi lại OTP. Vui lòng thử đăng ký lại.', 'danger')
        return redirect(url_for('register'))

    try:
        email = session['otp_email']
        username = session['registration_data']['username']
        new_otp = generate_otp()
        session['otp'] = new_otp

        msg = Message('Mã Xác Thực Tài Khoản Mới - Quản lý QR',
                      recipients=[email])
        msg.body = f'Chào {username},\n\nMã OTP mới để xác thực tài khoản của bạn là: {new_otp}\n\nMã này sẽ có hiệu lực trong 10 phút.\n\nTrân trọng,\nĐội ngũ Quản lý QR'

        mail.send(msg)

        flash('Mã OTP mới đã được gửi đến email của bạn.', 'info')
    except Exception as e:
        app.logger.error(f"Resend OTP error: {e}")
        flash(f'Lỗi khi gửi lại OTP: {str(e)}', 'danger')

    return redirect(url_for('verify_otp_page'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)













