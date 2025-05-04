## Cài đặt và Cấu hình Database

1. Cài đặt các thư viện cần thiết:
    ```
    pip install -r requirements.txt
    ```

2. Khởi tạo cấu trúc database:
    ```
    alembic upgrade head
    ```

3. Để tạo từ điển ban đầu trong database:
    ```
    python -m scripts.create_dictionary
    ```

4. Khởi động server:
    ```
    python main.py
    ```
