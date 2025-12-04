# 📦 Telegram → Bale Forwarding Bridge  
Forward Telegram channel messages (texts, photos, videos) to Bale channels — with filters, caption editing, admin panel, and userbot (no admin needed in Telegram).

## 🚀 Features
- **Userbot-based (Telethon)** → Reads Telegram channels **without admin permissions**.  
- **Forwards text, photos & videos** to Bale channel.
- **Admin Panel inside Telegram**:
  - Add new source channels  
  - List channels  
  - Set per-channel caption  
  - Set Bale destination  
  - Remove channel  
- **Keyword filtering**
- **Duplicate prevention**
- **Automatic caption cleaning & watermark removal**
- **URL & Text-Link stripping (including hidden hyperlinks)**
- **Clean architecture: SQLite + async Python**

## 📁 Folder Structure

```
TelToBale/
│── 2.py                # Main bridge script
│── .env                # Configuration file
│── requirements.txt    # Dependencies
│── db.sqlite3          # Auto-created database (channels + sent messages)
│── README.md
```

## ⚙️ Installation

### 1. Clone project

```bash
git clone <your-repo-url>
cd TelToBale
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

## 🔧 Environment Setup (`.env`)

Create a `.env` file:

```env
TELEGRAM_API_ID=YOUR_API_ID
TELEGRAM_API_HASH=YOUR_API_HASH
TELEGRAM_SESSION=TelToBale

ADMIN_ID=YOUR_TELEGRAM_USER_ID

BALE_BOT_TOKEN=YOUR_BALE_BOT_TOKEN

KEYWORDS=
REMOVE_PATTERNS=@oldchannel,t.me/oldchannel
SEND_DELAY_SECONDS=1.5
DB_PATH=db.sqlite3
```

### Where to get values:

| Variable | Description |
|---------|-------------|
| `TELEGRAM_API_ID` | From https://my.telegram.org |
| `TELEGRAM_API_HASH` | From https://my.telegram.org |
| `ADMIN_ID` | Your Telegram numeric ID (use @userinfobot) |
| `BALE_BOT_TOKEN` | Token from Bale bot creation page |
| `TELEGRAM_SESSION` | Name of your Telethon session file |

## 🧩 How It Works

### Telegram Side (Telethon Userbot)
You login using your **phone number** (NOT bot token).  
Telethon reads messages from channels that your account has joined.

### Bale Side
Bot sends:
- Text  
- Photos  
- Videos  
To your Bale channel.

Make sure your **Bale bot is ADMIN in Bale destination channel**.

## ▶️ Running the Bot

```bash
python 2.py
```

First run → Telethon asks:

```
Please enter your phone:
```

Enter your Telegram number:  
`+98xxxxxxxxxx`

Then enter the verification code.

## 🛠️ Admin Panel Commands (Telegram → Your PV)

Use these commands in **private chat** with your own Telegram account:

### `/panel`  
Shows admin menu.

### `/channels`  
Lists all configured source channels.

### `/addchannel`  
Add a new Telegram source channel  
Bot asks for:
1. Telegram channel link / username  
2. Bale destination channel username

### `/manage <id>`  
Manage channel settings:
1. Set caption  
2. Set Bale destination  
3. Delete channel

### `/cancel`  
Stops current operation.

## 🔍 Caption / Cleaning System

### Cleaned automatically:
- `@usernames`
- `https://t.me/...`
- Any `http/https/www` URLs
- Hidden hyperlinks (MessageEntityTextUrl)
- Custom patterns via `.env` → `REMOVE_PATTERNS`

### Per-channel captions:
- Add via `/manage <id>`
- Remove by sending:  
  ```
  -
  ```

## 🖼 Media Forwarding  
Supports:
- Photo → `send_photo()`
- Video → `send_video()`
- Caption preserved + suffix caption

## 🗄 Database (SQLite)

Stores:
- Channels configuration  
- Sent message IDs (prevents duplicates)

Auto-created on first run.

## 🔐 Notes & Limitations

- Telegram reading works only via **Userbot** (NOT Bot API).  
- The userbot must **join** each source channel manually.  
- Media files are streamed in bytes and re-uploaded to Bale.  

## 🧪 Testing

### Test text forwarding
Send:
```
test123
```
into the source channel.

### Test photo
Send a random image.

### Test video
Send a short video.

Check Bale destination channel for results.

## ❗ Common Issues

### ❌ Bot does not forward messages
Check:
- Did userbot join the source Telegram channel?  
- Is Bale bot admin in Bale channel?  
- Is `KEYWORDS=` empty or configured correctly?  
- Did you restart after adding channels?  
- `Loaded 0 channels` → DB is empty → re-add channels.

### ❌ Cannot send media to Bale  
Use correct:

```python
InputFile(photo_bytes, file_name="photo.jpg")
```

## ⭐ Future Add-ons (optional)
- Web dashboard for channel management  
- Automatic channel joining  
- Queue-based retry system  
- Forward document & audio support  
