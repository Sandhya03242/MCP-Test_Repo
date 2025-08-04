from langchain_openai import ChatOpenAI
from fastapi import FastAPI,Request
from langchain_core.messages import HumanMessage, BaseMessage, SystemMessage
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated, Sequence
from langgraph.graph.message import add_messages
from github import gt_tools, github_agent
import uvicorn
from multiprocessing import Process

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)



class AgentState(TypedDict):
    messages:Annotated[Sequence[BaseMessage],add_messages]

tools=gt_tools

llm=ChatOpenAI(model="gpt-4.1-nano",temperature=0).bind_tools(tools=tools,tool_choice='auto')

def should_continue(state:AgentState):
    """check if last message contain tool"""
    result=state['messages'][-1]
    return hasattr(result,'tool_call') and len(result.tool_calls)>0

sys_prompt="""You are a Github assistant. Use the tools to answer queries about repository events, workflow status or file changes."""

def call_llm(state:AgentState)->AgentState:
    messages=[SystemMessage(content=sys_prompt)]+list(state['messages'])
    response=llm.invoke(messages)
    return {"messages":state['messages']+[response]}

def router(state:AgentState):
    return "GitHubAgent" if state['messages'][-1].tool_calls else END


graph=StateGraph(state_schema=AgentState)
graph.add_node("MainAgent",call_llm)
graph.add_node("GitHub",github_agent)
graph.set_entry_point("MainAgent")
graph.add_edge("GitHub","MainAgent")
graph.add_conditional_edges("MainAgent",router,{
    "GitHubAgent":"GitHub",
    END:END
})

agent=graph.compile()


# ----------------------------------------------------------------------------------------------------------------------------------
# receive webhook notification
app=FastAPI()
@app.post("/notify")
async def notify(request:Request):
    payload=await request.json()
    print("Manager received webhook notification:",payload)
    return {"status":"notified"}



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




