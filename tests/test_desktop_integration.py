"""時計と通知の境界・認証・非保存・抑制を検証する。OS通知は取得しない。"""
from datetime import datetime, timedelta, timezone
import json
import math
import pytest
from functions import desktop_integration as desktop


def event(id='one',**values):
    return {'id':id,'app':'Mail','title':'通知テスト','body':'UI検証用の本文',**values}


def allowed(hub,*events):
    return hub.ingest({'state':'allowed','notifications':list(events)})


def test_default_off_and_no_notification_content_is_saved(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    hub=desktop.NotificationHub()
    assert not hub.settings()['enabled'] and hub.settings()['duration_sec']==5
    assert allowed(hub,event())['accepted']==0
    assert hub.events(0,'INFO')['notifications']==[]
    assert list(tmp_path.iterdir())==[]
    assert hub._token not in json.dumps(hub.settings())


def test_enable_disable_generation_and_memory_clear():
    hub=desktop.NotificationHub(); before=hub.settings()['generation']
    hub.configure({'enabled':True}); assert hub.settings()['generation']==before+1
    assert allowed(hub,event())['accepted']==1
    hub.configure({'enabled':False})
    assert not hub._events and not hub.events(0,'INFO')['notifications']


def test_chat_mode_consumes_cursor_without_delivering_text():
    hub=desktop.NotificationHub();hub.configure({'enabled':True});allowed(hub,event())
    chat=hub.events(0,'CHAT');assert chat['notifications']==[] and chat['cursor']==1
    assert hub.events(chat['cursor'],'INFO')['notifications']==[]
    allowed(hub,event('two'))
    assert hub.events(chat['cursor'],'SEARCH')['notifications'][0]['sequence']==2


def test_duplicate_notifications_and_priority_and_icon():
    hub=desktop.NotificationHub();hub.configure({'enabled':True,'important_apps':['mail']})
    assert allowed(hub,event(icon='https://external.example/icon.png'))['accepted']==1
    assert allowed(hub,event())['accepted']==0
    result=hub.events(0,'INFO')['notifications'][0]
    assert result['priority']=='important' and result['icon'] is None


def test_revoked_permission_stops_content_delivery():
    hub=desktop.NotificationHub();hub.configure({'enabled':True});allowed(hub,event())
    hub.ingest({'state':'denied','notifications':[]})
    assert hub.events(0,'INFO')['notifications']==[]
    assert hub.settings()['bridge_state']=='denied'


def test_old_notifications_expire_without_history(monkeypatch):
    hub=desktop.NotificationHub();hub.configure({'enabled':True})
    monkeypatch.setattr(desktop.time,'time',lambda:1000)
    allowed(hub,event())
    monkeypatch.setattr(desktop.time,'time',lambda:1061)
    assert hub.events(0,'INFO')['notifications']==[] and not hub._events


def test_settings_validation_is_atomic():
    hub=desktop.NotificationHub()
    with pytest.raises(ValueError):hub.configure({'enabled':True,'duration_sec':float('nan')})
    assert not hub.settings()['enabled']
    with pytest.raises(ValueError):hub.configure({'enabled':'true'})
    assert hub.configure({'duration_sec':999})['duration_sec']==15
    assert hub.configure({'duration_sec':1})['duration_sec']==2


def test_bridge_authentication_does_not_accept_empty_or_wrong_token():
    hub=desktop.NotificationHub()
    assert not hub.authorized(None) and not hub.authorized('Bearer wrong')
    assert hub.authorized('Bearer '+hub._token)


def test_clock_uses_backend_datetime_timezone(monkeypatch):
    now=datetime(2026,10,30,23,59,59,tzinfo=timezone(timedelta(hours=5,minutes=30)))
    class LocalDate:
        def astimezone(self):return now
    class Clock:
        @staticmethod
        def now():return LocalDate()
    monkeypatch.setattr(desktop,'datetime',Clock)
    value=desktop.system_clock()
    assert value['epoch_ms']==now.timestamp()*1000
    assert value['utc_offset_minutes']==330
    assert value['source']=='backend_pc'


def test_buffered_notification_survives_missed_heartbeat_but_not_revocation():
    from functions.desktop_integration import NotificationHub
    from unittest.mock import patch
    hub=NotificationHub()
    hub.configure({'enabled':True})
    with patch('functions.desktop_integration.time.monotonic',return_value=100):
        hub.ingest({'state':'allowed','notifications':[{'id':'buffered','title':'accepted'}]})
    with patch('functions.desktop_integration.time.monotonic',return_value=110):
        assert not hub.settings()['connected']
        assert len(hub.events(0)['notifications'])==1
        hub.ingest({'state':'denied','notifications':[]})
        assert not hub.events(0)['notifications']
