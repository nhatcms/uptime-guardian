# Hướng Dẫn Chạy Dự Án NCMS Monitor (Uptime Guardian)

NCMS Monitor là nền tảng giám sát website **đa người dùng (multi-tenant)**: mỗi
người dùng sở hữu các monitor riêng, nhận cảnh báo Telegram riêng và đăng ký một
**gói dịch vụ** (Free / Pro / Enterprise) quy định số lượng monitor, chu kỳ kiểm
tra và việc bật giám sát chứng chỉ SSL. Hệ thống đi kèm trang giới thiệu (landing
page), đăng ký/đăng nhập có chống bot (Cloudflare Turnstile), dashboard tự phục
vụ, nâng cấp gói trả phí qua **SePay** (QR chuyển khoản ngân hàng) và một trang
quản trị (admin console).

Tài liệu này hướng dẫn từng bước để chạy dự án và mở giao diện web. Có hai cách:
chạy bằng **Docker Compose** (nhanh, ít cài đặt) hoặc chạy **thủ công** (backend
+ frontend riêng).

## 1. Yêu cầu cài đặt

- Python 3.11 trở lên.
- Node.js 20+ và [pnpm](https://pnpm.io/) (`corepack enable` rồi
  `corepack prepare pnpm@9.15.4 --activate`).
- Một Telegram bot token và chat ID (để nhận cảnh báo).
- Tùy chọn: Docker và Docker Compose nếu chạy bằng container.
- Tùy chọn: site/secret key của Cloudflare Turnstile và thông tin SePay (cả hai
  đều có chế độ dev mặc định an toàn — có thể chạy toàn bộ giao diện mà không cần).

## 2. Chuẩn bị cấu hình (.env)

Sao chép file mẫu ở thư mục gốc và điền giá trị của bạn:

```bash
cp .env.example .env
```

### 2.1. Biến bắt buộc

Backend sẽ **không khởi động** nếu thiếu một trong các biến sau:

| Biến                 | Mô tả                                                                 |
| -------------------- | --------------------------------------------------------------------- |
| `TELEGRAM_BOT_TOKEN` | Token bot lấy từ BotFather (dùng để gửi cảnh báo).                     |
| `TELEGRAM_CHAT_ID`   | Chat ID toàn cục (legacy); được gán cho tài khoản admin khi migrate. Chat ID của từng người dùng đặt trong dashboard. |
| `AUTH_SECRET_KEY`    | Chuỗi bí mật để ký token đăng nhập — hãy dùng chuỗi ngẫu nhiên dài.    |

### 2.2. Biến tùy chọn thường dùng

| Biến                     | Mặc định                                       | Mô tả                                              |
| ------------------------ | ---------------------------------------------- | -------------------------------------------------- |
| `DATABASE_URL`           | `sqlite:///./uptime.db`                        | Đường dẫn cơ sở dữ liệu SQLAlchemy.                |
| `CHECK_INTERVAL_MINUTES` | `5`                                            | Chu kỳ kiểm tra mặc định (phút).                   |
| `ALERT_COOLDOWN_MINUTES` | `10`                                           | Khoảng cách tối thiểu giữa các cảnh báo (phút).    |
| `CORS_ALLOW_ORIGINS`     | `http://localhost:5173,http://localhost:3000`  | Origin trình duyệt được phép gọi API (ngăn cách bằng dấu phẩy, hoặc `*`). |
| `FREE_PLAN_NAME`         | `Free`                                         | Tên gói miễn phí được tạo sẵn trong lần chạy đầu.  |

### 2.3. Cloudflare Turnstile (chống bot khi đăng ký/đăng nhập)

| Biến                   | Mặc định                  | Mô tả                                                         |
| ---------------------- | ------------------------- | ------------------------------------------------------------- |
| `TURNSTILE_SECRET_KEY` | *(trống)*                 | Để trống = **chế độ dev**: mọi token khác rỗng đều được chấp nhận. |
| `TURNSTILE_VERIFY_URL` | URL siteverify Cloudflare | Chỉ ghi đè khi cần.                                           |

Ở chế độ dev, form đăng nhập/đăng ký hiển thị nút **"Complete bot challenge
(dev)"** thay cho widget thật — bấm nút này để tạo token rồi gửi form. Khi triển
khai thật, đặt `TURNSTILE_SECRET_KEY` ở backend và `VITE_TURNSTILE_SITE_KEY` ở
frontend.

### 2.4. SePay (chỉ cần khi muốn nâng cấp gói trả phí)

