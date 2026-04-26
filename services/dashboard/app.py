import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(
    page_title="NOAH Unified Commerce Dashboard",
    page_icon="📊",
    layout="wide",
)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://kong:8000").rstrip("/")
API_KEY = os.getenv("API_KEY", "noah-secret-key")
RABBITMQ_MGMT_URL = os.getenv("RABBITMQ_MGMT_URL", "http://rabbitmq:15672").rstrip("/")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
DEFAULT_LIMIT = int(os.getenv("DEFAULT_LIMIT", "10"))

st.markdown("""
<style>
.block-container {padding-top: 1.1rem; padding-bottom: 1.1rem;}
.kpi-card {border:1px solid rgba(49,51,63,.15); border-radius:18px; padding:16px 18px; background:linear-gradient(180deg,#f8fbff,#ffffff); box-shadow:0 6px 18px rgba(31,41,55,.06);}
.kpi-title {font-size:.9rem; color:#64748b; margin-bottom:6px;}
.kpi-value {font-size:1.85rem; font-weight:700; color:#0f172a;}
.kpi-sub {font-size:.82rem; color:#475569;}
.section-card {border:1px solid rgba(49,51,63,.12); border-radius:20px; padding:14px 16px 8px 16px; background:#fff; box-shadow:0 8px 22px rgba(15,23,42,.05);}
.status-pill {display:inline-block; padding:.25rem .7rem; border-radius:999px; font-size:.82rem; font-weight:600; margin-right:.4rem; margin-bottom:.4rem;}
.ok {background:#dcfce7; color:#166534;}
.warn {background:#fef3c7; color:#92400e;}
.info {background:#dbeafe; color:#1d4ed8;}
.bad {background:#fee2e2; color:#b91c1c;}
.small-note {font-size:.86rem; color:#64748b;}
</style>
""", unsafe_allow_html=True)


def auth_headers():
    return {"apikey": API_KEY}


@st.cache_data(ttl=60, show_spinner=False)
def fetch_report(page: int, limit: int):
    r = requests.get(
        f"{GATEWAY_URL}/report/api/report",
        params={"page": page, "limit": limit},
        headers=auth_headers(),
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=20, show_spinner=False)
def fetch_queue():
    try:
        r = requests.get(
            f"{RABBITMQ_MGMT_URL}/api/queues/%2F/order_queue",
            auth=(RABBITMQ_USER, RABBITMQ_PASS),
            timeout=10,
        )
        if r.status_code == 200:
            d = r.json()
            return {
                "messages": d.get("messages", 0),
                "ready": d.get("messages_ready", 0),
                "unacked": d.get("messages_unacknowledged", 0),
                "consumers": d.get("consumers", 0),
                "state": d.get("state", "unknown"),
            }
    except Exception:
        pass

    return {
        "messages": 0,
        "ready": 0,
        "unacked": 0,
        "consumers": 0,
        "state": "unavailable",
    }


def send_order(user_id: int, product_id: int, quantity: int):
    return requests.post(
        f"{GATEWAY_URL}/orders/api/orders",
        json={
            "user_id": user_id,
            "product_id": product_id,
            "quantity": quantity,
        },
        headers={**auth_headers(), "Content-Type": "application/json"},
        timeout=20,
    )


def kpi_card(title, value, sub=""):
    st.markdown(
        f'<div class="kpi-card"><div class="kpi-title">{title}</div><div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>',
        unsafe_allow_html=True,
    )


def pill(text, cls):
    st.markdown(
        f'<span class="status-pill {cls}">{text}</span>',
        unsafe_allow_html=True,
    )


st.sidebar.title("NOAH Control Panel")
page = st.sidebar.number_input("Page", min_value=1, value=1, step=1)
limit = st.sidebar.selectbox("Rows per page", [5, 10, 20, 50], index=1)
auto_refresh = st.sidebar.checkbox("Auto refresh", value=False)

