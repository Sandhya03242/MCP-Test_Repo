# main_agrnt.py


from langchain_openai import ChatOpenAI
from fastapi import FastAPI,Request,Form
from fastapi.responses import JSONResponse, PlainTextResponse
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
    timestamp=payload.get("timestamp")
    if timestamp:
        timestamp=convert_utc_to_ist(timestamp)
    else:
        timestamp=datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S IST")

    message = f"🔔 New GitHub event: {event_type} on repository: {repo}"
    message+=f"\n- Title: {title}\n- Description: {description}\n- Timestamp: {timestamp}\n- User: {sender}\n"
    print(message)
    state={
        "messages":[
            HumanMessage(content=f"Send this GitHub event to slack:\n{message}")
        ]
    }
    result=agent.invoke(state)
    print("Agent: ", result['messages'][-1].content)
    return {"status": "notified and send to slack"}
# -------------------------------------------------------------------------------------------------------------------------------

@app.post("/slack/actions")
async def handler_slack_actions(request:Request):
    form_data=await request.form()
    payload=form_data.get("payload")
    if not payload:
        return PlainTextResponse("No payload received",status_code=400)
    data=json.loads(payload)
    action_id=data['actions'][0]['action_id']
    repo=data['repo']
    user=data['user']['username']
    pr_number=123

    if action_id=="merge_action":
        message=f"merge pull request {pr_number} in {repo}"
    elif action_id=='cancel_action':
        message=f"cancel pull request {pr_number} in {repo}"
    else:
        return JSONResponse({"text":"unknown action"},status_code=400)
    state={
        HumanMessage(content=message)
    }

    result=agent.invoke(state)
    return JSONResponse({"text":f"Action {action_id} triggered by {user}"})


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



# slack.py
from dotenv import load_dotenv
import os
import requests
from fastmcp import FastMCP
from fastapi import FastAPI
from typing import TypedDict,List, Union
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
import asyncio
from dotenv import load_dotenv
load_dotenv()

mcp=FastMCP(name="slack_mcp")
app=FastAPI()
SLACK_BOT_TOKEN=os.environ.get("SLACK_API_KEY")


@mcp.tool()
def send_slack_notification(message:str)->str:
    """Send a formatted notification to the team slack channel."""
    webhook_url=os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return "Error: SLACK_WEBHOOK_URL environment  variable not set"
    blocks=[
        {"type":"section","text":{"type":"mrkdwn","text":message}},
        {
            "type":"actions",
            "elements":[
                {
                    "type":"button",
                    "text":{"type":"plain_text","text":"✅ Merge"},
                    "style":"primary",
                    "value":"merge_pr",
                    "action_id":"merge_action"
                },
                {
                    "type":"button",
                    "text":{"type":"plain_text","text":"❌ Cancle"},
                    "style":"danger",
                    "value":"cancle_pr",
                    "action_id":"cancel_action"
                }
            ]
        }
    ]

    payload={
            "blocks":blocks,
            "text":message,
            "mrkdwn":True
        }
    try:
        response=requests.post(webhook_url,json=payload,timeout=10)
        if response.status_code==200:
            return "✅ Message sent successfully to slack."
        else:
            return f"❌ Failed to send message. Status: {response.status_code}, Response: {response.text}"
    except requests.exceptions.Timeout:
        return "❌ Request timed out. Check your internet connection and try again."
    except requests.exceptions.ConnectionError:
        return "❌ Connection error. Check your  internet connection and webhook URL."
    except Exception as e:
        return f"❌ Error sending message: {str(e)}"



    
slack_tools=[send_slack_notification.fn]
slack_tools= {tool.__name__:tool for tool in slack_tools}


class SlackAgentState(TypedDict):
    messages:List[Union[HumanMessage,AIMessage,ToolMessage]]

def slack_agent(state:SlackAgentState)->SlackAgentState:
    tool_calls=state["messages"][-1].tool_calls
    results=[]
    for t in tool_calls:
        fn=slack_tools.get(t['name'])
        if fn:
            try:
                result= fn(**t["args"])
            except Exception as e:
                result=f"Error: {e}"
            results.append(ToolMessage(tool_call_id=t['id'],name=t['name'],content=str(result)))
    return {"messages":state['messages']+results}


# github.py
from dotenv import load_dotenv
from fastmcp import FastMCP
import json
from pathlib import Path
import subprocess
from typing import TypedDict,List, Union
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from datetime import datetime
from zoneinfo import ZoneInfo
import pytz

load_dotenv()

mcp=FastMCP(name="github_mcp")

EVENTS_FILE=Path(__file__).parent/"github_events.json"

    
@mcp.tool
def get_recent_actions_events()->str:
    """Return recent GitHub Actions events from stored webhook payloads"""
    if EVENTS_FILE.exists():
        return json.loads(EVENTS_FILE.read_text())
    return []


@mcp.tool
def get_repository_detail() -> str:
    """Return basic repository info and summary of recent events"""
    if not EVENTS_FILE.exists():
        return "No repository events available."
    events = json.loads(EVENTS_FILE.read_text())
    if not events:
        return "No events recorded yet."
    
    latest_event = events[-1]
    repo = latest_event.get("repository", {})
    full_name = repo.get("full_name", "Unknown")
    owner = repo.get("owner", {}).get("login", "Unknown")

    counts = {}
    for e in events:
        etype = e.get('event_type', 'unknown')
        counts[etype] = counts.get(etype, 0) + 1

    count_summary = ", ".join(f"{etype}: {count}" for etype, count in counts.items())

    return (
        f"Repository: {full_name} (owner: {owner})\n"
        f"Total events: {len(events)} ({count_summary})\n"
        f"Most recent event: {latest_event.get('event_type')} "
        f"by {latest_event.get('sender')}"
    )

