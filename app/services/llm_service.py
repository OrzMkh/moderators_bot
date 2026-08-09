import asyncio
import structlog
from google import genai

from app.config import settings

logger = structlog.get_logger()

ANSWER_SYSTEM_PROMPT = """
Ты — вежливый, профессиональный старший оператор поддержки курьеров логистики, доставки еды и аренды велосипедов в Узбекистане.

Инструкция:
1. Подготовь лаконичный, чёткий и максимально полезный ответ курьеру.
2. Язык ответа: {language} (если 'uz_cyr' — узбекская кириллица, если 'uz_lat' — узбекская латиница, если 'ru' — русский).
3. Используй дружелюбный тон, учитывай контекст курьерской работы (слоты, заказы, Flit and Go, велосипеды, геопозиция).
4. Максимальная длина ответа — 3-4 предложения.
"""


class LLMAnswerService:
    def __init__(self, gemini_client: genai.Client) -> None:
        self._client = gemini_client

    async def generate_draft_answer(
        self,
        question: str,
        language: str = "ru",
        rag_context: str | None = None,
    ) -> str:
        """Generates draft answer using google.genai SDK (non-blocking thread)."""
        sys_prompt = ANSWER_SYSTEM_PROMPT.format(language=language)
        if rag_context:
            sys_prompt += f"\n\nКонтекст из базы знаний:\n{rag_context}"

        try:
            def _call_api():
                return self._client.models.generate_content(
                    model=settings.gemini_model_chat,
                    contents=f"{sys_prompt}\n\nВопрос курьера: {question}",
                )

            response = await asyncio.to_thread(_call_api)
            return response.text or "Спасибо за обращение! Оператор скоро ответит вам."
        except Exception as e:
            logger.error("Gemini draft generation failed", error=str(e), question=question[:50])
            return "Спасибо за вопрос! Передаю оператору поддержки."
