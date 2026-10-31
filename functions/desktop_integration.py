"""バックエンドPCの時計と、明示的に有効化した通知の一時受け渡し。"""
from collections import deque
from datetime import datetime
from pathlib import Path
import base64
import json
import math
import os
import re
import secrets
import threading
import time


def system_clock():
    now = datetime.now().astimezone()
    return {'ok': True, 'source': 'backend_pc', 'epoch_ms': now.timestamp()*1000,
            'utc_offset_minutes': int(now.utcoffset().total_seconds()/60),
            'timezone': now.tzname() or 'Local', 'iso': now.isoformat()}


class NotificationHub:
    """通知本文はディスク・会話履歴・研究ログに書かない。最大60秒だけ保持。"""
    def __init__(self):
        self._lock = threading.RLock()
        self._token = secrets.token_urlsafe(32)
        self._events = deque(maxlen=100)
        self._seen = deque(maxlen=256)
        self._sequence = 0
        self._generation = 0
        self._enabled = False
        self._duration = 5
        self._important_apps = []
        self._bridge_state = 'not_connected'
        self._last_bridge = 0.0
        self._configuration_path = None

    def authorized(self, authorization):
        return secrets.compare_digest(str(authorization or ''), 'Bearer '+self._token)

    def settings(self):
        with self._lock:
            connected = self._last_bridge > 0 and time.monotonic()-self._last_bridge < 6
            return {'ok': True, 'enabled': self._enabled, 'duration_sec': self._duration,
                    'important_apps': list(self._important_apps), 'cursor': self._sequence,
                    'bridge_state': self._bridge_state if connected else 'not_connected',
                    'connected': connected, 'generation': self._generation,
                    'source': 'windows_notification_listener', 'retention_sec': 60}

    def configure(self, values):
        if not isinstance(values, dict):
            raise ValueError('settings must be an object')
        with self._lock:
            enabled=values.get('enabled', self._enabled)
            if not isinstance(enabled, bool):
                raise ValueError('enabled must be boolean')
            duration=values.get('duration_sec', self._duration)
            if not isinstance(duration,(int,float)) or isinstance(duration,bool) or not math.isfinite(duration):
                raise ValueError('表示秒数は数値で指定してください。')
            apps=values.get('important_apps', self._important_apps)
            if not isinstance(apps,list):
                raise ValueError('important_apps must be a list')
            important=[str(value).strip()[:100] for value in apps[:30] if str(value).strip()]
            if self._enabled != enabled:
                self._generation += 1
                self._events.clear(); self._seen.clear()
            self._enabled=enabled
            self._duration=min(15,max(2,int(duration)))
            self._important_apps=important
            return self.settings()

    def ingest(self, payload):
        if not isinstance(payload,dict):
            raise ValueError('notification payload must be an object')
        with self._lock:
            self._last_bridge = time.monotonic()
            state = str(payload.get('state') or '')
            if state in {'allowed','denied','unspecified','error','identity_required'}:
                self._bridge_state = state
            if state != 'allowed':
                self._events.clear()
            if not self._enabled or state != 'allowed':
                return {'ok': True, 'accepted': 0}
            values = payload.get('notifications', [])
            if not isinstance(values, list):
                raise ValueError('notifications must be a list')
            accepted = 0
            for value in values[:20]:
                if not isinstance(value, dict):
                    continue
                key = str(value.get('id') or '')[:200]
                if not key or key in self._seen:
                    continue
                self._seen.append(key)
                icon = str(value.get('icon') or '')
                if not re.fullmatch(r'data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]{1,90000}', icon):
                    icon = None
                self._sequence += 1
                app = str(value.get('app') or '不明なアプリ')[:100]
                created = value.get('created_at')
                if not isinstance(created,(int,float)) or isinstance(created,bool) or not math.isfinite(created):
                    created = None
                event = {'sequence': self._sequence, 'app': app,
                         'title': str(value.get('title') or '')[:180],
                         'body': str(value.get('body') or '')[:350], 'created_at': created,
                         'received_at': time.time(), 'icon': icon,
                         'priority': 'important' if app.casefold() in {name.casefold() for name in self._important_apps} else 'normal'}
                self._events.append(event); accepted += 1
            return {'ok':True,'accepted':accepted}

    def events(self, cursor, mode='INFO'):
        with self._lock:
            now=time.time()
            while self._events and now-self._events[0]['received_at']>60:
                self._events.popleft()
            items=[]
            # Already authenticated notifications remain valid until retention expiry,
            # even if a busy PC misses a bridge heartbeat. Revocation clears them in ingest().
            if self._enabled and self._bridge_state=='allowed' and mode!='CHAT':
                items=[dict(item) for item in self._events if item['sequence']>cursor]
            return {'ok':True,'cursor':self._sequence,'notifications':items,'enabled':self._enabled, 'bridge_state':self.settings()['bridge_state']}

    def connect(self, port, launch=True):
        """Windows側の登録済みアプリを、利用者が設定ボタンを押した時だけ開く。"""
        if os.name != 'nt':
            return {'ok':False,'error':'Windows専用の機能です。'}
        project=Path(__file__).resolve().parents[1]/'native'/'NotificationBridge'
        directory=project/'publish'
        registration=project/'bridge-registration.json'
        if not registration.exists() or not (directory/'NotificationBridge.exe').exists():
            return {'ok':False,'error':'通知補助アプリの登録が必要です。native/NotificationBridge/Install.ps1 を実行してください。','setup_required':True}
        info=json.loads(registration.read_text(encoding='utf-8-sig'))
        app_id=str(info.get('app_user_model_id') or '')
        if not re.fullmatch(r'[A-Za-z0-9._-]+![A-Za-z0-9._-]+',app_id):
            raise ValueError('補助アプリの登録情報が不正です。')
        configuration=directory/'bridge-config.json'
        configuration.write_text(json.dumps({'endpoint':f'http://127.0.0.1:{int(port)}','token':self._token}),encoding='utf-8')
        self._configuration_path=configuration
        if launch:
            os.startfile('shell:AppsFolder\\'+app_id)
        return {'ok':True,'message':'補助アプリの画面で通知アクセスを許可してください。'}


notification_hub=NotificationHub()
