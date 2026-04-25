# Sử dụng Python 3.10 làm base image
FROM python:3.10-slim

# Thiết lập thư mục làm việc trong container
WORKDIR /app

# Thiết lập biến môi trường
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Cài đặt các gói phụ thuộc
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y sqlite3 && rm -rf /var/lib/apt/lists/*

# Sao chép mã nguồn vào container
COPY . .

# Tạo thư mục data và đảm bảo quyền ghi
RUN mkdir -p /app/data && chmod 777 /app/data

# Chạy script tạo từ điển khi build image
RUN python -m scripts.create_dictionary

# Thêm script khởi tạo database
COPY scripts/init_database.sh /app/scripts/
RUN sed -i 's/\r$//' /app/scripts/init_database.sh && chmod +x /app/scripts/init_database.sh

# Mở cổng cho FastAPI
EXPOSE 8800

# Khởi động ứng dụng
CMD ["/bin/bash", "-c", "bash /app/scripts/init_database.sh && python main.py"]
