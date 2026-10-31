"""Apple calendars and explicit offline iPhone reminder file exchange."""
from __future__ import annotations
import base64
import copy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import uuid4
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

PATH=Path(__file__).resolve().parents[1]/'data'/'apple_agenda.json'
LOCK=threading.RLock()
D='{DAV:}';C='{urn:ietf:params:xml:ns:caldav}'
CREDS=None
COLLECTIONS={}
FIELDS=('kind','calendar_id','title','notes','location','start','end','due','all_day','completed','priority','due_has_time')
class Conflict(ValueError):pass
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def now():return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
def digest(value):return hashlib.sha256(str(value).encode()).hexdigest()
def _libraries():
    try:
        import icalendar
        return icalendar
    except ImportError:raise ValueError('icalendarをrequirements.txtからインストールしてください。')
def default_sources():
    return {key:{'id':key,'name':label,'provider':'upload','kind':kind,'writable':True} for key,label,kind in [('local-events','PC内カレンダー（iPhone未反映）','event'),('local-reminders','PC内リマインダー（iPhone未反映）','reminder')]}
def load():
    if not PATH.exists():return {'version':1,'sources':default_sources(),'items':{},'jobs':[],'iphone_mode':'file'}
    try:
        result=json.loads(PATH.read_text(encoding='utf-8'))
        if result.get('version')!=1 or not isinstance(result.get('items'),dict):raise ValueError()
        result['sources']={**default_sources(),**result['sources']}
        return result
    except (OSError,ValueError,AttributeError):raise ValueError('Apple予定の保存ファイルを読み取れません。上書きせず復旧してください。')
def save(state):
    PATH.parent.mkdir(parents=True,exist_ok=True);temp=PATH.with_suffix('.tmp')
    temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    for attempt in range(6):
        try:os.replace(temp,PATH);break
        except PermissionError:
            if attempt==5:raise
            time.sleep(.03*(attempt+1))
def timestamp(value):
    if not value:return ''
    try:
        v=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if v.tzinfo is None:raise ValueError()
        return v.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
    except (ValueError,TypeError):raise ValueError('日時はタイムゾーン付きで指定してください。')
def normalized(data):
    result={key:data.get(key) for key in FIELDS}
    result.update(kind=data.get('kind','event'),calendar_id=str(data.get('calendar_id') or '')[:512],
      title=str(data.get('title') or '').strip(),notes=str(data.get('notes') or ''),location=str(data.get('location') or ''),
      all_day=data.get('all_day') is True,due_has_time=data.get('due_has_time',True) is True,completed=data.get('completed') is True,priority=int(data.get('priority') or 0))
    if result['kind'] not in {'event','reminder'} or not result['title'] or len(result['title'])>300 or len(result['notes'])>10000 or len(result['location'])>1000:raise ValueError('件名・種類・文字数を確認してください。')
    if not 0<=result['priority']<=9:raise ValueError('優先度は0〜9です。')
    if result['kind']=='event':
        if result['all_day']:
            result['start']=date.fromisoformat(str(data.get('start'))).isoformat();result['end']=date.fromisoformat(str(data.get('end'))).isoformat()
        else:result['start']=timestamp(data.get('start'));result['end']=timestamp(data.get('end'))
        if not result['start'] or not result['end'] or result['end']<=result['start']:raise ValueError('終了は開始より後に指定してください。終日の終了日は翌日以降です。')
        result['due']=''
    else:
        result['start']=result['end']='';result['location']='';result['due']=timestamp(data.get('due'))
        result['all_day']=False
    return result

def visible(item):return {k:v for k,v in item.items() if k not in {'ics','url','remote_etag'}}
def view():
    with LOCK:
        state=load()
        return {'ok':True,'sources':list(state['sources'].values()),'items':[visible(v) for v in state['items'].values() if not v.get('deleted')],
                'jobs':[{k:j.get(k) for k in ['id','action','status','error','created_at','title']} for j in state['jobs'][-200:]],
                'connected':CREDS is not None,'iphone_mode':'file','server_time':now()}

def _date_property(component,key,tz):
    value=component.get(key)
    if value is None:return ''
    value=value.dt
    if isinstance(value,datetime):
        if value.tzinfo is None:value=value.replace(tzinfo=tz)
        return timestamp(value.isoformat())
    if isinstance(value,date):return value.isoformat()
    return ''

