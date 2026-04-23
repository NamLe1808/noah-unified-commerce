import csv
import logging
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor

# =========================
# CONFIG
# =========================
INPUT_DIR = Path(os.getenv('INPUT_DIR', '/app/input'))
PROCESSED_DIR = Path(os.getenv('PROCESSED_DIR', '/app/processed'))
POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', '5'))
CSV_FILE_PATTERN = os.getenv('CSV_FILE_PATTERN', '*.csv')

DB_HOST = os.getenv('DB_HOST', 'mysql')
DB_PORT = int(os.getenv('DB_PORT', '3306'))
DB_NAME = os.getenv('DB_NAME', 'webstore')
DB_USER = os.getenv('DB_USER', 'noah_user')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'noah_pass')
DB_CONNECT_RETRIES = int(os.getenv('DB_CONNECT_RETRIES', '30'))
DB_RETRY_DELAY = int(os.getenv('DB_RETRY_DELAY', '5'))

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

# =========================
# LOGGING
# =========================
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='[%(levelname)s] %(asctime)s - %(message)s'
)
logger = logging.getLogger('legacy_adapter')


# =========================
# DB CONNECTION
# =========================
def get_connection():
    """Retry connection because MySQL may take time to boot."""
    last_error = None
    for attempt in range(1, DB_CONNECT_RETRIES + 1):
        try:
            conn = pymysql.connect(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASSWORD,
                database=DB_NAME,
                autocommit=False,
                cursorclass=DictCursor,
            )
            logger.info('Connected to MySQL at %s:%s/%s', DB_HOST, DB_PORT, DB_NAME)
            return conn
        except Exception as exc:
            last_error = exc
            logger.warning(
                'MySQL not ready yet (attempt %s/%s). Retrying in %ss. Error: %s',
                attempt, DB_CONNECT_RETRIES, DB_RETRY_DELAY, exc
            )
            time.sleep(DB_RETRY_DELAY)
    raise RuntimeError(f'Could not connect to MySQL after retries: {last_error}')


# =========================
# DATA CLEANING
# =========================
def parse_int_strict(value: str):
    if value is None:
        return None
    text = str(value).strip()
    if text == '':
        return None
    if re.fullmatch(r'-?\d+', text):
        return int(text)
    return None


def sanitize_quantity(raw_quantity: str):
    """
    Handle dirty quantity values like:
    - 141pcs
    - 182N/A
    - 294approx

    Strategy:
    1. If pure integer => accept
    2. If starts with integer then has trailing junk => recover leading integer and log warning
    3. If no usable integer => reject
    4. If negative => reject
    """
    if raw_quantity is None:
        return None, 'missing quantity'

    text = str(raw_quantity).strip()
    if text == '':
        return None, 'empty quantity'

    direct = parse_int_strict(text)
    if direct is not None:
        if direct < 0:
            return None, f'negative quantity: {text}'
        return direct, None

    match = re.match(r'^(-?\d+)', text)
    if not match:
        return None, f'invalid quantity format: {text}'

    recovered = int(match.group(1))
    if recovered < 0:
        return None, f'negative quantity after sanitization: {text}'

    return recovered, f'sanitized quantity from {text!r} -> {recovered}'


def sanitize_product_id(raw_product_id: str):
    product_id = parse_int_strict(raw_product_id)
    if product_id is None:
        return None, f'invalid product_id: {raw_product_id}'
    return product_id, None


# =========================
# DB OPERATIONS
# =========================
def product_exists(cursor, product_id: int) -> bool:
    cursor.execute('SELECT 1 FROM products WHERE id = %s LIMIT 1', (product_id,))
    return cursor.fetchone() is not None


def update_stock(cursor, product_id: int, quantity: int):
    cursor.execute(
        'UPDATE products SET stock = %s WHERE id = %s',
        (quantity, product_id)
    )


# =========================
# FILE PROCESSING
# =========================
def ensure_directories():
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def move_to_processed(file_path: Path):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    new_name = f'{file_path.stem}_{timestamp}{file_path.suffix}'
    destination = PROCESSED_DIR / new_name
    shutil.move(str(file_path), str(destination))
    logger.info('Moved processed file to %s', destination)


def process_csv_file(file_path: Path, conn):
    processed_count = 0
    skipped_count = 0
    sanitized_count = 0

    logger.info('Processing file: %s', file_path)

    try:
        with conn.cursor() as cursor:
            with file_path.open('r', encoding='utf-8-sig', newline='') as csvfile:
                reader = csv.DictReader(csvfile)

                expected_columns = {'product_id', 'quantity'}
                if not reader.fieldnames or not expected_columns.issubset(set(reader.fieldnames)):
                    raise ValueError(
                        f'CSV header invalid. Expected columns {expected_columns}, got {reader.fieldnames}'
                    )

                for line_number, row in enumerate(reader, start=2):
                    try:
                        raw_product_id = row.get('product_id')
                        raw_quantity = row.get('quantity')

                        product_id, product_error = sanitize_product_id(raw_product_id)
                        if product_error:
                            skipped_count += 1
                            logger.warning('Line %s skipped: %s', line_number, product_error)
                            continue

                        quantity, quantity_note = sanitize_quantity(raw_quantity)
                        if quantity is None:
                            skipped_count += 1
                            logger.warning('Line %s skipped: %s', line_number, quantity_note)
                            continue

                        if quantity_note:
                            sanitized_count += 1
                            logger.warning('Line %s sanitized: %s', line_number, quantity_note)

                        if not product_exists(cursor, product_id):
                            skipped_count += 1
                            logger.warning(
                                'Line %s skipped: product_id %s not found in products table',
                                line_number,
                                product_id,
                            )
                            continue

                        update_stock(cursor, product_id, quantity)
                        processed_count += 1

                    except Exception as row_error:
                        skipped_count += 1
                        logger.warning('Line %s skipped due to row error: %s | data=%s', line_number, row_error, row)
                        continue

            conn.commit()
            logger.info(
                'Processed file %s successfully. Updated %s records, skipped %s invalid records, sanitized %s records.',
                file_path.name,
                processed_count,
                skipped_count,
                sanitized_count,
            )

    except Exception:
        conn.rollback()
        logger.exception('Failed while processing file %s. Transaction rolled back.', file_path.name)
        raise
    finally:
        move_to_processed(file_path)


# =========================
# POLLING LOOP
# =========================
def run():
    logger.info('Legacy Adapter started. Watching %s every %ss', INPUT_DIR, POLL_INTERVAL)
    ensure_directories()
    conn = get_connection()

    try:
        while True:
            files = sorted(INPUT_DIR.glob(CSV_FILE_PATTERN))
            if not files:
                logger.info('No CSV files found. Waiting...')
                time.sleep(POLL_INTERVAL)
                continue

            for file_path in files:
                try:
                    if file_path.is_file():
                        process_csv_file(file_path, conn)
                except Exception as file_error:
                    logger.exception('Error processing file %s: %s', file_path.name, file_error)

            time.sleep(POLL_INTERVAL)

    finally:
        conn.close()
        logger.info('MySQL connection closed.')


if __name__ == '__main__':
    run()
