"""Real iCalendar round trips and offline phone operation state; no real account writes."""
import json
from datetime import datetime,timezone
from unittest.mock import patch
import pytest
from functions import apple_sync as a

ICS='''BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Test//JA\r
BEGIN:VEVENT\r
UID:one\r
DTSTART;VALUE=DATE:20261101\r
DTEND;VALUE=DATE:20261102\r
SUMMARY:終日テスト\r
DESCRIPTION:メモ\r
END:VEVENT\r
BEGIN:VTODO\r
UID:two\r
SUMMARY:提出\r
DUE:20261102T030000Z\r
PRIORITY:1\r
STATUS:NEEDS-ACTION\r
END:VTODO\r
END:VCALENDAR\r
'''

@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(a,'PATH',tmp_path/'apple.json');monkeypatch.setattr(a,'CREDS',None);monkeypatch.setattr(a,'COLLECTIONS',{})

def test_ics_import_preview_dedupe_edit_export_delete_conflict():
    assert a.import_file({'name':'test.ics','content':ICS,'dry_run':True})['count']==2
    assert not a.PATH.exists()
    a.import_file({'name':'test.ics','content':ICS})
    a.import_file({'name':'test.ics','content':ICS});assert len(a.view()['items'])==2
    item=next(i for i in a.view()['items'] if i['kind']=='event')
    a.mutate({'action':'update','id':item['id'],'revision':item['revision'],'item':{**item,'title':'変更した予定'}})
    with pytest.raises(a.Conflict):a.mutate({'action':'delete','id':item['id'],'revision':item['revision']})
    with pytest.raises(a.Conflict):a.import_file({'name':'test.ics','content':ICS})
    raw=a.export_ics();assert '変更した予定' in raw and 'VALUE=DATE:20261101' in raw
    assert len(a.parse_ics(raw,'roundtrip'))==2
    item=next(i for i in a.view()['items'] if i['kind']=='event')
    a.mutate({'action':'delete','id':item['id'],'revision':item['revision']});assert len(a.view()['items'])==1


def test_local_create_idempotency_and_reminder_complete():
    values={'kind':'reminder','title':'課題','due':'2026-11-01T12:00:00+09:00'}
    request={'action':'create','source_id':'local-reminders','client_id':'same-id-1234','item':values}
    a.mutate(request)
    with pytest.raises(a.Conflict):a.mutate(request)
    item=a.view()['items'][0];a.mutate({'action':'update','id':item['id'],'revision':item['revision'],'item':{**item,'completed':True}})
    assert 'STATUS:COMPLETED' in a.export_ics()


def test_recurrence_expansion_and_protected_series():
    raw=ICS.replace('DTSTART;VALUE=DATE:20261101','RRULE:FREQ=DAILY;COUNT=3\r\nDTSTART;VALUE=DATE:20261101')
    a.import_file({'name':'repeat.ics','content':raw})
    item=next(i for i in a.view()['items'] if i['kind']=='event');assert item['recurring']
    result=a.occurrences({'start':'2026-11-01T00:00:00Z','end':'2026-12-01T00:00:00Z'})
    assert len(result['occurrences'])==3
    with pytest.raises(ValueError):a.mutate({'action':'update','id':item['id'],'revision':item['revision'],'item':{**item,'title':'変更'}})
    a.mutate({'action':'update','id':item['id'],'revision':item['revision'],'series_confirmed':True,'item':{**item,'title':'変更'}})
    assert 'RRULE:FREQ=DAILY;COUNT=3' in a.export_ics()


def phone_snapshot(title='元の用件'):
    return {'version':1,'type':'ai-iphone-snapshot','created_at':a.now(),'calendars':[{'id':'native-list','kind':'reminder','name':'iPhoneの用件','writable':True}],
            'items':[{'remote_id':'native-id','calendar_id':'native-list','kind':'reminder','title':title,'due':'','priority':0}], 'acknowledgments':[]}


