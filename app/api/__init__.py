from fastapi import APIRouter
from app.api.routes import core_router, game_router, word_router, dictionary_router, system_router, database_router, npc_router

# Tạo router chính và thêm tất cả router con
router = APIRouter()
router.include_router(core_router)
router.include_router(game_router)
router.include_router(word_router)
router.include_router(dictionary_router)
router.include_router(system_router)
router.include_router(database_router) 
router.include_router(npc_router)
