# app.py
import os
from pydantic import SecretStr
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

load_dotenv()

key = os.getenv("OPENAI_API_KEY")
if not key:
    raise RuntimeError("Missing OPENAI_API_KEY in .env")

openai_api_key = SecretStr(key).get_secret_value()


# 初始化 LLM 客户端
llm = ChatOpenAI(
    model="gpt-4o-mini", 
    openai_api_key=openai_api_key
)

print("----- LLM Mode-----")

print(llm.invoke("Who are you?").content)

print("----- Agent Mode-----")

agent = create_agent(
    llm,
    system_prompt="You are a helpful assistant that translates English to Chinese.",
)

print(
    agent.invoke(
        {"messages": [{"role": "user", "content": "Who are you?"}]}
    )["messages"]
)

