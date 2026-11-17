import os, sqlite3, secrets, json
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
          phone TEXT DEFAULT '', account_type TEXT NOT NULL DEFAULT 'participant', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL,
          category TEXT NOT NULL DEFAULT 'Microtarefas', reward REAL NOT NULL DEFAULT 0, points_reward INTEGER NOT NULL DEFAULT 0,
          source TEXT NOT NULL DEFAULT 'own', external_url TEXT DEFAULT '',
          status TEXT NOT NULL DEFAULT 'pending', budget_available REAL NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, task_type TEXT NOT NULL DEFAULT 'test',
          quiz_question TEXT DEFAULT '', quiz_options TEXT DEFAULT '', quiz_answer TEXT DEFAULT '', quiz_duration INTEGER NOT NULL DEFAULT 5
        );
        CREATE TABLE IF NOT EXISTS quiz_questions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL, question TEXT NOT NULL,
          options TEXT NOT NULL, correct_answer TEXT DEFAULT '', question_kind TEXT NOT NULL DEFAULT 'choice',
          sort_order INTEGER NOT NULL DEFAULT 1, FOREIGN KEY(task_id) REFERENCES tasks(id)
        );
        CREATE TABLE IF NOT EXISTS submissions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
          proof TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', reward REAL NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, reviewed_at TEXT DEFAULT '', points_awarded INTEGER NOT NULL DEFAULT 0,
          UNIQUE(task_id, user_id), FOREIGN KEY(task_id) REFERENCES tasks(id),
          FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS points_wallet (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, points INTEGER NOT NULL,
          description TEXT NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS metcash_wallet (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount INTEGER NOT NULL,
          description TEXT NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS point_redemptions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, points INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
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
        # Upgrade existing databases without deleting accounts.
        user_cols=[r["name"] for r in con.execute("PRAGMA table_info(users)").fetchall()]
        if "account_type" not in user_cols:
            con.execute("ALTER TABLE users ADD COLUMN account_type TEXT NOT NULL DEFAULT 'participant'")
        task_cols=[r["name"] for r in con.execute("PRAGMA table_info(tasks)").fetchall()]
        if "points_reward" not in task_cols:
            con.execute("ALTER TABLE tasks ADD COLUMN points_reward INTEGER NOT NULL DEFAULT 0")
        for col,definition in [("task_type","TEXT NOT NULL DEFAULT 'test'"),("external_url","TEXT DEFAULT ''"),("quiz_question","TEXT DEFAULT ''"),("quiz_options","TEXT DEFAULT ''"),("quiz_answer","TEXT DEFAULT ''"),("quiz_duration","INTEGER NOT NULL DEFAULT 5")]:
            if col not in task_cols:
                con.execute(f"ALTER TABLE tasks ADD COLUMN {col} {definition}")
        sub_cols=[r["name"] for r in con.execute("PRAGMA table_info(submissions)").fetchall()]
        if "points_awarded" not in sub_cols:
            con.execute("ALTER TABLE submissions ADD COLUMN points_awarded INTEGER NOT NULL DEFAULT 0")
        # Optional admin bootstrap. Set ADMIN_EMAIL and ADMIN_PASSWORD in environment.
        admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
        admin_password = os.environ.get("ADMIN_PASSWORD", "")
        if admin_email and admin_password and not con.execute("SELECT id FROM users WHERE role='admin'").fetchone():
            con.execute("INSERT OR IGNORE INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                        ("Administrador", admin_email, generate_password_hash(admin_password), "admin", now()))
        # New practical tasks: quizzes, short videos, sharing and usability tests.
        old_titles = ('Melhorias para a plataforma','Hábitos digitais','Testar a página inicial','Nova categoria de tarefas','Mensagem de apresentação','Negócios locais','Experiência no telemóvel','Ideia de campanha positiva','Acessibilidade','Interesses de formação','Partilha voluntária','Apresentar a um negócio','Rever instruções','Pergunta de questionário','Ideia para criadores','Revisão de termos','Publicidade responsável','Dica de segurança digital','Ideia de parceria','Feedback geral')
        con.execute("UPDATE tasks SET status='paused' WHERE title IN (" + ",".join("?" for _ in old_titles) + ")", old_titles)
        starter_tasks = [
          ("01 · Divulga no WhatsApp","Partilha o link da Oportunidade360 com pessoas e grupos que possam ter interesse. A meta sugerida é chegar a 10 contactos e 10 grupos relevantes, sem spam e respeitando as regras de cada grupo.","Divulgação",10,"share","","","",""),
          ("02 · Apresenta no Facebook","Partilha a página numa publicação tua, se quiseres, e explica honestamente para que serve.","Divulgação",10,"share","","","",""),
          ("03 · Partilha no Instagram","Partilha o link na tua bio ou story, se te sentires confortável. Não mostres dados pessoais.","Divulgação",10,"share","","","",""),
          ("04 · Quiz: segurança da conta","Escolhe a opção mais segura para proteger a tua conta.","Quiz de segurança",12,"quiz","","Qual é a melhor forma de proteger uma conta?","Usar uma palavra-passe forte e única|Partilhar a palavra-passe com amigos|Usar a mesma palavra-passe em todos os sites","Usar uma palavra-passe forte e única"),
          ("05 · Quiz: links suspeitos","Identifica a atitude mais segura perante um link desconhecido.","Quiz de segurança",12,"quiz","","Recebeste um link estranho a prometer prémios. O que deves fazer?","Abrir imediatamente|Verificar a origem e não fornecer dados|Enviar a palavra-passe para confirmar","Verificar a origem e não fornecer dados"),
          ("06 · Quiz: privacidade","Aprende a proteger os teus dados pessoais.","Quiz de segurança",12,"quiz","","Que informação nunca deves publicar numa tarefa pública?","A tua palavra-passe ou códigos de acesso|A tua opinião sobre o site|Uma sugestão de melhoria","A tua palavra-passe ou códigos de acesso"),
          ("07 · Quiz: melhorias","Ajuda-nos a escolher a próxima melhoria.","Quiz de produto",10,"quiz","","Qual melhoria seria mais útil?","Pesquisa e filtros de tarefas|Mais mensagens repetidas|Esconder as regras","Pesquisa e filtros de tarefas"),
          ("08 · Quiz: navegação","Testa o teu conhecimento sobre a plataforma.","Quiz de produto",10,"quiz","","Onde consultas os pontos atribuídos após aprovação?","Na carteira|Na página de anúncios|No formulário de registo","Na carteira"),
          ("09 · Quiz: anúncios","Aprende a reconhecer publicidade transparente.","Quiz de literacia digital",10,"quiz","","Como deve aparecer uma publicação paga por uma marca?","Identificada como publicidade ou patrocínio|Como opinião espontânea|Sem indicar a marca","Identificada como publicidade ou patrocínio"),
          ("10 · Quiz: campanhas","Ajuda a perceber que campanhas são úteis.","Quiz de preferências",10,"quiz","","Que campanha tende a ser mais útil?","Informação clara e útil|Promessas de ganhos garantidos|Mensagem sem identificação","Informação clara e útil"),
          ("11 · Quiz: regras","Conhece as regras básicas de participação.","Quiz de regras",10,"quiz","","Quando marcas uma tarefa como concluída?","Depois de cumprir as instruções|Antes de começar|Sem abrir a tarefa","Depois de cumprir as instruções"),
          ("12 · Quiz: dados familiares","Aprende a proteger a privacidade da tua família.","Quiz de privacidade",12,"quiz","","Um questionário pede detalhes familiares desnecessários. O que fazer?","Não fornecer dados sensíveis e comunicar|Inventar dados|Publicar os dados da família","Não fornecer dados sensíveis e comunicar"),
          ("13 · Quiz: idade","Aprende porque a recolha de idade deve ser limitada.","Quiz de privacidade",10,"quiz","","Se a idade não for necessária, o que deve a plataforma fazer?","Não pedir essa informação|Pedir a data de nascimento completa|Mostrar a idade publicamente","Não pedir essa informação"),
          ("14 · Quiz: motivação","Ajuda-nos a perceber o que torna a plataforma útil.","Quiz de preferências",10,"quiz","","Qual é uma razão saudável para participar?","Aprender e experimentar tarefas úteis|Partilhar dados privados|Acreditar em dinheiro garantido","Aprender e experimentar tarefas úteis"),
          ("15 · Vídeo rápido: plataforma","Assiste a um vídeo de apresentação de 10 a 30 segundos quando disponível e responde ao quiz.","Vídeo curto",12,"video","https://oportunidade360.onrender.com/","Qual é o objetivo principal da plataforma?","Ligar participantes, criadores e anunciantes|Prometer dinheiro sem condições|Vender dados pessoais","Ligar participantes, criadores e anunciantes"),
          ("16 · Vídeo rápido: segurança","Vê um vídeo curto sobre segurança digital e escolhe a resposta correta.","Vídeo curto",12,"video","https://www.youtube.com/results?search_query=seguranca+digital+basica+portugues","O que deves fazer antes de abrir um link?","Confirmar se a origem é confiável|Enviar os teus dados primeiro|Partilhar com todos","Confirmar se a origem é confiável"),
          ("17 · Testa a página inicial","Abre a página inicial e escolhe como foi a experiência.","Teste de utilização",12,"test","","","",""),
          ("18 · Testa a área de tarefas","Abre as tarefas e indica se as instruções são fáceis de perceber.","Teste de utilização",12,"test","","","",""),
          ("19 · Testa a carteira","Consulta a carteira e confirma se está claro que pontos não são dinheiro garantido.","Teste de utilização",12,"test","","","",""),
          ("20 · Testa a área de anunciante","Visita a área de empresas e indica se está claro como pedir uma campanha.","Teste de utilização",12,"test","","","","")
        ]
        for title,description,category,points,task_type,external_url,question,options,answer in starter_tasks:
            if not con.execute("SELECT id FROM tasks WHERE title=?",(title,)).fetchone():
                con.execute("""INSERT INTO tasks(title,description,category,reward,points_reward,source,status,budget_available,created_at,task_type,external_url,quiz_question,quiz_options,quiz_answer)
                    VALUES(?,?,?,0,?,'own','active',0,?,?,?,?,?,?)""",
                    (title,description,category,points,now(),task_type,external_url,question,options,answer)) 
        quiz_bank = [
          ("Que tipo de oportunidade procuras neste momento?","Emprego ou estágio|Aprender uma competência|Pequenos trabalhos|Conhecer campanhas","","personal"),
          ("Que área gostarias de desenvolver?","Tecnologia|Comunicação|Negócios|Design e criatividade","","personal"),
          ("Qual é a maior dificuldade para encontrares oportunidades?","Falta de informação|Falta de experiência|Falta de contactos|Falta de tempo","","personal"),
          ("Como preferes aprender algo novo?","Vídeos curtos|Quizzes interactivos|Guias passo a passo|Praticar directamente","","personal"),
          ("Que melhoria ajudaria mais na plataforma?","Pesquisa e filtros|Mais quizzes|Explicações em vídeo|Melhor experiência no telemóvel","","personal"),
          ("Qual é a melhor forma de proteger a tua conta?","Usar palavra-passe forte e única|Partilhar a palavra-passe|Usar a mesma palavra-passe em todo lado","Usar palavra-passe forte e única","choice"),
          ("Recebeste um link inesperado. O que deves fazer?","Verificar a origem antes de abrir|Enviar os teus dados|Partilhar imediatamente","Verificar a origem antes de abrir","choice"),
          ("Que informação nunca deves partilhar publicamente?","Palavra-passe e códigos de acesso|Uma sugestão de melhoria|A tua opinião sobre o site","Palavra-passe e códigos de acesso","choice"),
          ("O que deve acontecer quando um anúncio é patrocinado?","Ser identificado como publicidade|Parecer uma opinião espontânea|Esconder o patrocinador","Ser identificado como publicidade","choice"),
          ("Quando deves concluir uma tarefa?","Depois de cumprir as instruções|Antes de começar|Sem a abrir","Depois de cumprir as instruções","choice"),
          ("Que formato de tarefa preferes?","Quiz|Vídeo curto com perguntas|Teste de utilização|Partilha voluntária","","personal"),
          ("O que te faria voltar à plataforma?","Novas actividades úteis|Mais explicações|Uma navegação simples|Campanhas interessantes","","personal"),
          ("Quanto tempo preferes dedicar a uma actividade?","1 a 2 minutos|5 minutos|10 minutos|15 minutos","","personal"),
          ("Em que dispositivo usas mais a internet?","Telemóvel|Computador|Tablet|Depende do dia","","personal"),
          ("Que apoio seria mais útil para ti?","Aprender a criar CV|Aprender competências digitais|Encontrar oportunidades|Divulgar um pequeno negócio","","personal")
        ]
        durations = [1,2,5,10,15]
        for task in con.execute("SELECT id,task_type,category FROM tasks WHERE status='active' AND task_type IN ('quiz','video')").fetchall():
            if con.execute("SELECT COUNT(*) FROM quiz_questions WHERE task_id=?",(task["id"],)).fetchone()[0] == 0:
                selected = quiz_bank[5:10] + quiz_bank[:5] if "segurança" in (task["category"] or "").lower() else quiz_bank[:10]
                for idx,(question,options,correct,kind) in enumerate(selected,1):
                    con.execute("INSERT INTO quiz_questions(task_id,question,options,correct_answer,question_kind,sort_order) VALUES(?,?,?,?,?,?)",(task["id"],question,options,correct,kind,idx))
                con.execute("UPDATE tasks SET quiz_duration=? WHERE id=?",(durations[(task["id"]-1)%5],task["id"]))


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
        return con.execute("SELECT id,name,email,role,phone,account_type FROM users WHERE id=?", (uid,)).fetchone()

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
        account_type=request.form.get("account_type","participant")
        if account_type not in ("participant","advertiser","influencer"): account_type="participant"
        if len(name)<2 or "@" not in email or len(password)<8:
            flash("Preenche os dados corretamente. A palavra-passe deve ter pelo menos 8 caracteres.", "danger")
        else:
            try:
                with db() as con:
                    admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
                    assigned_role = "admin" if admin_email and email == admin_email else "user"
                    cur=con.execute("INSERT INTO users(name,email,password_hash,role,phone,account_type,created_at) VALUES(?,?,?,?,?,?,?)",
                                    (name,email,generate_password_hash(password),assigned_role,phone,account_type,now()))
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
            WHERE t.status='active' ORDER BY t.id ASC""",(user["id"],)).fetchall()
        balance=con.execute("SELECT COALESCE(SUM(amount),0) AS total FROM wallet WHERE user_id=?",(user["id"],)).fetchone()["total"]
        points=con.execute("SELECT COALESCE(SUM(points),0) FROM points_wallet WHERE user_id=?",(user["id"],)).fetchone()[0]
        metcash=con.execute("SELECT COALESCE(SUM(amount),0) FROM metcash_wallet WHERE user_id=?",(user["id"],)).fetchone()[0]
        history=con.execute("SELECT * FROM wallet WHERE user_id=? ORDER BY id DESC LIMIT 8",(user["id"],)).fetchall()
        withdrawals=con.execute("SELECT * FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 5",(user["id"],)).fetchall()
    return render_template("dashboard.html",tasks=tasks,balance=balance,points=points,metcash=metcash,history=history,withdrawals=withdrawals)

@app.route("/quiz/<int:task_id>", methods=["GET"])
@login_required
def quiz_page(task_id):
    uid=get_user()["id"]
    with db() as con:
        task=con.execute("SELECT * FROM tasks WHERE id=? AND status='active' AND task_type IN ('quiz','video')",(task_id,)).fetchone()
        if not task: abort(404)
        done=con.execute("SELECT id FROM submissions WHERE task_id=? AND user_id=?",(task_id,uid)).fetchone()
        if done:
            flash("Já participaste neste quiz. Obrigado!", "success")
            return redirect(url_for("dashboard"))
        questions=con.execute("SELECT * FROM quiz_questions WHERE task_id=? ORDER BY sort_order,id",(task_id,)).fetchall()
    if not questions: abort(404)
    session["quiz_started_"+str(task_id)]=int(datetime.utcnow().timestamp())
    return render_template("quiz.html",task=task,questions=questions)

@app.post("/quiz/<int:task_id>/concluir")
@login_required
def finish_quiz(task_id):
    uid=get_user()["id"]
    started=session.get("quiz_started_"+str(task_id))
    with db() as con:
        task=con.execute("SELECT * FROM tasks WHERE id=? AND status='active' AND task_type IN ('quiz','video')",(task_id,)).fetchone()
        if not task: abort(404)
        if not started:
            flash("Abre o quiz pelo botão Participar para começar.", "warning")
            return redirect(url_for("dashboard"))
        elapsed=max(0,int(datetime.utcnow().timestamp())-int(started))
        if elapsed > int(task["quiz_duration"])*60+120:
            flash("O tempo deste quiz terminou. Volta às actividades para tentar outro.", "warning")
            return redirect(url_for("dashboard"))
        questions=con.execute("SELECT * FROM quiz_questions WHERE task_id=? ORDER BY sort_order,id",(task_id,)).fetchall()
        answers={}
        score=0
        for q in questions:
            value=request.form.get("q_"+str(q["id"]),"").strip()
            if not value:
                flash("Responde a todas as perguntas antes de concluir.", "warning")
                return redirect(url_for("quiz_page",task_id=task_id))
            answers[str(q["id"])]=value
            if q["question_kind"]=="choice" and q["correct_answer"] and value==q["correct_answer"]:
                score+=1
        proof=json.dumps({"answers":answers,"score":score,"total":len(questions),"duration_seconds":elapsed},ensure_ascii=False)
        try:
            con.execute("INSERT INTO submissions(task_id,user_id,proof,created_at) VALUES(?,?,?,?)",(task_id,uid,proof,now()))
            flash("Quiz concluído! As respostas foram registadas para análise.", "success")
        except sqlite3.IntegrityError:
            flash("Já participaste neste quiz.", "warning")
    session.pop("quiz_started_"+str(task_id),None)
    return redirect(url_for("dashboard"))

@app.post("/partilhar/<int:task_id>/<platform>")
@login_required
def start_share_task(task_id, platform):
    destinations = {
        "whatsapp": "https://wa.me/?text=Ol%C3%A1%21%20Quero%20partilhar%20contigo%20a%20Oportunidade360%2C%20uma%20plataforma%20de%20actividades%20e%20oportunidades.%20Conhece%20aqui%3A%20https%3A%2F%2Foportunidade360.onrender.com",
        "facebook": "https://www.facebook.com/sharer/sharer.php?u=https%3A%2F%2Foportunidade360.onrender.com",
        "instagram": "https://www.instagram.com/"
    }
    if platform not in destinations:
        abort(404)
    uid = get_user()["id"]
    with db() as con:
        task = con.execute("SELECT id FROM tasks WHERE id=? AND status='active' AND task_type='share'", (task_id,)).fetchone()
        if not task:
            abort(404)
        existing = con.execute("SELECT id FROM submissions WHERE task_id=? AND user_id=?", (task_id, uid)).fetchone()
        if not existing:
            con.execute(
                "INSERT INTO submissions(task_id,user_id,proof,created_at,status) VALUES(?,?,?,?, 'pending')",
                (task_id, uid, "Partilha iniciada em " + platform + " — aguarda verificação", now())
            )
            flash("Partilha iniciada. A tarefa está agora Em análise e será verificada pela equipa.", "success")
        else:
            flash("Esta tarefa já está Em análise ou já foi analisada.", "info")
    return redirect(destinations[platform])


@app.post("/tarefa/<int:task_id>/enviar")
@login_required
def submit_task(task_id):
    answer=request.form.get("answer","").strip()
    confirmed=request.form.get("confirmed","")
    feedback=request.form.get("feedback","").strip()
    with db() as con:
        task=con.execute("SELECT * FROM tasks WHERE id=? AND status='active'",(task_id,)).fetchone()
        if not task:
            flash("Esta tarefa já não está disponível.", "warning")
        elif task["task_type"] in ("quiz","video") and (not answer or answer != task["quiz_answer"]):
            flash("Resposta incorreta. Revê o conteúdo e tenta novamente.", "warning")
        elif task["task_type"] == "share" and confirmed != "yes":
            flash("Confirma que fizeste a partilha de forma voluntária e sem spam.", "warning")
        elif task["task_type"] == "test" and feedback not in ("Funcionou bem","Funcionou parcialmente","Não funcionou"):
            flash("Escolhe como foi o teste.", "warning")
        else:
            proof = answer if task["task_type"] in ("quiz","video") else (feedback if task["task_type"]=="test" else "Partilha confirmada pelo utilizador")
            try:
                con.execute("INSERT INTO submissions(task_id,user_id,proof,created_at) VALUES(?,?,?,?)",
                            (task_id,get_user()["id"],proof,now()))
                flash("Atividade enviada para análise. Os pontos só serão atribuídos após validação.", "success")
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

@app.route("/carteira")
@login_required
def wallet_page():
    uid=get_user()["id"]
    with db() as con:
        points=con.execute("SELECT COALESCE(SUM(points),0) FROM points_wallet WHERE user_id=?",(uid,)).fetchone()[0]
        metcash=con.execute("SELECT COALESCE(SUM(amount),0) FROM metcash_wallet WHERE user_id=?",(uid,)).fetchone()[0]
        metcash_movements=con.execute("SELECT * FROM metcash_wallet WHERE user_id=? ORDER BY id DESC LIMIT 30",(uid,)).fetchall()
        movements=con.execute("SELECT * FROM points_wallet WHERE user_id=? ORDER BY id DESC LIMIT 30",(uid,)).fetchall()
        requests=con.execute("SELECT * FROM point_redemptions WHERE user_id=? ORDER BY id DESC LIMIT 20",(uid,)).fetchall()
    return render_template("wallet.html",points=points,metcash=metcash,metcash_movements=metcash_movements,movements=movements,requests=requests)

@app.post("/carteira/levantamento")
@login_required
def point_redemption():
    try: points=int(request.form.get("points","0"))
    except ValueError: points=0
    uid=get_user()["id"]
    with db() as con:
        balance=con.execute("SELECT COALESCE(SUM(points),0) FROM points_wallet WHERE user_id=?",(uid,)).fetchone()[0]
        pending=con.execute("SELECT COALESCE(SUM(points),0) FROM point_redemptions WHERE user_id=? AND status='pending'",(uid,)).fetchone()[0]
        if points<100 or points>balance-pending:
            flash("O pedido deve ter pelo menos 100 pontos e não pode ultrapassar o saldo disponível.","warning")
        else:
            con.execute("INSERT INTO point_redemptions(user_id,points,created_at) VALUES(?,?,?)",(uid,points,now()))
            flash("Pedido registado para análise. Pontos não são dinheiro e não têm conversão garantida; qualquer recompensa depende de campanha financiada e das regras confirmadas pela equipa.","success")
    return redirect(url_for("wallet_page"))

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
          "withdrawals":con.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0],
          "point_requests":con.execute("SELECT COUNT(*) FROM point_redemptions WHERE status='pending'").fetchone()[0]
        }
        submissions=con.execute("""SELECT s.*,u.name,u.email,t.title,t.reward,t.budget_available
            FROM submissions s JOIN users u ON u.id=s.user_id JOIN tasks t ON t.id=s.task_id
            ORDER BY s.id DESC LIMIT 30""").fetchall()
        campaigns=con.execute("SELECT * FROM campaign_requests ORDER BY id DESC LIMIT 20").fetchall()
        withdrawals=con.execute("SELECT w.*,u.name,u.email FROM withdrawals w JOIN users u ON u.id=w.user_id ORDER BY w.id DESC LIMIT 20").fetchall()
        point_requests=con.execute("SELECT r.*,u.name,u.email FROM point_redemptions r JOIN users u ON u.id=r.user_id ORDER BY r.id DESC LIMIT 30").fetchall()
        tasks=con.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()
        partners=con.execute("SELECT * FROM partners ORDER BY id DESC").fetchall()
    return render_template("admin.html",counts=counts,submissions=submissions,campaigns=campaigns,withdrawals=withdrawals,point_requests=point_requests,tasks=tasks,partners=partners)

@app.post("/admin/tarefa/criar")
@login_required
@admin_required
def create_task():
    title=request.form.get("title","").strip(); desc=request.form.get("description","").strip()
    category=request.form.get("category","Microtarefas").strip()
    source=request.form.get("source","own")
    task_type=request.form.get("task_type","test")
    external_url=request.form.get("external_url","").strip()
    quiz_question=request.form.get("quiz_question","").strip()
    quiz_options=request.form.get("quiz_options","").strip()
    quiz_answer=request.form.get("quiz_answer","").strip()
    if task_type not in ("quiz","video","share","test"): task_type="test"
    try: points_reward=max(0,int(request.form.get("points_reward","0") or 0))
    except ValueError: points_reward=0
    try: reward=max(0,float(request.form.get("reward","0") or 0))
    except ValueError: reward=0
    try: budget=max(0,float(request.form.get("budget","0") or 0))
    except ValueError: budget=0
    if not title or not desc:
        flash("Título e descrição são obrigatórios.", "danger")
    else:
        with db() as con:
            con.execute("""INSERT INTO tasks(title,description,category,reward,points_reward,source,status,budget_available,created_at,task_type,external_url,quiz_question,quiz_options,quiz_answer)
                VALUES(?,?,?,?,?,?, 'active',?,?,?,?,?,?,?)""",
                (title,desc,category,reward,points_reward,source,budget,now(),task_type,external_url,quiz_question,quiz_options,quiz_answer))
        flash("Tarefa criada.", "success")
    return redirect(url_for("admin"))

@app.post("/admin/submissao/<int:sid>/<action>")
@login_required
@admin_required
def review_submission(sid,action):
    if action not in ("approve","reject"): abort(404)
    with db() as con:
        sub=con.execute("""SELECT s.*,t.reward,t.points_reward,t.budget_available,t.title FROM submissions s
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
                points=int(sub["points_reward"] or 0)
                if points>0:
                    con.execute("INSERT INTO points_wallet(user_id,points,description,created_at) VALUES(?,?,?,?)",
                                (sub["user_id"],points,"Tarefa aprovada: "+sub["title"],now()))
                    con.execute("UPDATE submissions SET points_awarded=? WHERE id=?",(points,sid))
                flash("Submissão aprovada. Os pontos foram adicionados à carteira.", "success")
        else:
            con.execute("UPDATE submissions SET status='rejected',reviewed_at=? WHERE id=?",(now(),sid))
            flash("Submissão rejeitada.", "success")
    return redirect(url_for("admin"))

@app.post("/admin/pontos/<int:rid>/<action>")
@login_required
@admin_required
def review_point_request(rid,action):
    if action not in ("reviewed","reject"): abort(404)
    with db() as con:
        item=con.execute("SELECT * FROM point_redemptions WHERE id=?",(rid,)).fetchone()
        if not item or item["status"]!="pending":
            flash("Pedido não encontrado ou já analisado.","warning")
        else:
            con.execute("UPDATE point_redemptions SET status=? WHERE id=?",("reviewed" if action=="reviewed" else "rejected",rid))
            flash("Pedido analisado. Isto não confirma qualquer transferência de dinheiro.","success")
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
