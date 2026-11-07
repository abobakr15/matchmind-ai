
import os
import sqlite3
import hashlib
import secrets
from pathlib import Path
from datetime import datetime, timezone
import streamlit as st

APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "matchmind.db"
REPORT_DIR = APP_DIR / "reports"
REPORT_DIR.mkdir(exist_ok=True)
ADMIN_PASSWORD = os.getenv("MATCHMIND_ADMIN_PASSWORD", "")

st.set_page_config(page_title="MatchMind AI", page_icon="⚽", layout="wide")

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wallet_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            change_amount INTEGER NOT NULL,
            reason TEXT NOT NULL,
            reference TEXT UNIQUE,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS report_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            team_name TEXT NOT NULL,
            competition TEXT,
            scope TEXT NOT NULL DEFAULT 'آخر 10 مباريات رسمية مكتملة',
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            pdf_path TEXT,
            created_at TEXT NOT NULL,
            delivered_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_reports_customer ON report_requests(customer_id);
        """)
        c.commit()

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240000).hex()
    return f"{salt}${digest}"

def verify_password(password, stored):
    try:
        salt, expected = stored.split("$", 1)
        return secrets.compare_digest(password_hash(password, salt).split("$", 1)[1], expected)
    except Exception:
        return False

def get_balance(customer_id):
    with db() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(change_amount),0) AS balance FROM wallet_ledger WHERE customer_id=?",
            (customer_id,)
        ).fetchone()
        return int(row["balance"])

def register(email, password):
    with db() as c:
        c.execute("INSERT INTO customers(email,password_hash,created_at) VALUES(?,?,?)",
                  (email.lower().strip(), password_hash(password), now()))
        c.commit()

def login(email, password):
    with db() as c:
        row = c.execute("SELECT * FROM customers WHERE email=?", (email.lower().strip(),)).fetchone()
        if row and verify_password(password, row["password_hash"]):
            return dict(row)
    return None

def customer_reports(customer_id):
    with db() as c:
        return c.execute(
            "SELECT * FROM report_requests WHERE customer_id=? ORDER BY id DESC",
            (customer_id,)
        ).fetchall()

def create_request(customer_id, team, competition, notes):
    # Reserve/check is not a debit: credits are deducted only when delivered.
    with db() as c:
        balance = c.execute(
            "SELECT COALESCE(SUM(change_amount),0) AS b FROM wallet_ledger WHERE customer_id=?",
            (customer_id,)
        ).fetchone()["b"]
        active = c.execute(
            "SELECT COUNT(*) AS n FROM report_requests WHERE customer_id=? AND status IN ('queued','processing')",
            (customer_id,)
        ).fetchone()["n"]
        if int(balance) - int(active) <= 0:
            raise ValueError("لا يوجد رصيد متاح لطلب تقرير جديد.")
        c.execute("""INSERT INTO report_requests(customer_id,team_name,competition,notes,created_at)
                     VALUES(?,?,?,?,?)""",
                  (customer_id, team.strip(), competition.strip(), notes.strip(), now()))
        c.commit()

def set_status(report_id, status):
    with db() as c:
        c.execute("UPDATE report_requests SET status=? WHERE id=? AND status!='delivered'",
                  (status, report_id))
        c.commit()

def deliver_report(report_id, pdf_bytes, original_name):
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("الملف المرفوع لا يبدو ملف PDF صالحاً.")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        report = c.execute("SELECT * FROM report_requests WHERE id=?", (report_id,)).fetchone()
        if not report:
            raise ValueError("الطلب غير موجود.")
        if report["status"] == "delivered":
            raise ValueError("تم تسليم هذا التقرير بالفعل.")
        customer_id = report["customer_id"]
        balance = c.execute(
            "SELECT COALESCE(SUM(change_amount),0) AS b FROM wallet_ledger WHERE customer_id=?",
            (customer_id,)
        ).fetchone()["b"]
        if int(balance) < 1:
            raise ValueError("رصيد العميل غير كافٍ.")
        safe_name = f"report_{report_id}.pdf"
        path = REPORT_DIR / safe_name
        path.write_bytes(pdf_bytes)
        # Unique reference prevents duplicate debit on retries.
        c.execute("""INSERT INTO wallet_ledger(customer_id,change_amount,reason,reference,created_at)
                     VALUES(?,?,?,?,?)""",
                  (customer_id, -1, f"تسليم التقرير #{report_id}", f"report-delivery-{report_id}", now()))
        c.execute("""UPDATE report_requests SET status='delivered',pdf_path=?,delivered_at=?
                     WHERE id=?""", (str(path), now(), report_id))
        c.commit()

def all_customers():
    with db() as c:
        return c.execute("SELECT id,email,created_at FROM customers ORDER BY id DESC").fetchall()

def all_requests():
    with db() as c:
        return c.execute("""SELECT r.*, u.email FROM report_requests r
                            JOIN customers u ON u.id=r.customer_id ORDER BY r.id DESC""").fetchall()

def add_credits(customer_id, amount, note):
    if amount <= 0:
        raise ValueError("عدد التقارير يجب أن يكون أكبر من صفر.")
    ref = f"manual-{secrets.token_urlsafe(16)}"
    with db() as c:
        c.execute("""INSERT INTO wallet_ledger(customer_id,change_amount,reason,reference,created_at)
                     VALUES(?,?,?,?,?)""",
                  (customer_id, amount, note, ref, now()))
        c.commit()

init_db()

if "user" not in st.session_state:
    st.session_state.user = None
if "admin" not in st.session_state:
    st.session_state.admin = False

st.title("⚽ MatchMind AI")
st.caption("منصة طلب تقارير تحليل المنافسين — نسخة أولية قابلة للتشغيل")

with st.sidebar:
    st.subheader("الحساب")
    if st.session_state.user:
        st.write(st.session_state.user["email"])
        if st.button("تسجيل الخروج", use_container_width=True):
            st.session_state.user = None
            st.rerun()
    elif st.session_state.admin:
        st.write("مدير النظام")
        if st.button("خروج المدير", use_container_width=True):
            st.session_state.admin = False
            st.rerun()
    else:
        mode = st.radio("الدخول", ["تسجيل الدخول", "إنشاء حساب"])
        email = st.text_input("البريد الإلكتروني")
        password = st.text_input("كلمة المرور", type="password")
        if mode == "إنشاء حساب":
            confirm = st.text_input("تأكيد كلمة المرور", type="password")
            if st.button("إنشاء الحساب", use_container_width=True):
                if not email or "@" not in email or len(password) < 10:
                    st.error("اكتب بريداً صحيحاً وكلمة مرور 10 أحرف على الأقل.")
                elif password != confirm:
                    st.error("كلمتا المرور غير متطابقتين.")
                else:
                    try:
                        register(email, password)
                        st.success("تم إنشاء الحساب. سجّل الدخول الآن.")
                    except sqlite3.IntegrityError:
                        st.error("هذا البريد مسجل بالفعل.")
        else:
            if st.button("دخول", use_container_width=True):
                user = login(email, password)
                if user:
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error("بيانات الدخول غير صحيحة.")
        st.divider()
        st.caption("للدخول كمدير، اضبط MATCHMIND_ADMIN_PASSWORD ثم استخدم:")
        admin_pw = st.text_input("كلمة مرور المدير", type="password")
        if st.button("دخول المدير", use_container_width=True):
            if ADMIN_PASSWORD and secrets.compare_digest(admin_pw, ADMIN_PASSWORD):
                st.session_state.admin = True
                st.rerun()
            else:
                st.error("دخول المدير غير مفعّل أو كلمة المرور غير صحيحة.")

if st.session_state.user:
    user = st.session_state.user
    balance = get_balance(user["id"])
    left, right = st.columns([2,1])
    with left:
        st.subheader("لوحة العميل")
        st.write(f"مرحباً، **{user['email']}**")
        st.metric("رصيد التقارير المتاح", balance)
        st.info("رصيد التقارير دائم ولا تنتهي صلاحيته. لا يتم خصم تقرير إلا بعد رفع وتسليم ملف PDF بنجاح.")
    with right:
        st.subheader("الباقة المعتمدة")
        st.metric("5 تقارير", "$99")
        st.caption("شراء مرة واحدة — لا يوجد تجديد تلقائي. إضافة الرصيد حالياً تتم من لوحة المدير إلى حين ربط الدفع لاحقاً.")
    st.divider()
    st.subheader("طلب تقرير جديد")
    with st.form("new_report"):
        team = st.text_input("اسم الفريق", placeholder="مثال: الزمالك")
        competition = st.text_input("المسابقة (اختياري)", placeholder="مثال: الدوري المصري")
        notes = st.text_area("ملاحظات إضافية (اختياري)")
        submitted = st.form_submit_button("إرسال طلب التحليل")
        if submitted:
            if not team.strip():
                st.error("اكتب اسم الفريق.")
            else:
                try:
                    create_request(user["id"], team, competition, notes)
                    st.success("تم تسجيل طلبك. سيتم تحديث حالته من لوحة التشغيل.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    st.divider()
    st.subheader("تقاريري")
    reports = customer_reports(user["id"])
    if not reports:
        st.caption("لا توجد تقارير حتى الآن.")
    for r in reports:
        with st.container(border=True):
            a,b = st.columns([3,1])
            a.write(f"**#{r['id']} — {r['team_name']}**")
            a.caption(f"{r['competition'] or 'المسابقة غير محددة'} · {r['created_at'][:10]}")
            status_ar = {"queued":"قيد الانتظار","processing":"جارٍ التحليل","delivered":"تم التسليم","cancelled":"ملغي"}.get(r["status"], r["status"])
            b.write(status_ar)
            if r["status"] == "delivered" and r["pdf_path"] and Path(r["pdf_path"]).exists():
                a.download_button("تحميل التقرير PDF", data=Path(r["pdf_path"]).read_bytes(),
                                  file_name=f"MatchMind_Report_{r['id']}.pdf", mime="application/pdf",
                                  key=f"dl_{r['id']}")
elif st.session_state.admin:
    st.subheader("لوحة إدارة MatchMind AI")
    tabs = st.tabs(["العملاء والأرصدة", "طلبات التقارير"])
    with tabs[0]:
        customers = all_customers()
        st.write(f"عدد العملاء: **{len(customers)}**")
        if customers:
            options = {f"{u['email']} (#{u['id']})": u["id"] for u in customers}
            chosen = st.selectbox("اختر العميل", list(options.keys()))
            amount = st.number_input("عدد الأرصدة المراد إضافتها", min_value=1, max_value=100, value=5, step=1)
            note = st.text_input("سبب الإضافة", value="باقة 5 تقارير — إضافة يدوية")
            if st.button("إضافة الرصيد"):
                add_credits(options[chosen], int(amount), note)
                st.success("تمت إضافة الرصيد.")
                st.rerun()
            st.divider()
            for u in customers:
                st.write(f"**{u['email']}** — الرصيد: {get_balance(u['id'])}")
        else:
            st.caption("لا يوجد عملاء بعد.")
    with tabs[1]:
        requests = all_requests()
        if not requests:
            st.caption("لا توجد طلبات.")
        for r in requests:
            with st.container(border=True):
                st.write(f"**طلب #{r['id']} — {r['team_name']}**")
                st.caption(f"{r['email']} · {r['competition'] or 'المسابقة غير محددة'} · {r['created_at'][:10]}")
                st.write(f"الحالة: {r['status']}")
                c1,c2,c3 = st.columns(3)
                if c1.button("بدء التحليل", key=f"proc_{r['id']}") and r["status"] != "delivered":
                    set_status(r["id"], "processing")
                    st.rerun()
                if c2.button("إلغاء الطلب", key=f"cancel_{r['id']}") and r["status"] != "delivered":
                    set_status(r["id"], "cancelled")
                    st.rerun()
                if r["status"] != "delivered":
                    uploaded = st.file_uploader("رفع التقرير النهائي PDF", type=["pdf"], key=f"pdf_{r['id']}")
                    if st.button("تسليم التقرير وخصم رصيد واحد", key=f"deliver_{r['id']}"):
                        if not uploaded:
                            st.error("ارفع ملف PDF أولاً.")
                        else:
                            try:
                                deliver_report(r["id"], uploaded.getvalue(), uploaded.name)
                                st.success("تم التسليم وخصم رصيد واحد.")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))
else:
    st.subheader("تقارير تحليل المنافسين لكرة القدم")
    st.write("أنشئ حساباً لمتابعة رصيد تقاريرك وطلبات التحليل واستلام ملفات PDF.")
    st.markdown("""
    **الباقة الأساسية المعتمدة**
    - 5 تقارير مقابل **99 دولاراً**
    - رصيد دائم لا تنتهي صلاحيته
    - لا يوجد تجديد تلقائي
    - خصم الرصيد بعد تسليم التقرير بنجاح
    """)
    st.warning("هذه نسخة MVP أولية: إدارة الطلبات والمحفظة تعمل، أما جمع إحصائيات المباريات والتحليل الآلي فسيتم ربطهما في المرحلة التالية بمصادر بيانات مرخصة.")
