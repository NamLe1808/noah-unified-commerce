import json
import logging
import os
import time
from decimal import Decimal

import pika
import pymysql
from flask import Flask, jsonify, request

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="[%(levelname)s] %(asctime)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "mysql"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "noah_user"),
    "password": os.getenv("DB_PASSWORD", "noah_pass"),
    "database": os.getenv("DB_NAME", "webstore"),
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": False,
}

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
RABBITMQ_QUEUE = os.getenv("RABBITMQ_QUEUE", "order_queue")
APP_PORT = int(os.getenv("APP_PORT", "5000"))
CONNECT_RETRIES = int(os.getenv("CONNECT_RETRIES", "30"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "5"))


def get_mysql_connection() -> pymysql.connections.Connection:
    return pymysql.connect(**DB_CONFIG)


def wait_for_mysql() -> None:
    for attempt in range(1, CONNECT_RETRIES + 1):
        try:
            conn = get_mysql_connection()
            conn.close()
            logger.info(
                "Connected to MySQL at %s:%s/%s",
                DB_CONFIG["host"],
                DB_CONFIG["port"],
                DB_CONFIG["database"],
            )
            return
        except Exception as exc:
            logger.warning(
                "MySQL not ready yet (attempt %s/%s). Retrying in %ss. Error: %s",
                attempt,
                CONNECT_RETRIES,
                RETRY_DELAY,
                exc,
            )
            time.sleep(RETRY_DELAY)
    raise RuntimeError("Could not connect to MySQL after multiple retries")


class RabbitPublisher:
    def __init__(self) -> None:
        self.connection = None
        self.channel = None

    def connect(self) -> None:
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        params = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            port=RABBITMQ_PORT,
            credentials=credentials,
            heartbeat=600,
            blocked_connection_timeout=300,
        )
        self.connection = pika.BlockingConnection(params)
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)
        logger.info("Connected to RabbitMQ at %s:%s", RABBITMQ_HOST, RABBITMQ_PORT)

    def wait_until_ready(self) -> None:
        for attempt in range(1, CONNECT_RETRIES + 1):
            try:
                self.connect()
                return
            except Exception as exc:
                logger.warning(
                    "RabbitMQ not ready yet (attempt %s/%s). Retrying in %ss. Error: %s",
                    attempt,
                    CONNECT_RETRIES,
                    RETRY_DELAY,
                    exc,
                )
                time.sleep(RETRY_DELAY)
        raise RuntimeError("Could not connect to RabbitMQ after multiple retries")

    def ensure_open(self) -> None:
        if self.connection is None or self.connection.is_closed or self.channel is None or self.channel.is_closed:
            self.connect()

    def publish(self, payload: dict) -> None:
        self.ensure_open()
        self.channel.basic_publish(
            exchange="",
            routing_key=RABBITMQ_QUEUE,
            body=json.dumps(payload),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
            ),
        )


publisher = RabbitPublisher()


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "order_api"}), 200


@app.post("/api/orders")
def create_order():
    data = request.get_json(silent=True) or {}

    user_id = data.get("user_id")
    product_id = data.get("product_id")
    quantity = data.get("quantity")

    if user_id is None or product_id is None or quantity is None:
        return jsonify({"error": "user_id, product_id, quantity are required"}), 400

    try:
        user_id = int(user_id)
        product_id = int(product_id)
        quantity = int(quantity)
    except (TypeError, ValueError):
        return jsonify({"error": "user_id, product_id, quantity must be integers"}), 400

    if quantity <= 0:
        return jsonify({"error": "quantity must be greater than 0"}), 400

    conn = None
    try:
        conn = get_mysql_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, price, stock FROM products WHERE id = %s",
                (product_id,),
            )
            product = cursor.fetchone()

            if not product:
                conn.rollback()
                return jsonify({"error": f"product_id {product_id} not found"}), 404

            total_price = Decimal(product["price"]) * quantity

            cursor.execute(
                """
                INSERT INTO orders (user_id, product_id, quantity, total_price, status)
                VALUES (%s, %s, %s, %s, 'PENDING')
                """,
                (user_id, product_id, quantity, total_price),
            )
            order_id = cursor.lastrowid
            conn.commit()

        message = {
            "order_id": order_id,
            "user_id": user_id,
            "product_id": product_id,
            "quantity": quantity,
            "total_price": float(total_price),
            "status": "PENDING",
            "created_from": "order_api",
        }
        publisher.publish(message)
        logger.info("Order #%s inserted into MySQL and published to queue", order_id)

        return (
            jsonify(
                {
                    "message": "Order received",
                    "order_id": order_id,
                    "status": "PENDING",
                    "product_name": product["name"],
                    "total_price": float(total_price),
                }
            ),
            202,
        )
    except Exception as exc:
        if conn:
            conn.rollback()
        logger.exception("Failed to create order: %s", exc)
        return jsonify({"error": "Internal server error", "details": str(exc)}), 500
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    wait_for_mysql()
    publisher.wait_until_ready()
    logger.info("Order API started on port %s", APP_PORT)
    app.run(host="0.0.0.0", port=APP_PORT)
