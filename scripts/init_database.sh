#!/bin/bash
set -e

echo "Initializing database..."

# Chạy migration Alembic
alembic upgrade head

# Kiểm tra nếu database đã có dữ liệu
DB_FILE="/app/data/noitu_game.db"
if [ -f "$DB_FILE" ]; then
    echo "Database file already exists. Checking if it has content..."
    WORD_COUNT=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM words;")
    
    if [ "$WORD_COUNT" -gt 10 ]; then
        echo "Database already has $WORD_COUNT words. Skipping dictionary creation."
        exit 0
    fi
fi

# Chạy script tạo từ điển
echo "Populating database with initial dictionary..."
python -m scripts.create_dictionary

echo "Database initialization completed."