def parse_ics(raw,source_id,calendar_id='',tz_name='Asia/Tokyo'):
    lib=_libraries()
    if len(raw.encode('utf-8'))>1500000:raise ValueError('ICSは1.5MBまでです。')
    tz=ZoneInfo(tz_name);cal=lib.Calendar.from_ical(raw)
    if cal.name!='VCALENDAR':raise ValueError('VCALENDAR形式を選択してください。')
    groups={}
    for component in cal.subcomponents:
        if component.name in {'VEVENT','VTODO'}:
            uid=str(component.get('UID') or '')
            if not uid or len(uid)>512:raise ValueError('UIDのない予定が含まれています。')
            groups.setdefault(uid,[]).append(component)
    if len(groups)>2000:raise ValueError('取込は2000件までです。')
    result=[]
    for uid,components in groups.items():
        master=next((c for c in components if not c.get('RECURRENCE-ID')),components[0])
        kind='event' if master.name=='VEVENT' else 'reminder'
        start=_date_property(master,'DTSTART',tz);end=_date_property(master,'DTEND',tz);due=_date_property(master,'DUE',tz)
        all_day=bool(start and len(start)==10)
        if kind=='event' and not end:
            duration=master.get('DURATION')
            if duration and start:
                end=((date.fromisoformat(start) if all_day else datetime.fromisoformat(start.replace('Z','+00:00')))+duration.dt).isoformat()
                if not all_day:end=timestamp(end)
            elif all_day:end=(date.fromisoformat(start)+timedelta(days=1)).isoformat()
            else:end=timestamp((datetime.fromisoformat(start.replace('Z','+00:00'))+timedelta(hours=1)).isoformat())
        if kind=='reminder' and due and len(due)==10:due=timestamp(datetime.combine(date.fromisoformat(due),datetime.min.time(),tzinfo=tz).isoformat())
        one=lib.Calendar()
        for key,value in cal.items():one[key]=copy.deepcopy(value)
        for sub in cal.subcomponents:
            if sub.name=='VTIMEZONE':one.add_component(copy.deepcopy(sub))
        for sub in components:one.add_component(copy.deepcopy(sub))
        item=normalized({'kind':kind,'calendar_id':calendar_id,'title':str(master.get('SUMMARY') or '(件名なし)'),
             'notes':str(master.get('DESCRIPTION') or ''),'location':str(master.get('LOCATION') or ''),'start':start,'end':end,'due':due,'all_day':all_day,
             'due_has_time':not bool(master.get('DUE') and isinstance(master['DUE'].dt,date) and not isinstance(master['DUE'].dt,datetime)),
             'completed':str(master.get('STATUS') or '')=='COMPLETED','priority':int(master.get('PRIORITY') or 0)})
        item.update(id=digest(source_id+'|'+uid),source_id=source_id,remote_id=uid,ics=one.to_ical().decode(),revision=1,
                    recurring=bool(master.get('RRULE') or len(components)>1 or master.get('RECURRENCE-ID')),readonly=bool(master.get('ATTENDEE')),
                    sync_status='file',updated_at=now())
        result.append(item)
    return result

def import_file(data):
    name=str(data.get('name') or 'アップロード')[:150];mode=data.get('format','ics')
    source_id='upload-'+digest(name)[:16]
    if mode=='ics':items=parse_ics(str(data.get('content') or ''),source_id,tz_name=data.get('timezone','Asia/Tokyo'))
    elif mode=='json':
        value=data.get('content');value=json.loads(value) if isinstance(value,str) else value
        if not isinstance(value,dict) or value.get('version')!=1 or not isinstance(value.get('items'),list) or len(value['items'])>2000:raise ValueError('version:1とitems配列を持つJSONを指定してください。')
        items=[]
        for entry in value['items']:
            item=normalized(entry);uid=str(entry.get('remote_id') or entry.get('id') or uuid4().hex)[:512]
            item.update(id=digest(source_id+'|'+uid),source_id=source_id,remote_id=uid,revision=1,recurring=bool(entry.get('recurring')),readonly=bool(entry.get('readonly')),sync_status='file',updated_at=now())
            items.append(item)
    else:raise ValueError('ICSまたはJSONを選択してください。')
    if len({i['id'] for i in items})!=len(items):raise ValueError('同じUIDの項目が重複しています。')
    if data.get('dry_run') is True:return {'ok':True,'preview':[visible(i) for i in items],'count':len(items)}
    with LOCK:
        state=load()
        if any(state['items'].get(i['id'],{}).get('sync_status')=='file-edited' for i in items):raise Conflict('UIで編集済みのファイルがあります。別のファイル名で取り込んで比較してください。')
        for item in items:
            old=state['items'].get(item['id']);item['revision']=old['revision']+1 if old else 1;state['items'][item['id']]=item
        state['sources'][source_id]={'id':source_id,'name':name,'provider':'upload','kind':'mixed','writable':True,'updated_at':now()}
        save(state)
    return {'ok':True,'imported':len(items)}

