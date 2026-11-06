"""One real local-model probe, using synthetic memory in an isolated directory."""
import json,os,time,urllib.request
from pathlib import Path
from models import user_profile_memory as memory
from models.memory_retrieval import retrieve
from config import OLLAMA_MODEL
root=Path(__file__).resolve().parent/'local-research-probe'
root.mkdir(exist_ok=True);os.chdir(root)
memory.upsert_titled_note('卒研の検証コード','The verification code is SOTU-1106. This is synthetic test data.')
query='卒研の検証コードを答えて'
selected=retrieve(query,memory.load_notes()['notes'])
context=memory.build_profile_context(query=query,selected_notes=selected)
payload={'model':OLLAMA_MODEL,'prompt':context+'\nReturn only the verification code in the saved note. Do not explain.','stream':False,'keep_alive':0,'options':{'temperature':0,'num_predict':32}}
start=time.perf_counter()
try:
    request=urllib.request.Request('http://127.0.0.1:11434/api/generate',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=60) as response:data=json.load(response)
    answer=str(data.get('response','')).strip()
    result={'kind':'real_local_model_probe','model':OLLAMA_MODEL,'cloud_called':False,'selected_titles':[n['title'] for n in selected],'response':answer,'expected_code_found':'SOTU-1106' in answer,'elapsed_sec':round(time.perf_counter()-start,3),'limitations':'One synthetic recall probe; not a general accuracy or performance evaluation.'}
except Exception as error:
    result={'kind':'real_local_model_probe','model':OLLAMA_MODEL,'cloud_called':False,'expected_code_found':False,'elapsed_sec':round(time.perf_counter()-start,3),'error':str(error)}
(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
