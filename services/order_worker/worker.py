import json
import logging
import os
import time
from decimal import Decimal

import pika
import pymysql
import psycopg2
import psycopg2.extras

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="[%(levelname)s] %(asctime)s - %(message)s",
)
logger = logging.getLogger(__name__)

MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "mysql"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "noah_user"),
    "password": os.getenv("MYSQL_PASSWORD", "noah_pass"),
    "database": os.getenv("MYSQL_DB", "webstore"),
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": False,
}

POSTGRES_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "postgres"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "user": os.getenv("POSTGRES_USER", "noah_pg"),
    "password": os.getenv("POSTGRES_PASSWORD", "noah_pg_pass"),
    "dbname": os.getenv("POSTGRES_DB", "finance"),
}

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
RABBITMQ_QUEUE = os.getenv("RABBITMQ_QUEUE", "order_queue")
PROCESSING_DELAY = int(os.getenv("PROCESSING_DELAY", "2"))
CONNECT_RETRIES = int(os.getenv("CONNECT_RETRIES", "30"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "5"))


def wait_for_mysql() -> None:
    for attempt in range(1, CONNECT_RETRIES + 1):
        try:
            conn = pymysql.connect(**MYSQL_CONFIG)
            conn.close()
            logger.info(
                "Connected to MySQL at %s:%s/%s",
                MYSQL_CONFIG["host"], MYSQL_CONFIG["port"], MYSQL_CONFIG["database"]
            )
            return
        except Exception as exc:
            logger.warning(
                "MySQL not ready yet (attempt %s/%s). Retrying in %ss. Error: %s",
                attempt, CONNECT_RETRIES, RETRY_DELAY, exc
            )
            time.sleep(RETRY_DELAY)
    raise RuntimeError("Could not connect to MySQL")


def wait_for_postgres() -> None:
    for attempt in range(1, CONNECT_RETRIES + 1):
        try:
            conn = psycopg2.connect(**POSTGRES_CONFIG)
            conn.close()
            logger.info(
                "Connected to PostgreSQL at %s:%s/%s",
                POSTGRES_CONFIG["host"], POSTGRES_CONFIG["port"], POSTGRES_CONFIG["dbname"]
            )
            return
        except Exception as exc:
            logger.warning(
                "PostgreSQL not ready yet (attempt %s/%s). Retrying in %ss. Error: %s",
                attempt, CONNECT_RETRIES, RETRY_DELAY, exc
            )
            time.sleep(RETRY_DELAY)
    raise RuntimeError("Could not connect to PostgreSQL")


def ensure_finance_table() -> None:
    conn = psycopg2.connect(**POSTGRES_CONFIG)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS finance_transactions (
                        id SERIAL PRIMARY KEY,
                        order_id INT UNIQUE NOT NULL,
                        user_id INT NOT NULL,
                        product_id INT NOT NULL,
                        quantity INT NOT NULL,
                        total_price NUMERIC(12,2) NOT NULL,
                        payment_status VARCHAR(50) NOT NULL DEFAULT 'PAID',
                        synced_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
        logger.info("Ensured PostgreSQL table finance_transactions exists")
    finally:
        conn.close()


def process_message(ch, method, properties, body):
    message = json.loads(body.decode("utf-8"))
    order_id = int(message["order_id"])
    user_id = int(message["user_id"])
    product_id = int(message["product_id"])
    quantity = int(message["quantity"])
    total_price = Decimal(str(message["total_price"]))

    logger.info("Received order #%s from queue. Simulating processing...", order_id)
    time.sleep(PROCESSING_DELAY)

    pg_conn = None
    my_conn = None
    try:
        pg_conn = psycopg2.connect(**POSTGRES_CONFIG)
        with pg_conn:
            with pg_conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO finance_transactions
                    (order_id, user_id, product_id, quantity, total_price, payment_status)
                    VALUES (%s, %s, %s, %s, %s, 'PAID')
                    ON CONFLICT (order_id) DO NOTHING
                    """,
                    (order_id, user_id, product_id, quantity, total_price),
                )

        my_conn = pymysql.connect(**MYSQL_CONFIG)
        with my_conn.cursor() as cur:
            cur.execute(
                "UPDATE orders SET status = 'SYNCED' WHERE id = %s",
                (order_id,),
            )
            my_conn.commit()

        ch.basic_ack(delivery_tag=method.delivery_tag)
        logger.info("Order #%s synced successfully. PostgreSQL inserted, MySQL updated, ACK sent.", order_id)
    except Exception as exc:
        if my_conn:
            my_conn.rollback()
        logger.exception("Failed processing order #%s: %s", order_id, exc)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
    finally:
        if pg_conn:
            pg_conn.close()
        if my_conn:
            my_conn.close()


def consume_forever() -> None:
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)

    for attempt in range(1, CONNECT_RETRIES + 1):
        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    port=RABBITMQ_PORT,
                    credentials=credentials,
                    heartbeat=600,
                    blocked_connection_timeout=300,
                )
            )
            channel = connection.channel()
            channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=RABBITMQ_QUEUE, on_message_callback=process_message)
            logger.info("Worker is listening to queue '%s'", RABBITMQ_QUEUE)
            channel.start_consuming()
            return
        except Exception as exc:
            logger.warning(
                "RabbitMQ not ready yet (attempt %s/%s). Retrying in %ss. Error: %s",
                attempt, CONNECT_RETRIES, RETRY_DELAY, exc
            )
            time.sleep(RETRY_DELAY)

    raise RuntimeError("Could not connect to RabbitMQ")


if __name__ == "__main__":
    wait_for_mysql()
    wait_for_postgres()
    ensure_finance_table()
    consume_forever()
