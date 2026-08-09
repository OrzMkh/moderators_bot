import structlog
from openai import AsyncOpenAI

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
    def __init__(self, gemini_client: any = None) -> None:
        self._openai_client = AsyncOpenAI(
            api_key=settings.gemini_api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )

    async def generate_draft_answer(
        self,
        question: str,
        language: str = "ru",
        rag_context: str | None = None,
    ) -> str:
        """Generates draft answer using OpenAI compatible Gemini endpoint."""
        sys_prompt = ANSWER_SYSTEM_PROMPT.format(language=language)
        if rag_context:
            sys_prompt += f"\n\nКонтекст из базы знаний:\n{rag_context}"

        try:
            response = await self._openai_client.chat.completions.create(
                model=settings.gemini_model_chat,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"Вопрос курьера: {question}"},
                ],
            )
            return response.choices[0].message.content or "Спасибо за обращение! Оператор скоро ответит вам."
        except Exception as e:
            logger.error("Gemini draft generation failed", error=str(e), question=question[:50])
            return "Спасибо за вопрос! Передаю оператору поддержки."
