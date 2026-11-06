import json,time,urllib.request
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 b=p.chromium.launch(channel='chrome',headless=True);page=b.new_page(viewport={'width':1600,'height':1000});tokens=[]
 def response(r):
  if r.url=='http://127.0.0.1:8766/session' and r.status==200:tokens.append(r.json()['token'])
 page.on('response',response);page.on('pageerror',lambda e:print('JSERROR',e,flush=True))
 def state():
  if not tokens:return {}
  req=urllib.request.Request('http://127.0.0.1:8766/state',headers={'Origin':'http://localhost:8000','X-Sotuken-Browser':'1','Authorization':'Bearer '+tokens[-1]})
  return json.loads(urllib.request.urlopen(req).read())
 def wait_state(predicate,timeout=45):
  until=time.monotonic()+timeout
  while time.monotonic()<until:
   page.wait_for_timeout(500);s=state()
   if predicate(s):return s
  raise RuntimeError(str(state()))
 page.goto('http://localhost:8000/',wait_until='domcontentloaded');page.locator('#browser-toggle-btn').click()
 page.wait_for_function("document.querySelector('#embedded-browser-screen img').naturalWidth>100",timeout=60000)
 page.wait_for_timeout(5000);print('ready',state(),flush=True)
 r=page.locator('#embedded-browser-screen').bounding_box()
 page.locator('#embedded-browser-screen img').click(position={'x':600,'y':28})
 page.get_by_label('ページ内へ入力する文字',exact=True).fill('Me at zoo')
 page.get_by_label('ページ内へ入力する文字',exact=True).press('Enter')
 print('search',wait_state(lambda s:'search_query' in s.get('url','')),flush=True)
 page.wait_for_timeout(5000);page.screenshot(path='work/embedded-search.png')
 page.locator('#browser-search').fill('https://www.youtube.com/watch?v=jNQXAC9IVRw');page.locator('#browser-search-btn').click()
 print('video URL',wait_state(lambda s:'watch?v=jNQXAC9IVRw' in s.get('url','')),flush=True)
 page.wait_for_timeout(10000);page.screenshot(path='work/embedded-video.png');print('video state',state(),flush=True)
 page.locator('#embedded-browser-screen img').click(position={'x':370,'y':220})
 page.wait_for_timeout(8000);print('after play click',state(),flush=True);page.screenshot(path='work/embedded-video-play.png')
 page.get_by_role('button',name='ブラウザを終了',exact=True).click();page.wait_for_function("document.querySelector('#browser-pane').hidden",timeout=15000);b.close()
