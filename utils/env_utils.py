from dotenv import load_dotenv
import os

load_dotenv(override=True)

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

MILVUS_URI = "http://43.143.166.242:19530"
COLLECTION_NAME = "t_collection01"