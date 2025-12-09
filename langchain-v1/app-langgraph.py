import os
from typing import TypedDict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from pydantic import SecretStr
from typing_extensions import NotRequired

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

# define state
class State(TypedDict):
    author: NotRequired[str]
    joke: NotRequired[str]

# define node 1: select author
def author_node(state: State):
    prompt = """
帮我推荐一位受人们欢迎的作家，只需要给出作家的名字即可。
"""
    author = llm.invoke(prompt)
    return {"author": author.content}

# define node 2: generate joke
def joke_node(state: State):
    prompt = f"""
用作家：{state['author']} 的风格，写一个100字以内的笑话
"""
    joke = llm.invoke(prompt)
    return {"joke": joke.content}

# build graph
builder = StateGraph(State)
builder.add_node(author_node)
builder.add_node(joke_node)

builder.add_edge(START, "author_node")
builder.add_edge("author_node", "joke_node")
builder.add_edge("joke_node", END)

# checkpoint manager
checkpointer = InMemorySaver()

# compile
graph = builder.compile(checkpointer=checkpointer)

print(graph)

import uuid

config = {
    "configurable": {
        "thread_id": uuid.uuid4()
    }
}

state = graph.invoke({}, config)

print(state)


# 查看所有 checkpoint 检查点
states = list(graph.get_state_history(config))

# 随便取某一步，比如取第二个状态
selected_state = states[1]

# 重新设定 State（改 author）
new_config = graph.update_state(
    selected_state.config,
    values={"author": "鲁迅"}
)

# 重新执行 Graph，从这个新 State 开始继续运行
state = graph.invoke(None, new_config)

print(state)