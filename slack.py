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
def send_slack_notification(message:str,event_type:str="unknown",repo:str="Sandhya03242/MCP-Test_Repo",pr_number:int="48")->str:
    """Send a formatted notification to the team slack channel."""
    webhook_url="https://hooks.slack.com/services/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"
    if not webhook_url:
        return "Error: SLACK_WEBHOOK_URL environment  variable not set"
    blocks=[
        {"type":"section","text":{"type":"mrkdwn","text":message}}]
    if event_type=='pull_request':
        value_payload = json.dumps({"repo": repo, "pr_number": pr_number})

        blocks.append({
            "type":"actions",
            "elements":[
                {
                    "type":"button",
                    "text":{"type":"plain_text","text":"✅ Merge"},
                    "style":"primary",
                    "value":value_payload,
                    "action_id":"merge_action"
                },
                {
                    "type":"button",
                    "text":{"type":"plain_text","text":"❌ Cancel"},
                    "style":"danger",
                    "value":value_payload,
                    "action_id":"cancel_action"
                }
            ]
        }
        )
    payload={
            "blocks":blocks,
            "text":message,
            "mrkdwn":True,
            "private_metadata":json.dumps({"repo":repo,"pr_number":pr_number})
        }
    print(f"DEBUG send_slack_notification called with repo={repo}, pr_number={pr_number}")

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





