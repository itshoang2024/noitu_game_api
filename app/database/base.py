from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.utils.constants import DATA_DIR
import os

# Đảm bảo thư mục data tồn tại
os.makedirs(DATA_DIR, exist_ok=True)

# Đường dẫn tới database SQLite
DATABASE_URL = f"sqlite:///{os.path.join(DATA_DIR, 'noitu_game.db')}"
ASYNC_DATABASE_URL = f"sqlite+aiosqlite:///{os.path.join(DATA_DIR, 'noitu_game.db')}"

# Tạo engine
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
async_engine = create_async_engine(ASYNC_DATABASE_URL)

# Tạo session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
AsyncSessionLocal = sessionmaker(class_=AsyncSession, autocommit=False, autoflush=False, bind=async_engine)

# Base model
Base = declarative_base()

# Hàm để lấy database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Hàm để lấy async database session
async def get_async_db():
    async with AsyncSessionLocal() as db:
        yield db