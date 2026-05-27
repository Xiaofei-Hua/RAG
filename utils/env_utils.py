from dotenv import load_dotenv
import os

load_dotenv(override=True)

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "ollama")
# TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

MILVUS_URI = "./milvus_data.db"
COLLECTION_NAME = "t_collection01"