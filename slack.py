from dotenv import load_dotenv
import os
import requests
from fastmcp import FastMCP
from fastapi import FastAPI
from typing import TypedDict,List, Union
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
import asyncio
from dotenv import load_dotenv
import json
load_dotenv()

mcp=FastMCP(name="slack_mcp")
app=FastAPI()
SLACK_BOT_TOKEN=os.environ.get("SLACK_API_KEY")


@mcp.tool()
def send_slack_notification(message:str,event_type:str="unknown",repo:str=None,pr_number:int=None)->str:
    """Send a formatted notification to the team slack channel."""
    webhook_url=os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return "Error: SLACK_WEBHOOK_URL environment  variable not set"
    blocks=[
        {"type":"section","text":{"type":"mrkdwn","text":message}}]
    # repo="Sandhya03242/MCP-Test_Repo"
    # pr_number=123
    if event_type=='pull_request':
        blocks.append({
            "type":"actions",
            "elements":[
                {
                    "type":"button",
                    "text":{"type":"plain_text","text":"✅ Merge"},
                    "style":"primary",
                    "value":json.dumps({"action": "merge", "repo": repo, "pr_number": pr_number}),
                    "action_id":"merge_action"
                },
                {
                    "type":"button",
                    "text":{"type":"plain_text","text":"❌ Cancel"},
                    "style":"danger",
                    "value":json.dumps({"action": "cancel", "repo": repo, "pr_number": pr_number}),
                    "action_id":"cancel_action"
                }
            ]
        }
        )
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





