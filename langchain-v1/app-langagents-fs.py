import datetime
import os

from deepagents.backends import FilesystemBackend
from deepagents import create_deep_agent
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

# load environment variables
load_dotenv()

# config LLM
key = os.getenv("OPENAI_API_KEY")
if not key:
    raise RuntimeError("Missing OPENAI_API_KEY in .env")

openai_api_key = SecretStr(key).get_secret_value()

llm = ChatOpenAI(
    model="gpt-4o-mini", 
    openai_api_key=openai_api_key
)

# 创建 DeepAgent，给它配置后端能力：访问本地文件系统
deep_agent = create_deep_agent(
    llm,
    backend=FilesystemBackend(
        root_dir="./articles"
    )
)

# 用户询问：列出一个目录下所有文件
response = deep_agent.invoke({
    "messages": [
        {
            "role": "user",
            "content": "列出 ./articles 目录下所有文件的名称。"
        }
    ]
})

# 打印输出
for message in response["messages"]:
    print(message)
    print("================")