"""Native browser launcher must stay local and reject cross-origin requests."""
import threading
from unittest.mock import patch
import urllib.request
import urllib.error
import pytest
import local_ai_server as server


@pytest.fixture
def browser_server():
    http = server.QuietThreadingHTTPServer(('127.0.0.1', 0), server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{http.server_port}'
    http.shutdown()
    http.server_close()


def test_launcher_rejects_websites_and_requires_intent_header(browser_server):
    for headers in [{}, {'Origin': 'https://untrusted.example', 'X-Jarvis-Notifications': '1'}]:
        request = urllib.request.Request(browser_server+'/browser/launch', data=b'', headers=headers)
        with patch('subprocess.Popen') as launch:
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            assert error.value.code == 403
            launch.assert_not_called()


def test_browser_script_is_served(browser_server):
    response = urllib.request.urlopen(browser_server+'/site/dashboard/chat_browser.js')
    assert response.status == 200
    assert 'javascript' in response.headers['Content-Type']
    script = response.read()
    assert b'embedded-browser-screen' in script
    assert b'window.openSotukenBrowser=navigate' in script