| Biến                   | Mô tả                                                                |
| ---------------------- | -------------------------------------------------------------------- |
| `SEPAY_API_KEY`        | API key SePay gửi kèm webhook (`Authorization: Apikey <key>`).       |
| `SEPAY_WEBHOOK_SECRET` | Khóa chia sẻ cho chế độ xác thực webhook HMAC-SHA256 (tùy chọn).     |
| `SEPAY_BANK_CODE`      | Mã ngân hàng nhận tiền, mã hóa vào QR (ví dụ `MBBank`).              |
| `SEPAY_ACCOUNT_NUMBER` | Số tài khoản nhận tiền cho QR.                                       |
| `SEPAY_QR_BASE_URL`    | URL ảnh QR của SePay (mặc định `https://qr.sepay.vn/img`).          |

Nếu không đặt cả `SEPAY_API_KEY` lẫn `SEPAY_WEBHOOK_SECRET`, việc xác thực chữ ký
webhook bị tắt (chỉ dùng cho dev). **Không bao giờ commit khóa bí mật thật** —
giữ chúng trong `.env` (đã được .gitignore).

### Lấy Telegram bot token và chat ID

1. Mở chat với [@BotFather](https://t.me/BotFather), gửi `/newbot` và làm theo hướng dẫn.
2. BotFather trả về **bot token** dạng `123456789:ABC-DEF...` → đây là `TELEGRAM_BOT_TOKEN`.
3. Gửi một tin nhắn bất kỳ tới bot, sau đó mở
   `https://api.telegram.org/bot<TOKEN>/getUpdates` và tìm `"chat":{"id":...}` →
   đó là chat ID. (Hoặc nhắn [@userinfobot](https://t.me/userinfobot).)

> Mỗi người dùng đặt chat ID riêng trong **Dashboard → Settings** để nhận cảnh báo
> cho monitor của mình.

## 3. Cách A — Chạy bằng Docker Compose (khuyến nghị)

Ở thư mục gốc dự án:

```bash
cp .env.example .env        # điền Telegram + AUTH_SECRET_KEY
docker compose up --build
```

Sau khi build xong, mở trình duyệt:

- **Giao diện web (dashboard):** http://localhost:3000
- **API backend:** http://localhost:8000 (tài liệu API: http://localhost:8000/docs)

Đăng nhập bằng tài khoản admin mặc định: **admin / admin** (đổi mật khẩu sau khi
đăng nhập), hoặc bấm **Get started free** trên landing page để đăng ký tài khoản mới.

> URL backend của frontend được "nướng" vào lúc build qua build-arg
> `VITE_API_BASE_URL` (mặc định `http://localhost:8000`). Nếu deploy backend ở nơi
> khác, sửa arg này trong `docker-compose.yml` rồi build lại.

Dừng dự án: nhấn `Ctrl+C`, hoặc chạy `docker compose down`.
Xóa luôn dữ liệu đã lưu: `docker compose down -v`.

> Truy cập qua LAN bằng địa chỉ IP? Đặt `CORS_ALLOW_ORIGINS=*` (hoặc origin cụ thể)
> trong `.env`, và trỏ `VITE_API_BASE_URL` tới địa chỉ backend có thể truy cập được.

## 4. Cách B — Chạy thủ công

### 4.1. Backend (API + bộ lập lịch) — cổng 8000

```bash
cd backend
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env .                       # backend đọc .env từ thư mục làm việc của nó
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Lần chạy đầu tiên backend sẽ:

- tạo schema cơ sở dữ liệu SQLite,
- chạy migration đa người dùng một lần (idempotent),
- tạo sẵn gói **Free** và tài khoản admin mặc định **admin / admin**,
- thêm 2 monitor ví dụ rồi khởi động bộ lập lịch.

Kiểm tra backend đã chạy: mở **http://localhost:8000/docs** (tài liệu API tương
tác) hoặc **http://localhost:8000/api/plans** (danh sách gói công khai).

### 4.2. Frontend (giao diện web) — cổng 5173

Mở một cửa sổ terminal khác:

```bash
cd frontend
cp .env.example .env             # đặt VITE_API_BASE_URL=http://localhost:8000
pnpm install
pnpm dev
```

Mở trình duyệt tại **http://localhost:5173**.

Các biến frontend (`frontend/.env`):

| Biến                      | Mặc định                | Mô tả                                       |
| ------------------------- | ----------------------- | ------------------------------------------- |
| `VITE_API_BASE_URL`       | `http://localhost:8000` | URL backend mà trình duyệt gọi tới.         |
| `VITE_TURNSTILE_SITE_KEY` | *(trống)*               | Site key Cloudflare; để trống = nút dev.    |

## 5. Truy cập giao diện web

| Trang               | URL (chạy thủ công)              | Đối tượng                       |
| ------------------- | -------------------------------- | ------------------------------- |
| Landing / bảng giá  | `http://localhost:5173/`         | Công khai                       |
| Đăng ký             | `http://localhost:5173/register` | Công khai                       |
| Đăng nhập           | `http://localhost:5173/login`    | Công khai                       |
| Dashboard           | `http://localhost:5173/dashboard`| Người dùng đã đăng nhập         |
| Trang quản trị      | `http://localhost:5173/admin`    | Chỉ admin (`is_admin`)          |

### Các bước đầu tiên trên giao diện

1. **Landing page** (`/`) hiển thị bảng giá lấy trực tiếp từ cơ sở dữ liệu. Bấm
   **Get started free** để sang trang đăng ký.
2. **Đăng ký** (`/register`): nhập username, email, mật khẩu, hoàn tất thử thách
   bot (nút dev ở chế độ dev) rồi gửi. Tài khoản mới bắt đầu ở gói **Free**.
3. **Đăng nhập** (`/login`): hoàn tất thử thách bot trước rồi đăng nhập. Dùng
   `admin` / `admin` cho tài khoản admin tạo sẵn.
4. **Dashboard** (`/dashboard`):
   - Thêm monitor bằng nút **+** nổi (giới hạn theo gói của bạn).
   - Mở **Settings** để xem giới hạn gói, mức sử dụng ("đã dùng / tổng"), đặt
     **Telegram chat ID** (để cảnh báo gửi tới bạn) và **nâng cấp** gói trả phí
     (hiển thị mã QR SePay).
   - Admin thấy thêm liên kết **Admin** tới trang quản trị.
5. **Trang quản trị** (`/admin`, chỉ admin): tạo/sửa/xóa gói, xem toàn bộ người
   dùng và xem các giao dịch thanh toán.

## 6. Bảng tóm tắt địa chỉ truy cập

| Thành phần        | Docker Compose             | Chạy thủ công              |
| ----------------- | -------------------------- | -------------------------- |
| Dashboard (web)   | http://localhost:3000      | http://localhost:5173      |
| API backend       | http://localhost:8000      | http://localhost:8000      |
| Tài liệu API      | http://localhost:8000/docs | http://localhost:8000/docs |

## 7. Webhook thanh toán SePay (tùy chọn)

Để tự động nâng cấp gói trả phí, cấu hình SePay POST xác nhận thanh toán tới:

```
POST http://<địa-chỉ-backend>:8000/api/payments/sepay-webhook
```

Đây là endpoint duy nhất không cần token đăng nhập; nó được bảo vệ bằng chữ ký
`SEPAY_API_KEY` (hoặc HMAC `SEPAY_WEBHOOK_SECRET`) và đối chiếu số tiền nghiêm
ngặt. Endpoint này phải truy cập được từ internet công khai cho thanh toán thật.

## 8. Chạy kiểm thử (tests)

```bash
# Backend (trong thư mục backend/, đã kích hoạt venv)
python -m pytest

# Frontend (trong thư mục frontend/)
pnpm test
```

## 9. Xử lý sự cố thường gặp

- **Backend không khởi động / "Missing required configuration value(s)":** kiểm
  tra đã điền đủ `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `AUTH_SECRET_KEY` trong
  `.env` chưa, và backend có thấy file `.env` không (copy vào `backend/` hoặc chạy
  uvicorn từ thư mục chứa `.env`).
- **Nút đăng nhập/đăng ký không phản hồi:** bạn phải hoàn tất thử thách bot trước
  (ở chế độ dev, bấm nút "Complete bot challenge (dev)").
- **Lỗi CORS trên console trình duyệt:** thêm origin frontend vào
  `CORS_ALLOW_ORIGINS` (hoặc dùng `*`) rồi khởi động lại backend.
- **Web không gọi được API:** kiểm tra `VITE_API_BASE_URL` trong `frontend/.env`
  trỏ đúng địa chỉ backend, và khởi động lại `pnpm dev` sau khi sửa.
- **Không nhận được cảnh báo Telegram:** đặt **Telegram chat ID** của bạn trong
  Dashboard → Settings; một monitor phải chuyển từ up → down (và tôn trọng
  cooldown) thì cảnh báo mới được gửi.
```