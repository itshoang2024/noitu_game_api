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

# Sao chép mã nguồn vào container
COPY . .

# Chạy script tạo từ điển khi build image
RUN python -m scripts.create_dictionary

# Mở cổng cho FastAPI
EXPOSE 8800

# Khởi động ứng dụng
CMD ["python", "main.py"]