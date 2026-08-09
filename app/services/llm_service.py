import structlog
from openai import AsyncOpenAI

from app.config import settings

logger = structlog.get_logger()

# Phrases that indicate Gemini couldn't answer properly
FALLBACK_PHRASES = [
    "передаю оператору",
    "скоро ответит",
    "не могу ответить",
    "уточните у",
    "обратитесь к",
    "не знаю",
]

ANSWER_SYSTEM_PROMPT = """
Ты — вежливый, профессиональный старший оператор поддержки курьеров логистики, доставки еды и аренды велосипедов в Узбекистане.

Инструкция:
1. Подготовь лаконичный, чёткий и максимально полезный ответ курьеру.
2. Язык ответа: {language} (если 'uz_cyr' — узбекская кириллица, если 'uz_lat' — узбекская латиница, если 'ru' — русский).
3. Используй дружелюбный тон, учитывай контекст курьерской работы (слоты, заказы, Flit and Go, велосипеды, геопозиция).
4. Максимальная длина ответа — 3-4 предложения.
5. ВАЖНО: Если ты точно НЕ ЗНАЕШЬ ответ — верни строго одно слово: ESCALATE
   Не придумывай ответы. Лучше честно вернуть ESCALATE.
"""


class LLMAnswerService:
    def __init__(self, gemini_client: any = None) -> None:
        self._openai_client = AsyncOpenAI(
            api_key=settings.gemini_api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )

    async def generate_answer(
        self,
        question: str,
        language: str = "ru",
        rag_context: str | None = None,
    ) -> tuple[str, bool]:
        """
        Generates answer using Gemini.

        Returns:
            (answer_text, should_escalate):
                - should_escalate=False -> send directly to courier
                - should_escalate=True  -> send to moderator for review
        """
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
            raw = (response.choices[0].message.content or "").strip()
            logger.info("Gemini response", raw=raw[:80])

            # Check if Gemini explicitly escalated
            if raw.upper().startswith("ESCALATE") or not raw:
                return raw, True

            # Check for fallback phrases
            low = raw.lower()
            for phrase in FALLBACK_PHRASES:
                if phrase in low:
                    return raw, True

            return raw, False

        except Exception as e:
            logger.error("Gemini answer generation failed", error=str(e), question=question[:50])
            return "Спасибо за вопрос! Передаю оператору поддержки.", True

    # Keep backward compatibility alias
    async def generate_draft_answer(
        self,
        question: str,
        language: str = "ru",
        rag_context: str | None = None,
    ) -> str:
        answer, _ = await self.generate_answer(question, language, rag_context)
        return answer
