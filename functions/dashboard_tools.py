"""カード用の実データ取得。QRはローカル生成し、検索失敗を成功に置き換えない。"""
import base64
import io
import json
import re
from urllib.parse import quote_plus
from functions.research_tools import _http_get_text


def youtube_results(query):
    query = str(query or '').strip()
    if not query:
        return {'ok': False, 'error': '検索語を入力してください。', 'videos': []}
    search_url = 'https://www.youtube.com/results?search_query=' + quote_plus(query)
    try:
        html = _http_get_text(search_url)
        match = re.search(r'(?:var\s+)?ytInitialData\s*=\s*', html)
        if not match:
            raise ValueError('動画一覧を取得できませんでした')
        data, _ = json.JSONDecoder().raw_decode(html[match.end():])
        videos = []
        seen = set()
        def walk(node):
            if isinstance(node, list):
                for item in node:
                    walk(item)
            elif isinstance(node, dict):
                video = node.get('videoRenderer')
                if video and len(videos) < 8:
                    video_id = video.get('videoId', '')
                    if re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id) and video_id not in seen:
                        seen.add(video_id)
                        title = ''.join(run.get('text', '') for run in video.get('title', {}).get('runs', []))
                        videos.append({'title': title or video_id, 'url': 'https://www.youtube.com/watch?v='+video_id,
                                       'thumbnail': 'https://i.ytimg.com/vi/'+video_id+'/mqdefault.jpg'})
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        walk(value)
        walk(data)
        return {'ok': bool(videos), 'query': query, 'search_url': search_url, 'videos': videos,
                'error': '' if videos else '動画を取得できませんでした。YouTubeで検索できます。'}
    except Exception as error:
        return {'ok': False, 'query': query, 'search_url': search_url, 'videos': [], 'error': str(error)}


def local_qr(text):
    text = str(text or '').strip()
    if not text or len(text) > 2000:
        return {'ok': False, 'error': 'QRコードにする文字列を1〜2000文字で指定してください。'}
    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
        image = qrcode.make(text, image_factory=SvgPathImage, border=4)
        output = io.BytesIO(); image.save(output)
        return {'ok': True, 'text': text, 'image_url': 'data:image/svg+xml;base64,' + base64.b64encode(output.getvalue()).decode('ascii')}
    except Exception as error:
        return {'ok': False, 'error': 'QRコードを生成できませんでした: '+str(error)}
