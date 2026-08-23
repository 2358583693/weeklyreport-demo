from fastapi import FastAPI
from pydantic import BaseModel
import requests
from dotenv import load_dotenv
import os
import json
import smtplib
from email.mime.text import MIMEText
from duckduckgo_search import DDGS
from fastapi.responses import RedirectResponse

load_dotenv()
app = FastAPI()

ZHIPU_API_KEY = os.getenv("API_KEY")
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
EMAIL_AUTH_CODE = os.getenv("EMAIL_AUTH_CODE")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT","465"))
TARGET_EMAIL = os.getenv("TARGET_EMAIL")

# 请求体
class ReportRequest(BaseModel):
    work_content: str
    industry: str

# =========工具函数1：搜索行业新闻=========
def search_news(industry: str):
    results = []
    with DDGS() as ddgs:
        res = ddgs.text(f"{industry} 本周行业动态", max_results=3)
        for item in res:
            results.append({"title":item["title"],"body":item["body"]})
    return json.dumps(results,ensure_ascii=False)

# =========工具函数2：发送邮件（主程序手动调用，不给AI调用）=========
def send_email(report_text:str):
    msg = MIMEText(report_text,"plain","utf-8")
    msg["Subject"] = "本周工作周报"
    msg["From"] = EMAIL_ACCOUNT
    msg["To"] = TARGET_EMAIL
    with smtplib.SMTP_SSL(SMTP_SERVER,SMTP_PORT) as server:
        server.login(EMAIL_ACCOUNT,EMAIL_AUTH_CODE)
        server.send_message(msg)
    return True

#工具描述，仅搜索新闻交给AI调用
tools = [
    {
        "type":"function",
        "function":{
            "name":"search_news",
            "description":"搜索某个行业本周最新行业动态资讯，用于补充周报素材",
            "parameters":{
                "type":"object",
                "properties":{
                    "industry":{"type":"string","description":"行业名称，例如AI应用开发"}
                },
                "required":["industry"]
            }
        }
    }
]
tool_map = {"search_news":search_news}

#Agent循环主逻辑
def agent_run(user_input:str,industry:str):
    messages = [
        {"role":"system","content":"你是周报助手。根据用户本周工作内容,必要时调用search_news获取本周行业动态,整合一份正式完整周报。素材充足后直接输出周报正文，不要再调用工具。"},
        {"role":"user","content":f"用户本周工作：{user_input}；所属行业：{industry}"}
    ]
    max_loop = 5
    for _ in range(max_loop):
        payload = {
            "model":"glm-4-flash",
            "messages":messages,
            "tools":tools
        }
        resp = requests.post("https://open.bigmodel.cn/api/paas/v4/chat/completions",
            headers={"Authorization":f"Bearer {ZHIPU_API_KEY}","Content-Type":"application/json"},
            json=payload,timeout=60
        )
        data = resp.json()
        print("大模型完整返回=",data)
        choice = data["choices"][0]
        finish_reason = choice["finish_reason"]
        ai_msg = choice["message"]
        messages.append(ai_msg)
        if finish_reason != "tool_calls":
            #不再调用工具，拿到最终周报
            return ai_msg["content"]
        #执行工具调用
        tool_calls = ai_msg["tool_calls"]
        for call in tool_calls:
            func_name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"])
            res = tool_map[func_name](**args)
            messages.append({
                "role":"tool",
                "tool_call_id":call["id"],
                "content":res
            })
    return "达到最大循环次数，周报生成终止"

#接口
@app.get("/")
async def root():
    return RedirectResponse(url="/docs")
@app.post("/weekly_report")
async def create_report(req:ReportRequest):
    try:
        report = agent_run(req.work_content,req.industry)
        send_email(report)
        return {"weekly_report":report,"msg":"周报已生成并发送邮箱"}
        return {"ok":True}
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return{"error":str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app,host="0.0.0.0",port=8000)
