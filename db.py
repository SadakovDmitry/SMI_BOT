# db.py
import aiosqlite
from config import DB_PATH

# Инициализация (создание) таблиц базы данных, если их нет
async def create_tables():
    '''Инициализация таблиц базы данных'''
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        # Таблица пользователей с полями display_name, tariff и флагом is_active
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE,
            username TEXT,
            display_name TEXT,
            email TEXT,
            role TEXT,
            tariff TEXT,
            is_active INTEGER DEFAULT 0
        );
        """)
        # Остальные таблицы
        await db.execute("""
        CREATE TABLE IF NOT EXISTS specializations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_specializations (
            user_id INTEGER,
            spec_id INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(spec_id) REFERENCES specializations(id),
            PRIMARY KEY (user_id, spec_id)
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            journalist_id INTEGER,
            spec_id INTEGER,
            title TEXT,
            deadline TEXT,
            format TEXT,
            content TEXT,
            status TEXT,
            chosen_speaker_id INTEGER,
            FOREIGN KEY(journalist_id) REFERENCES users(id),
            FOREIGN KEY(spec_id) REFERENCES specializations(id),
            FOREIGN KEY(chosen_speaker_id) REFERENCES users(id)
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS request_invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER,
            speaker_id INTEGER,
            status TEXT,
            answer_text TEXT,
            answer_accepted INTEGER,
            revision_requested INTEGER,
            FOREIGN KEY(request_id) REFERENCES requests(id),
            FOREIGN KEY(speaker_id) REFERENCES users(id)
        );
        """)
        await db.commit()

async def add_pending_user(tg_id: int, username: str, display_name: str, email: str, role: str, tariff: str):
    """Добавляем пользователя как неактивного (ожидает одобрения)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO users
              (tg_id, username, display_name, email, role, tariff, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        """, (tg_id, username, display_name, email, role, tariff))
        await db.commit()

async def approve_user(user_id: int):
    """Подтверждаем пользователя по internal ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_active = 1 WHERE id = ?;", (user_id,))
        await db.commit()

async def activate_user(tg_id: int):
    """Подтверждаем пользователя по tg_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_active = 1 WHERE tg_id = ?;", (tg_id,))
        await db.commit()

async def reject_user(user_id: int):
    """Удаляем или помечаем отклонённого. Здесь — удаляем."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE id = ?;", (user_id,))
        await db.commit()

async def update_user_tariff(tg_id: int, tariff: str):
    """Обновляем выбранный тариф для пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET tariff = ? WHERE tg_id = ?;", (tariff, tg_id))
        await db.commit()

# Добавление или обновление пользователя
async def add_user(tg_id: int,
                   username: str,
                   display_name: str,
                   email: str,
                   role: str,
                   tariff: str = None,
                   is_active: int = 0):
    """Добавляет или обновляет пользователя сразу со всеми полями."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO users
                (tg_id, username, display_name, email, role, tariff, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (tg_id, username, display_name, email, role, tariff, is_active)
        )
        await db.commit()

# Получение пользователя по Telegram ID
async def get_user_by_tg_id(tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT id, tg_id, username, display_name, email, role, tariff, is_active
              FROM users
             WHERE tg_id = ?;
            """,
            (tg_id,)
        )
        user = await cursor.fetchone()
        await cursor.close()
        return user  # кортеж из 8 элементов

# Получение пользователя по внутреннему ID — аналогично
async def get_user_by_id(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT id, tg_id, username, display_name, email, role, tariff, is_active
              FROM users
             WHERE id = ?;
            """,
            (user_id,)
        )
        user = await cursor.fetchone()
        await cursor.close()
        return user  # кортеж из 8 элементов

