"""МОД-ХОСТИНГ: сайт в стиле Nexus Mods (Flask + Access)."""
import os
import secrets
from datetime import datetime
from pathlib import Path
from functools import wraps
from werkzeug.utils import secure_filename

from dotenv import load_dotenv
from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)

from db import Db

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)
_db_path = BASE_DIR / "dt.accdb"
app.config.update(
    DB_PATH=str(_db_path),
    SECRET_KEY=os.getenv("SECRET_KEY", secrets.token_hex(32)),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=50 * 1024 * 1024, # Максимум 50 МБ на файл
)

def get_val(row, key_name):
    if not row: return None
    for k, v in row.items():
        if k.strip().lower() == key_name.strip().lower():
            return v
    return None

def get_title(row):
    if not row: return None
    val = get_val(row, 'Название')
    if val: return val
    for k, v in row.items():
        if 'азван' in k.lower() or 'name' in k.lower():
            return v
    vals = list(row.values())
    if len(vals) > 2 and isinstance(vals[2], str):
        return vals[2]
    return None

# ---------------------------------------------------------------- база данных
def get_db():
    if "db" not in g:
        g.db = Db(app.config["DB_PATH"])
    return g.db

@app.after_request
def commit_on_success(response):
    db = g.get("db")
    if db is not None and response.status_code < 400:
        db.commit()
    return response

@app.teardown_request
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        if exc is not None:
            db.rollback()
        db.close()

# ------------------------------------------------------------- пользователь
@app.before_request
def load_user_and_check_csrf():
    if request.endpoint == "static":
        return
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        if not sent or not secrets.compare_digest(sent, session.get("csrf_token", "")):
            abort(400)
    g.user = None
    user_id = session.get("uid")
    if user_id:
        row = get_db().one("SELECT * FROM Пользователь WHERE id_user = ?", (user_id,))
        if row:
            row['login'] = get_val(row, 'Никнейм')
            row['role_name'] = get_val(row, 'Роль')
            # Читаем премиум статус (-1 в Access это True)
            row['is_premium'] = get_val(row, 'Премиум_статус') == -1 or get_val(row, 'Премиум_статус') is True
            g.user = row

@app.context_processor
def inject_globals():
    return {"csrf_token": csrf_token, "user": g.get("user"), "ROLE_ADMIN": "Администратор"}

def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]

