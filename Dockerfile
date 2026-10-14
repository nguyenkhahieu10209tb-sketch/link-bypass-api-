# Sử dụng Python 3.10 mỏng nhẹ
FROM python:3.10-slim

# Thiết lập thư mục làm việc
WORKDIR /app

# Cài đặt các gói hệ thống cần thiết cho trình duyệt (đã sửa lỗi libext6)
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    gnupg \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Sao chép và cài đặt các thư viện Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Nếu dùng Playwright, tải trình duyệt đi kèm
RUN playwright install chromium || true

# Sao chép toàn bộ mã nguồn vào container
COPY . .

# Khai báo cổng chạy (khớp với ứng dụng app.py)
EXPOSE 8080

# Lệnh khởi chạy ứng dụng
CMD ["python", "app.py"]
