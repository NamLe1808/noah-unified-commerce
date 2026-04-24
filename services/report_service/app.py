import os
import time
import logging
from decimal import Decimal
from typing import Any, Dict, List

from flask import Flask, jsonify, request
import pymysql
import psycopg2
from psycopg2.extras import RealDictCursor


logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="[%(levelname)s] %(asctime)s - %(message)s",
)
logger = logging.getLogger(__name__)

MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DB = os.getenv("MYSQL_DB", "webstore")
MYSQL_USER = os.getenv("MYSQL_USER", "noah_user")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "noah_pass")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "finance")
POSTGRES_USER = os.getenv("POSTGRES_USER", "noah_pg")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "noah_pg_pass")

CONNECT_RETRIES = int(os.getenv("CONNECT_RETRIES", "30"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "5"))
APP_PORT = int(os.getenv("APP_PORT", "5001"))
DEFAULT_LIMIT = int(os.getenv("DEFAULT_LIMIT", "10"))
MAX_LIMIT = int(os.getenv("MAX_LIMIT", "100"))

app = Flask(__name__)


def wait_for_mysql():
    last_error = None
    for attempt in range(1, CONNECT_RETRIES + 1):
        try:
            conn = pymysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DB,
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True,
            )
            logger.info("Connected to MySQL at %s:%s/%s", MYSQL_HOST, MYSQL_PORT, MYSQL_DB)
            return conn
        except Exception as e:
            last_error = e
            logger.warning(
                "MySQL not ready yet (attempt %s/%s). Retrying in %ss. Error: %s",
                attempt, CONNECT_RETRIES, RETRY_DELAY, e
            )
            time.sleep(RETRY_DELAY)
    raise RuntimeError(f"Could not connect to MySQL: {last_error}")


def wait_for_postgres():
    last_error = None
    for attempt in range(1, CONNECT_RETRIES + 1):
        try:
            conn = psycopg2.connect(
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                dbname=POSTGRES_DB,
                cursor_factory=RealDictCursor,
            )
            conn.autocommit = True
            logger.info("Connected to PostgreSQL at %s:%s/%s", POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB)
            return conn
        except Exception as e:
            last_error = e
            logger.warning(
                "PostgreSQL not ready yet (attempt %s/%s). Retrying in %ss. Error: %s",
                attempt, CONNECT_RETRIES, RETRY_DELAY, e
            )
            time.sleep(RETRY_DELAY)
    raise RuntimeError(f"Could not connect to PostgreSQL: {last_error}")


mysql_conn = wait_for_mysql()
postgres_conn = wait_for_postgres()


def to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def fetch_mysql_orders(limit: int, offset: int) -> List[Dict[str, Any]]:
    query = """
        SELECT
            o.id,
            o.user_id,
            o.product_id,
            o.quantity,
            o.total_price,
            o.status,
            o.created_at,
            p.name AS product_name,
            p.price AS product_price,
            p.stock AS current_stock
        FROM orders o
        LEFT JOIN products p ON o.product_id = p.id
        ORDER BY o.id DESC
        LIMIT %s OFFSET %s
    """
    with mysql_conn.cursor() as cur:
        cur.execute(query, (limit, offset))
        return cur.fetchall()


def fetch_mysql_total_orders() -> int:
    with mysql_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM orders")
        result = cur.fetchone()
    return int(result["total"])


def fetch_postgres_transactions(order_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not order_ids:
        return {}

    placeholders = ",".join(["%s"] * len(order_ids))
    query = f"""
        SELECT
            order_id,
            user_id,
            product_id,
            quantity,
            total_price,
            payment_status,
            synced_at
        FROM finance_transactions
        WHERE order_id IN ({placeholders})
    """

    with postgres_conn.cursor() as cur:
        cur.execute(query, tuple(order_ids))
        rows = cur.fetchall()

    mapped = {}
    for row in rows:
        mapped[int(row["order_id"])] = dict(row)
    return mapped


def fetch_postgres_revenue_summary() -> List[Dict[str, Any]]:
    query = """
        SELECT
            user_id,
            COUNT(*) AS transaction_count,
            SUM(total_price) AS total_revenue
        FROM finance_transactions
        GROUP BY user_id
        ORDER BY total_revenue DESC, user_id ASC
        LIMIT 10
    """
    with postgres_conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()
    return [dict(row) for row in rows]


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "report_service"}), 200


@app.route("/api/report", methods=["GET"])
def report():
    try:
        limit = min(max(int(request.args.get("limit", DEFAULT_LIMIT)), 1), MAX_LIMIT)
        page = max(int(request.args.get("page", "1")), 1)
        offset = (page - 1) * limit

        orders = fetch_mysql_orders(limit=limit, offset=offset)
        total_orders = fetch_mysql_total_orders()
        order_ids = [int(order["id"]) for order in orders]
        tx_map = fetch_postgres_transactions(order_ids)

        stitched_orders: List[Dict[str, Any]] = []
        pending_count = 0
        synced_count = 0
        page_revenue = 0.0

        for order in orders:
            order_id = int(order["id"])
            status = str(order.get("status", "UNKNOWN"))

            if status == "SYNCED":
                synced_count += 1
            elif status == "PENDING":
                pending_count += 1

            total_price = to_float(order.get("total_price"))
            page_revenue += total_price

            tx = tx_map.get(order_id)

            created_at = order.get("created_at")
            if created_at is not None and hasattr(created_at, "isoformat"):
                created_at = created_at.isoformat()
            else:
                created_at = str(created_at) if created_at is not None else None

            processed_at = None
            if tx and tx.get("synced_at") is not None:
                if hasattr(tx["synced_at"], "isoformat"):
                    processed_at = tx["synced_at"].isoformat()
                else:
                    processed_at = str(tx["synced_at"])

            stitched_orders.append({
                "order_id": order_id,
                "user_id": int(order["user_id"]) if order.get("user_id") is not None else None,
                "product_id": int(order["product_id"]) if order.get("product_id") is not None else None,
                "product_name": order.get("product_name"),
                "quantity": int(order["quantity"]) if order.get("quantity") is not None else None,
                "total_price": total_price,
                "status": status,
                "created_at": created_at,
                "current_stock": int(order["current_stock"]) if order.get("current_stock") is not None else None,
                "finance": {
                    "found_in_finance": tx is not None,
                    "payment_status": tx.get("payment_status") if tx else None,
                    "processed_at": processed_at,
                }
            })

        revenue_by_user_raw = fetch_postgres_revenue_summary()
        revenue_by_user = [
            {
                "user_id": int(row["user_id"]) if row.get("user_id") is not None else None,
                "transaction_count": int(row["transaction_count"]),
                "total_revenue": to_float(row["total_revenue"]),
            }
            for row in revenue_by_user_raw
        ]

        response = {
            "pagination": {
                "page": page,
                "limit": limit,
                "total_orders": total_orders,
                "total_pages": (total_orders + limit - 1) // limit,
            },
            "summary": {
                "orders_in_this_page": len(stitched_orders),
                "page_total_revenue": round(page_revenue, 2),
                "synced_orders_in_page": synced_count,
                "pending_orders_in_page": pending_count,
            },
            "revenue_by_user_top10": revenue_by_user,
            "orders": stitched_orders,
        }
        return jsonify(response), 200

    except Exception as e:
        logger.exception("Error while generating report: %s", e)
        return jsonify({
            "error": "internal_server_error",
            "message": str(e)
        }), 500


if __name__ == "__main__":
    logger.info("Report Service started on port %s", APP_PORT)
    app.run(host="0.0.0.0", port=APP_PORT)