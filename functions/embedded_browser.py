"""Loopback-only interactive Chromium display for the dashboard chat pane."""
import atexit
import base64
from concurrent.futures import Future
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import queue
import secrets
import threading
import time
from urllib.parse import urlparse, parse_qs

PORT = 8766
ORIGINS = {'http://localhost:8000', 'http://127.0.0.1:8000',
           'http://localhost:8001', 'http://127.0.0.1:8001'}


def web_url(value):
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower().rstrip('.')
    if host == 'localhost' or host.endswith(('.localhost', '.local')):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return '.' in host


class BrowserSession:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.jobs = queue.Queue(maxsize=100)
        self.frame = b''
        self.state = {'url': '', 'title': '', 'error': '', 'width': 1280, 'height': 720}
        self.sequence = 0
        self.stopped = threading.Event()
        self.last_use = time.monotonic()
        self.thread = threading.Thread(target=self.run, daemon=True, name='chat-browser')
        self.thread.start()

    def command(self, data):
        self.last_use = time.monotonic()
        if data.get('action') == 'close':
            self.stopped.set()
            return {'ok':True}
        if self.stopped.is_set():
            return {'ok':False,'error':self.state['error'] or 'ブラウザは終了しました。'}
        future = Future()
        self.jobs.put_nowait((data, future))
        return future.result(timeout=35)

    def run(self):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as driver:
                browser = driver.chromium.launch(channel='chrome', headless=True, chromium_sandbox=True,
                    ignore_default_args=['--mute-audio'], args=['--autoplay-policy=document-user-activation-required'])
                context = browser.new_context(viewport={'width': 1280, 'height': 720}, accept_downloads=False)
                # External pages never receive the local UI's cookies, APIs or permissions.
                context.route('**/*', lambda route: route.continue_() if web_url(route.request.url) else route.abort())
                page = context.new_page()
                page.set_default_timeout(5000)
                page.on('popup', lambda popup: self._popup(page, popup))
                cdp = context.new_cdp_session(page)
                def receive_frame(event):
                    # Keep the latest frame, including the final frame after loading.
                    self.frame = base64.b64decode(event['data'])
                    self.sequence += 1
                    cdp.send('Page.screencastFrameAck', {'sessionId':event['sessionId']})
                cdp.on('Page.screencastFrame', receive_frame)
                cdp.send('Page.startScreencast', {'format':'jpeg','quality':65,
                         'maxWidth':1600,'maxHeight':900,'everyNthFrame':2})
                # Start on the empty page: navigate only to what the user requests.
                last_state = 0
                while not self.stopped.is_set() and time.monotonic()-self.last_use < 120:
                    try:
                        data, future = self.jobs.get(timeout=0.01)
                    except queue.Empty:
                        data = future = None
                    if data is not None:
                        try:
                            action = data.get('action')
                            if action == 'navigate':
                                url = str(data.get('url', ''))
                                if not web_url(url): raise ValueError('公開WebサイトのHTTP/HTTPS URLを入力してください。')
                                page.goto(url, wait_until='commit', timeout=25000)
                            elif action == 'click':
                                page.mouse.click(float(data['x']), float(data['y']), button=data.get('button','left'))
                            elif action == 'wheel':
                                page.mouse.move(float(data['x']), float(data['y']))
                                page.mouse.wheel(float(data.get('dx',0)), float(data.get('dy',0)))
                            elif action == 'text': page.keyboard.insert_text(str(data.get('text',''))[:8000])
                            elif action == 'key': page.keyboard.press(str(data.get('key',''))[:80])
                            elif action == 'back': page.go_back(wait_until='commit',timeout=20000)
                            elif action == 'forward': page.go_forward(wait_until='commit',timeout=20000)
                            elif action == 'reload': page.reload(wait_until='commit',timeout=20000)
                            elif action == 'resize':
                                page.set_viewport_size({'width':max(480,min(1920,int(data['width']))),
                                                        'height':max(240,min(1080,int(data['height'])))})
                            elif action == 'close': self.stopped.set()
                            else: raise ValueError('Unknown browser action')
                            self.state['error'] = ''
                            future.set_result({'ok':True})
                        except Exception as error:
                            self.state['error'] = str(error)[:300]
                            future.set_result({'ok':False,'error':self.state['error']})
                    if not self.stopped.is_set():
                        page.wait_for_timeout(20)
                        if time.monotonic()-last_state > 0.5:
                            last_state = time.monotonic()
                            self.state.update(url=page.url,title=page.title(),**page.viewport_size)
                            self.state['media'] = page.evaluate('''() => {
                              const v=document.querySelector('video');
                              return v ? {paused:v.paused,time:v.currentTime,muted:v.muted,
                                ready:v.readyState,duration:Number.isFinite(v.duration)?v.duration:null} : null;
                            }''')
                browser.close()
        except Exception as error:
            self.state['error'] = str(error)[:500]
        finally:
            self.stopped.set()
            while not self.jobs.empty():
                _, future = self.jobs.get_nowait()
                future.set_result({'ok':False,'error':self.state['error'] or 'ブラウザは終了しました。'})

    @staticmethod
    def _popup(page, popup):
        url = popup.url
        popup.close()
        if web_url(url): page.goto(url,wait_until='commit',timeout=20000)