def test_phone_full_file_round_trip_pending_ack_and_duplicate_result():
    a.import_phone(phone_snapshot())
    original=a.view()['items'][0]
    a.mutate({'action':'update','id':original['id'],'revision':original['revision'],'item':{**original,'title':'PCで更新'}})
    assert a.view()['items'][0]['sync_status']=='pending'
    exported=a.export_jobs();assert exported['jobs'][0]['action']=='update' and 'before' not in exported['jobs'][0]
    assert a.view()['jobs'][0]['status']=='exported'
    with pytest.raises(a.Conflict):a.cancel_job({'id':exported['jobs'][0]['id']})
    a.import_phone(phone_snapshot());assert a.view()['items'][0]['title']=='PCで更新'
    result=phone_snapshot('PCで更新');result['acknowledgments']=[{'id':exported['jobs'][0]['id'],'ok':True,'remote_id':'native-id','item':{**a.view()['items'][0],'title':'PCで更新'}}]
    a.import_phone(result);a.import_phone(result)
    assert len(a.view()['items'])==1 and a.view()['items'][0]['sync_status']=='synced'
    item=a.view()['items'][0];a.mutate({'action':'delete','id':item['id'],'revision':item['revision']});assert not a.view()['items']
    exported=a.export_jobs();assert exported['jobs'][0]['action']=='delete'
    result=phone_snapshot();result['items']=[];result['acknowledgments']=[{'id':exported['jobs'][0]['id'],'ok':True}]
    a.import_phone(result);assert not a.view()['items']


def test_phone_add_failure_cancel_and_snapshot_revision():
    a.import_phone(phone_snapshot());first=a.view()['items'][0]
    a.import_phone(phone_snapshot());assert a.view()['items'][0]['revision']>first['revision']
    source=a.view()['items'][0]['source_id']
    a.mutate({'action':'create','source_id':source,'item':{'kind':'reminder','title':'新しい用件'}})
    job=a.export_jobs()['jobs'][0];a.acknowledge({'id':job['id'],'ok':False,'error':'端末で変更されています'})
    assert any(i['sync_status']=='failed' for i in a.view()['items'])
    a.cancel_job({'id':job['id']});assert len(a.view()['items'])==1


def test_cloud_write_etag_and_credentials_are_not_exposed():
    with a.LOCK:
        state=a.load();state['sources']['icloud-test']={'id':'icloud-test','name':'test','provider':'icloud','kind':'event','writable':True};a.save(state)
    a.COLLECTIONS['icloud-test']={'url':'https://p01-caldav.icloud.com/test/'};a.CREDS=('account@example.com','secret')
    with patch.object(a,'_dav',return_value=(201,b'',{'ETag':'"v1"'})) as dav:
        a.mutate({'action':'create','source_id':'icloud-test','item':{'kind':'event','title':'試験','start':'2026-11-01T00:00:00Z','end':'2026-11-01T01:00:00Z'}})
        assert dav.call_args.args[3]=={'If-None-Match':'*'}
    item=a.view()['items'][0];assert 'secret' not in json.dumps(a.view()) and 'url' not in item
    with patch.object(a,'_dav',side_effect=a.Conflict('412')) as dav:
        with pytest.raises(a.Conflict):a.mutate({'action':'delete','id':item['id'],'revision':item['revision']})
        assert dav.call_args.args[3]=={'If-Match':'"v1"'}
    assert len(a.view()['items'])==1
    for url in ['http://caldav.icloud.com','https://icloud.com.attacker.test/','https://evil.test/','https://user@caldav.icloud.com/']:
        with pytest.raises(ValueError):a._safe_url(url)
    a.logout();assert a.CREDS is None


def test_old_phone_snapshot_does_not_replace_newer_data():
    old=phone_snapshot('古い');old['created_at']='2026-11-01T00:00:00Z'
    fresh=phone_snapshot('新しい');fresh['created_at']='2026-11-01T01:00:00Z'
    a.import_phone(fresh)
    with pytest.raises(a.Conflict):a.import_phone(old)
    assert a.view()['items'][0]['title']=='新しい'
