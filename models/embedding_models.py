from langchain_openai import OpenAIEmbeddings
from utils.env_utils import OPENAI_BASE_URL, OPENAI_API_KEY
from langchain_huggingface import HuggingFaceEmbeddings  

openai_embeddings = OpenAIEmbeddings(
    openai_api_key=OPENAI_API_KEY,
    openai_api_base=OPENAI_BASE_URL,
)

local_model_path = "/home/ubuntu/LocalModels/bge-small-zh-v1.5"
model_kwargs = {
    "device": "cpu",
}
encode_kwargs = {
    "normalize_embeddings": True,
    "batch_size": 8,
}
bge_embedding = HuggingFaceEmbeddings(
    model_name=local_model_path,
    model_kwargs=model_kwargs,
    encode_kwargs=encode_kwargs,
)

if __name__ == "__main__":
    text = "这是一个本地部署的测试文本"
    vector = bge_embedding.embed_query(text)
    print(f"向量维度: {len(vector)}")