"""Módulo de base de datos para Zenix."""
import pymysql
import mysql.connector
from mysql.connector import Error as MySQLError
from config import Config


class DatabaseManager:
    def __init__(self):
        self.connection = None

    def connect(self):
        if self.connection and self.connection.is_connected():
            return self.connection

        try:
            self.connection = mysql.connector.connect(
                host=Config.MYSQL_HOST,
                port=Config.MYSQL_PORT,
                user=Config.MYSQL_USER,
                password=Config.MYSQL_PASSWORD,
                database=Config.MYSQL_DATABASE,
            )
        except MySQLError as exc:
            if exc.errno == 1049:
                temp_conn = mysql.connector.connect(
                    host=Config.MYSQL_HOST,
                    port=Config.MYSQL_PORT,
                    user=Config.MYSQL_USER,
                    password=Config.MYSQL_PASSWORD,
                )
                temp_cursor = temp_conn.cursor()
                temp_cursor.execute(f"CREATE DATABASE IF NOT EXISTS {Config.MYSQL_DATABASE};")
                temp_conn.commit()
                temp_cursor.close()
                temp_conn.close()
                self.connection = mysql.connector.connect(
                    host=Config.MYSQL_HOST,
                    port=Config.MYSQL_PORT,
                    user=Config.MYSQL_USER,
                    password=Config.MYSQL_PASSWORD,
                    database=Config.MYSQL_DATABASE,
                )
            else:
                self.connection = pymysql.connect(
                    host=Config.MYSQL_HOST,
                    port=Config.MYSQL_PORT,
                    user=Config.MYSQL_USER,
                    password=Config.MYSQL_PASSWORD,
                    database=Config.MYSQL_DATABASE,
                    cursorclass=pymysql.cursors.DictCursor,
                )
        except Exception:
            self.connection = pymysql.connect(
                host=Config.MYSQL_HOST,
                port=Config.MYSQL_PORT,
                user=Config.MYSQL_USER,
                password=Config.MYSQL_PASSWORD,
                database=Config.MYSQL_DATABASE,
                cursorclass=pymysql.cursors.DictCursor,
            )
        return self.connection

    def execute_sql(self, query: str, params: tuple | list | None = None) -> None:
        conn = self.connect()
        cursor = conn.cursor()
        try:
            cursor.execute(query, params or ())
            conn.commit()
        finally:
            cursor.close()

    def close(self):
        if self.connection:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None
