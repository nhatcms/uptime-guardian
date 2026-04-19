# Hướng Dẫn Chạy Dự Án Uptime Guardian

Tài liệu này hướng dẫn từng bước để chạy dự án và truy cập giao diện web (dashboard)
trên trình duyệt. Có hai cách: chạy bằng **Docker Compose** (nhanh, ít cài đặt) hoặc
chạy **thủ công** (backend + frontend riêng).

## 1. Yêu cầu cài đặt

- Python 3.11 trở lên.
- Node.js 20+ và [pnpm](https://pnpm.io/).
- Một Telegram bot và chat ID (để nhận cảnh báo).
- Tùy chọn: Docker và Docker Compose nếu chạy bằng container.

## 2. Chuẩn bị cấu hình (.env)

Sao chép file mẫu ở thư mục gốc và điền giá trị của bạn:

```bash
cp .env.example .env
```

Các biến quan trọng cần điền:

| Biến                     | Bắt buộc | Mặc định                 | Mô tả                                        |
| ------------------------ | -------- | ------------------------ | -------------------------------------------- |
| `DATABASE_URL`           | không    | `sqlite:///./uptime.db`  | Đường dẫn cơ sở dữ liệu SQLAlchemy.          |
| `TELEGRAM_BOT_TOKEN`     | **có**   | —                        | Token bot lấy từ BotFather.                  |
| `TELEGRAM_CHAT_ID`       | **có**   | —                        | Chat ID nhận cảnh báo.                       |
| `CHECK_INTERVAL_MINUTES` | không    | `5`                      | Chu kỳ kiểm tra mặc định (phút).             |
| `ALERT_COOLDOWN_MINUTES` | không    | `10`                     | Khoảng cách tối thiểu giữa các cảnh báo.     |
| `AUTH_SECRET_KEY`        | **có**   | —                        | Chuỗi bí mật để ký token đăng nhập.          |

> Lưu ý: Backend sẽ không khởi động nếu thiếu các biến bắt buộc.

### Lấy Telegram bot token và chat ID

1. Mở chat với [@BotFather](https://t.me/BotFather), gửi `/newbot` và làm theo hướng dẫn.
2. BotFather trả về **bot token** dạng `123456789:ABC-DEF...` → đây là `TELEGRAM_BOT_TOKEN`.
3. Gửi một tin nhắn bất kỳ tới bot, sau đó mở
   `https://api.telegram.org/bot<TOKEN>/getUpdates` và tìm `"chat":{"id":...}` →
   đó là `TELEGRAM_CHAT_ID`. (Hoặc nhắn [@userinfobot](https://t.me/userinfobot).)

## 3. Cách A — Chạy bằng Docker Compose (khuyến nghị)

Ở thư mục gốc dự án:

```bash
cp .env.example .env        # điền Telegram + AUTH_SECRET_KEY
docker compose up --build
```

Sau khi build xong, mở trình duyệt:

- **Giao diện web (dashboard):** http://localhost:3000
- **API backend:** http://localhost:8000 (tài liệu API: http://localhost:8000/docs)

Đăng nhập bằng tài khoản mặc định: **admin / admin** (đổi mật khẩu sau khi đăng nhập).

Dừng dự án: nhấn `Ctrl+C`, hoặc chạy `docker compose down`.
Xóa luôn dữ liệu đã lưu: `docker compose down -v`.

## 4. Cách B — Chạy thủ công

### 4.1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

> Backend nạp file `.env` từ thư mục làm việc. Hãy chạy từ thư mục có `.env`
> hoặc copy `.env` vào thư mục `backend/`.

Lần chạy đầu tiên backend sẽ tự tạo cơ sở dữ liệu SQLite, thêm 2 monitor ví dụ
(Google, GitHub) và tài khoản `admin` / `admin`, rồi khởi động bộ lập lịch.

- API: http://localhost:8000
- Tài liệu API: http://localhost:8000/docs

### 4.2. Frontend

Mở một cửa sổ terminal khác:

```bash
cd frontend
cp .env.example .env             # đặt VITE_API_BASE_URL=http://localhost:8000
pnpm install
pnpm dev
```

Mở trình duyệt tại **http://localhost:5173** và đăng nhập bằng `admin` / `admin`.

## 5. Thêm monitor đầu tiên trên web

1. Mở dashboard và đăng nhập.
2. Bấm nút **+** (góc dưới bên phải) để mở form thêm monitor.
3. Nhập **tên**, **URL** đầy đủ (ví dụ `https://example.com`) và chọn **chu kỳ kiểm tra**
   (5, 10, 15 hoặc 30 phút).
4. Bấm lưu. Monitor xuất hiện trên dashboard và được kiểm tra tự động. Dùng
   **Check Now** trong trang chi tiết để kiểm tra ngay lập tức.

## 6. Bảng tóm tắt địa chỉ truy cập

| Thành phần        | Docker Compose          | Chạy thủ công             |
| ----------------- | ----------------------- | ------------------------- |
| Dashboard (web)   | http://localhost:3000   | http://localhost:5173     |
| API backend       | http://localhost:8000   | http://localhost:8000     |
| Tài liệu API      | http://localhost:8000/docs | http://localhost:8000/docs |

## 7. Xử lý sự cố thường gặp

- **Backend không khởi động:** kiểm tra đã điền đủ `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID`, `AUTH_SECRET_KEY` trong `.env` chưa.
- **Web không gọi được API:** kiểm tra `VITE_API_BASE_URL` trong `frontend/.env`
  trỏ đúng địa chỉ backend.
- **Không nhận được cảnh báo Telegram:** xác nhận token và chat ID đúng, và bạn
  đã gửi tin nhắn cho bot ít nhất một lần.
