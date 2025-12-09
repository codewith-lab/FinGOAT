import datetime
import os

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


# 定义工具函数：获取当前日期
def get_date():
    """获取当前日期"""
    print("调用了 get_date 工具函数")
    return datetime.datetime.now().strftime("%Y-%m-%d")


# 定义工具函数：获取某城市某天的天气
def get_weather(city: str, date: str):
    """获取城市天气"""
    print("调用了 get_weather 工具函数")
    return f"{city} 在 {date} 的天气是：晴天"


# 创建 DeepAgent：给 LLM 配一些工具
deep_agent = create_deep_agent(
    llm,
    tools=[get_date, get_weather],
    system_prompt="""
你是一个助手，现在有以下这些工具可以使用：
## `get_date`：获取当前日期
## `get_weather`：获取城市的天气
结合这些工具，完成用户的请求。
""",
)

# 示例请求，只调用 get_weather 工具
# response = deep_agent.invoke({
#     "messages": [
#         {"role": "user", "content": "明天长沙的天气怎么样?"}
#     ]
# })

# 示例请求，会先调用 get_date 再调用 get_weather 工具
response = deep_agent.invoke({
    "messages": [
        {"role": "user", "content": "明天星期几？这一天长沙的天气怎么样?"}
    ]
})

# 打印结果
for message in response["messages"]:
    print(message)
    print("=========")