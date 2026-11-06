"""バックエンドPCの実測値。非対応センサーは値を推測せず None にする。"""
from __future__ import annotations
import csv
import math
import io
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path
try:
    import psutil
except ImportError:
    psutil = None


def _numeric_fields(record):
    """Only numeric counters returned by psutil; no process arguments or environment."""
    if record is None:
        return None
    values = record._asdict() if hasattr(record, '_asdict') else vars(record)
    return {key: value for key, value in values.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)}


class SystemMonitor:
    def __init__(self):
        self._lock = threading.Lock()
        self._cached = None
        self._sampled = 0.0
        self._network = None
        self._gpu_time = 0.0
        self._gpus = []
        if psutil:
            self._cpu_times = psutil.cpu_times()
            self._per_cpu_times = psutil.cpu_times(percpu=True)
        self._disk_io = None
        self._hardware_sample = None
        self._hardware_at = 0
        self._started = time.monotonic()
        self._processes_at = None
        self._top_memory = []
        self._drives = []
        self._drives_at = None
        self._process_cpu_previous = {}
        self._own_cpu_previous = None
        self._native = None
        self._sampler_lock = threading.Lock()
        self._sampler_thread = None
        self._ready = threading.Event()
        self._sampler_stop = threading.Event()
        self._sample_error = None

    @staticmethod
    def _cpu_usage(current, previous):
        if previous is None:
            return None
        current_total = sum(current) - getattr(current, 'guest', 0) - getattr(current, 'guest_nice', 0)
        prior_total = sum(previous) - getattr(previous, 'guest', 0) - getattr(previous, 'guest_nice', 0)
        elapsed = current_total-prior_total
        idle = current.idle-previous.idle + getattr(current,'iowait',0)-getattr(previous,'iowait',0)
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

    @staticmethod
    def _counter_rate(current, previous, elapsed):
        """A reset or missing counter is unknown, never an invented zero."""
        if current is None or previous is None or elapsed <= 0 or current < previous:
            return None
        return (current - previous) / elapsed

    def _process_snapshot(self, now):
        # Names and working sets only; never expose command lines or environment.
        if self._processes_at is not None and now - self._processes_at < 2:
            return self._top_memory
        rows = []
        previous = self._process_cpu_previous
        next_previous = {}
        cores = psutil.cpu_count()
        try:
            for process in psutil.process_iter(['pid', 'name', 'memory_info', 'num_threads', 'cpu_times', 'create_time']):
                try:
                    info = process.info
                    memory = info.get('memory_info')
                    if memory is None:
                        continue
                    cpu_times = info.get('cpu_times')
                    cpu_total = cpu_times.user+cpu_times.system if cpu_times else None
                    key = (info['pid'], info.get('create_time'))
                    usage = self._process_percent(cpu_total, previous.get(key), now, cores)
                    if cpu_total is not None:next_previous[key]=(now,cpu_total)
                    rows.append({'cpu_percent': usage, 'pid': info['pid'], 'name': info.get('name') or '不明',
                                 'rss_bytes': memory.rss, 'threads': info.get('num_threads')})
                except (OSError, psutil.Error):
                    continue
        except (OSError, psutil.Error):
            rows = []
        self._process_cpu_previous = next_previous
        self._top_memory = sorted(rows, key=lambda item: item['rss_bytes'], reverse=True)[:6]
        self._processes_at = now
        return self._top_memory

    def _gpu_snapshot(self, now):
        if now - self._gpu_time < 15:
            return self._gpus
        self._gpu_time = now
        executable = shutil.which('nvidia-smi')
        if not executable:
            self._gpus = []
            return []
        try:
            result = subprocess.run(
                [executable, '--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu',
                 '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=2,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True,
            )
            def numeric(value):
                try:
                    return float(value.strip())
                except ValueError:
                    return None
            self._gpus = [dict(zip(
                ['name', 'usage_percent', 'vram_used_mb', 'vram_total_mb', 'temperature_c'],
                [row[0].strip(), *[numeric(v) for v in row[1:]]],
            )) for row in csv.reader(io.StringIO(result.stdout)) if len(row) == 5]
        except (OSError, subprocess.SubprocessError):
            self._gpus = []
        return self._gpus

    def _drive_snapshot(self, now):
        """Explorer's mounted volumes, from OS counters; no folder scan."""
        if self._drives_at is not None and now - self._drives_at < 15:
            return self._drives
        rows, seen = [], set()
        try:
            partitions = psutil.disk_partitions(all=False)
        except (OSError, psutil.Error):
            partitions = []
        for partition in partitions:
            if partition.mountpoint in seen:
                continue
            seen.add(partition.mountpoint)
            row = dict(device=partition.device, mountpoint=partition.mountpoint,
                       filesystem=partition.fstype, options=partition.opts)
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                row.update(total_bytes=usage.total, used_bytes=usage.used,
                           free_bytes=usage.free, usage_percent=usage.percent, available=True)
            except (OSError, psutil.Error):
                row.update(total_bytes=None, used_bytes=None, free_bytes=None,
                           usage_percent=None, available=False)
            rows.append(row)
        self._drives, self._drives_at = rows, now
        return rows

    def snapshot(self):
        if psutil is None:
            return {'ok': False, 'error': 'psutil が未インストールです', 'source': 'backend_pc'}
        with self._lock:
            sample_started = time.monotonic()
            if self._cached is not None and sample_started - self._sampled < .9:
                return self._cached
            now = sample_started
            cpu_times = psutil.cpu_times()
            cpu_usage = self._cpu_usage(cpu_times, self._cpu_times)
            self._cpu_times = cpu_times
            per_cpu = psutil.cpu_times(percpu=True)
            core_usage = [self._cpu_usage(current,prior) for current,prior in zip(per_cpu,self._per_cpu_times)]
            self._per_cpu_times = per_cpu
            if self._native is None:
                from functions.windows_performance import WindowsPerformanceCounters
                self._native=WindowsPerformanceCounters(psutil.cpu_count())
            try:native=self._native.sample()
            except (OSError,RuntimeError):native={}
            cpu_source='OS CPU time delta'
            if native.get('cpu_utility') is not None:
                cpu_usage=round(native['cpu_utility'],1)
                cpu_source='Windows Processor Utility / PDH'
            for i in range(len(core_usage)):
                if native.get('core_'+str(i)) is not None:core_usage[i]=round(native['core_'+str(i)],1)
            def optional(function, default=None):
                try:
                    return function()
                except (OSError, AttributeError, NotImplementedError, RuntimeError, psutil.Error):
                    return default
            io_counts = optional(psutil.disk_io_counters)
            read_rate = write_rate = None
            if io_counts and self._disk_io:
                sample_time, last_read, last_write = self._disk_io
                read_rate = self._counter_rate(io_counts.read_bytes, last_read, now-sample_time)
                write_rate = self._counter_rate(io_counts.write_bytes, last_write, now-sample_time)
            if io_counts:
                self._disk_io = (now,io_counts.read_bytes,io_counts.write_bytes)
            if self._hardware_sample is None or now-self._hardware_at>15:
                frequency = optional(psutil.cpu_freq)
                adapters = optional(psutil.net_if_stats,{}) or {}
                self._hardware_sample = {
                    'os': platform.system(), 'os_release': platform.release(), 'architecture': platform.machine(),
                    'python': platform.python_version(), 'processor': platform.processor(),
                    'cpu_frequency_mhz': frequency.current if frequency else None,
                    'cpu_frequency_detail_mhz': _numeric_fields(frequency),
                    'network_adapters': [{'name': name, 'is_up': item.isup, 'speed_mbps': item.speed,
                                          'mtu_bytes': item.mtu, 'duplex': getattr(item.duplex, 'name', str(item.duplex))}
                                         for name, item in list(adapters.items())[:32]],
                    'active_adapters': sum(1 for item in adapters.values() if item.isup),
                    'reported_link_mbps': max((item.speed for item in adapters.values() if item.isup and item.speed>0),default=None),
                }
                self._hardware_at = now
            own_process = optional(lambda: psutil.Process(os.getpid()))
            process_ids = optional(psutil.pids)
            from functions.windows_performance import system_counts
            counts=system_counts()
            process_info = {'pid':os.getpid(), 'threads':optional(own_process.num_threads) if own_process else None,
                            'rss_bytes':optional(lambda:own_process.memory_info().rss) if own_process else None,
                            'system_process_count':counts.get('processes',len(process_ids) if process_ids is not None else None),
                            'system_thread_count':counts.get('threads'),
                            'visible_process_count':len(process_ids) if process_ids is not None else None,
                            'server_uptime_sec': max(0, now-self._started),
                            'cpu_time_seconds': _numeric_fields(optional(own_process.cpu_times)) if own_process else None,
                            'top_memory': self._process_snapshot(now)}
            own_times = process_info['cpu_time_seconds']
            own_total = own_times.get('user',0)+own_times.get('system',0) if own_times else None
            process_info['usage_percent']=self._process_percent(own_total,self._own_cpu_previous,now,psutil.cpu_count())
            if own_total is not None:self._own_cpu_previous=(now,own_total)
            process_info['cpu_basis']='100% = total logical CPU capacity; memory = working set (RSS)'
            swap = optional(psutil.swap_memory)
            memory = optional(psutil.virtual_memory)
            disk = optional(lambda:psutil.disk_usage(Path(__file__).resolve().anchor or os.sep))
            network = optional(psutil.net_io_counters)
            tx_rate = rx_rate = None
            elapsed = None
            if self._network and network:
                last_time, last_tx, last_rx = self._network
                elapsed = now - last_time
                tx_rate = self._counter_rate(network.bytes_sent, last_tx, elapsed)
                rx_rate = self._counter_rate(network.bytes_recv, last_rx, elapsed)
            if network:
                self._network = (now, network.bytes_sent, network.bytes_recv)
            temperature = None
            try:
                groups = psutil.sensors_temperatures() if hasattr(psutil, 'sensors_temperatures') else {}
                values = [entry.current for name, entries in groups.items() for entry in entries
                          if any(k in (name + ' ' + entry.label).lower() for k in ('coretemp', 'k10temp', 'cpu', 'package'))
                          and entry.current is not None]
                temperature = max(values) if values else None
            except (OSError, AttributeError, NotImplementedError):
                pass
            try:
                battery = psutil.sensors_battery()
            except (OSError, AttributeError, NotImplementedError):
                battery = None
            remaining = getattr(battery, 'secsleft', None) if battery else None
            if remaining is not None and remaining < 0:
                remaining = None  # Unknown/unlimited psutil sentinel.
            self._cached = {
                'ok': True, 'source': 'backend_pc', 'hostname': platform.node(), 'sampled_at': time.time(),
                'cpu': {'usage_percent': cpu_usage, 'usage_source':cpu_source, 'physical_cores': psutil.cpu_count(logical=False),
                        'logical_cores': psutil.cpu_count(), 'temperature_c': temperature, 'per_core_percent':core_usage, 'time_seconds':_numeric_fields(cpu_times), 'per_core_time_seconds':[_numeric_fields(core) for core in per_cpu]},
                'memory': {'usage_percent': getattr(memory,'percent',None), 'used_bytes': memory.total-memory.available if memory else None,
                           'total_bytes': getattr(memory,'total',None), 'available_bytes': getattr(memory,'available',None), 'os_reported':_numeric_fields(memory)},
                'storage': {'volumes': self._drive_snapshot(now), 'source': 'OS mounted volumes / Explorer PC', 'refresh_interval_sec': 15},
                'disk': {'path': str(Path(__file__).resolve().anchor), 'usage_percent': getattr(disk,'percent',None), 'active_percent':round(100-native['disk_idle'],1) if 'disk_idle' in native else None,
                         'active_source':'Windows PhysicalDisk Idle Time / PDH' if 'disk_idle' in native else 'unavailable',
                         'used_bytes': getattr(disk,'used',None), 'total_bytes': getattr(disk,'total',None), 'free_bytes': getattr(disk,'free',None)},
                'network': {'sent_bytes': network.bytes_sent if network else None, 'received_bytes': network.bytes_recv if network else None,
                            'send_bytes_sec': tx_rate, 'receive_bytes_sec': rx_rate, 'sample_interval_sec': elapsed, 'source':'OS all interfaces combined' if network else None,
                            'errors_in': getattr(network, 'errin', None), 'errors_out': getattr(network, 'errout', None),
                            'drops_in': getattr(network, 'dropin', None), 'drops_out': getattr(network, 'dropout', None)},
                'uptime_sec': max(0, time.time() - psutil.boot_time()),
                'battery': {'percent': battery.percent, 'plugged': battery.power_plugged,
                            'remaining_sec': remaining} if battery else None,
                'gpus': self._gpu_snapshot(now),
                'hardware': dict(self._hardware_sample), 'process': process_info,
                'disk_io': {'read_bytes_sec':read_rate,'write_bytes_sec':write_rate,
                            'read_bytes': getattr(io_counts, 'read_bytes', None),
                            'write_bytes': getattr(io_counts, 'write_bytes', None), 'os_counters':_numeric_fields(io_counts)},
                'swap': {'used_bytes':swap.used,'total_bytes':swap.total,'usage_percent':swap.percent} if swap else None,
            }
            self._sampled = time.monotonic()
            return self._cached


system_monitor = SystemMonitor()
