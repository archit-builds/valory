import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "valory")

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_EMBEDDING_MODEL: str = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")

    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

    EMBEDDING_AUTO_MERGE_THRESHOLD: float = float(os.getenv("EMBEDDING_AUTO_MERGE_THRESHOLD", "0.88"))
    EMBEDDING_AMBIGUOUS_FLOOR: float = float(os.getenv("EMBEDDING_AMBIGUOUS_FLOOR", "0.75"))

    VALID_RELATION_TYPES = {
        "brand", "training", "association", "ambassador", "endorsement", "coaching",
    }


settings = Settings()
