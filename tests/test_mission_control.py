"""Mission persistence, tool contracts, unit math and connector boundaries."""
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from functions import mission_control as mc

@pytest.fixture(autouse=True)
def isolate(tmp_path,monkeypatch):
    monkeypatch.setattr(mc,'STORE_PATH',tmp_path/'mission.json')
    monkeypatch.chdir(tmp_path)
    for key in ['JARVIS_HOME_URL','JARVIS_HOME_TOKEN','JARVIS_GRAPH_TOKEN']:
        monkeypatch.delenv(key,raising=False)


def test_board_persistence_edit_complete_import_and_corruption():
    result=mc.board('add',{'title':'実験','priority':'high'})
    item=result['items'][0];assert result['revision']==1
    result=mc.board('update',{'id':item['id'],'title':'再実験','kind':'reminder','due':'2026-11-01T12:00:00+09:00'})
    assert result['items'][0]['due']=='2026-11-01T03:00:00+00:00'
    mc.board('ack',{'id':item['id']})
    mc.board('update',{'id':item['id'],'title':'再実験','kind':'reminder','due':'2026-11-02T12:00:00+09:00'})
    assert not mc.board()['items'][0].get('acknowledged')
    assert mc.board('toggle',{'id':item['id']})['items'][0]['done']
    result=mc.board('import',{'items':result['items']});assert len(result['items'])==2
    assert result['items'][0]['id']!=result['items'][1]['id']
    mc.board('delete',{'id':item['id']});assert len(mc.board()['items'])==1
    original=mc.STORE_PATH.read_text(encoding="utf-8")
    with pytest.raises(ValueError):mc.board('import',{'items':[{'title':'valid'},{'title':''}]})
    assert mc.STORE_PATH.read_text(encoding="utf-8")==original
    mc.STORE_PATH.write_text('broken')
    with pytest.raises(ValueError):mc.board('add',{'title':'never overwrite'})
    assert mc.STORE_PATH.read_text(encoding="utf-8")=='broken'


def test_board_concurrent_writes_and_invalid_dates():
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda n:mc.board('add',{'title':str(n)}),range(24)))
    assert len(mc.board()['items'])==24
    for value in ['2026-11-01T13:00','invalid']:
        with pytest.raises(ValueError):mc.board('add',{'title':'X','kind':'event','due':value})


def test_ics_escape_fold_utc():
    mc.board('add',{'title':'日本語予定'*30+';x,\ny','kind':'event','due':'2026-11-01T12:00:00+09:00'})
    raw=mc.calendar_ics();assert 'DTSTART:20261101T030000Z' in raw
    assert all(len(line.encode('utf-8'))<=75 for line in raw.split('\r\n'))
    unfolded=raw.replace('\r\n ','');assert r'\;x\,\ny' in unfolded


@pytest.mark.parametrize('value,a,b,expected',[(1,'km','m',1000),(32,'F','C',0),(1,'GiB','MiB',1024),(60,'km/h','m/s',16.6666666667)])
def test_units(value,a,b,expected):
    assert mc.lab({'action':'convert','value':value,'from':a,'to':b})['result']==pytest.approx(expected)


def test_lab_rejects_code_and_unbounded_math():
    assert mc.lab({'action':'calculate','text':'(128 + 64) / 3'})['result']==64
    for expr in ['__import__("os").getcwd()','9**999999','1/0','(-1)**0.5','2e308+1','[1,2]']:
        with pytest.raises((ValueError,ArithmeticError)):mc.lab({'action':'calculate','text':expr})
    with pytest.raises(ValueError):mc.lab({'action':'convert','from':'kg','to':'m','value':1})
    with pytest.raises(ValueError):mc.lab({'action':'convert','from':'K','to':'C','value':-1})
    result=mc.lab({'action':'text','text':' a\nあ '});assert result['characters']==5 and result['without_whitespace']==2


def test_knowledge_real_documents_and_no_external_send():
    result=mc.import_text({'title':'実験記録','content':'ローカル推論の応答時間は実測する。\nCPU負荷も記録する。'})
    assert result['ok']
    result=mc.knowledge_search('ローカル CPU')
    assert result['matched']==1 and 'CPU' in result['results'][0]['snippet']
    assert mc.knowledge_search('存在しない検索')['matched']==0


def test_connectors_unconfigured_and_actions_blocked():
    assert not mc.systems()['connections']['home_configured']
    with pytest.raises(ValueError):mc.home_request({'action':'states'})
    with pytest.raises(ValueError):mc.graph_read('mail')
    with pytest.raises(ValueError):mc.device_action('shutdown')


def test_home_service_contract_and_confirmation(monkeypatch):
    monkeypatch.setenv('JARVIS_HOME_URL','http://home.test:8123')
    monkeypatch.setenv('JARVIS_HOME_TOKEN','secret')
    with patch.object(mc,'_json_request',return_value=[]) as request:
        with pytest.raises(ValueError):mc.home_request({'action':'turn_on','entity':'light.desk'})
        with pytest.raises(ValueError):mc.home_request({'action':'turn_on','entity':'lock.front','confirmed':True})
        request.assert_not_called()
        assert mc.home_request({'action':'turn_on','entity':'light.desk','confirmed':True})['ok']
        assert request.call_args.args==('http://home.test:8123/api/services/light/turn_on','secret',{'entity_id':'light.desk'})


def test_vision_validates_local_host_image_and_model(monkeypatch):
    monkeypatch.setattr(mc.config,'OLLAMA_HOST','https://remote.example')
    with pytest.raises(ValueError):mc.vision_models()
    monkeypatch.setattr(mc.config,'OLLAMA_HOST','http://localhost:11434')
    with pytest.raises(ValueError):mc.vision_analyze({'image':'not image'})
    encoded=base64.b64encode(b'\x89PNG\r\n\x1a\nxxx').decode()
    with patch.object(mc,'vision_models',return_value={'models':['vision-model']}),patch.object(mc,'_json_request',return_value={'message':{'content':'画像の説明'}}) as request:
        result=mc.vision_analyze({'image':encoded,'model':'vision-model','prompt':'文字を読んで'})
        assert result['source']=='local_ollama'
        assert request.call_args.kwargs['payload']['messages'][1]['images']==[encoded]
        assert not mc.STORE_PATH.exists()


def test_news_fixed_sources_xml_contract_and_no_entities():
    import io
    xml=b'<rss><channel><item><title>Actual feed title</title><link>https://example.com/news</link><pubDate>Sun, 01 Nov 2026</pubDate></item></channel></rss>'
    class Opener:
        def open(self,request,timeout=0):
            assert request.full_url==mc.NEWS_FEEDS['bbc_world'][1]
            assert request.get_header('Authorization') is None
            return io.BytesIO(xml)
    with patch.object(mc,'build_opener',return_value=Opener()):
        assert mc.news_read('bbc_world')['items'][0]['title']=='Actual feed title'
        with pytest.raises(ValueError):mc.news_read('http://127.0.0.1')
        xml=b'<!DOCTYPE rss [<!ENTITY x "bad">]><rss />'
        with pytest.raises(ValueError):mc.news_read('bbc_world')
