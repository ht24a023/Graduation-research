from pathlib import Path
p=Path('functions/system_monitor.py');s=p.read_text(encoding='utf-8');s=s.replace('import csv\n','import csv\nimport math\n',1)
s=s.replace('        self._drives_at = None', '''        self._drives_at = None
        self._process_cpu_previous = {}
        self._own_cpu_previous = None
        self._native = None
        self._sampler_lock = threading.Lock()
        self._sampler_thread = None
        self._ready = threading.Event()
        self._sampler_stop = threading.Event()
        self._sample_error = None''',1)
a=s.index('    @staticmethod\n    def _counter_rate')
helpers='''    @staticmethod
    def _cpu_usage(current, previous):
        if previous is None:
            return None
        current_total = sum(current) - getattr(current, 'guest', 0) - getattr(current, 'guest_nice', 0)
        prior_total = sum(previous) - getattr(previous, 'guest', 0) - getattr(previous, 'guest_nice', 0)
        elapsed = current_total-prior_total
        idle = current.idle-prior_total*0-previous.idle + getattr(current,'iowait',0)-getattr(previous,'iowait',0)
        if elapsed<=0 or idle<0 or idle>elapsed:
            return None
        return round(max(0,min(100,(1-idle/elapsed)*100)),1)

    @staticmethod
    def _process_percent(current, previous, now, cores):
        if current is None or previous is None or not cores or now<=previous[0] or current<previous[1]:
            return None
        return round(max(0,min(100,(current-previous[1])/(now-previous[0])/cores*100)),2)

    def latest(self):
        """One sampler per server; HTTP readers never wait for a slow OS query."""
        with self._sampler_lock:
            if self._sampler_thread is None or not self._sampler_thread.is_alive():
                self._sampler_stop.clear()
                self._sampler_thread=threading.Thread(target=self._sample_loop,daemon=True,name='pc-telemetry')
                self._sampler_thread.start()
        self._ready.wait(.08)
        data=self._cached
        if data is None:
            return {'ok':False,'warming_up':self._sample_error is None,'source':'backend_pc',
                    'error':self._sample_error or 'PC情報を計測しています。'}
        age=max(0,time.monotonic()-self._sampled)
        return {**data,'telemetry':{'sample_interval_sec':1,'age_sec':round(age,3),
                'stale':age>5,'collection_error':self._sample_error}}

    def _sample_loop(self):
        while not self._sampler_stop.is_set():
            begin=time.monotonic()
            try:
                data=self.snapshot()
                self._sample_error=None if data.get('ok') else data.get('error','取得失敗')
            except Exception:
                self._sample_error='PC情報を取得できませんでした。再計測します。'
            finally:
                self._ready.set()
            self._sampler_stop.wait(max(.1,1-(time.monotonic()-begin)))

    def stop(self):
        self._sampler_stop.set()
        if self._sampler_thread:self._sampler_thread.join(timeout=3)
        if self._native and (not self._sampler_thread or not self._sampler_thread.is_alive()):self._native.close()

'''
s=s[:a]+helpers+s[a:];s=s.replace('current.idle-prior_total*0-previous.idle','current.idle-previous.idle')
s=s.replace('now - self._processes_at < 15','now - self._processes_at < 2')
s=s.replace("        rows = []\n        try:\n            for process in psutil.process_iter(['pid', 'name', 'memory_info', 'num_threads']):", "        rows = []\n        previous = self._process_cpu_previous\n        next_previous = {}\n        cores = psutil.cpu_count()\n        try:\n            for process in psutil.process_iter(['pid', 'name', 'memory_info', 'num_threads', 'cpu_times', 'create_time']):",1)
s=s.replace("                    rows.append({'pid': info['pid']", "                    cpu_times = info.get('cpu_times')\n                    cpu_total = cpu_times.user+cpu_times.system if cpu_times else None\n                    key = (info['pid'], info.get('create_time'))\n                    usage = self._process_percent(cpu_total, previous.get(key), now, cores)\n                    if cpu_total is not None:next_previous[key]=(now,cpu_total)\n                    rows.append({'cpu_percent': usage, 'pid': info['pid']",1)
s=s.replace('        self._top_memory = sorted(rows,', '        self._process_cpu_previous = next_previous\n        self._top_memory = sorted(rows,',1)
s=s.replace('sample_started - self._sampled < 2','sample_started - self._sampled < .9')
a=s.index('            previous = self._cpu_times');b=s.index('            def optional(',a)
s=s[:a]+'''            cpu_usage = self._cpu_usage(cpu_times, self._cpu_times)
            self._cpu_times = cpu_times
            per_cpu = psutil.cpu_times(percpu=True)
            core_usage = [self._cpu_usage(current,prior) for current,prior in zip(per_cpu,self._per_cpu_times)]
            self._per_cpu_times = per_cpu
            if self._native is None:
                from functions.windows_performance import WindowsPerformanceCounters
                self._native=WindowsPerformanceCounters(psutil.cpu_count())
            native=self._native.sample()
            cpu_source='OS CPU time delta'
            if native.get('cpu_utility') is not None:
                cpu_usage=round(native['cpu_utility'],1)
                cpu_source='Windows Processor Utility / PDH'
            for i in range(len(core_usage)):
                if native.get('core_'+str(i)) is not None:core_usage[i]=round(native['core_'+str(i)],1)
'''+s[b:]
s=s.replace('            swap = optional(psutil.swap_memory)', '''            own_times = process_info['cpu_time_seconds']
            own_total = own_times.get('user',0)+own_times.get('system',0) if own_times else None
            process_info['usage_percent']=self._process_percent(own_total,self._own_cpu_previous,now,psutil.cpu_count())
            if own_total is not None:self._own_cpu_previous=(now,own_total)
            process_info['cpu_basis']='100% = total logical CPU capacity; memory = working set (RSS)'
            swap = optional(psutil.swap_memory)''',1)
s=s.replace('            memory = psutil.virtual_memory()\n            disk = psutil.disk_usage(Path(__file__).resolve().anchor or os.sep)', '''            memory = optional(psutil.virtual_memory)
            disk = optional(lambda:psutil.disk_usage(Path(__file__).resolve().anchor or os.sep))''')
s=s.replace("'cpu': {'usage_percent': cpu_usage,", "'cpu': {'usage_percent': cpu_usage, 'usage_source':cpu_source,")
s=s.replace("'usage_percent': memory.percent, 'used_bytes': memory.total - memory.available,\n                           'total_bytes': memory.total, 'available_bytes': memory.available", "'usage_percent': getattr(memory,'percent',None), 'used_bytes': memory.total-memory.available if memory else None,\n                           'total_bytes': getattr(memory,'total',None), 'available_bytes': getattr(memory,'available',None)")
s=s.replace("'usage_percent': disk.percent,\n                         'used_bytes': disk.used, 'total_bytes': disk.total, 'free_bytes': disk.free", "'usage_percent': getattr(disk,'percent',None), 'active_percent':round(100-native['disk_idle'],1) if 'disk_idle' in native else None,\n                         'active_source':'Windows PhysicalDisk Idle Time / PDH' if 'disk_idle' in native else 'unavailable',\n                         'used_bytes': getattr(disk,'used',None), 'total_bytes': getattr(disk,'total',None), 'free_bytes': getattr(disk,'free',None)")
p.write_text(s,encoding='utf-8')