def _ics_update(old,values):
    lib=_libraries()
    if old and old.get('ics'):cal=lib.Calendar.from_ical(old['ics'])
    else:
        cal=lib.Calendar();cal.add('prodid','-//Sotuken//Apple Agenda//JA');cal.add('version','2.0')
        comp=lib.Event() if values['kind']=='event' else lib.Todo();comp.add('uid',old.get('remote_id') if old else uuid4().hex);cal.add_component(comp)
    components=[c for c in cal.subcomponents if c.name in {'VEVENT','VTODO'}]
    master=next((c for c in components if not c.get('RECURRENCE-ID')),components[0])
    for comp in components:
        for key,field in [('SUMMARY','title'),('DESCRIPTION','notes'),('LOCATION','location')]:comp.pop(key,None);comp.add(key,values[field])
    if old and old.get('recurring') and any(old.get(k)!=values[k] for k in ['start','end','due','all_day']):raise ValueError('繰り返し予定の日時変更は対象外です。名前・メモ・場所の変更、シリーズ全体の削除に対応します。')
    if not old or not old.get('recurring'):
        for key in ['DTSTART','DTEND','DUE','DURATION']:master.pop(key,None)
        if values['kind']=='event':
            for key,field in [('DTSTART','start'),('DTEND','end')]:master.add(key,date.fromisoformat(values[field]) if values['all_day'] else datetime.fromisoformat(values[field].replace('Z','+00:00')))
        elif values['due']:master.add('due',datetime.fromisoformat(values['due'].replace('Z','+00:00')) if values.get('due_has_time',True) else datetime.fromisoformat(values['due'].replace('Z','+00:00')).astimezone(ZoneInfo('Asia/Tokyo')).date())
    if values['kind']=='reminder':
        master.pop('status',None);master.add('status','COMPLETED' if values['completed'] else 'NEEDS-ACTION')
        master.pop('priority',None);master.add('priority',values['priority'])
        master.pop('completed',None)
        if values['completed']:master.add('completed',datetime.now(timezone.utc))
    master.pop('dtstamp',None);master.add('dtstamp',datetime.now(timezone.utc));master.pop('sequence',None);master.add('sequence',int((old or {}).get('revision',0))+1)
    return cal.to_ical().decode()


