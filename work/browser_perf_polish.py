from pathlib import Path
p=Path('functions/embedded_browser.py');s=p.read_text(encoding='utf-8');a=s.index('                last_frame = 0');b=s.index("                cdp.on('Page.screencastFrame'",a);s=s[:a]+'''                def receive_frame(event):
                    # Keep the latest frame, including the final frame after loading.
                    self.frame = base64.b64decode(event['data'])
                    self.sequence += 1
                    cdp.send('Page.screencastFrameAck', {'sessionId':event['sessionId']})
'''+s[b:];s=s.replace("'everyNthFrame':2", "'everyNthFrame':2");p.write_text(s,encoding='utf-8')
