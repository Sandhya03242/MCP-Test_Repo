from dotenv import load_dotenv
import os
import requests
from fastmcp import FastMCP
from fastapi import FastAPI
from typing import TypedDict,List, Union
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
import asyncio
import json
from dotenv import load_dotenv
load_dotenv()

mcp=FastMCP(name="slack_mcp")
app=FastAPI()
SLACK_BOT_TOKEN=os.environ.get("SLACK_API_KEY")


@mcp.tool()
def send_slack_notification(message:str,pr_number:int=None,repo:str=None,event_type:str=None)->str:
    """Send a formatted notification to the team slack channel."""
    # webhook_url=os.environ.get("SLACK_WEBHOOK_URL")
    if not SLACK_BOT_TOKEN:
        return "Error: SLACK_API_KEY environment  variable not set"
    blocks=[
        {
            "type":"section",
            "text":{"type":"mrkdwn","text":message}
        }
    ]


    if (event_type and event_type.lower() == "pull_request" and repo is not None and pr_number is not None):
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Merge"},
                    "style": "primary",
                    "value": json.dumps({"action": "merge", "repo": repo, "pr_number": pr_number}),
                    "action_id": "merge_pr"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Cancel"},
                    "style": "danger",
                    "value": json.dumps({"action": "cancel"}),
                    "action_id": "cancel_pr"
                }
            ]
        })


    payload={
        "channel":"#general",
        "blocks":blocks,
        "text":message,
        "mrkdwn":True
        }
    try:
        response=requests.post("https://slack.com/api/chat.postMessage",json=payload,timeout=10)
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