if st.sidebar.button("Refresh now", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

if auto_refresh:
    st.sidebar.caption("Auto refresh bật: dữ liệu sẽ dùng cache để tránh vượt rate limit của Kong.")

head_l, head_r = st.columns([3.2, 1.2])
with head_l:
    st.title("NOAH Unified Commerce Dashboard")
    st.caption("Góc nhìn toàn cảnh (Single View) bằng cách ghép dữ liệu từ MySQL, PostgreSQL, RabbitMQ và Kong Gateway.")

with head_r:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown("**Quick Links**")
    st.markdown("- Dashboard: `localhost:8501`")
    st.markdown("- Swagger: `localhost:8081`")
    st.markdown("- RabbitMQ: `localhost:15672`")
    st.markdown("- Kong Proxy: `localhost:8000`")
    st.markdown("</div>", unsafe_allow_html=True)

report_error = None
try:
    report = fetch_report(int(page), int(limit))
except Exception as e:
    report_error = str(e)

queue = fetch_queue()

st.subheader("Integration Status")
c = st.columns(5)
with c[0]:
    pill("MySQL / Orders", "ok" if not report_error else "bad")
with c[1]:
    pill("PostgreSQL / Finance", "ok" if not report_error else "bad")
with c[2]:
    pill(f"RabbitMQ / {queue['state']}", "ok" if queue["state"] != "unavailable" else "warn")
with c[3]:
    pill("Kong Protected", "info")
with c[4]:
    pill("API Key Enabled", "info")

if report_error:
    st.error(f"Không tải được report qua Kong Gateway: {report_error}")
    st.stop()

summary = report.get("summary", {})
pagination = report.get("pagination", {})
orders = report.get("orders", [])
top_users = report.get("revenue_by_user_top10", [])

current_page = int(pagination.get("page", 1))
total_pages = int(pagination.get("total_pages", 1))
total_orders = int(pagination.get("total_orders", 0))
orders_in_page = int(summary.get("orders_in_this_page", 0))

k1, k2, k3, k4, k5, k6 = st.columns(6)
with k1:
    kpi_card("Total Orders", str(total_orders), "Tổng số đơn trong hệ thống")
with k2:
    kpi_card("Rows on Page", str(orders_in_page), f"Trang {current_page}/{total_pages}")
with k3:
    kpi_card("Synced Orders", str(summary.get("synced_orders_in_page", 0)), "Đã đối soát sang Finance")
with k4:
    kpi_card("Pending Orders", str(summary.get("pending_orders_in_page", 0)), "Đang chờ worker xử lý")
with k5:
    kpi_card("Page Revenue", f"{summary.get('page_total_revenue', 0):,.0f}", "Doanh thu trang hiện tại")
with k6:
    kpi_card("Queue Ready", str(queue.get("ready", 0)), f"Unacked: {queue.get('unacked', 0)}")

rows = []
for item in orders:
    finance = item.get("finance", {}) or {}
    rows.append({
        "Order ID": item.get("order_id"),
        "User ID": item.get("user_id"),
        "Product ID": item.get("product_id"),
        "Product": item.get("product_name"),
        "Qty": item.get("quantity"),
        "Total Price": item.get("total_price"),
        "Status": item.get("status"),
        "Current Stock": item.get("current_stock"),
        "Finance Found": finance.get("found_in_finance"),
        "Payment Status": finance.get("payment_status"),
        "Synced At": finance.get("processed_at"),
        "Created At": item.get("created_at"),
    })

orders_df = pd.DataFrame(rows)
top_df = pd.DataFrame(top_users)

if not orders_df.empty:
    orders_df["Created At"] = pd.to_datetime(orders_df["Created At"], errors="coerce")
    orders_df["Synced At"] = pd.to_datetime(orders_df["Synced At"], errors="coerce")

    orders_df["Created At"] = orders_df["Created At"].dt.strftime("%Y-%m-%d %H:%M:%S")
    orders_df["Synced At"] = orders_df["Synced At"].dt.strftime("%Y-%m-%d %H:%M:%S")

    orders_df["Created At"] = orders_df["Created At"].fillna("N/A")
    orders_df["Synced At"] = orders_df["Synced At"].fillna("N/A")
    orders_df["Payment Status"] = orders_df["Payment Status"].fillna("N/A")
    orders_df["Finance Found"] = orders_df["Finance Found"].fillna(False)

    orders_df["Finance Found"] = orders_df["Finance Found"].map({
        True: "Yes",
        False: "No",
    })

    orders_df["Total Price"] = pd.to_numeric(orders_df["Total Price"], errors="coerce").fillna(0)
    orders_df["Qty"] = pd.to_numeric(orders_df["Qty"], errors="coerce").fillna(0).astype(int)
    orders_df["Current Stock"] = pd.to_numeric(orders_df["Current Stock"], errors="coerce").fillna(0).astype(int)

display_orders_df = orders_df.copy()
if not display_orders_df.empty:
    display_orders_df["Total Price"] = display_orders_df["Total Price"].apply(lambda x: f"{x:,.0f}")
    display_orders_df = display_orders_df.fillna("N/A").astype(str).reset_index(drop=True)

    start_index = (current_page - 1) * int(limit) + 1
    display_orders_df.index = range(start_index, start_index + len(display_orders_df))
    display_orders_df.index.name = ""

l, r = st.columns([1.3, 1])

with l:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown("### Revenue by Top Customers")
    if not top_df.empty:
        top_df["total_revenue"] = pd.to_numeric(top_df["total_revenue"], errors="coerce").fillna(0)
        fig = px.bar(
            top_df,
            x="user_id",
            y="total_revenue",
            text="total_revenue",
            labels={"user_id": "User ID", "total_revenue": "Revenue"},
        )
        fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=20, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Chưa có dữ liệu doanh thu từ PostgreSQL.")
    st.markdown("</div>", unsafe_allow_html=True)

with r:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown("### Sync Status")
    sync_df = pd.DataFrame([
        {"Status": "SYNCED", "Count": summary.get("synced_orders_in_page", 0)},
        {"Status": "PENDING", "Count": summary.get("pending_orders_in_page", 0)},
    ])
    fig2 = px.pie(sync_df, names="Status", values="Count", hole=0.58)
    fig2.update_layout(height=360, margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(fig2, use_container_width=True)
    st.markdown(
        f"<div class='small-note'>Queue snapshot — messages: {queue.get('messages', 0)}, ready: {queue.get('ready', 0)}, unacked: {queue.get('unacked', 0)}, consumers: {queue.get('consumers', 0)}</div>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

table_col, side_col = st.columns([2.1, 1])

with table_col:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown("### Reconciliation View (Data Stitching)")

    if orders_in_page > 0:
        start_row = (current_page - 1) * int(limit) + 1
        end_row = start_row + orders_in_page - 1
    else:
        start_row = 0
        end_row = 0

    st.caption(f"Showing rows {start_row} - {end_row} of {total_orders}")

    if not display_orders_df.empty:
        st.table(display_orders_df)
    else:
        st.warning("Không có dữ liệu order để hiển thị.")
    st.markdown("</div>", unsafe_allow_html=True)

with side_col:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown("### Quick Order Test")

    with st.form("send_order_form"):
        user_id = st.number_input("User ID", min_value=1, value=1, step=1)
        product_id = st.number_input("Product ID", min_value=1, value=101, step=1)
        quantity = st.number_input("Quantity", min_value=1, value=1, step=1)
        submitted = st.form_submit_button("Send Order", use_container_width=True)

    if submitted:
        try:
            resp = send_order(int(user_id), int(product_id), int(quantity))
            if resp.ok:
                st.success(f"Gửi đơn thành công: {resp.json()}")
                st.cache_data.clear()
            else:
                st.error(f"Lỗi {resp.status_code}: {resp.text}")
        except Exception as e:
            st.error(f"Không gửi được order: {e}")

    st.markdown("---")
    st.markdown("### Queue Snapshot")
    st.write(queue)

    st.markdown("---")
    st.markdown("### Why this page matters")
    st.markdown("""
- Hiển thị dữ liệu từ **nhiều nguồn rời rạc**
- Kết hợp MySQL + PostgreSQL
- Tạo góc nhìn toàn cảnh (Single View)
""")
    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")
st.caption(
    f"Last rendered at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
    f"Gateway: {GATEWAY_URL} | "
    f"Page {current_page}/{total_pages}"
)