# Получить все специализации (для списка в регистрационном хендлере)
async def list_specializations():
    """
    Возвращает список всех специализаций из таблицы specializations.
    Каждый элемент — кортеж (id, name).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id, name FROM specializations;")
        specs = await cursor.fetchall()
        await cursor.close()
        return specs

# Добавление новой специализации (если такой еще нет)
async def add_specialization(name: str):
    '''Add a new specialization'''
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO specializations (name) VALUES (?);", (name,))
        await db.commit()

# Получение специализации по названию
async def get_specialization_by_name(name: str):
    '''Get specialization record by name'''
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id, name FROM specializations WHERE name = ?;", (name,))
        spec = await cursor.fetchone()
        await cursor.close()
        return spec

# Получение специализации по ID
async def get_specialization_by_id(spec_id: int):
    '''Get specialization by ID'''
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id, name FROM specializations WHERE id = ?;", (spec_id,))
        spec = await cursor.fetchone()
        await cursor.close()
        return spec

# Привязка специализации к спикеру (добавление записи в user_specializations)
async def assign_specialization_to_user(user_id: int, spec_id: int):
    '''Associate a specialization with a speaker'''
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO user_specializations (user_id, spec_id) VALUES (?, ?);",
            (user_id, spec_id)
        )
        await db.commit()

# Получение всех спикеров, обладающих данной специализацией
async def get_speakers_by_specialization(spec_id: int):
    '''Get all speakers (users) who have a given specialization'''
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT u.id, u.tg_id, u.username, u.email FROM user_specializations us "
            "JOIN users u ON us.user_id = u.id "
            "WHERE us.spec_id = ? AND u.role = 'speaker';",
            (spec_id,)
        )
        speakers = await cursor.fetchall()
        await cursor.close()
        return speakers

# Получение всех спикеров, без специализации
async def get_speakers_without_specialization():
    """
    Return all speakers who have no entry in user_specializations.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT u.id, u.tg_id, u.username, u.email
              FROM users u
             WHERE u.role = 'speaker'
               AND u.id NOT IN (SELECT user_id FROM user_specializations)
            """
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return rows

# Создание нового запроса от журналиста и рассылка приглашений спикерам
async def create_request(journalist_id: int, spec_id: int, title: str, deadline: str, fmt: str, content: str, speaker_ids: list):
    '''Create a new press request and invite selected speakers'''
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        # Вставка новой записи запроса
        cursor = await db.execute(
            "INSERT INTO requests (journalist_id, spec_id, title, deadline, format, content, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'open');",
            (journalist_id, spec_id, title, deadline, fmt, content)
        )
        request_id = cursor.lastrowid
        # Вставка записей приглашений для каждого выбранного спикера
        for sid in speaker_ids:
            await db.execute(
                "INSERT INTO request_invites (request_id, speaker_id, status, answer_accepted, revision_requested) "
                "VALUES (?, ?, 'pending', 0, 0);",
                (request_id, sid)
            )
        await db.commit()
        return request_id

# Получение информации о запросе по его ID
async def get_request_by_id(request_id: int):
    '''Get a request by its ID'''
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM requests WHERE id = ?;", (request_id,))
        req = await cursor.fetchone()
        await cursor.close()
        return req

async def get_request_title(request_id: int) -> str:
    """
    Возвращает название (title) запроса по его ID.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT title FROM requests WHERE id = ?;",
            (request_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()
    return row[0] if row else ""

# Получение конкретного приглашения спикера (по запросу и спикеру)
async def get_invite(request_id: int, speaker_id: int):
    '''Get a specific invite entry'''
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT * FROM request_invites WHERE request_id = ? AND speaker_id = ?;",
            (request_id, speaker_id)
        )
        invite = await cursor.fetchone()
        await cursor.close()
        return invite

# Обновление статуса приглашения спикера
async def update_invite_status(request_id: int, speaker_id: int, status: str):
    '''Update the invite status for a given speaker and request'''
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE request_invites SET status = ? WHERE request_id = ? AND speaker_id = ?;",
            (status, request_id, speaker_id)
        )
        await db.commit()

# Пометить запрос как находящийся в работе (есть принявший спикер)
async def mark_request_in_progress(request_id: int):
    '''Mark a request as in progress after at least one speaker accepted'''
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE requests SET status = 'in_progress' WHERE id = ?;",
            (request_id,)
        )
        await db.commit()

