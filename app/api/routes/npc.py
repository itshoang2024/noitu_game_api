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
    prompt = f"""Bối cảnh NPC: {background}.
    NPC đang tham gia một lễ hội nhân dịp Ngày Thống nhất tại Việt Nam. Lễ hội có thể náo nhiệt hoặc có những khoảnh khắc trầm lắng. 
    Hãy tạo 1-2 câu ngắn, tự nhiên thể hiện suy nghĩ hoặc cảm xúc hiện tại của NPC về tình huống sau: {random.choice(prompts)}.
    Cảm xúc có thể vui vẻ, hồi hộp, lạ lẫm, bối rối, xúc động, hoặc bất kỳ phản ứng người thật nào phù hợp. 
    Mỗi câu cách nhau bằng dấu xuống dòng '\n', không có 2 '\n' liền nhau."""
    ai_service = AIService.get_instance()
    reply = await ai_service.generate_normal_response(prompt)
    logger.info(f"{reply}")

    return NPCIntroResponse(
        reply=reply,
        status="success"
    )