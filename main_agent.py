from langchain_openai import ChatOpenAI
from fastapi import FastAPI,Request
from langchain_core.messages import HumanMessage, BaseMessage, SystemMessage
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated, Sequence
from langgraph.graph.message import add_messages
from github import gt_tools, github_agent
from slack import slack_tools,slack_agent
import uvicorn
from multiprocessing import Process
from datetime import datetime
from zoneinfo import ZoneInfo


import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)



class AgentState(TypedDict):
    messages:Annotated[Sequence[BaseMessage],add_messages]

tools=gt_tools + list(slack_tools.values())

llm=ChatOpenAI(model="gpt-4.1-nano",temperature=0).bind_tools(tools=tools,tool_choice='auto')

def should_continue(state:AgentState):
    """check if last message contain tool"""
    result=state['messages'][-1]
    return hasattr(result,'tool_call') and len(result.tool_calls)>0

sys_prompt="""You are an assistant that helps with GitHub and slack workflows. Use GitHub tools for repo queries and slack tools for team notifications."""

def call_llm(state:AgentState)->AgentState:
    messages=[SystemMessage(content=sys_prompt)]+list(state['messages'])
    response=llm.invoke(messages)
    return {"messages":state['messages']+[response]}

def router(state: AgentState):
    tool_calls = getattr(state['messages'][-1], 'tool_calls', [])
    tool_names = [t['name'] for t in tool_calls]

    gt_tool_names = [fn.__name__ for fn in gt_tools]
    slack_tool_names = list(slack_tools.keys())

    if any(t in gt_tool_names for t in tool_names):
        return "GitHub"
    elif any(t in slack_tool_names for t in tool_names):
        return "Slack"
    else:
        return END

graph=StateGraph(state_schema=AgentState)
graph.add_node("MainAgent",call_llm)
graph.add_node("GitHub", github_agent)
graph.add_node("Slack", slack_agent)
graph.set_entry_point("MainAgent")
graph.add_edge("GitHub","MainAgent")
graph.add_edge("Slack","MainAgent")
graph.add_conditional_edges("MainAgent", router, {
    "GitHub": "GitHub",
    "Slack": "Slack",
    END: END
})


agent=graph.compile()


# ----------------------------------------------------------------------------------------------------------------------------------
app=FastAPI()
@app.post("/notify")
async def notify(request: Request):
    payload = await request.json()
    event_type = payload.get('event_type', 'unknown')
    if event_type=="pull_request":
        action=payload.get("action")
        if action=='synchronize':
            return {"status":"ignored synchronize event"}

    repo = payload.get('repository', {}).get('full_name', 'unknown')
    sender = payload.get('sender', 'unknown')
    title=payload.get("title",'')
    description=payload.get("description","")
    timestamp=payload.get("timestamp",'')
    try:
        utc_time=datetime.fromisoformat(timestamp.replace("Z","+00:00"))
        ist_time=utc_time.astimezone(ZoneInfo("Asia/Kolkata"))
        formatted_time=ist_time.strftime("%Y-%m-%d %H:%M:%S IST")
    except Exception as e:
        formatted_time=timestamp
    message = f"🔔 New GitHub event: {event_type} on repository: {repo}"
    message+=f"\n- Title: {title}\n- Description: {description}\n- Timestamp: {formatted_time}\n- User: {sender}\n"
    print(message)
    # state={
    #     "messages":[
    #         HumanMessage(content=f"Send this GitHub event to slack:\n{message}")
    #     ]
    # }
    # result=agent.invoke(state)
    # print("Agent: ", result['messages'][-1].content)
    return {"status": "notified and send to slack"}


# ---------------------------------------------------------------------------------------------------------------------------------
def run_agent():
    print("🤖 Assistant ready")
    while True:
        q=input("You: ")
        if q.lower() in {"exit","quit"}:
            break
        state={"messages":[HumanMessage(content=q)]}
        result=agent.invoke(state)
        print("Agent: ",result['messages'][-1].content)
def run_sever():
        uvicorn.run(app,host="0.0.0.0",port=8001,log_level='critical')

if __name__=="__main__":
    server_process=Process(target=run_sever)
    server_process.start()

    run_agent()

    server_process.terminate()



