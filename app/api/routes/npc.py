from fastapi import APIRouter, HTTPException
from app.services.ai_service import AIService
from app.models.schemas import NPCIntroResponse, NPCIntroRequest
import random

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/npc", tags=["npc"])

@router.post("/npc_intro", response_model=NPCIntroResponse)
async def generate_npc_intro(data: NPCIntroRequest):
    """Trả về một câu thoại ngắn hoặc câu trò chuyện từ AI dựa trên mô tả NPC"""
    background = data.npc_background
    logger.info(f"{background}")

    if not background:
        raise HTTPException(status_code=400, detail="Thiếu mô tả npc_background")

    prompts = [
    "Hôm nay vui không?",
    "Bạn thấy lễ hội thế nào?",
    "Món ăn nào bạn thích nhất?",
    "Bạn vừa làm gì ở lễ hội?",
    "Bạn đến đây cùng ai vậy?",
    "Bạn có hay đi lễ hội không?",
    "Bạn thấy đông người quá không?",
    "Có trò chơi nào bạn muốn thử không?"
]
    # Get the casual conversational reply from the AI model
    prompt = f"Bối cảnh NPC: {background}.NPC đang tham gia một lễ hội vui tươi nhân dịp Ngày Thống nhất tại Việt Nam. Hãy tạo 1-2 câu ngắn, tự nhiên thể hiện suy nghĩ hoặc cảm xúc hiện tại của NPC. Có thể lồng ghép một chút bối cảnh văn hóa địa phương nếu phù hợp. Mỗi câu cách nhau bằng dấu xuống dòng '\n', không có 2 '\n' liền nhau . {random.choice(prompts)}"
    ai_service = AIService.get_instance()
    reply = await ai_service.generate_normal_response(prompt)
    logger.info(f"{reply}")

    return NPCIntroResponse(
        reply=reply,
        status="success"
    )