import json
from datetime import datetime
from pathlib import Path
from aiohttp import web
import requests

EVENTS_FILE=Path(__file__).parent / "github_events.json"
async def handle_webhook(request):
    try:
        data=await request.json()
        event={
            "timestamp":datetime.utcnow().isoformat(),
            "event_type":request.headers.get("X-GitHub-Event","unknown"),
            "action":data.get("action"),
            "repository": data.get("repository",{}),
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