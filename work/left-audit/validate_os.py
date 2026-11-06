"""名前：左. Live OS comparison; no fixture values are presented as machine readings."""
import json,os,time
from pathlib import Path
from datetime import datetime,timezone
import psutil
from functions.system_monitor import SystemMonitor

monitor=SystemMonitor();first=monitor.snapshot();time.sleep(2.2)
before_memory=psutil.virtual_memory();before_network=psutil.net_io_counters();second=monitor.snapshot();after_network=psutil.net_io_counters();after_memory=psutil.virtual_memory()
checks={}
checks['logical_cores_exact']=second['cpu']['logical_cores']==psutil.cpu_count()
checks['physical_cores_exact']=second['cpu']['physical_cores']==psutil.cpu_count(logical=False)
checks['per_core_count_exact']=len(second['cpu']['per_core_percent'])==psutil.cpu_count()
checks['ram_total_exact']=second['memory']['total_bytes']==after_memory.total
checks['ram_accounting_exact']=second['memory']['used_bytes']+second['memory']['available_bytes']==second['memory']['total_bytes']
checks['ram_usage_close_to_os']=min(abs(second['memory']['usage_percent']-before_memory.percent),abs(second['memory']['usage_percent']-after_memory.percent))<=2
checks['cpu_fraction_from_counters']=None
old=first['cpu']['time_seconds'];new=second['cpu']['time_seconds'];elapsed=sum(new.values())-sum(old.values());idle=(new['idle']+new.get('iowait',0))-(old['idle']+old.get('iowait',0))
if elapsed>0:checks['cpu_fraction_from_counters']=abs(second['cpu']['usage_percent']-round(max(0,min(100,(1-idle/elapsed)*100)),1))<.11
checks['network_tx_between_os_samples']=before_network.bytes_sent<=second['network']['sent_bytes']<=after_network.bytes_sent
checks['network_rx_between_os_samples']=before_network.bytes_recv<=second['network']['received_bytes']<=after_network.bytes_recv
interval=second['network']['sample_interval_sec']
checks['network_delta_formula_exact']=all(abs(second['network'][rate]-(second['network'][counter]-first['network'][counter])/interval)<1e-6 for counter,rate in [('sent_bytes','send_bytes_sec'),('received_bytes','receive_bytes_sec')])
checks['backend_pid_exact']=second['process']['pid']==os.getpid()
checks['backend_cpu_times_available']=all(isinstance(second['process']['cpu_time_seconds'].get(k),(int,float)) for k in ['user','system'])
checks['backend_rss_positive']=second['process']['rss_bytes']>0
volumes=[]
for volume in second['storage']['volumes']:
    if not volume['available']:continue
    direct=psutil.disk_usage(volume['mountpoint']);volumes.append({'device':volume['device'],'total_exact':volume['total_bytes']==direct.total,'usage_difference_pp':abs(volume['usage_percent']-direct.percent)})
checks['volume_totals_exact']=all(v['total_exact'] for v in volumes) and bool(volumes)
checks['volume_usage_close']=all(v['usage_difference_pp']<=1 for v in volumes)
report={'name':'左','checked_at':datetime.now(timezone.utc).isoformat(),'method':'実際のSystemMonitorと同じPCのpsutilを前後比較。CPU・通信はカウンター差分を再計算。','checks':checks,'volume_checks':volumes,
 'observed':{'logical_cores':second['cpu']['logical_cores'],'physical_cores':second['cpu']['physical_cores'],'ram_total_bytes':second['memory']['total_bytes'],'ram_usage_percent':second['memory']['usage_percent'],'cpu_usage_percent':second['cpu']['usage_percent'],'network_interval_sec':interval,'gpu_count':len(second['gpus']),'cpu_temperature_c':second['cpu']['temperature_c'],'disk_read_bytes_sec':second['disk_io']['read_bytes_sec'],'disk_write_bytes_sec':second['disk_io']['write_bytes_sec']},
 'limits':['別プロセスのタスクマネージャー画面との同時読取は未実施。','この検証のプロセスPIDは検証スクリプト自身。稼働中サーバーのPIDはブラウザー検証で確認する。','GPU・温度は取得できたものだけ。未取得は数値を補っていない。']}
path=Path(r'C:\Users\ht24a023\Documents\Codex\2026-10-30\code\outputs\left-os-validation.json');path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
assert all(value is True for value in checks.values()),checks
