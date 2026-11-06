"""Protect live browser pixels and input from unrelated websites."""
import json
import threading
import urllib.error
import urllib.request
import pytest
from functions.embedded_browser import BrowserService, web_url


@pytest.fixture
def service():
    http = BrowserService(('127.0.0.1',0))
    threading.Thread(target=http.serve_forever,daemon=True).start()
    yield f'http://127.0.0.1:{http.server_port}'
    http.shutdown();http.server_close()


@pytest.mark.parametrize('url', ['file:///C:/secret','javascript:alert(1)',
    'http://127.0.0.1:8000/','http://localhost/','http://192.168.1.1/',
    'https://user:password@example.com/','http://[::1]/'])
def test_internal_and_non_web_destinations_are_rejected(url):
    assert not web_url(url)


def test_public_sites_are_accepted():
    assert web_url('https://www.youtube.com/watch?v=jNQXAC9IVRw')
    assert web_url('https://example.com/')


@pytest.mark.parametrize('headers', [{}, {'Origin':'https://attacker.example','X-Sotuken-Browser':'1'},
    {'Origin':'http://localhost:8000'}])
def test_unrelated_pages_cannot_open_browser(service,headers):
    request=urllib.request.Request(service+'/session',data=b'{}',headers=headers)
    with pytest.raises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
    assert error.value.code==403


def test_frames_require_a_session_token(service):
    request=urllib.request.Request(service+'/frame',headers={
        'Origin':'http://localhost:8000','X-Sotuken-Browser':'1'})
    with pytest.raises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
    assert error.value.code==401


def test_health_identifies_service_and_does_not_expose_browser(service):
    request=urllib.request.Request(service+'/health',headers={
        'Origin':'http://localhost:8000','X-Sotuken-Browser':'1'})
    response=urllib.request.urlopen(request)
    assert response.headers['Cache-Control']=='no-store'
    assert json.loads(response.read())=={'ok':True,'kind':'embedded-chat-browser'}
