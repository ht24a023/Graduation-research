from pathlib import Path
p=Path('tests/test_chat_browser_launch.py');s=p.read_text(encoding='utf-8');s=s.replace("    assert b'sotukenBrowser' in response.read()", "    script = response.read()\n    assert b'embedded-browser-screen' in script\n    assert b'window.openSotukenBrowser=navigate' in script");p.write_text(s,encoding='utf-8')
