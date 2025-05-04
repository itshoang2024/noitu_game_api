from fastapi import APIRouter
from app.api.routes import core, game, word, dictionary, system

# Export tất cả routers
core_router = core.router
game_router = game.router
word_router = word.router
dictionary_router = dictionary.router
system_router = system.router