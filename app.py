# -*- coding: utf-8 -*-
import os
import sqlite3
import datetime
import hashlib
import uuid
import shutil
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from functools import wraps

app = Flask(__name__)
app.secret_key = os.urandom(32)
DB_FILE = "sarrafi.db"
BACKUP_DIR = "backups"

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def migrate_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(PersonBalances)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'trust_balance' in columns and 'debt_balance' in columns and 'balance' not in columns:
        print("Migrating PersonBalances...")
        cursor.execute("ALTER TABLE PersonBalances ADD COLUMN balance REAL DEFAULT 0")
        cursor.execute("UPDATE PersonBalances SET balance = trust_balance - debt_balance")
        cursor.execute("CREATE TABLE PersonBalances_new (person_id INTEGER, currency TEXT, balance REAL DEFAULT 0, PRIMARY KEY(person_id, currency))")
        cursor.execute("INSERT INTO PersonBalances_new (person_id, currency, balance) SELECT person_id, currency, balance FROM PersonBalances")
        cursor.execute("DROP TABLE PersonBalances")
        cursor.execute("ALTER TABLE PersonBalances_new RENAME TO PersonBalances")
        conn.commit()
        print("Migration done.")
    conn.close()

def init_db():
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS Users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            full_name TEXT
        )''')
        admin_pass = hashlib.sha256("admin123".encode()).hexdigest()
        c.execute("INSERT OR IGNORE INTO Users (username, password, full_name) VALUES (?,?,?)",
                  ('admin', admin_pass, 'مدیر سیستم'))

        c.execute('''CREATE TABLE IF NOT EXISTS CashBalances (
            currency TEXT PRIMARY KEY,
            amount REAL DEFAULT 0
        )''')
        default_currencies = ['AFN', 'PKR', 'USD']
        for curr in default_currencies:
            c.execute("INSERT OR IGNORE INTO CashBalances (currency, amount) VALUES (?,0)", (curr,))

        c.execute('''CREATE TABLE IF NOT EXISTS ExchangeRates (
            from_curr TEXT,
            to_curr TEXT,
            rate REAL,
            PRIMARY KEY(from_curr, to_curr)
        )''')
        default_rates = [
            ('AFN','USD',0.0115), ('AFN','PKR',3.2),
            ('PKR','USD',0.0036), ('PKR','AFN',0.31),
            ('USD','AFN',87.0), ('USD','PKR',277.0)
        ]
        for f,t,r in default_rates:
            c.execute("INSERT OR IGNORE INTO ExchangeRates (from_curr, to_curr, rate) VALUES (?,?,?)", (f,t,r))

        c.execute('''CREATE TABLE IF NOT EXISTS ExchangeTransactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            given_currency TEXT,
            given_amount REAL,
            received_currency TEXT,
            received_amount REAL,
            rate REAL,
            trans_date TEXT,
            notes TEXT
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS Remittances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_name TEXT,
            sender_id TEXT,
            sender_phone TEXT,
            sender_country TEXT,
            receiver_name TEXT,
            receiver_country TEXT,
            amount REAL,
            currency TEXT,
            commission REAL DEFAULT 0,
            commission_type TEXT,
            net_amount REAL,
            reference_number TEXT UNIQUE,
            status TEXT DEFAULT 'pending',
            trans_date TEXT,
            notes TEXT
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS Persons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            id_number TEXT UNIQUE,
            phone TEXT
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS PersonBalances (
            person_id INTEGER,
            currency TEXT,
            balance REAL DEFAULT 0,
            PRIMARY KEY(person_id, currency)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS PrincipalTransactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER,
            person_name TEXT,
            person_id_number TEXT,
            trans_type TEXT,
            amount REAL,
            currency TEXT,
            trans_date TEXT,
            notes TEXT
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS CashTransactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            currency TEXT,
            amount_change REAL,
            balance_after REAL,
            description TEXT,
            trans_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS SystemSettings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')
        c.execute("INSERT OR IGNORE INTO SystemSettings (key, value) VALUES ('default_commission_percent', '5')")

        conn.commit()
    except Exception as e:
        print("Init error:", e)
    finally:
        conn.close()
    migrate_db()

def update_cash(currency, delta, description='', conn=None):
    own_conn = False
    if conn is None:
        conn = get_db()
        own_conn = True
    try:
        cur = conn.execute("SELECT amount FROM CashBalances WHERE currency=?", (currency,)).fetchone()
        if cur:
            new_bal = cur[0] + delta
            if new_bal < 0:
                raise ValueError(f"په {currency} کې کافي پیسې نشته! اوسنی موجودي: {cur[0]}")
            conn.execute("UPDATE CashBalances SET amount=? WHERE currency=?", (new_bal, currency))
        else:
            if delta < 0:
                raise ValueError(f"په {currency} کې پیسې نشته او منفي مقدار نشي اضافه کیدلی")
            new_bal = delta
            conn.execute("INSERT INTO CashBalances (currency, amount) VALUES (?,?)", (currency, new_bal))
        conn.execute("INSERT INTO CashTransactions (currency, amount_change, balance_after, description) VALUES (?,?,?,?)",
                     (currency, delta, new_bal, description))
        if own_conn:
            conn.commit()
    except Exception as e:
        if own_conn:
            conn.rollback()
        raise e
    finally:
        if own_conn:
            conn.close()
    return True

def get_or_create_person(name, id_number, phone='', conn=None):
    own_conn = False
    if conn is None:
        conn = get_db()
        own_conn = True
    try:
        c = conn.cursor()
        c.execute("SELECT id FROM Persons WHERE id_number=?", (id_number,))
        row = c.fetchone()
        if row:
            pid = row[0]
            c.execute("UPDATE Persons SET name=?, phone=? WHERE id=?", (name, phone, pid))
        else:
            c.execute("INSERT INTO Persons (name, id_number, phone) VALUES (?,?,?)", (name, id_number, phone))
            pid = c.lastrowid
            currencies = conn.execute("SELECT currency FROM CashBalances").fetchall()
            for curr_row in currencies:
                c.execute("INSERT OR IGNORE INTO PersonBalances (person_id, currency) VALUES (?,?)", (pid, curr_row[0]))
        if own_conn:
            conn.commit()
        return pid
    except Exception as e:
        if own_conn:
            conn.rollback()
        raise e
    finally:
        if own_conn:
            conn.close()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            if request.is_json:
                return jsonify({'success': False, 'message': 'لطفاً ننوځئ'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated

# ------------------ Routes ------------------
@app.route('/')
@login_required
def home():
    return render_template('index.html', full_name=session.get('full_name', ''))

@app.route('/login')
def login_page():
    if 'user' in session:
        return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({'success': False, 'message': 'معلومات نیمګړي'})
    conn = get_db()
    hashed = hashlib.sha256(data['password'].encode()).hexdigest()
    user = conn.execute("SELECT full_name FROM Users WHERE username=? AND password=?", (data['username'], hashed)).fetchone()
    conn.close()
    if user:
        session['user'] = data['username']
        session['full_name'] = user[0]
        return jsonify({'success': True, 'full_name': user[0]})
    return jsonify({'success': False, 'message': 'کارن نوم یا پاسورډ غلط'})

@app.route('/api/get_cash_balances')
@login_required
def get_cash():
    conn = get_db()
    rows = conn.execute("SELECT currency, amount FROM CashBalances").fetchall()
    conn.close()
    return jsonify({r[0]: r[1] for r in rows})

@app.route('/api/get_all_currencies')
@login_required
def get_all_currencies():
    conn = get_db()
    rows = conn.execute("SELECT currency FROM CashBalances").fetchall()
    conn.close()
    return jsonify([r[0] for r in rows])

@app.route('/api/get_exchange_rate', methods=['POST'])
@login_required
def get_rate():
    d = request.get_json()
    from_c = d.get('from_curr')
    to_c = d.get('to_curr')
    if not from_c or not to_c:
        return jsonify({'rate': None})
    conn = get_db()
    r = conn.execute("SELECT rate FROM ExchangeRates WHERE from_curr=? AND to_curr=?", (from_c, to_c)).fetchone()
    if r:
        conn.close()
        return jsonify({'rate': r[0]})
    r = conn.execute("SELECT rate FROM ExchangeRates WHERE from_curr=? AND to_curr=?", (to_c, from_c)).fetchone()
    conn.close()
    if r and r[0] != 0:
        return jsonify({'rate': round(1.0 / r[0], 6)})
    return jsonify({'rate': None})

@app.route('/api/get_all_rates')
@login_required
def get_all_rates():
    conn = get_db()
    rows = conn.execute("SELECT from_curr, to_curr, rate FROM ExchangeRates ORDER BY from_curr").fetchall()
    conn.close()
    return jsonify([{'from': r[0], 'to': r[1], 'rate': r[2]} for r in rows])

@app.route('/api/update_exchange_rate', methods=['POST'])
@login_required
def update_rate():
    d = request.get_json()
    if not all(k in d for k in ('from_curr', 'to_curr', 'rate')):
        return jsonify({'success': False, 'message': 'نیمګړي معلومات'})
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO ExchangeRates (from_curr, to_curr, rate) VALUES (?,?,?)",
                 (d['from_curr'], d['to_curr'], d['rate']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/add_currency', methods=['POST'])
@login_required
def add_currency():
    d = request.get_json()
    new_curr = d.get('currency', '').upper().strip()
    if not new_curr or len(new_curr) != 3:
        return jsonify({'success': False, 'message': 'اسعار باید درې توري ولري (لکه EUR)'})
    conn = get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO CashBalances (currency, amount) VALUES (?,0)", (new_curr,))
        existing = conn.execute("SELECT currency FROM CashBalances WHERE currency != ?", (new_curr,)).fetchall()
        for row in existing:
            other = row[0]
            conn.execute("INSERT OR IGNORE INTO ExchangeRates (from_curr, to_curr, rate) VALUES (?,?,1)", (new_curr, other))
            conn.execute("INSERT OR IGNORE INTO ExchangeRates (from_curr, to_curr, rate) VALUES (?,?,1)", (other, new_curr))
        persons = conn.execute("SELECT id FROM Persons").fetchall()
        for p in persons:
            conn.execute("INSERT OR IGNORE INTO PersonBalances (person_id, currency) VALUES (?,?)", (p[0], new_curr))
        conn.commit()
        return jsonify({'success': True, 'message': f'اسعار {new_curr} اضافه شو'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@app.route('/api/delete_currency', methods=['POST'])
@login_required
def delete_currency():
    data = request.get_json()
    currency = data.get('currency', '').upper().strip()
    if not currency:
        return jsonify({'success': False, 'message': 'اسعار ونه موندل شو'})
    conn = get_db()
    try:
        ex_count = conn.execute("SELECT COUNT(*) FROM ExchangeTransactions WHERE given_currency=? OR received_currency=?", (currency, currency)).fetchone()[0]
        rem_count = conn.execute("SELECT COUNT(*) FROM Remittances WHERE currency=?", (currency,)).fetchone()[0]
        princ_count = conn.execute("SELECT COUNT(*) FROM PrincipalTransactions WHERE currency=?", (currency,)).fetchone()[0]
        if ex_count > 0 or rem_count > 0 or princ_count > 0:
            return jsonify({'success': False, 'message': f'دا اسعار د مخکینیو معاملو په {ex_count+rem_count+princ_count} قضیو کې کارول شوی، نشي ړنګول کېدای.'})
        conn.execute("DELETE FROM CashBalances WHERE currency=?", (currency,))
        conn.execute("DELETE FROM ExchangeRates WHERE from_curr=? OR to_curr=?", (currency, currency))
        conn.execute("DELETE FROM PersonBalances WHERE currency=?", (currency,))
        conn.commit()
        return jsonify({'success': True, 'message': f'اسعار {currency} په بریالیتوب سره ړنګ شو.'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@app.route('/api/add_exchange_transaction', methods=['POST'])
@login_required
def add_exchange():
    d = request.get_json()
    required = ['given_currency', 'given_amount', 'received_currency', 'received_amount', 'rate']
    if not all(k in d for k in required) or d['given_amount'] <= 0:
        return jsonify({'success': False, 'message': 'معلومات ناسم'})
    conn = get_db()
    now = datetime.datetime.now().isoformat()
    try:
        cur_cash = conn.execute("SELECT amount FROM CashBalances WHERE currency=?", (d['given_currency'],)).fetchone()
        if not cur_cash or cur_cash[0] < d['given_amount']:
            return jsonify({'success': False, 'message': f"په {d['given_currency']} کې کافي پیسې نشته!"})
        conn.execute('''INSERT INTO ExchangeTransactions 
                        (given_currency, given_amount, received_currency, received_amount, rate, trans_date, notes)
                        VALUES (?,?,?,?,?,?,?)''',
                     (d['given_currency'], d['given_amount'], d['received_currency'], d['received_amount'], d['rate'], now, d.get('notes', '')))
        update_cash(d['given_currency'], -d['given_amount'], "د اسعارو تبادله (ورکړه)", conn)
        update_cash(d['received_currency'], d['received_amount'], "د اسعارو تبادله (ترلاسه)", conn)
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@app.route('/api/get_exchange_transactions')
@login_required
def get_exchanges():
    conn = get_db()
    rows = conn.execute("SELECT * FROM ExchangeTransactions ORDER BY trans_date DESC LIMIT 200").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/delete_exchange_transaction', methods=['POST'])
@login_required
def del_exchange():
    tid = request.get_json().get('id')
    if not tid:
        return jsonify({'success': False})
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM ExchangeTransactions WHERE id=?", (tid,)).fetchone()
        if not row:
            return jsonify({'success': False, 'message': 'معامله ونه موندل شوه'})
        update_cash(row['given_currency'], row['given_amount'], f"حذف تبادله {tid} (بېرته)", conn)
        update_cash(row['received_currency'], -row['received_amount'], f"حذف تبادله {tid} (بېرته)", conn)
        conn.execute("DELETE FROM ExchangeTransactions WHERE id=?", (tid,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@app.route('/api/edit_exchange_transaction', methods=['POST'])
@login_required
def edit_exchange():
    d = request.get_json()
    tid = d.get('id')
    if not tid:
        return jsonify({'success': False, 'message': 'ID نشته'})
    conn = get_db()
    try:
        old = conn.execute("SELECT * FROM ExchangeTransactions WHERE id=?", (tid,)).fetchone()
        if not old:
            return jsonify({'success': False, 'message': 'معامله ونه موندل شوه'})
        # Revert old
        update_cash(old['given_currency'], old['given_amount'], f"حذف تبادله {tid} (بېرته)", conn)
        update_cash(old['received_currency'], -old['received_amount'], f"حذف تبادله {tid} (بېرته)", conn)
        # Apply new
        update_cash(d['given_currency'], -d['given_amount'], f"د تبادلې سمون {tid}", conn)
        update_cash(d['received_currency'], d['received_amount'], f"د تبادلې سمون {tid}", conn)
        conn.execute("""UPDATE ExchangeTransactions 
                        SET given_currency=?, given_amount=?, received_currency=?, received_amount=?, rate=?, notes=?
                        WHERE id=?""",
                     (d['given_currency'], d['given_amount'], d['received_currency'], d['received_amount'], d['rate'], d.get('notes', ''), tid))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@app.route('/api/add_remittance', methods=['POST'])
@login_required
def add_remittance():
    d = request.get_json()
    required = ['sender_name', 'receiver_name', 'amount', 'currency', 'commission_percent']
    if not all(k in d for k in required):
        return jsonify({'success': False, 'message': 'نیمګړي معلومات'})
    conn = get_db()
    ref = str(uuid.uuid4())[:8].upper()
    now = datetime.datetime.now().isoformat()
    amount = float(d['amount'])
    commission_percent = float(d['commission_percent'])
    commission = round(amount * commission_percent / 100, 2)
    net_amount = amount - commission

    try:
        conn.execute('''INSERT INTO Remittances 
                        (sender_name, sender_id, sender_phone, sender_country, receiver_name, receiver_country, 
                         amount, currency, commission, commission_type, net_amount, reference_number, status, trans_date, notes)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                     (d['sender_name'], d.get('sender_id'), d.get('sender_phone'), d.get('sender_country', ''),
                      d['receiver_name'], d.get('receiver_country', ''), amount, d['currency'],
                      commission, 'percent', net_amount, ref, 'pending', now, d.get('notes', '')))
        update_cash(d['currency'], commission, f"د حوالې کمیسیون {ref}", conn)
        conn.commit()
        return jsonify({'success': True, 'reference': ref, 'commission': commission})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@app.route('/api/update_remittance_status', methods=['POST'])
@login_required
def update_rem():
    d = request.get_json()
    if not d.get('ref') or d.get('status') not in ('completed', 'failed', 'pending'):
        return jsonify({'success': False, 'message': 'ناسم معلومات'})
    conn = get_db()
    try:
        row = conn.execute("SELECT amount, currency, status, net_amount FROM Remittances WHERE reference_number=?", (d['ref'],)).fetchone()
        if not row:
            return jsonify({'success': False, 'message': 'حواله ونه موندل شوه'})
        old = row['status']
        if d['status'] == 'completed' and old != 'completed':
            update_cash(row['currency'], -row['net_amount'], f"تکمیل حواله {d['ref']} (لیږل شوی)", conn)
        elif old == 'completed' and d['status'] != 'completed':
            update_cash(row['currency'], row['net_amount'], f"بېرته حواله {d['ref']}", conn)
        conn.execute("UPDATE Remittances SET status=? WHERE reference_number=?", (d['status'], d['ref']))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@app.route('/api/get_remittances')
@login_required
def get_remittances():
    conn = get_db()
    rows = conn.execute("SELECT * FROM Remittances ORDER BY trans_date DESC LIMIT 200").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/delete_remittance', methods=['POST'])
@login_required
def del_remittance():
    ref = request.get_json().get('ref')
    if not ref:
        return jsonify({'success': False})
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM Remittances WHERE reference_number=?", (ref,)).fetchone()
        if row:
            if row['status'] == 'completed':
                update_cash(row['currency'], row['net_amount'], f"حذف حواله {ref} (بېرته)", conn)
            update_cash(row['currency'], -row['commission'], f"حذف کمیسیون {ref}", conn)
        conn.execute("DELETE FROM Remittances WHERE reference_number=?", (ref,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@app.route('/api/add_principal_transaction', methods=['POST'])
@login_required
def add_principal():
    d = request.get_json()
    required = ['person_name', 'person_id_number', 'trans_type', 'amount', 'currency']
    if not all(k in d for k in required):
        return jsonify({'success': False, 'message': 'ټول فیلډونه اړین'})
    conn = get_db()
    try:
        pid = get_or_create_person(d['person_name'], d['person_id_number'], conn=conn)
        c = conn.cursor()
        c.execute("SELECT balance FROM PersonBalances WHERE person_id=? AND currency=?", (pid, d['currency']))
        row = c.fetchone()
        balance = row['balance'] if row else 0.0
        ttype = d['trans_type']
        amount = float(d['amount'])
        curr = d['currency']

        if ttype == 'deposit':
            balance += amount
            update_cash(curr, amount, f"امانت ورکول {d['person_name']}", conn)
        elif ttype == 'withdrawal':
            if balance < amount:
                raise ValueError(f"د {d['person_name']} امانت کافي نه دی (موجود: {balance})")
            balance -= amount
            update_cash(curr, -amount, f"امانت اخیستل {d['person_name']}", conn)
        elif ttype == 'loan_given':
            cur_cash = conn.execute("SELECT amount FROM CashBalances WHERE currency=?", (curr,)).fetchone()
            if not cur_cash or cur_cash[0] < amount:
                raise ValueError(f"په {curr} کې کافي پیسې نشته! د پور ورکولو لپاره")
            balance -= amount
            update_cash(curr, -amount, f"پور ورکول {d['person_name']}", conn)
        elif ttype == 'loan_received':
            if balance + amount > 0:
                allowed = -balance
                if allowed <= 0:
                    raise ValueError("پور نشته، نشي تادیه کیدی")
                if amount > allowed:
                    raise ValueError(f"تادیه د پور مقدار څخه زیاته ده (پاتې پور: {allowed})")
            balance += amount
            update_cash(curr, amount, f"پور اخیستل {d['person_name']}", conn)
        elif ttype == 'settlement':
            # Settlement: close the balance to zero
            if balance > 0:
                # Person has money with exchange -> exchange pays person
                if balance > amount:
                    raise ValueError(f"تادیه مقدار ({amount}) د بیلانس ({balance}) څخه کم دی")
                update_cash(curr, -balance, f"وصل (ادا) {d['person_name']}", conn)
                balance = 0
            elif balance < 0:
                # Person owes exchange -> person pays exchange
                if amount < -balance:
                    raise ValueError(f"ترلاسه شوی مقدار ({amount}) د پور ({-balance}) څخه کم دی")
                update_cash(curr, -balance, f"وصل (ترلاسه) {d['person_name']}", conn)
                balance = 0
            else:
                raise ValueError("بیلانس صفر دی، وصل کولو ته اړتیا نشته")
        else:
            raise ValueError('ناسم ډول معامله')
        c.execute("UPDATE PersonBalances SET balance=? WHERE person_id=? AND currency=?", (balance, pid, curr))
        now = datetime.datetime.now().isoformat()
        c.execute('''INSERT INTO PrincipalTransactions 
                     (person_id, person_name, person_id_number, trans_type, amount, currency, trans_date, notes)
                     VALUES (?,?,?,?,?,?,?,?)''',
                  (pid, d['person_name'], d['person_id_number'], ttype, amount, curr, now, d.get('notes', '')))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@app.route('/api/edit_principal_transaction', methods=['POST'])
@login_required
def edit_principal():
    d = request.get_json()
    tid = d.get('id')
    if not tid:
        return jsonify({'success': False, 'message': 'ID نشته'})
    conn = get_db()
    try:
        old = conn.execute("SELECT * FROM PrincipalTransactions WHERE id=?", (tid,)).fetchone()
        if not old:
            return jsonify({'success': False, 'message': 'معامله ونه موندل شوه'})
        # Revert old transaction
        pid = old['person_id']
        curr = old['currency']
        old_amt = old['amount']
        old_type = old['trans_type']
        bal = conn.execute("SELECT balance FROM PersonBalances WHERE person_id=? AND currency=?", (pid, curr)).fetchone()
        balance = bal['balance'] if bal else 0.0
        # Reverse effect
        if old_type == 'deposit':
            balance -= old_amt
            update_cash(curr, -old_amt, f"بېرته امانت ورکول {old['person_name']}", conn)
        elif old_type == 'withdrawal':
            balance += old_amt
            update_cash(curr, old_amt, f"بېرته امانت اخیستل {old['person_name']}", conn)
        elif old_type == 'loan_given':
            balance += old_amt
            update_cash(curr, old_amt, f"بېرته پور ورکول {old['person_name']}", conn)
        elif old_type == 'loan_received':
            balance -= old_amt
            update_cash(curr, -old_amt, f"بېرته پور اخیستل {old['person_name']}", conn)
        elif old_type == 'settlement':
            # Reverse settlement: restore previous balance
            if old_amt > 0:
                balance = old_amt
                update_cash(curr, old_amt, f"بېرته وصل {old['person_name']}", conn)
            else:
                balance = old_amt
                update_cash(curr, old_amt, f"بېرته وصل {old['person_name']}", conn)
        # Apply new transaction
        new_type = d['trans_type']
        new_amt = float(d['amount'])
        if new_type == 'deposit':
            balance += new_amt
            update_cash(curr, new_amt, f"سمون امانت ورکول {d['person_name']}", conn)
        elif new_type == 'withdrawal':
            if balance < new_amt:
                raise ValueError(f"کافي امانت نشته: {balance}")
            balance -= new_amt
            update_cash(curr, -new_amt, f"سمون امانت اخیستل {d['person_name']}", conn)
        elif new_type == 'loan_given':
            cur_cash = conn.execute("SELECT amount FROM CashBalances WHERE currency=?", (curr,)).fetchone()
            if not cur_cash or cur_cash[0] < new_amt:
                raise ValueError(f"په {curr} کې کافي پیسې نشته")
            balance -= new_amt
            update_cash(curr, -new_amt, f"سمون پور ورکول {d['person_name']}", conn)
        elif new_type == 'loan_received':
            balance += new_amt
            update_cash(curr, new_amt, f"سمون پور اخیستل {d['person_name']}", conn)
        elif new_type == 'settlement':
            if balance > 0:
                update_cash(curr, -balance, f"سمون وصل (ادا) {d['person_name']}", conn)
                balance = 0
            elif balance < 0:
                update_cash(curr, -balance, f"سمون وصل (ترلاسه) {d['person_name']}", conn)
                balance = 0
        else:
            raise ValueError('ناسم ډول')
        conn.execute("UPDATE PersonBalances SET balance=? WHERE person_id=? AND currency=?", (balance, pid, curr))
        conn.execute("""UPDATE PrincipalTransactions 
                        SET person_name=?, person_id_number=?, trans_type=?, amount=?, currency=?, notes=?
                        WHERE id=?""",
                     (d['person_name'], d['person_id_number'], new_type, new_amt, curr, d.get('notes', ''), tid))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@app.route('/api/get_all_person_balances')
@login_required
def get_persons():
    conn = get_db()
    rows = conn.execute('''SELECT p.id, p.name, p.id_number, p.phone, b.balance as net, b.currency
                           FROM Persons p JOIN PersonBalances b ON p.id=b.person_id
                           WHERE b.balance != 0
                           ORDER BY p.name''').fetchall()
    conn.close()
    return jsonify([{'id': r[0], 'name': r[1], 'id_number': r[2], 'phone': r[3], 'net': r[4], 'currency': r[5]} for r in rows])

@app.route('/api/get_principal_transactions')
@login_required
def get_principal_trans():
    conn = get_db()
    rows = conn.execute("SELECT * FROM PrincipalTransactions ORDER BY trans_date DESC LIMIT 200").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/delete_principal_transaction', methods=['POST'])
@login_required
def del_principal():
    tid = request.get_json().get('id')
    if not tid:
        return jsonify({'success': False})
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM PrincipalTransactions WHERE id=?", (tid,)).fetchone()
        if not row:
            return jsonify({'success': False, 'message': 'معامله ونه موندل شوه'})
        pid, curr, amt, ttype = row['person_id'], row['currency'], row['amount'], row['trans_type']
        bal = conn.execute("SELECT balance FROM PersonBalances WHERE person_id=? AND currency=?", (pid, curr)).fetchone()
        if bal:
            balance = bal['balance']
            if ttype == 'deposit':
                balance -= amt
                update_cash(curr, -amt, f"حذف امانت ورکول {row['person_name']}", conn)
            elif ttype == 'withdrawal':
                balance += amt
                update_cash(curr, amt, f"حذف امانت اخیستل {row['person_name']}", conn)
            elif ttype == 'loan_given':
                balance += amt
                update_cash(curr, amt, f"حذف پور ورکول {row['person_name']}", conn)
            elif ttype == 'loan_received':
                balance -= amt
                update_cash(curr, -amt, f"حذف پور اخیستل {row['person_name']}", conn)
            elif ttype == 'settlement':
                if amt > 0:
                    balance = amt
                    update_cash(curr, amt, f"بېرته وصل {row['person_name']}", conn)
                else:
                    balance = amt
                    update_cash(curr, amt, f"بېرته وصل {row['person_name']}", conn)
            conn.execute("UPDATE PersonBalances SET balance=? WHERE person_id=? AND currency=?", (balance, pid, curr))
        conn.execute("DELETE FROM PrincipalTransactions WHERE id=?", (tid,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@app.route('/api/get_dashboard_data')
@login_required
def dashboard():
    cash = get_cash().json
    today = datetime.date.today().isoformat()
    conn = get_db()
    today_ex = [dict(r) for r in conn.execute("SELECT * FROM ExchangeTransactions WHERE trans_date LIKE ?", (today+'%',)).fetchall()]
    today_rem = [dict(r) for r in conn.execute("SELECT * FROM Remittances WHERE trans_date LIKE ?", (today+'%',)).fetchall()]
    persons = get_persons().json
    conn.close()
    return jsonify({'cash': cash, 'today_exchanges': today_ex, 'today_remittances': today_rem, 'persons': persons})

@app.route('/api/get_report_data')
@login_required
def report_data():
    conn = get_db()
    cash_rows = conn.execute("SELECT currency, amount FROM CashBalances").fetchall()
    cash_dict = {r[0]: r[1] for r in cash_rows}
    persons_rows = conn.execute('''SELECT p.name, b.currency, b.balance as net
                                   FROM Persons p JOIN PersonBalances b ON p.id=b.person_id
                                   WHERE b.balance != 0''').fetchall()
    persons_net = [{'name': r[0], 'currency': r[1], 'net': r[2]} for r in persons_rows]
    conn.close()
    return jsonify({'cash': cash_dict, 'persons_net': persons_net})

@app.route('/api/change_credentials', methods=['POST'])
@login_required
def change_creds():
    d = request.get_json()
    old_pass = d.get('old_pass')
    new_user = d.get('new_user')
    new_pass = d.get('new_pass')
    if not old_pass:
        return jsonify({'success': False, 'message': 'اوسنی پاسورډ اړین دی'})
    conn = get_db()
    hashed = hashlib.sha256(old_pass.encode()).hexdigest()
    user = conn.execute("SELECT id FROM Users WHERE username=? AND password=?", (session['user'], hashed)).fetchone()
    if not user:
        conn.close()
        return jsonify({'success': False, 'message': 'اوسنی پاسورډ غلط دی'})
    if new_user:
        conn.execute("UPDATE Users SET username=? WHERE username=?", (new_user, session['user']))
    if new_pass:
        new_hashed = hashlib.sha256(new_pass.encode()).hexdigest()
        conn.execute("UPDATE Users SET password=? WHERE username=?", (new_hashed, new_user or session['user']))
    conn.commit()
    conn.close()
    session.clear()
    return jsonify({'success': True, 'message': 'معلومات نوي شول'})

@app.route('/api/get_app_info')
def info():
    return jsonify({
        'app': 'صرافي او حوالې',
        'dev': 'عبیدالله اریان',
        'phone': '+۹۳۷۷۹۰۶۲۱۵۵',
        'email': 'Obaidaryan155@gmail.com',
        'addr': 'افغانستان - پکتیا'
    })

@app.route('/api/backup_database')
@login_required
def backup():
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
    fname = f"backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(DB_FILE, os.path.join(BACKUP_DIR, fname))
    return jsonify({'success': True, 'file': fname})

if __name__ == '__main__':
    init_db()
    app.run(debug=False, host='0.0.0.0', port=5000)