# Telegram Notification Setup

## 1) Create a Telegram bot
- Open Telegram and chat with `@BotFather`.
- Create a bot with `/newbot`.
- Copy the bot token and put it into `TELEGRAM_BOT_TOKEN` in `.env`.

## 2) Get your chat id
### Option A: Send to a private chat
- Start a chat with your bot and send any message.
- Open: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
- Find `chat.id` and copy it into `TELEGRAM_CHAT_ID`.

### Option B: Send to a group
- Add the bot into your group.
- Send one message in the group.
- Open `getUpdates` again and copy the negative `chat.id` of the group.

## 3) Enable notification
In `.env` set:

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=<your_bot_token>
TELEGRAM_CHAT_ID=<your_chat_id>
```

## 4) Start the system
```bash
docker compose up --build
```

## 5) Trigger an order
When the Worker syncs an order successfully, it will send a Telegram message like:

```
Xin chào User [ID], đơn hàng #[Order_ID] trị giá $[Total] đã được xác nhận thanh toán thành công lúc [Time].
```

## Expected worker logs
- Success sync: `Order #123 synced successfully. PostgreSQL inserted, MySQL updated, ACK sent.`
- Success notification: `Order #123 synced. Notification sent to user.`
- Disabled notification: `Order #123 synced. Notification skipped because TELEGRAM_ENABLED=false.`
