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
        pr_number=None
        repo_full_name=None
        title=''
        description=''
        if event_type=='pull_request':
            pr=data.get("pull_request",{}).get("number")
            print("PR payload",pr)
            title=pr.get("title",'')
            description=pr.get("body",'')
            pr_number=pr.get("pull_request", {}).get("number") or pr.get("number")

            repo_full_name=data.get("repository",{}).get("full_name")
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
            "repository": {"full_name": repo_full_name},
            "pr_number":pr_number,
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