import json,time
from functions.system_monitor import SystemMonitor
from pathlib import Path
m=SystemMonitor();result={'samples':[]}
try:
    begin=time.perf_counter();first=m.latest();result['first_request_ms']=round((time.perf_counter()-begin)*1000,2);result['first_warming_up']=bool(first.get('warming_up'))
    for _ in range(3):
        time.sleep(1.1);begin=time.perf_counter();data=m.latest();latency=(time.perf_counter()-begin)*1000
        result['samples'].append({'request_ms':round(latency,3),'ok':data.get('ok'),'cpu_percent':data.get('cpu',{}).get('usage_percent'),'cpu_source':data.get('cpu',{}).get('usage_source'),'memory_percent':data.get('memory',{}).get('usage_percent'),'disk_activity_available':data.get('disk',{}).get('active_percent') is not None,'age_sec':data.get('telemetry',{}).get('age_sec')})
finally:m.stop()
Path('work/cloud-monitor-live-sample.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