def mutate(data):
    action=data.get('action');identifier=str(data.get('id') or '')
    if action not in {'create','update','delete'}:raise ValueError('操作を確認してください。')
    with LOCK:
        state=load();old=state['items'].get(identifier) if identifier else None
        if action!='create' and (not old or old.get('deleted')):raise Conflict('対象がありません。再取得してください。')
        if old and int(data.get('revision',-1))!=old['revision']:raise Conflict('別の操作で更新されています。再取得してから編集してください。')
        source_id=old['source_id'] if old else str(data.get('source_id') or '')
        source=state['sources'].get(source_id)
        if not source or not source.get('writable'):raise ValueError('書き込み可能な保存先を選択してください。')
        if old and old.get('readonly'):raise ValueError('招待・読取専用・繰り返しなど、この項目は表示のみ対応しています。')
        if old and old.get('sync_status') in {'pending','failed','exported'}:raise Conflict('iPhoneへの反映待ちです。同期または取消後に編集してください。')
        if old and old.get('recurring') and data.get('series_confirmed') is not True:raise ValueError('シリーズ全体への操作であることを確認してください。')
        values=normalized(data.get('item') or old or {}) if action!='delete' else {k:old[k] for k in FIELDS}
        if old and old['kind']!=values['kind']:raise ValueError('予定とリマインダーの種類は変更できません。')
        if source['kind'] not in {'mixed',values['kind']}:raise ValueError('選択した保存先の種類と一致しません。')
        identifier=identifier if old else str(data.get('client_id') or uuid4().hex)
        if not old and not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',identifier):raise ValueError('追加要求のIDが不正です。')
        if not old and identifier in state['items']:raise Conflict('同じ追加要求は保存済みです。再取得してください。')
        item={**(old or {}),**values,'id':identifier,'source_id':source_id,'remote_id':old['remote_id'] if old else 'ai-'+identifier,
              'revision':old['revision']+1 if old else 1,'updated_at':now(),'recurring':bool((old or {}).get('recurring')),'readonly':False}
        if source['provider']=='icloud':
            raw=None if action=='delete' else _ics_update(old,values)
            url=old['url'] if old else urljoin(COLLECTIONS.get(source_id,{}).get('url',''),quote(item['remote_id'])+'.ics')
            if not COLLECTIONS.get(source_id):raise ValueError('iCloudへ再接続してください。')
            headers={'If-Match':old['remote_etag']} if old else {'If-None-Match':'*'}
            if old and not old.get('remote_etag'):raise Conflict('ETagを取得してから操作してください。')
            response,body,resp_headers=_dav(url,'DELETE' if action=='delete' else 'PUT',raw,headers)
            if action!='delete':
                etag=resp_headers.get('ETag')
                item.update(ics=raw,url=url,remote_etag=etag,sync_status='synced')
        elif source['provider']=='iphone':
            if len([j for j in state['jobs'] if j['status'] in {'pending','failed','exported'}])>=200:raise ValueError('反映待ちが200件あります。先にiPhoneで同期してください。')
            item['calendar_id']=source['native_id'];item['sync_status']='pending';item['deleted']=action=='delete'
            job={'id':uuid4().hex,'action':action,'status':'pending','item_id':identifier,'title':item['title'],'created_at':now(),
                 'base':{k:old.get(k) for k in FIELDS} if old else None,'remote_id':old['remote_id'] if old else '',
                 'item':{k:item[k] for k in FIELDS},'before':copy.deepcopy(old)}
            state['jobs'].append(job)
        else:
            item['sync_status']='file-edited'
            if action!='delete':item['ics']=_ics_update(old,values)
        if action=='delete' and source['provider']!='iphone':state['items'].pop(identifier,None)
        else:state['items'][identifier]=item
        state['jobs']=[j for j in state['jobs'] if j['status'] in {'pending','failed','exported'}]+[j for j in state['jobs'] if j['status'] in {'done','cancelled'}][-200:];save(state)
        return {'ok':True,'sync_status':item.get('sync_status','synced')}


def export_ics(source_id=''):
    lib=_libraries();cal=lib.Calendar();cal.add('prodid','-//Sotuken//Apple Agenda//JA');cal.add('version','2.0');zones=set()
    with LOCK:items=list(load()['items'].values())
    for item in items:
        if item.get('deleted') or source_id and item['source_id']!=source_id:continue
        raw=item.get('ics') or _ics_update(None,item)
        for sub in lib.Calendar.from_ical(raw).subcomponents:
            if sub.name=='VTIMEZONE':
                tz=str(sub.get('TZID'))
                if tz in zones:continue
                zones.add(tz)
            cal.add_component(sub)
    return cal.to_ical().decode()


def _safe_url(url):
    p=urlparse(url)
    if p.scheme!='https' or not (p.hostname=='caldav.icloud.com' or (p.hostname or '').endswith('.icloud.com')) or p.username or p.password or p.port not in {None,443}:raise ValueError('iCloud以外の接続先には認証情報を送信できません。')
    return url

