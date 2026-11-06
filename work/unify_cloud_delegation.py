from pathlib import Path
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8');a=s.index("      if (role === 'assistant') {\n        const cloudButton");b=s.index('      const copyIconSvg',a);s=s[:a]+s[b:]
a=s.index('    function buildCloudVerificationPrompt(');b=s.index('    function linkifyText(',a);s=s[:a]+s[b:]
p.write_text(s,encoding='utf-8')
p=Path('tests/test_post_answer_cloud_browser.py');s=p.read_text(encoding='utf-8');s=s.replace("            assert button.count()==1 and not calls", "            assert button.count()==1 and not calls\n            assert page.locator('.cloud-check-btn').count()==0\n            page.screenshot(path=str(Path(server.__file__).parent/'work/post-answer-cloud-button.png'))",1);p.write_text(s,encoding='utf-8')
