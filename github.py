from dotenv import load_dotenv
from fastmcp import FastMCP
import json
from pathlib import Path
import subprocess
from typing import TypedDict,List, Union
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from datetime import datetime
from zoneinfo import ZoneInfo


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
    timestamp=latest.get('timestamp',datetime.now(ZoneInfo("Asia/Kolkata")))

    return (
        f"# Event: {event_type}\nTitle: {title}\nDescription:{description}\nTimestamp:{timestamp}\nSource: {sender}"
    )


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


