from pathlib import Path
p=Path('tests/test_browser_performance.py');s=p.read_text(encoding='utf-8');s=s.replace('import json\n','import json\nimport base64\n',1)
s=s.replace("elif path.startswith('/frame'):frames.append(path);route.fulfill(status=204,headers={'Access-Control-Allow-Origin':'*'});return", """elif path.startswith('/frame'):
                    frames.append(path)
                    if 'after=-1' in path:
                        route.fulfill(status=200,content_type='image/png',body=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='),headers={'Access-Control-Allow-Origin':'*','Access-Control-Expose-Headers':'X-Frame-Sequence','X-Frame-Sequence':'1'})
                    else:route.fulfill(status=204,headers={'Access-Control-Allow-Origin':'*'})
                    return""")
s=s.replace("assert len(sessions)==1", "assert len(sessions)==1\n            assert sum('after=-1' in frame for frame in frames)==1\n            assert any('after=1' in frame for frame in frames)")
p.write_text(s,encoding='utf-8')