async def set_chosen_speaker(request_id: int, speaker_id: int):
    """
    Пометить, что по данному запросу journalist уже выбрал этого спикера.
    Обновляет поле chosen_speaker_id в таблице requests.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE requests SET chosen_speaker_id = ? WHERE id = ?;",
            (speaker_id, request_id)
        )
        await db.commit()

# Сохранение текста ответа спикера по запросу
async def record_answer(request_id: int, speaker_id: int, answer_text: str):
    '''Store the speaker's answer for a request'''
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE request_invites SET answer_text = ?, status = 'answered', answer_accepted = 0, revision_requested = 0 "
            "WHERE request_id = ? AND speaker_id = ?;",
            (answer_text, request_id, speaker_id)
        )
        await db.commit()

# Пометить, что по ответу спикера запрошены правки
async def mark_revision_requested(request_id: int, speaker_id: int):
    '''Mark that a revision was requested for the speaker's answer'''
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE request_invites SET revision_requested = 1 WHERE request_id = ? AND speaker_id = ?;",
            (request_id, speaker_id)
        )
        await db.commit()

# Принятие ответа спикера журналистом (закрытие запроса)
async def accept_answer(request_id: int, speaker_id: int):
    '''Mark an answer as accepted and close the request'''
    async with aiosqlite.connect(DB_PATH) as db:
        # Отметить ответ как принятый
        await db.execute(
            "UPDATE request_invites SET answer_accepted = 1 WHERE request_id = ? AND speaker_id = ?;",
            (request_id, speaker_id)
        )
        # Обновить статус запроса на завершён и зафиксировать выбранного спикера
        await db.execute(
            "UPDATE requests SET status = 'completed', chosen_speaker_id = ? WHERE id = ?;",
            (speaker_id, request_id)
        )
        await db.commit()

# Получение всех запросов, созданных конкретным журналистом
async def get_requests_by_journalist(journalist_id: int):
    '''Get all requests created by a journalist'''
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, spec_id, title, deadline, format, content, status, chosen_speaker_id "
            "FROM requests WHERE journalist_id = ?;",
            (journalist_id,)
        )
        requests = await cursor.fetchall()
        await cursor.close()
        return requests

# Получение всех приглашений (списка спикеров) по запросу
async def get_invites_for_request(request_id: int):
    '''Get all invites for a given request'''
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT speaker_id, status, answer_text, answer_accepted, revision_requested "
            "FROM request_invites WHERE request_id = ?;",
            (request_id,)
        )
        invites = await cursor.fetchall()
        await cursor.close()
        return invites

# Получение всех запросов (приглашений) с участием данного спикера
async def get_requests_for_speaker(speaker_id: int):
    """
    Get all requests (invites) involving a particular speaker,
    но только с теми статусами приглашения, где он действительно участвует.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT
                r.id,
                r.title,
                r.deadline,
                r.status       AS request_status,
                i.status       AS invite_status,
                i.answer_text,
                i.answer_accepted,
                i.revision_requested
            FROM request_invites AS i
            JOIN requests AS r ON i.request_id = r.id
            WHERE i.speaker_id = ?
              AND i.status NOT IN ('declined', 'cancelled')
              AND r.status NOT IN ('open')
            """,
            (speaker_id,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return rows

# Получение Telegram ID всех пользователей определённой роли (для рассылки)
async def get_all_user_ids_by_role(role: str):
    '''Get Telegram IDs of all users with a given role'''
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT tg_id FROM users WHERE role = ?;", (role,))
        rows = await cursor.fetchall()
        await cursor.close()
        return [row[0] for row in rows]

# Получение всех пользователей (для экспорта)
async def get_all_users():
    """
    Возвращает все записи из users со всеми полями.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT
                id,
                tg_id,
                username,
                display_name,
                email,
                role,
                tariff,
                is_active
            FROM users;
            """
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return rows

# Получение всех запросов (для экспорта)
async def get_all_requests():
    '''Get all request records with additional info for export'''
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT r.id, j.username, s.name, r.title, r.deadline, r.format, r.content, r.status, sp.username "
            "FROM requests r "
            "LEFT JOIN users j ON r.journalist_id = j.id "
            "LEFT JOIN specializations s ON r.spec_id = s.id "
            "LEFT JOIN users sp ON r.chosen_speaker_id = sp.id;"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return rows

# Функции db.py