def _dav(url,method,body=None,headers=None,redirects=0):
    _safe_url(url)
    if CREDS is None:raise ValueError('iCloudへ接続してください。')
    auth=base64.b64encode((CREDS[0]+':'+CREDS[1]).encode()).decode()
    hdr={'Authorization':'Basic '+auth,'User-Agent':'Sotuken-Calendar/1.0','Content-Type':'text/calendar; charset=utf-8' if method=='PUT' else 'application/xml; charset=utf-8',**(headers or {})}
    request=Request(url,data=body.encode() if isinstance(body,str) else body,headers=hdr,method=method)
    try:
        with build_opener(NoRedirect()).open(request,timeout=20) as response:
            content=response.read(4000001)
            if len(content)>4000000:raise ValueError('応答が大きすぎます。期間を短くしてください。')
            return response.status,content,response.headers
    except HTTPError as error:
        if error.code in {301,302,303,307,308} and redirects<3:
            target=_safe_url(urljoin(url,error.headers.get('Location','')))
            return _dav(target,method,body,headers,redirects+1)
        if error.code==412:raise Conflict('iPhone側で変更されています。再取得してから編集してください。')
        if error.code in {401,403}:raise ValueError('認証または書込権限を確認してください。App用パスワードを使用します。')
        raise ValueError('iCloudとの通信に失敗しました（HTTP '+str(error.code)+'）。再取得して状態を確認してください。')

