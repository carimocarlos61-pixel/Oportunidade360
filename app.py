import os, sqlite3, secrets
from functools import wraps
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "oportunidade360.db"))

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-before-production-" + secrets.token_hex(16))
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user',
          phone TEXT DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL,
          category TEXT NOT NULL DEFAULT 'Microtarefas', reward REAL NOT NULL DEFAULT 0,
          source TEXT NOT NULL DEFAULT 'own', external_url TEXT DEFAULT '',
          status TEXT NOT NULL DEFAULT 'pending', budget_available REAL NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS submissions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
          proof TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', reward REAL NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, reviewed_at TEXT DEFAULT '',
          UNIQUE(task_id, user_id), FOREIGN KEY(task_id) REFERENCES tasks(id),
          FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS wallet (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount REAL NOT NULL,
          kind TEXT NOT NULL, description TEXT NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS withdrawals (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount REAL NOT NULL,
          method TEXT NOT NULL, phone TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS campaign_requests (
          id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL, contact_name TEXT NOT NULL,
          email TEXT NOT NULL, phone TEXT DEFAULT '', campaign_type TEXT NOT NULL,
          details TEXT NOT NULL, budget REAL DEFAULT 0, status TEXT NOT NULL DEFAULT 'new',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS partners (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT DEFAULT '',
          url TEXT NOT NULL, commission_note TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        # Optional admin bootstrap. Set ADMIN_EMAIL and ADMIN_PASSWORD in environment.
        admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
        admin_password = os.environ.get("ADMIN_PASSWORD", "")
        if admin_email and admin_password and not con.execute("SELECT id FROM users WHERE role='admin'").fetchone():
            con.execute("INSERT OR IGNORE INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                        ("Administrador", admin_email, generate_password_hash(admin_password), "admin", now()))
        if not con.execute("SELECT id FROM tasks LIMIT 1").fetchone():
            con.execute("""INSERT INTO tasks(title,description,category,reward,source,status,budget_available,created_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                ("Conhecer a plataforma", "Leia as páginas principais do Oportunidade360 e envie uma opinião curta sobre uma melhoria útil.", "Questionário", 0, "own", "active", 0, now()))

def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

@app.before_request
def csrf_setup():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)

@app.context_processor
def inject_globals():
    return {"csrf_token": session.get("csrf", ""), "current_user": get_user(),
            "site_name": "Oportunidade360"}

@app.before_request
def csrf_check():
    if request.method == "POST":
        token = request.form.get("csrf_token", "")
        if not token or not secrets.compare_digest(token, session.get("csrf", "")):
            abort(400, "Pedido inválido. Atualize a página e tente novamente.")

def get_user():
    uid = session.get("user_id")
    if not uid: return None
    with db() as con:
        return con.execute("SELECT id,name,email,role,phone FROM users WHERE id=?", (uid,)).fetchone()

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not get_user():
            flash("Inicia sessão para continuar.", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_user()
        if not user or user["role"] != "admin": abort(403)
        return fn(*args, **kwargs)
    return wrapper

@app.route("/")
def index():
    with db() as con:
        tasks = con.execute("SELECT * FROM tasks WHERE status='active' ORDER BY id DESC LIMIT 6").fetchall()
        partners = con.execute("SELECT * FROM partners WHERE status='active' ORDER BY id DESC LIMIT 4").fetchall()
    return render_template("index.html", tasks=tasks, partners=partners)

@app.route("/registo", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name=request.form.get("name","").strip()
        email=request.form.get("email","").strip().lower()
        password=request.form.get("password","")
        phone=request.form.get("phone","").strip()
        if len(name)<2 or "@" not in email or len(password)<8:
            flash("Preenche os dados corretamente. A palavra-passe deve ter pelo menos 8 caracteres.", "danger")
        else:
            try:
                with db() as con:
                    admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
                    assigned_role = "admin" if admin_email and email == admin_email else "user"
                    cur=con.execute("INSERT INTO users(name,email,password_hash,role,phone,created_at) VALUES(?,?,?,?,?,?)",
                                    (name,email,generate_password_hash(password),assigned_role,phone,now()))
                    session["user_id"]=cur.lastrowid
                flash("Conta criada com sucesso!", "success")
                return redirect(url_for("admin") if assigned_role == "admin" else url_for("dashboard"))
            except sqlite3.IntegrityError:
                flash("Este email já está registado.", "warning")
    return render_template("auth.html", mode="register")

@app.route("/entrar", methods=["GET","POST"])
def login():
    if request.method=="POST":
        email=request.form.get("email","").strip().lower()
        password=request.form.get("password","")
        with db() as con:
            user=con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"]=user["id"]
            session["csrf"]=secrets.token_urlsafe(24)
            return redirect(url_for("admin") if user["role"]=="admin" else url_for("dashboard"))
        flash("Email ou palavra-passe incorretos.", "danger")
    return render_template("auth.html", mode="login")

@app.post("/sair")
@login_required
def logout():
    session.clear()
    flash("Sessão terminada.", "success")
    return redirect(url_for("index"))

@app.route("/painel")
@login_required
def dashboard():
    user=get_user()
    with db() as con:
        tasks=con.execute("""SELECT t.*, s.id AS submission_id, s.status AS submission_status
            FROM tasks t LEFT JOIN submissions s ON s.task_id=t.id AND s.user_id=?
            WHERE t.status='active' ORDER BY t.id DESC""",(user["id"],)).fetchall()
        balance=con.execute("SELECT COALESCE(SUM(amount),0) AS total FROM wallet WHERE user_id=?",(user["id"],)).fetchone()["total"]
        history=con.execute("SELECT * FROM wallet WHERE user_id=? ORDER BY id DESC LIMIT 8",(user["id"],)).fetchall()
        withdrawals=con.execute("SELECT * FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 5",(user["id"],)).fetchall()
    return render_template("dashboard.html",tasks=tasks,balance=balance,history=history,withdrawals=withdrawals)

@app.post("/tarefa/<int:task_id>/enviar")
@login_required
def submit_task(task_id):
    proof=request.form.get("proof","").strip()
    if len(proof)<5:
        flash("Explica brevemente como concluíste a tarefa.", "warning")
        return redirect(url_for("dashboard"))
    with db() as con:
        task=con.execute("SELECT * FROM tasks WHERE id=? AND status='active'",(task_id,)).fetchone()
        if not task:
            flash("Esta tarefa já não está disponível.", "warning")
        else:
            try:
                con.execute("INSERT INTO submissions(task_id,user_id,proof,created_at) VALUES(?,?,?,?)",
                            (task_id,get_user()["id"],proof,now()))
                flash("Tarefa enviada para análise. O saldo só será atribuído após validação e confirmação do orçamento.", "success")
            except sqlite3.IntegrityError:
                flash("Já enviaste esta tarefa.", "warning")
    return redirect(url_for("dashboard"))

@app.post("/levantamento")
@login_required
def withdrawal():
    method=request.form.get("method","")
    phone=request.form.get("phone","").strip()
    try: amount=float(request.form.get("amount","0"))
    except ValueError: amount=0
    if method not in ("M-Pesa","e-Mola") or len(phone)<9 or amount<=0:
        flash("Verifica o valor, o número e o método de pagamento.", "danger")
        return redirect(url_for("dashboard"))
    with db() as con:
        bal=con.execute("SELECT COALESCE(SUM(amount),0) AS total FROM wallet WHERE user_id=?",(get_user()["id"],)).fetchone()["total"]
        pending=con.execute("SELECT COALESCE(SUM(amount),0) AS total FROM withdrawals WHERE user_id=? AND status='pending'",(get_user()["id"],)).fetchone()["total"]
        if amount > bal-pending:
            flash("Saldo disponível insuficiente.", "warning")
        else:
            con.execute("INSERT INTO withdrawals(user_id,amount,method,phone,created_at) VALUES(?,?,?,?,?)",
                        (get_user()["id"],amount,method,phone,now()))
            flash("Pedido registado. Ainda não é um pagamento efetuado; será analisado pelo administrador.", "success")
    return redirect(url_for("dashboard"))

@app.route("/empresas", methods=["GET","POST"])
def companies():
    if request.method=="POST":
        data=[request.form.get(k,"").strip() for k in ("company","contact_name","email","phone","campaign_type","details")]
        try: budget=max(0,float(request.form.get("budget","0") or 0))
        except ValueError: budget=0
        if any(not x for x in (data[0],data[1],data[2],data[4],data[5])) or "@" not in data[2]:
            flash("Preenche os campos obrigatórios corretamente.", "danger")
        else:
            with db() as con:
                con.execute("""INSERT INTO campaign_requests(company,contact_name,email,phone,campaign_type,details,budget,created_at)
                    VALUES(?,?,?,?,?,?,?,?)""",(*data,budget,now()))
            flash("Pedido recebido! A nossa equipa poderá contactar-te para conversar sobre a campanha.", "success")
            return redirect(url_for("companies"))
    return render_template("companies.html")

@app.route("/parceiros")
def partners_page():
    with db() as con:
        partners=con.execute("SELECT * FROM partners WHERE status='active' ORDER BY name").fetchall()
    return render_template("partners.html",partners=partners)

@app.route("/sobre")
def about(): return render_template("about.html")

@app.route("/privacidade")
def privacy(): return render_template("privacy.html")

@app.route("/termos")
def terms(): return render_template("terms.html")

@app.route("/admin")
@login_required
@admin_required
def admin():
    with db() as con:
        counts={
          "users":con.execute("SELECT COUNT(*) FROM users WHERE role!='admin'").fetchone()[0],
          "tasks":con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
          "submissions":con.execute("SELECT COUNT(*) FROM submissions WHERE status='pending'").fetchone()[0],
          "campaigns":con.execute("SELECT COUNT(*) FROM campaign_requests WHERE status='new'").fetchone()[0],
          "withdrawals":con.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0]
        }
        submissions=con.execute("""SELECT s.*,u.name,u.email,t.title,t.reward,t.budget_available
            FROM submissions s JOIN users u ON u.id=s.user_id JOIN tasks t ON t.id=s.task_id
            ORDER BY s.id DESC LIMIT 30""").fetchall()
        campaigns=con.execute("SELECT * FROM campaign_requests ORDER BY id DESC LIMIT 20").fetchall()
        withdrawals=con.execute("SELECT w.*,u.name,u.email FROM withdrawals w JOIN users u ON u.id=w.user_id ORDER BY w.id DESC LIMIT 20").fetchall()
        tasks=con.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()
        partners=con.execute("SELECT * FROM partners ORDER BY id DESC").fetchall()
    return render_template("admin.html",counts=counts,submissions=submissions,campaigns=campaigns,withdrawals=withdrawals,tasks=tasks,partners=partners)

@app.post("/admin/tarefa/criar")
@login_required
@admin_required
def create_task():
    title=request.form.get("title","").strip(); desc=request.form.get("description","").strip()
    category=request.form.get("category","Microtarefas").strip()
    source=request.form.get("source","own")
    try: reward=max(0,float(request.form.get("reward","0") or 0))
    except ValueError: reward=0
    try: budget=max(0,float(request.form.get("budget","0") or 0))
    except ValueError: budget=0
    if not title or not desc:
        flash("Título e descrição são obrigatórios.", "danger")
    else:
        with db() as con:
            con.execute("INSERT INTO tasks(title,description,category,reward,source,status,budget_available,created_at) VALUES(?,?,?,?,?,'active',?,?)",
                        (title,desc,category,reward,source,budget,now()))
        flash("Tarefa criada.", "success")
    return redirect(url_for("admin"))

@app.post("/admin/submissao/<int:sid>/<action>")
@login_required
@admin_required
def review_submission(sid,action):
    if action not in ("approve","reject"): abort(404)
    with db() as con:
        sub=con.execute("""SELECT s.*,t.reward,t.budget_available,t.title FROM submissions s
            JOIN tasks t ON t.id=s.task_id WHERE s.id=?""",(sid,)).fetchone()
        if not sub or sub["status"]!="pending":
            flash("Submissão não encontrada ou já analisada.", "warning")
        elif action=="approve":
            reward=float(sub["reward"])
            # Do not credit paid tasks without a funded budget.
            if reward>0 and sub["budget_available"]<reward:
                flash("Orçamento insuficiente nesta tarefa. Adiciona fundos confirmados antes de aprovar.", "danger")
            else:
                con.execute("UPDATE submissions SET status='approved',reward=?,reviewed_at=? WHERE id=?",(reward,now(),sid))
                if reward>0:
                    con.execute("UPDATE tasks SET budget_available=budget_available-? WHERE id=?",(reward,sub["task_id"]))
                    con.execute("INSERT INTO wallet(user_id,amount,kind,description,created_at) VALUES(?,?,?,?,?)",
                                (sub["user_id"],reward,"credit","Recompensa: "+sub["title"],now()))
                flash("Submissão aprovada.", "success")
        else:
            con.execute("UPDATE submissions SET status='rejected',reviewed_at=? WHERE id=?",(now(),sid))
            flash("Submissão rejeitada.", "success")
    return redirect(url_for("admin"))

@app.post("/admin/levantamento/<int:wid>/<action>")
@login_required
@admin_required
def review_withdrawal(wid,action):
    if action not in ("paid","reject"): abort(404)
    with db() as con:
        w=con.execute("SELECT * FROM withdrawals WHERE id=?",(wid,)).fetchone()
        if not w or w["status"]!="pending":
            flash("Pedido não encontrado ou já analisado.", "warning")
        elif action=="paid":
            # Admin must perform transfer outside the app and only then mark paid.
            con.execute("UPDATE withdrawals SET status='paid' WHERE id=?",(wid,))
            con.execute("INSERT INTO wallet(user_id,amount,kind,description,created_at) VALUES(?,?,?,?,?)",
                        (w["user_id"],-w["amount"],"debit","Levantamento "+w["method"],now()))
            flash("Marcado como pago. Confirma que a transferência foi realmente efetuada.", "success")
        else:
            con.execute("UPDATE withdrawals SET status='rejected' WHERE id=?",(wid,))
            flash("Pedido rejeitado; o saldo permanece disponível.", "success")
    return redirect(url_for("admin"))

@app.post("/admin/campanha/<int:cid>/<status>")
@login_required
@admin_required
def campaign_status(cid,status):
    if status not in ("contacted","closed","rejected"): abort(404)
    with db() as con: con.execute("UPDATE campaign_requests SET status=? WHERE id=?",(status,cid))
    flash("Estado da campanha atualizado.", "success")
    return redirect(url_for("admin"))

@app.post("/admin/parceiro")
@login_required
@admin_required
def add_partner():
    name=request.form.get("name","").strip(); url=request.form.get("url","").strip()
    desc=request.form.get("description","").strip(); note=request.form.get("commission_note","").strip()
    if name and url.startswith(("https://","http://")):
        with db() as con: con.execute("INSERT INTO partners(name,description,url,commission_note) VALUES(?,?,?,?)",(name,desc,url,note))
        flash("Parceiro adicionado.", "success")
    else: flash("Indica o nome e um link válido iniciado por https://.", "danger")
    return redirect(url_for("admin"))

@app.post("/admin/parceiro/<int:pid>/toggle")
@login_required
@admin_required
def toggle_partner(pid):
    with db() as con:
        p=con.execute("SELECT status FROM partners WHERE id=?",(pid,)).fetchone()
        if p: con.execute("UPDATE partners SET status=? WHERE id=?",("inactive" if p["status"]=="active" else "active",pid))
    return redirect(url_for("admin"))

@app.errorhandler(403)
def forbidden(e): return render_template("error.html",code=403,message="Não tens autorização para aceder a esta página."),403
@app.errorhandler(404)
def not_found(e): return render_template("error.html",code=404,message="A página que procuras não existe."),404
@app.errorhandler(400)
def bad_request(e): return render_template("error.html",code=400,message="Pedido inválido. Atualiza a página e tenta novamente."),400

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_DEBUG")=="1")
