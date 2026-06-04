"""Scheduler para Zenix_OS: persistencia y revisión crítica de tareas en MySQL."""
import logging
import re
import time
from datetime import datetime
from typing import Optional, Sequence

import mysql.connector
from mysql.connector import Error

LOGGER = logging.getLogger("zenix_scheduler")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "vega",
    "database": "zenix_os",
    "autocommit": False,
}

CRITICAL_ALERTS = [
    ("07:00:00", "Despertar"),
    ("15:00:00", "Recordatorio_Critico"),
]


def get_connection(use_database: bool = True):
    config = DB_CONFIG.copy()
    if not use_database:
        config.pop("database", None)
    try:
        return mysql.connector.connect(**config)
    except Error as exc:
        LOGGER.error("Error conectando a MySQL: %s", exc)
        raise


def execute_query(query: str, params: Optional[tuple] = None, use_database: bool = True, fetch: bool = False):
    conn = get_connection(use_database=use_database)
    cursor = conn.cursor()
    try:
        try:
            cursor.execute(query, params or ())
        except Error as exc:
            conn.rollback()
            LOGGER.error("MySQL Error executing query: %s", exc)
            raise
        if fetch:
            return cursor.fetchall()
        conn.commit()
        return None
    finally:
        cursor.close()
        conn.close()


def create_database_and_tables() -> None:
    LOGGER.info("Inicializando base de datos y tablas en zenix_os")
    conn = get_connection(use_database=False)
    cursor = conn.cursor()
    try:
        cursor.execute("CREATE DATABASE IF NOT EXISTS zenix_os CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
        cursor.execute("USE zenix_os;")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tareas (
                id INT AUTO_INCREMENT PRIMARY KEY,
                titulo VARCHAR(255) NOT NULL,
                descripcion TEXT,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                estado VARCHAR(50) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS alertas_programadas (
                id INT AUTO_INCREMENT PRIMARY KEY,
                tarea_id INT NULL,
                hora_ejecucion TIME NOT NULL,
                tipo_alerta VARCHAR(100) NOT NULL,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_alerta_tarea FOREIGN KEY (tarea_id) REFERENCES tareas(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """
        )
        for hora, tipo in CRITICAL_ALERTS:
            cursor.execute(
                """
                INSERT INTO alertas_programadas (tarea_id, hora_ejecucion, tipo_alerta)
                SELECT NULL, %s, %s
                WHERE NOT EXISTS (
                    SELECT 1 FROM alertas_programadas WHERE hora_ejecucion = %s AND tipo_alerta = %s
                );
                """,
                (hora, tipo, hora, tipo),
            )
        conn.commit()
    finally:
        cursor.close()
        conn.close()



def extract_save_tag(text: str) -> Optional[tuple[str, str]]:
    match = re.search(r"\[SAVE:\s*([^|\]]+?)\s*\|\s*([0-9]{2}:[0-9]{2}:[0-9]{2})\s*\]", text)
    if not match:
        return None
    titulo = match.group(1).strip()
    hora = match.group(2).strip()
    if not titulo or not hora:
        return None
    return titulo, hora


def save_task_from_response(response: str) -> bool:
    parsed = extract_save_tag(response)
    if not parsed:
        LOGGER.debug("No se encontró etiqueta SAVE en la respuesta.")
        return False
    titulo, hora_ejecucion = parsed
    conn = get_connection(use_database=True)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO tareas (titulo, estado) VALUES (%s, 'Pendiente');",
            (titulo,),
        )
        tarea_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO alertas_programadas (tarea_id, hora_ejecucion, tipo_alerta) VALUES (%s, %s, 'Recordatorio_Critico');",
            (tarea_id, hora_ejecucion),
        )
        conn.commit()
        LOGGER.info("Tarea guardada: %s a las %s", titulo, hora_ejecucion)
        return True
    except Error as exc:
        conn.rollback()
        LOGGER.error("Error guardando tarea desde etiqueta SAVE: %s", exc)
        raise
    finally:
        cursor.close()
        conn.close()


def get_task_count() -> int:
    rows = execute_query("SELECT COUNT(*) FROM tareas WHERE estado = 'Pendiente';", fetch=True)
    return int(rows[0][0]) if rows else 0


def get_tasks_pending() -> list[tuple[str, str]]:
    query = (
        "SELECT t.titulo, TIME_FORMAT(a.hora_ejecucion, '%H:%i') "
        "FROM tareas t "
        "INNER JOIN alertas_programadas a ON t.id = a.tarea_id "
        "WHERE t.estado = 'Pendiente';"
    )
    rows = execute_query(query, fetch=True)
    return rows or []


def get_pending_tasks_response() -> str:
    rows = get_tasks_pending()
    if not rows:
        return "No tienes tareas pendientes"
    lines = ["Tareas pendientes:"]
    for index, (titulo, hora) in enumerate(rows, start=1):
        lines.append(f"{index}. {titulo} — {hora}")
    return "\n".join(lines)


def parse_time_string(value: str) -> Optional[str]:
    value = value.strip().lower().replace('.', ':').replace(' ', '')
    match = re.match(r'^(1[0-2]|0?[1-9])(?:[:](\d{2}))?(am|pm)?$', value)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or '00')
    suffix = match.group(3)
    if suffix == 'pm' and hour != 12:
        hour += 12
    if suffix == 'am' and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}:00"


def handle_morning_flow() -> None:
    print("Deseas agregar algun pendiente")
    answer = input().strip().lower()
    if answer not in {"si", "sí", "s"}:
        LOGGER.info("El usuario no confirmó agregar un pendiente.")
        return
    print("¿De qué se trata el pendiente?")
    titulo = input().strip()
    if not titulo:
        print("No entendí el pendiente. Intenta describirlo de nuevo.")
        return
    print("¿A qué hora se ejecutará?")
    time_answer = input().strip().lower()
    hora = parse_time_string(time_answer)
    if hora is None:
        print("No entendí la hora. Intenta con un formato como '7 am' o '07:00'.")
        return
    save_tag = f"[SAVE: {titulo} | {hora}]"
    if save_task_from_response(save_tag):
        print("Guardado con éxito")
    else:
        print("No se pudo guardar la tarea.")


def perform_critical_review() -> None:
    tasks = get_tasks_pending()
    if not tasks:
        LOGGER.info("Revisión crítica de tareas a las 15:00: no tienes tareas pendientes.")
        return
    LOGGER.info("Activando revisión crítica de tareas: %s tareas pendientes.", len(tasks))
    for index, (titulo, hora) in enumerate(tasks, start=1):
        LOGGER.info("%d. %s — %s", index, titulo, hora)


def scheduler_loop() -> None:
    last_run = {"07": None, "15": None}
    while True:
        now = datetime.now()
        current_date = now.date()
        current_hour = f"{now.hour:02d}"
        if now.hour == 7 and now.minute == 0 and last_run["07"] != current_date:
            last_run["07"] = current_date
            if get_task_count() == 0:
                handle_morning_flow()
            else:
                LOGGER.info("Verificación de las 07:00: ya existen pendientes en la base de datos.")
        if now.hour == 15 and now.minute == 0 and last_run["15"] != current_date:
            last_run["15"] = current_date
            perform_critical_review()
        time.sleep(20)


def main() -> None:
    create_database_and_tables()
    LOGGER.info("Zenix Scheduler iniciado. Esperando los horarios críticos de 07:00 y 15:00.")
    scheduler_loop()


if __name__ == "__main__":
    main()