class BrowserService(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address=('127.0.0.1', PORT)):
        super().__init__(address, BrowserHandler)
        self.sessions = {}
        self.lock = threading.Lock()


class BrowserHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args): pass

    def guard(self):
        host = self.headers.get('Host','')
        if host not in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}:
            self.reply({'ok':False,'error':'Invalid host'},403);return False
        if self.headers.get('Origin') not in ORIGINS or self.headers.get('X-Sotuken-Browser') != '1':
            self.reply({'ok':False,'error':'Local dashboard only'},403);return False
        return True

    def reply(self, data, status=200, mime='application/json', sequence=None):
        body = data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status)
        origin = self.headers.get('Origin')
        if origin in ORIGINS:self.send_header('Access-Control-Allow-Origin',origin)
        self.send_header('Vary','Origin')
        if sequence is not None:
            self.send_header('X-Frame-Sequence', str(sequence))
            self.send_header('Access-Control-Expose-Headers', 'X-Frame-Sequence')
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass

    def do_OPTIONS(self):
        if self.headers.get('Origin') not in ORIGINS:
            self.reply({'ok':False},403);return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin',self.headers['Origin'])
        self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type, X-Sotuken-Browser, Authorization')
        self.send_header('Access-Control-Allow-Private-Network','true')
        self.send_header('Access-Control-Max-Age','600')
        self.end_headers()

    def session(self):
        token = self.headers.get('Authorization','').removeprefix('Bearer ')
        item = self.server.sessions.get(token)
        if item:item.last_use=time.monotonic()
        return item

    def do_GET(self):
        if not self.guard():return
        if self.path=='/health':self.reply({'ok':True,'kind':'embedded-chat-browser'});return
        item=self.session()
        if item is None:self.reply({'ok':False,'error':'Invalid browser session'},401);return
        parsed = urlparse(self.path)
        if parsed.path == '/frame':
            after = (parse_qs(parsed.query).get('after') or ['-1'])[0]
            if not item.frame or after == str(item.sequence):
                self.reply(b'', 204)
            else:
                self.reply(item.frame, mime='image/jpeg', sequence=item.sequence)
        elif self.path=='/state':self.reply({**item.state,'sequence':item.sequence,'closed':item.stopped.is_set()})
        else:self.reply({'ok':False},404)

    def do_POST(self):
        if not self.guard():return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length>16384:raise ValueError('Request too large')
            data=json.loads(self.rfile.read(length) or b'{}')
            if self.path=='/session':
                with self.server.lock:
                    self.server.sessions={k:v for k,v in self.server.sessions.items() if not v.stopped.is_set()}
                    if len(self.server.sessions)>=3:
                        self.reply({'ok':False,'error':'ブラウザは3画面までです。不要な画面を閉じてください。'},409);return
                    item=BrowserSession();self.server.sessions[item.token]=item
                self.reply({'ok':True,'token':item.token});return
            item=self.session()
            if item is None:self.reply({'ok':False,'error':'Invalid browser session'},401);return
            if self.path=='/action':self.reply(item.command(data))
            else:self.reply({'ok':False},404)
        except Exception as error:self.reply({'ok':False,'error':str(error)[:400]},400)


_service = None
def start_service(origin=None):
    global _service
    if origin:ORIGINS.add(origin)
    if _service is not None:return _service
    try:
        _service=BrowserService()
        threading.Thread(target=_service.serve_forever,daemon=True,name='embedded-browser-http').start()
        atexit.register(lambda:[item.stopped.set() for item in _service.sessions.values()])
    except OSError:
        # Another dashboard process may already own the loopback browser service.
        pass
    return _service


if __name__=='__main__':
    service=BrowserService()
    try:service.serve_forever()
    finally:
        for item in service.sessions.values():item.stopped.set()
        service.server_close()
