"""Скрипт для заполнения базы знаний Qdrant первичными FAQ для курьеров Узбекистана."""
import asyncio
from google import genai

from app.config import settings
from app.services.rlhf_service import RLHFService
from app.vector.qdrant_client import init_qdrant_collections, qdrant_client

INITIAL_FAQS = [
    {
        "question": "Как поменять слот или отменить смену?",
        "answer": "Отменить слот можно в приложении не позднее чем за 2 часа до начала смены в разделе 'Мои Слоты'. При опоздании обратитесь к куратору.",
        "language": "ru",
        "service_type": "food_delivery",
    },
    {
        "question": "Flit and Go велосипед пробит или сломался, что делать?",
        "answer": "Снимите фото поломки, зафиксируйте геопозицию велосипеда и нажмите 'Авария/Ремонт' в приложении Flit and Go. Замена байка доступна на ближайшей точке сервиса.",
        "language": "ru",
        "service_type": "bike_rental",
    },
    {
        "question": "Когда выплата за доставку?",
        "answer": "Выплаты курьерам производятся каждый вторник на карту Uzcard/Humo за предыдущую рабочую неделю.",
        "language": "ru",
        "service_type": "logistics",
    },
    {
        "question": "Smena vaqtini qanday o'zgartirish mumkin?",
        "answer": "Smenani bekor qilish uchun ilovaning 'Mening smenalarim' bo'limida smena boshlanishidan kamida 2 soat oldin bekor tugmasini bosing.",
        "language": "uz_lat",
        "service_type": "food_delivery",
    },
]


async def seed() -> None:
    print("Seeding initial FAQs to Qdrant KB via Google GenAI SDK...")
    await init_qdrant_collections()

    genai_client = genai.Client(api_key=settings.gemini_api_key)
    rlhf_service = RLHFService(genai_client, qdrant_client)

    for item in INITIAL_FAQS:
        point_id = await rlhf_service.add_approved_knowledge(
            question=item["question"],
            answer=item["answer"],
            language=item["language"],
            service_type=item["service_type"],
        )
        print(f"Added FAQ entry: '{item['question']}' -> Point ID: {point_id}")

    await qdrant_client.close()
    print("Seeding completed successfully!")


if __name__ == "__main__":
    asyncio.run(seed())
