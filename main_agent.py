from langchain_openai import ChatOpenAI
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse, PlainTextResponse
from langchain_core.messages import HumanMessage, BaseMessage, SystemMessage
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated, Sequence
from langgraph.graph.message import add_messages
from github import gt_tools, github_agent,merge_pull_request, close_pull_request, get_pull_request_details
from slack import slack_tools,slack_agent,send_slack_notification
import uvicorn
from multiprocessing import Process
from datetime import datetime
import pytz
import json


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

def convert_utc_to_ist(utc_str:str)->str:
    try:
        utc_time=datetime.strptime(utc_str,"%Y-%m-%dT%H:%M:%SZ")
        utc_time=utc_time.replace(tzinfo=pytz.UTC)
        ist_time=utc_time.astimezone(pytz.timezone('Asia/Kolkata'))
        return ist_time.strftime("%Y-%m-%d %H:%M:%S IST")
    except Exception:
        return utc_str


# ----------------------------------------------------------------------------------------------------------------------------------
app=FastAPI()
handled_prs=set()

@app.post("/notify")
async def notify(request: Request):
    payload = await request.json()
    if payload.get("pull_request"):
         event_type="pull_request"
    else:
        event_type = payload.get('event_type', 'unknown')
    if event_type=="pull_request":
        action=payload.get("action")
        if action=='synchronize':
            return {"status":"ignored synchronize event"}
        if action not in ['opened',"reopened","closed"]:
             return {"status":f"Ignored PR action {action}"}
    repo_info = payload.get("repository")
    if isinstance(repo_info, dict):
        repo = repo_info.get("full_name", "unknown")
    else:
        repo = str(repo_info) if repo_info else "unknown"

    pr_number = payload.get("pr_number")

    if not pr_number:
        pr = payload.get("pull_request")
        if isinstance(pr, dict):
            pr_number = pr.get("number")
        if not pr_number:
            pr_number = payload.get("number") 
    if pr_number is not None:
         if pr_number in handled_prs:
              return {"status":f"Ignored duplicate event for PR #{pr_number}"}
         else:
              handled_prs.add(pr_number)


    sender = payload.get('sender', 'unknown')
    title=payload.get("title",'')
    description=payload.get("description","")
    timestamp=payload.get("timestamp")
    if timestamp:
        timestamp=convert_utc_to_ist(timestamp)
        timestamp=timestamp.split("+")[0].replace("T"," ").split(".")[0]
    else:
        timestamp=datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S IST")
    message = f"🔔 New GitHub event: {event_type} on repository: {repo}"
    message+=f"\n- Title: {title}\n- Description: {description}\n- Timestamp: {timestamp}\n- User: {sender}\n"
    print(message)
    tool_args={
        "message":message,
        "event_type":event_type,
        "repo":repo,
        "pr_number":pr_number,
    }
    slack_response=send_slack_notification.fn(message=message,event_type=event_type,repo=repo,pr_number=pr_number)
    print("Slack response",slack_response)
    return {"status": "notified and send to slack"}
# -------------------------------------------------------------------------------------------------------------------------------

@app.post("/slack/interact")
async def handler_slack_actions(request: Request):
    form_data = await request.form()
    payload = form_data.get("payload")
    if not payload:
        return PlainTextResponse("No payload received", status_code=400)

    try:
        data = json.loads(payload)
        action_id = data['actions'][0]['action_id']
        action_value = data['actions'][0]['value']
        try:
            metadata=json.loads(action_value)
        except json.JSONDecodeError:
            metadata={}
        repo = metadata.get("repo", "unknown")
        pr_number = metadata.get("pr_number", "unknown")
        user = data.get("user", {}).get("username", "unknown")
        
        if action_id=="merge_action":
            try:
                    pr_number = int(pr_number)
            except (ValueError, TypeError):
                    return JSONResponse({"error": "Invalid or missing PR number"}, status_code=400)
            result_text=merge_pull_request.fn(repo=repo,pr_number=pr_number)
            return JSONResponse({"text":f"{result_text}"})

        elif action_id=='cancel_action':
            try:
                    pr_number = int(pr_number)
            except (ValueError, TypeError):
                    return JSONResponse({"error": "Invalid or missing PR number"}, status_code=400)
            pr_details=get_pull_request_details.fn(repo=repo,pr_number=pr_number)
            if isinstance(pr_details,dict) and pr_details.get("merged"):
                 return JSONResponse({"text":f"PR #{pr_number} in {repo} is already merged. Cancel Skipped."})
            
            result_text=close_pull_request.fn(repo=repo,pr_number=pr_number)
            send_slack_notification.fn(message=result_text,repo=repo,pr_number=pr_number)

            return JSONResponse({"text":f"{result_text}"})
    except Exception as e:
        print("❌ Error in /slack/interact:", e)
        return JSONResponse({"error": str(e)}, status_code=500)



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
def run_server():
        uvicorn.run(app,host="0.0.0.0",port=8001,log_level='critical')

if __name__=="__main__":
    server_process=Process(target=run_server)
    server_process.start()

    run_agent()

    server_process.terminate()
