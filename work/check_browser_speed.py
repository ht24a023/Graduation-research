import json,time
from functions.embedded_browser import BrowserSession
s=BrowserSession();start=time.monotonic()
try:
    result=s.command({'action':'navigate','url':'https://www.google.com/search?q=sotuken'})
    commit=time.monotonic()-start
    limit=time.monotonic()+10
    while not s.frame and not s.stopped.is_set() and time.monotonic()<limit:time.sleep(.05)
    print(json.dumps({'ok':result.get('ok'),'startup_and_navigation_sec':round(commit,2),'first_frame_sec':round(time.monotonic()-start,2),'frame_bytes':len(s.frame),'sequence':s.sequence,'error':s.state.get('error','')},ensure_ascii=False))
finally:
    s.stopped.set();s.thread.join(timeout=5)
