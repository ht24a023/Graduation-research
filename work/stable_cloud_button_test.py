from pathlib import Path
p=Path('tests/test_post_answer_cloud_browser.py');s=p.read_text(encoding='utf-8');s=s.replace("button=answer.get_by_role('button',name='クラウドに委託して回答を改善',exact=True)", "button=answer.locator('[data-cloud-delegate]')")
s=s.replace("            assert not errors,errors\n            browser.close()", """            monkeypatch.setattr(server,'ask_local_llm',lambda *a,**k:'（ローカルLLM応答は空でした）')
            page.locator('#message').fill('ローカルモデルで研究の説明をして')
            page.locator('#send-btn').click()
            page.wait_for_function("!document.getElementById('send-btn').disabled")
            assert page.locator('#chat-log .bubble.assistant').last.locator('[data-cloud-delegate]').count()==1
            assert len(calls)==1
            assert button.is_disabled()
            assert not errors,errors
            browser.close()""",1)
p.write_text(s,encoding='utf-8')
