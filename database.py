
import sqlite3


# Подключаемся к базе данных
def connect_db():
    connection = sqlite3.connect("beauty_booking.db")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# Создаём таблицы
def init_db():
    connection = connect_db()
    cursor = connection.cursor()

    # Таблица свободных окошек мастеров
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS available_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_name TEXT NOT NULL,
            booking_date TEXT NOT NULL,
            booking_time TEXT NOT NULL,
            is_booked INTEGER DEFAULT 0,

            UNIQUE(master_name, booking_date, booking_time)
        )
    """)

    # Таблица записей клиентов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            username TEXT,
            service_name TEXT NOT NULL,
            master_name TEXT NOT NULL,
            slot_id INTEGER NOT NULL,
            status TEXT DEFAULT 'confirmed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (slot_id) REFERENCES available_slots(id)
        )
    """)

    connection.commit()
    connection.close()

    print("База данных успешно создана!")


# Добавляем свободное окошко
def add_available_slot(master_name: str, booking_date: str, booking_time: str):
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT OR IGNORE INTO available_slots
        (master_name, booking_date, booking_time)
        VALUES (?, ?, ?)
        """,
        (master_name, booking_date, booking_time)
    )

    added = cursor.rowcount == 1

    connection.commit()
    connection.close()

    return added

# Получаем расписание мастера
def get_available_slots(master_name: str):
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT id, booking_date, booking_time, is_booked
        FROM available_slots
        WHERE master_name = ?
        ORDER BY booking_date, booking_time
        """,
        (master_name,)
    )

    slots = cursor.fetchall()
    connection.close()

    return slots


# Удаляем свободное окошко
def delete_available_slot(slot_id: int, master_name: str):
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute(
        """
        DELETE FROM available_slots
        WHERE id = ?
        AND master_name = ?
        AND is_booked = 0
        """,
        (slot_id, master_name)
    )

    deleted = cursor.rowcount == 1

    connection.commit()
    connection.close()

    return deleted


# Запись клиента на свободное окошко
def book_available_slot(
    slot_id: int,
    telegram_id: int,
    username: str,
    service_name: str,
    master_name: str
):
    connection = connect_db()
    cursor = connection.cursor()

    try:
        # Проверяем, существует ли окошко и свободно ли оно
        cursor.execute(
            """
            SELECT booking_date, booking_time, master_name
            FROM available_slots
            WHERE id = ? AND is_booked = 0
            """,
            (slot_id,)
        )

        slot = cursor.fetchone()

        if slot is None:
            connection.close()
            return None

        booking_date, booking_time, actual_master = slot

        if actual_master != master_name:
            connection.close()
            return None

        # Занимаем окошко только если оно ещё свободно
        cursor.execute(
            """
            UPDATE available_slots
            SET is_booked = 1
            WHERE id = ? AND is_booked = 0
            """,
            (slot_id,)
        )

        if cursor.rowcount != 1:
            connection.rollback()
            connection.close()
            return None

        # Сохраняем запись клиента
        cursor.execute(
            """
            INSERT INTO bookings (
                telegram_id,
                username,
                service_name,
                master_name,
                slot_id,
                status
            )
            VALUES (?, ?, ?, ?, ?, 'confirmed')
            """,
            (
                telegram_id,
                username,
                service_name,
                master_name,
                slot_id
            )
        )

        connection.commit()

        return booking_date, booking_time, actual_master

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# Получение активных записей клиента
def get_client_bookings(telegram_id: int):
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            bookings.id,
            bookings.service_name,
            bookings.master_name,
            available_slots.booking_date,
            available_slots.booking_time,
            bookings.status,
            bookings.slot_id
        FROM bookings
        JOIN available_slots
            ON bookings.slot_id = available_slots.id
        WHERE bookings.telegram_id = ?
        AND bookings.status = 'confirmed'
        ORDER BY available_slots.booking_date, available_slots.booking_time
        """,
        (telegram_id,)
    )

    bookings = cursor.fetchall()
    connection.close()

    return bookings


# Отмена записи клиента

def cancel_client_booking(booking_id: int, telegram_id: int):
    connection = connect_db()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT slot_id
            FROM bookings
            WHERE id = ?
              AND telegram_id = ?
              AND status = 'confirmed'
            """,
            (booking_id, telegram_id)
        )

        booking = cursor.fetchone()

        if booking is None:
            return False

        slot_id = booking[0]

        # Отменяем запись клиента
        cursor.execute(
            """
            UPDATE bookings
            SET status = 'cancelled'
            WHERE id = ?
              AND telegram_id = ?
              AND status = 'confirmed'
            """,
            (booking_id, telegram_id)
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return False

        # Освобождаем окошко мастера
        cursor.execute(
            """
            UPDATE available_slots
            SET is_booked = 0
            WHERE id = ?
            """,
            (slot_id,)
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return False

        connection.commit()
        return True

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()
