import asyncio
import structlog
from google import genai
from pydantic import BaseModel, Field

from app.config import settings

logger = structlog.get_logger()

INTENT_SYSTEM_PROMPT = """
Ты — AI-классификатор сообщений из Telegram-чата курьеров доставки еды, логистики и аренды велосипедов в Узбекистане.
Классифицируй сообщение пользователя на одну из категорий:
1. 'work_question' — рабочий вопрос по доставке, заказам, слотам, оплате, аренде байка, штрафам, поддержке.
2. 'flood' — бытовой флуд курьеров между собой (приветствия, шутки, личное общение, мемчики, не относящиеся к поддержке).
3. 'mention' — прямая просьба помочь или обращение к боту/админам.

Отвечай строго в формате JSON со следующими полями:
- "intent": одно из ["work_question", "flood", "mention"]
- "confidence": число от 0.0 до 1.0
- "reasoning": краткое объяснение (1 предложение)
"""


class IntentResult(BaseModel):
    intent: str = Field(pattern="^(work_question|flood|mention)$")
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(max_length=256)


class IntentClassifierService:
    def __init__(self, gemini_client: genai.Client) -> None:
        self._client = gemini_client

    async def classify(self, text: str) -> IntentResult:
        """Classifies courier message using google.genai SDK (non-blocking thread)."""
        try:
            def _call_api():
                return self._client.models.generate_content(
                    model=settings.gemini_model_intent,
                    contents=f"{INTENT_SYSTEM_PROMPT}\n\nСообщение: {text}",
                    config={"response_mime_type": "application/json"},
                )

            response = await asyncio.to_thread(_call_api)
            raw_content = response.text or "{}"
            return IntentResult.model_validate_json(raw_content)
        except Exception as e:
            logger.error("Intent classification failed", error=str(e), text=text[:50])
            return IntentResult(
                intent="work_question",
                confidence=0.5,
                reasoning="Fallback due to classification service error",
            )