def _xml(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('未対応のXMLです。')
    try:return ET.fromstring(raw)
    except ET.ParseError:raise ValueError('iCloudの応答を読み取れませんでした。')
def _propfind(url,props,depth='0'):
    body='<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop>'+props+'</d:prop></d:propfind>'
    return _xml(_dav(url,'PROPFIND',body,{'Depth':depth})[1])
def login(data):
    global CREDS,COLLECTIONS
    email=str(data.get('email') or '').strip();password=str(data.get('password') or '').strip()
    if not email or not password or len(email)>320 or len(password)>100:raise ValueError('Apple AccountとApp用パスワードを入力してください。')
    with LOCK:
        CREDS=(email,password);COLLECTIONS={}
        try:
            base='https://caldav.icloud.com/';root=_propfind(base,'<d:current-user-principal/>')
            href=root.find('.//'+D+'current-user-principal/'+D+'href')
            if href is None:raise ValueError('iCloudの利用者情報を取得できませんでした。')
            principal=_safe_url(urljoin(base,href.text));root=_propfind(principal,'<c:calendar-home-set/>')
            home=root.find('.//'+C+'calendar-home-set/'+D+'href')
            if home is None:raise ValueError('カレンダー領域を取得できませんでした。')
            home=_safe_url(urljoin(principal,home.text));root=_propfind(home,'<d:resourcetype/><d:displayname/><c:supported-calendar-component-set/><d:current-user-privilege-set/>','1')
            sources=[]
            for response in root.findall(D+'response'):
                if response.find('.//'+C+'calendar') is None:continue
                components=response.findall('.//'+C+'comp')
                if not any(c.get('name')=='VEVENT' for c in components):continue
                href=response.findtext(D+'href');url=_safe_url(urljoin(home,href));identifier='icloud-'+digest(url)[:20]
                writable=response.find('.//'+D+'write') is not None or response.find('.//'+D+'all') is not None or response.find('.//'+D+'write-content') is not None
                source={'id':identifier,'name':response.findtext('.//'+D+'displayname') or 'iCloud','provider':'icloud','kind':'event','writable':writable,'updated_at':now()}
                COLLECTIONS[identifier]={'url':url};sources.append(source)
            if not sources:raise ValueError('利用可能なカレンダーがありません。')
            state=load()
            for source in sources:state['sources'][source['id']]=source
            save(state)
            return {'ok':True,'calendars':sources}
        except Exception:
            CREDS=None;COLLECTIONS={};raise

def logout():
    global CREDS,COLLECTIONS
    with LOCK:CREDS=None;COLLECTIONS={}
    return {'ok':True}

def refresh_cloud(data):
    identifier=str(data.get('source_id') or '')
    start=datetime.fromisoformat(timestamp(data.get('start')).replace('Z','+00:00'));end=datetime.fromisoformat(timestamp(data.get('end')).replace('Z','+00:00'))
    if not timedelta(0)<end-start<=timedelta(days=366):raise ValueError('期間は1日〜366日です。')
    with LOCK:
        collection=COLLECTIONS.get(identifier)
        if not collection:raise ValueError('iCloudへ再接続してください。')
        body='<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT"><c:time-range start="'+start.strftime('%Y%m%dT%H%M%SZ')+'" end="'+end.strftime('%Y%m%dT%H%M%SZ')+'"/></c:comp-filter></c:comp-filter></c:filter></c:calendar-query>'
        root=_xml(_dav(collection['url'],'REPORT',body,{'Depth':'1'})[1]);items=[]
        for response in root.findall(D+'response'):
            raw=response.findtext('.//'+C+'calendar-data');href=response.findtext(D+'href');etag=response.findtext('.//'+D+'getetag')
            if not raw or not href:continue
            for item in parse_ics(raw,identifier):
                item.update(url=_safe_url(urljoin(collection['url'],href)),remote_etag=etag,sync_status='synced');items.append(item)
        state=load()
        for key in [k for k,v in state['items'].items() if v['source_id']==identifier]:state['items'].pop(key)
        for item in items:state['items'][item['id']]=item
        state['sources'][identifier].update(updated_at=now(),range_start=timestamp(data['start']),range_end=timestamp(data['end']));save(state)
        return {'ok':True,'count':len(items)}


def snapshot(data,dry_run=False):
    calendars=data.get('calendars');entries=data.get('items')
    if not isinstance(calendars,list) or len(calendars)>100 or not isinstance(entries,list) or len(entries)>3000:raise ValueError('同期データが上限を超えています。')
    captured=timestamp(data.get('created_at')) or now()
    sources={}
    for calendar in calendars:
        native=str(calendar.get('id') or '')[:512];kind=calendar.get('kind')
        if not native or kind not in {'event','reminder'}:raise ValueError('カレンダーの形式が不正です。')
        source_id='iphone-'+digest(kind+'|'+native)[:20]
        sources[(native,kind)]={'id':source_id,'native_id':native,'name':str(calendar.get('name') or '')[:150],'kind':kind,'provider':'iphone',
                                'writable':calendar.get('writable') is True,'updated_at':now(),'snapshot_at':captured}
    incoming={}
    for entry in entries:
        item=normalized(entry);source=sources.get((item['calendar_id'],item['kind']))
        native=str(entry.get('remote_id') or '')[:512]
        if not source or not native:raise ValueError('同期対象のリストまたは項目IDが不明です。')
        identifier=digest(source['id']+'|'+native)
        item.update(id=identifier,source_id=source['id'],remote_id=native,revision=1,recurring=bool(entry.get('recurring')),readonly=bool(entry.get('readonly')),
                    sync_status='synced',updated_at=now())
        if identifier in incoming:raise ValueError('同じ項目IDが重複しています。')
        incoming[identifier]=item
    if dry_run:return {'ok':True,'count':len(incoming),'calendars':list(sources.values()),'preview':[visible(v) for v in incoming.values()]}
    with LOCK:
        state=load()
        for source in sources.values():
            previous=state['sources'].get(source['id'],{}).get('snapshot_at','')
            if previous and captured<previous:raise Conflict('以前より古いiPhoneファイルです。最新のJSONを選択してください。')
        for source in sources.values():state['sources'][source['id']]=source
        active_source_ids={s['id'] for s in sources.values()}
        # Only replace the explicitly selected lists. Pending changes remain until the device ACKs them.
        previous=copy.deepcopy(state['items'])
        for key,item in list(state['items'].items()):
            if item['source_id'] in active_source_ids and item.get('sync_status') not in {'pending','failed','exported'}:
                state['items'].pop(key)
        for key,item in incoming.items():
            pending=next((v for v in state['items'].values() if v['source_id']==item['source_id'] and v['remote_id']==item['remote_id'] and v.get('sync_status') in {'pending','failed','exported'}),None)
            if pending:continue
            old=previous.get(key);item['revision']=(old or {}).get('revision',0)+1;state['items'][key]=item
        save(state)
    return {'ok':True,'count':len(incoming)}

def export_jobs():
    with LOCK:
        state=load();result=[]
        for job in state['jobs']:
            if job['status'] in {'pending','failed','exported'}:
                job['status']='exported'
                result.append({k:v for k,v in job.items() if k!='before'})
        save(state)
        return {'ok':True,'version':1,'type':'ai-iphone-changes','jobs':result,'exported_at':now()}

def import_phone(data):
    if data.get('version')!=1 or data.get('type')!='ai-iphone-snapshot':raise ValueError('iPhone連携スクリプトのスナップショットJSONを選択してください。')
    acks=data.get('acknowledgments',[])
    if not isinstance(acks,list) or len(acks)>200:raise ValueError('反映結果の形式が不正です。')
    snapshot(data)
    for result in acks:acknowledge(result)
    snapshot(data)
    return {'ok':True,'count':len(data['items']),'acknowledged':len(acks)}

def acknowledge(data):
    with LOCK:
        state=load();job=next((j for j in state['jobs'] if j['id']==data.get('id')),None)
        if not job:raise ValueError('対象の同期操作がありません。')
        if job['status'] in {'done','cancelled'}:return {'ok':True}
        item=state['items'].get(job['item_id'])
        if data.get('ok') is not True:
            job.update(status='failed',error=str(data.get('error') or 'iPhoneで処理できませんでした。')[:300])
            if item:item['sync_status']='failed'
        else:
            job.update(status='done',error='')
            if job['action']=='delete':state['items'].pop(job['item_id'],None)
            else:
                returned=normalized(data.get('item') or {})
                native=str(data.get('remote_id') or '')[:512]
                if not native:raise ValueError('iPhoneの保存先IDがありません。')
                item.update(returned,remote_id=native,sync_status='synced',revision=item['revision']+1,updated_at=now())
                new_id=digest(item['source_id']+'|'+native);state['items'].pop(job['item_id']);item['id']=new_id;state['items'][new_id]=item
        save(state)
    return {'ok':True}

def cancel_job(data):
    with LOCK:
        state=load();job=next((j for j in state['jobs'] if j['id']==data.get('id')),None)
        if not job or job['status'] not in {'pending','failed','exported'}:raise Conflict('取り消せる操作がありません。')
        if job['status']=='exported' and data.get('confirmed_no_apply') is not True:raise Conflict('変更ファイルを書き出しています。iPhoneで未適用であることを確認してください。')
        # A device may already have applied a request whose ACK was lost. Re-sync before retrying.
        if job['before']:state['items'][job['item_id']]=job['before']
        else:state['items'].pop(job['item_id'],None)
        job['status']='cancelled';save(state)
    return {'ok':True,'message':'UIの反映待ちを取り消しました。iPhone側の状態は次の同期で確認してください。'}

def dispatch(action,data):
    if action=='view':return view()
    if action=='login':return login(data)
    if action=='logout':return logout()
    if action=='refresh':return refresh_cloud(data)
    if action=='import':return import_file(data)
    if action=='mutate':return mutate(data)
    if action=='export-jobs':return export_jobs()
    if action=='import-phone':return import_phone(data)
    if action=='preview-phone':return snapshot(data,True)
    if action=='cancel':return cancel_job(data)
    if action=='occurrences':return occurrences(data)
    raise ValueError('対応していないApple連携操作です。')

def occurrences(data):
    import recurring_ical_events
    start=datetime.fromisoformat(timestamp(data.get('start')).replace('Z','+00:00'));end=datetime.fromisoformat(timestamp(data.get('end')).replace('Z','+00:00'))
    if not timedelta(0)<end-start<=timedelta(days=62):raise ValueError('表示期間は62日以内です。')
    with LOCK:items=list(load()['items'].values())
    result=[];limited=False
    for item in items:
        if item.get('deleted') or item['kind']!='event':continue
        raw=item.get('ics')
        if raw and item.get('recurring'):
            cal=_libraries().Calendar.from_ical(raw)
            if any(str(c.get('RRULE',{}).get('FREQ',[''])[0]) in {'SECONDLY','MINUTELY','HOURLY'} for c in cal.subcomponents if c.name=='VEVENT'):
                limited=True;continue
            for comp in recurring_ical_events.of(cal).between(start,end):
                at=_date_property(comp,'DTSTART',ZoneInfo('Asia/Tokyo'));finish=_date_property(comp,'DTEND',ZoneInfo('Asia/Tokyo'))
                result.append({'id':item['id'],'title':str(comp.get('SUMMARY',item['title'])),'start':at,'end':finish,'all_day':len(at)==10,'source_id':item['source_id']})
                if len(result)>=2000:limited=True;break
        else:
            at=item.get('start','');finish=item.get('end','')
            if at and finish and finish[:10]>=start.date().isoformat() and at[:10]<=end.date().isoformat():result.append({k:item[k] for k in ['id','title','start','end','all_day','source_id']})
        if len(result)>=2000:limited=True;break
    return {'ok':True,'occurrences':result,'limited':limited}