def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not g.user:
            flash("Войдите в аккаунт.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapper

def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if g.user["role_name"] != "Администратор":
            abort(403)
        return view(*args, **kwargs)
    return wrapper

@app.template_filter("dt")
def dt_filter(value):
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y")
    return value or ""

# ------------------------------------------------------------------ каталог
@app.get("/")
def catalog():
    db = get_db()
    game_id = request.args.get("game", type=int)
    cat_id = request.args.get("category", type=int)
    q = request.args.get("q", "").strip()[:60]

    games = db.query("SELECT * FROM Игра")
    categories = db.query("SELECT * FROM Категория")
    authors = db.query("SELECT * FROM Разработчик")

    for g in games:
        g['id_game'] = get_val(g, 'id_game')
        g['game_name'] = get_title(g)
    for c in categories:
        c['id_cat'] = get_val(c, 'id_cat')
        c['category_name'] = get_title(c)

    games_dict = {g['id_game']: g['game_name'] for g in games}
    cats_dict = {c['id_cat']: c['category_name'] for c in categories}
    authors_dict = {get_val(a, 'id_author'): get_val(a, 'Никнейм') for a in authors}

    sql = "SELECT * FROM Модификация WHERE Активен = -1"
    params = []
    if game_id:
        sql += " AND id_game = ?"
        params.append(game_id)
    if cat_id:
        sql += " AND id_cat = ?"
        params.append(cat_id)

    mods = db.query(sql, params)

    for m in mods:
        m['mod_id'] = get_val(m, 'id_mod')
        m['mod_name'] = str(get_title(m) or 'Без названия').strip()
        m['version'] = get_val(m, 'Версия') or '1.0'
        m['downloads'] = get_val(m, 'Кол_во_Скачиваний') or 0
        m['image_url'] = get_val(m, 'Картинка')
        m['game_name'] = games_dict.get(get_val(m, 'id_game'), 'Игра не указана')
        m['category_name'] = cats_dict.get(get_val(m, 'id_cat'), 'Категория не указана')
        m['author'] = authors_dict.get(get_val(m, 'id_autor'), 'Неизвестный автор')

    if q:
        needle = q.casefold()
        mods = [m for m in mods if needle in m['mod_name'].casefold() or needle in str(m['game_name']).casefold()]

    return render_template("catalog.html", mods=mods, games=games, categories=categories,
                           f_game=game_id, f_category=cat_id, q=q)

# ------------------------------------------------------------ страница мода
@app.get("/mod/<int:mod_id>")
def mod_page(mod_id):
    db = get_db()
    mod = db.one("SELECT * FROM Модификация WHERE id_mod = ?", (mod_id,))
    if not mod: abort(404)

    mod['mod_id'] = get_val(mod, 'id_mod')
    mod['mod_name'] = str(get_title(mod) or 'Без названия').strip()
    mod['version'] = get_val(mod, 'Версия') or '1.0'
    mod['size'] = get_val(mod, 'Размер_файла') or 0
    mod['downloads'] = get_val(mod, 'Кол_во_Скачиваний') or 0
    mod['image_url'] = get_val(mod, 'Картинка')

    game = db.one("SELECT * FROM Игра WHERE id_game = ?", (get_val(mod, 'id_game'),))
    mod['game_name'] = get_title(game) if game else 'Неизвестно'
    cat = db.one("SELECT * FROM Категория WHERE id_cat = ?", (get_val(mod, 'id_cat'),))
    mod['category_name'] = get_title(cat) if cat else 'Неизвестно'
    author = db.one("SELECT * FROM Разработчик WHERE id_author = ?", (get_val(mod, 'id_autor'),))
    mod['author_name'] = get_val(author, 'Никнейм') if author else 'Неизвестно'

    files = db.query("SELECT * FROM ФайлМода WHERE id_mod = ?", (mod_id,))
    for f in files:
        f['file_id'] = get_val(f, 'id_file')
        f['url'] = get_val(f, 'Ссылка_на_скачивание') or ''

    reviews_raw = db.query("SELECT * FROM Отзыв WHERE id_mod = ?", (mod_id,))
    users = {get_val(u, 'id_user'): get_val(u, 'Никнейм') for u in db.query("SELECT * FROM Пользователь")}

    reviews = []
    for r in reviews_raw:
        reviews.append({
            'rating': get_val(r, 'Оценка') or 0,
            'created_at': get_val(r, 'Дата_отправки'),
            'user_name': users.get(get_val(r, 'id_user'), 'Пользователь')
        })
    rating = round(sum(r["rating"] for r in reviews) / len(reviews), 1) if reviews else 0
    return render_template("mod.html", mod=mod, files=files, reviews=reviews, rating=rating)

# --------------------------------------------------------------- скачивание
@app.get("/mod/<int:mod_id>/download/<int:file_id>")
def download(mod_id, file_id):
    db = get_db()
    file = db.one("SELECT * FROM ФайлМода WHERE id_file = ? AND id_mod = ?", (file_id, mod_id))
    if not file or not get_val(file, 'Ссылка_на_скачивание'): abort(404)

    db.execute("UPDATE Модификация SET Кол_во_Скачиваний = Кол_во_Скачиваний + 1 WHERE id_mod = ?", (mod_id,))
    db.commit()

    url = get_val(file, 'Ссылка_на_скачивание')
    if url.startswith("http"):
        return redirect(url)
    return redirect(url_for("static", filename=url))

# -------------------------------------------------------- ЛИЧНЫЙ КАБИНЕТ
@app.get("/profile")
@login_required
def profile():
    db = get_db()
    author = db.one("SELECT * FROM Разработчик WHERE Никнейм = ?", (g.user['login'],))
    my_mods = []
    if author:
        author_id = get_val(author, 'id_author')
        mods_raw = db.query("SELECT * FROM Модификация WHERE id_autor = ?", (author_id,))

        games = {get_val(g, 'id_game'): get_title(g) for g in db.query("SELECT * FROM Игра")}
        cats = {get_val(c, 'id_cat'): get_title(c) for c in db.query("SELECT * FROM Категория")}

        for m in mods_raw:
            m['mod_id'] = get_val(m, 'id_mod')
            m['mod_name'] = get_title(m)
            m['image_url'] = get_val(m, 'Картинка')
            m['version'] = get_val(m, 'Версия') or '1.0'
            m['downloads'] = get_val(m, 'Кол_во_Скачиваний') or 0
            m['game_name'] = games.get(get_val(m, 'id_game'), '—')
            m['category_name'] = cats.get(get_val(m, 'id_cat'), '—')
            my_mods.append(m)

    return render_template("profile.html", my_mods=my_mods)

@app.route("/profile/upload", methods=["GET", "POST"])
@login_required
def upload_mod():
    db = get_db()
    games = db.query("SELECT * FROM Игра")
    categories = db.query("SELECT * FROM Категория")

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        version = request.form.get("version", "1.0").strip()
        size = request.form.get("size", "0").strip()
        game_id = request.form.get("game_id", type=int)
        cat_id = request.form.get("cat_id", type=int)
        link = request.form.get("link", "").strip()

        if not title or not game_id or not cat_id:
            flash("Заполните обязательные поля (Название, Игра, Категория).", "error")
            return redirect(url_for("upload_mod"))

        # Обработка картинки
        image_file = request.files.get("image")
        image_name = None
        if image_file and image_file.filename:
            filename = secure_filename(image_file.filename)
            image_name = f"{secrets.token_hex(4)}_{filename}"

            # Создаем папку static/images, если ее нет
            os.makedirs(os.path.join(app.root_path, "static", "images"), exist_ok=True)
            image_path = os.path.join(app.root_path, "static", "images", image_name)
            image_file.save(image_path)

        # Ищем или создаем автора
        author = db.one("SELECT * FROM Разработчик WHERE Никнейм = ?", (g.user['login'],))
        if author:
            author_id = get_val(author, 'id_author')
        else:
            author_id = db.insert("INSERT INTO Разработчик (Никнейм) VALUES (?)", (g.user['login'],))

        # Сохраняем мод
        mod_id = db.insert(
            "INSERT INTO Модификация (id_game, Название, Версия, Дата_Публикации, Кол_во_Скачиваний, Размер_файла, Активен, id_cat, id_autor, Картинка) "
            "VALUES (?, ?, ?, ?, 0, ?, -1, ?, ?, ?)",
            (game_id, title, version, datetime.now(), size, cat_id, author_id, image_name)
        )

        # Сохраняем файл
        if link:
            db.insert("INSERT INTO ФайлМода (id_mod, Ссылка_на_скачивание) VALUES (?, ?)", (mod_id, link))

        db.commit()
        flash("Мод успешно загружен!", "success")
        return redirect(url_for("profile"))

    return render_template("upload_mod.html", games=games, categories=categories)

# -------------------------------------------------------- Авторизация
@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user: return redirect(url_for("catalog"))
    if request.method == "POST":
        login_name = request.form.get("login", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.one("SELECT * FROM Пользователь WHERE Никнейм = ?", (login_name,))
        if not user or get_val(user, 'пароль') != password:
            flash("Неверный логин или пароль.", "error")
            return render_template("login.html", login=login_name), 400
        session.clear()
        session["uid"] = get_val(user, 'id_user')
        return redirect(url_for("catalog"))
    return render_template("login.html", login="")

@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user: return redirect(url_for("catalog"))
    if request.method == "POST":
        login_name = request.form.get("login", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        if db.one("SELECT * FROM Пользователь WHERE Никнейм = ?", (login_name,)):
            flash("Этот никнейм уже занят.", "error")
            return render_template("register.html", login=login_name, email=email), 400

        user_id = db.insert("INSERT INTO Пользователь (Никнейм, Email, Роль, пароль) VALUES (?, ?, ?, ?)",
            (login_name, email, "Пользователь", password))
        session.clear()
        session["uid"] = user_id
        flash("Регистрация успешна!", "success")
        return redirect(url_for("catalog"))
    return render_template("register.html", login="", email="")

@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("catalog"))

# ------------------------------------------------------------ Отзывы
@app.post("/mod/<int:mod_id>/review")
@login_required
def add_review(mod_id):
    rating = request.form.get("rating", type=int)
    if rating and 1 <= rating <= 5:
        get_db().execute("INSERT INTO Отзыв (id_user, id_mod, Оценка, Дата_отправки) VALUES (?, ?, ?, ?)",
            (g.user["id_user"], mod_id, rating, datetime.now()))
        flash("Спасибо за ваш отзыв!", "success")
    return redirect(url_for("mod_page", mod_id=mod_id))

# ------------------------------------------------------- Админка
@app.get("/admin")
@admin_required
def admin():
    db = get_db()
    mods = db.query("SELECT * FROM Модификация ORDER BY id_mod DESC")
    return render_template("admin.html", mods=mods)

# ------------------------------------------------------- ОШИБКИ И ЗАПУСК
ERRORS = {400: "Ошибка запроса.", 403: "Доступ запрещен.", 404: "Страница не найдена."}
for code, msg in ERRORS.items():
    app.register_error_handler(code, lambda e, c=code, m=msg: (render_template("error.html", code=c, message=m), c))

if __name__ == "__main__":
    port = 3000
    print(f"Запуск сервера на http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)