@mcp.tool
def get_workflow_status(workflow_name:str)->str:
    """Return the latest status of a GitHub Actions workflow by name."""
    if not EVENTS_FILE.exists():
        return "No GitHub Actions events found."
    events=json.loads(EVENTS_FILE.read_text())
    events=[e for e in events if e.get("workflow_job") or e.get("workflow_run")]
    for event in reversed(events):
        job=event.get("workflow_job")
        run=event.get("workflow_run")
        name=""
        status=""
        if job and workflow_name.lower() in job.get("name","").lower():
            name=job['name']
            status=job['conclusion'] or job['status']
        elif run and workflow_name.lower() in run.get("name","").lower():
            name=run['name']
            status=run['conclusion'] or run['status']

        if name:
            return f"workflow '{name}' status: {status}"
    return f"No recent status found for workflow: {workflow_name}"


@mcp.tool
def summarize_latest_event()->str:
    """Summarize the latest GitHub event (PR,push etc)"""
    if not EVENTS_FILE.exists():
        return "No GitHub events found."
    events=json.loads(EVENTS_FILE.read_text())
    if not events:
        return "No events stored."
    latest=events[-1]
    event_type=latest.get('event_type','unknown')
    repo=latest.get("repository",'unknown')
    sender=latest.get('sender','unknown')
    title=repo.get("title",'')
    description=latest.get("description",'')
    timestamp=latest.get('timestamp')
    if timestamp:
        try:
            dt=datetime.fromisoformat(timestamp)
            if dt.tzinfo is None:
                dt=dt.replace(tzinfo=pytz.UTC)
            dt_ist=dt.astimezone(pytz.timezone("Asia/Kolkata"))
            formatted_time=dt_ist.strftime("%Y-%m-%d %H:%M:%S IST")
        except Exception as e:
            formatted_time=timestamp
    else:
        formatted_time=""


    return (
        f"# Event: {event_type}\nTitle: {title}\nDescription:{description}\nTimestamp:{formatted_time}\nSource: {sender}"
    )

def merge_pull_request(repo:str,pr_number:int)->str:
    """Merge a PR"""
    try:
        result=subprocess.run(
            ['gh','pr','merge',str(pr_number),"--repo",repo,'--merge'],
            capture_output=True,
            text=True,
            check=True
        )
        return f"✅ Merge PR #{pr_number} merged successfully.\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"❌ Failed to merge PR:\n{e.stderr}"





class GitHubAgentState(TypedDict):
    messages:List[Union[HumanMessage,AIMessage,ToolMessage]]

gt_tools=[get_recent_actions_events.fn,get_workflow_status.fn,get_repository_detail.fn,summarize_latest_event.fn]
github_tools= {tool.__name__:tool for tool in gt_tools}

def github_agent(state:GitHubAgentState)->GitHubAgentState:
    tool_calls=state["messages"][-1].tool_calls
    results=[]
    for t in tool_calls:
        fn=github_tools.get(t['name'])
        if fn:
            try:
                result=fn(**t["args"])
            except Exception as e:
                result=f"Error: {e}"
            results.append(ToolMessage(tool_call_id=t['id'],name=t['name'],content=str(result)))
    return {"messages":state['messages']+results}



# webhook_server.py
import json
from datetime import datetime
from pathlib import Path
from aiohttp import web
import requests
from zoneinfo import ZoneInfo
import pytz

EVENTS_FILE=Path(__file__).parent / "github_events.json"
async def handle_webhook(request):
    try:
        data=await request.json()
        event_type=request.headers.get("X-GitHub-Event","unknown")
        title=''
        description=''
        if event_type=='pull_request':
            pr=data.get("pull_request",{})
            title=pr.get("title",'')
            description=pr.get("body",'')
        elif event_type=='issues':
            issue=data.get("issue",{})
            title=issue.get("title",'')
            description=issue.get("body",'')
        elif event_type=='push':
            commits=data.get('commits',[])
            if commits:
                title=f"{len(commits)} commits pushed"
                description="\n".join(commit.get("message",'') for commit in commits)
        elif event_type=='release':
            release=data.get("release",{})
            title=release.get("name",release.get("tag_name",""))
            description=release.get("body",'')
        elif event_type=="create":
            ref_type=data.get("ref_type","")
            ref=data.get("ref","")
            title=f"Created {ref_type}: {ref}"
            description=""
        elif event_type=="delete":
            ref_type=data.get("ref_type","")
            ref=data.get("ref","")
            title=f"Deleted {ref_type}: {ref}"
            description=""
        else:
            title=data.get("title","")
            description=data.get("body","")


        ist_now=datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
        event={
            "timestamp":ist_now,
            "event_type":event_type,
            "action":data.get("action"),
            "repository": data.get("repository",{}),
            "title":title,
            "description":description,
            "sender":data.get("sender",{}).get("login")
        }
        events=[]
        if EVENTS_FILE.exists():
            with open(EVENTS_FILE) as f:
                events=json.load(f)
        events.append(event)
        events=events[-100:]
        with open(EVENTS_FILE,"w") as f:
            json.dump(events,f,indent=2)
        
        try:
            requests.post("http://localhost:8001/notify",json=event)
        except Exception as notify_error:
            print(F"Failed to notify manager agent:{notify_error}")

        return web.json_response({"status":"received"})
    except Exception as e:
        return web.json_response({"error":str(e)},status=400)
    
app=web.Application()
app.router.add_post("/webhook/github",handle_webhook)

if __name__ =="__main__":
    print("✅ Starting webhook server on http://localhost:8080")
    web.run_app(app,host='localhost',port=8080)