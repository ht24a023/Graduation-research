from unittest.mock import patch
from functions import google_workspace as g


def test_lite_current_markup():
    html = """<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpresident" class='result-link'><b>President</b> information</a><td class='result-snippet'>Current <b>information</b>.</td>"""
    with patch.object(g, '_http_get_text', return_value=html):
        result = g._search_duckduckgo_lite('アメリカの大統領')
    assert result['results'][0]['title'] == 'President information'
    assert result['results'][0]['url'] == 'https://example.com/president'
    assert result['results'][0]['snippet'] == 'Current information.'


def test_fallback_stops_at_success():
    result = {'results': [{'title': 'Result', 'url': 'https://example.com'}]}
    with patch.object(g, '_search_google_web_impl', return_value=result), patch.object(g, '_search_duckduckgo_lite') as lite:
        assert g._search_with_fallbacks('検索') is result
        lite.assert_not_called()


def test_provider_exception_uses_next_and_stops():
    result = {'engine': 'DuckDuckGo Lite', 'results': [{'title': 'Result', 'url': 'https://example.com'}]}
    with patch.object(g, '_search_google_web_impl', side_effect=TimeoutError), patch.object(g, '_search_duckduckgo_lite', return_value=result), patch.object(g, '_search_bing') as bing:
        assert g._search_with_fallbacks('検索') is result
        bing.assert_not_called()
