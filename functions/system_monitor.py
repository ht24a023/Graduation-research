"""バックエンドPCの実測値。非対応センサーは値を推測せず None にする。"""
from __future__ import annotations
import csv
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

    @staticmethod
    def _counter_rate(current, previous, elapsed):
        """A reset or missing counter is unknown, never an invented zero."""
        if current is None or previous is None or elapsed <= 0 or current < previous:
            return None
        return (current - previous) / elapsed

    def _process_snapshot(self, now):
        # Names and working sets only; never expose command lines or environment.
        if self._processes_at is not None and now - self._processes_at < 15:
            return self._top_memory
        rows = []
        try:
            for process in psutil.process_iter(['pid', 'name', 'memory_info', 'num_threads']):
                try:
                    info = process.info
                    memory = info.get('memory_info')
                    if memory is None:
                        continue
                    rows.append({'pid': info['pid'], 'name': info.get('name') or '不明',
                                 'rss_bytes': memory.rss, 'threads': info.get('num_threads')})
                except (OSError, psutil.Error):
                    continue
        except (OSError, psutil.Error):
            rows = []
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

    def snapshot(self):
        if psutil is None:
            return {'ok': False, 'error': 'psutil が未インストールです', 'source': 'backend_pc'}
        with self._lock:
            sample_started = time.monotonic()
            if self._cached is not None and sample_started - self._sampled < 2:
                return self._cached
            now = sample_started
            cpu_times = psutil.cpu_times()
            previous = self._cpu_times
            total = sum(cpu_times) - sum(previous)
            idle = (cpu_times.idle + getattr(cpu_times, 'iowait', 0)) - (previous.idle + getattr(previous, 'iowait', 0))
            cpu_usage = round(max(0, min(100, (1 - idle / total) * 100)), 1) if total > 0 else None
            self._cpu_times = cpu_times
            per_cpu = psutil.cpu_times(percpu=True)
            core_usage = []
            for current, prior in zip(per_cpu, self._per_cpu_times):
                elapsed_cpu = sum(current)-sum(prior)
                idle_cpu = current.idle-prior.idle
                core_usage.append(round(max(0,min(100,(1-idle_cpu/elapsed_cpu)*100)),1) if elapsed_cpu>0 else None)
            self._per_cpu_times = per_cpu
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
                    'active_adapters': sum(1 for item in adapters.values() if item.isup),
                    'reported_link_mbps': max((item.speed for item in adapters.values() if item.isup and item.speed>0),default=None),
                }
                self._hardware_at = now
            own_process = optional(lambda: psutil.Process(os.getpid()))
            process_ids = optional(psutil.pids)
            process_info = {'pid':os.getpid(), 'threads':optional(own_process.num_threads) if own_process else None,
                            'rss_bytes':optional(lambda:own_process.memory_info().rss) if own_process else None,
                            'system_process_count':len(process_ids) if process_ids is not None else None,
                            'server_uptime_sec': max(0, now-self._started),
                            'top_memory': self._process_snapshot(now)}
            swap = optional(psutil.swap_memory)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage(Path(__file__).resolve().anchor or os.sep)
            network = optional(psutil.net_io_counters)
            tx_rate = rx_rate = None
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
                'cpu': {'usage_percent': cpu_usage, 'physical_cores': psutil.cpu_count(logical=False),
                        'logical_cores': psutil.cpu_count(), 'temperature_c': temperature, 'per_core_percent':core_usage},
                'memory': {'usage_percent': memory.percent, 'used_bytes': memory.total - memory.available,
                           'total_bytes': memory.total, 'available_bytes': memory.available},
                'disk': {'path': str(Path(__file__).resolve().anchor), 'usage_percent': disk.percent,
                         'used_bytes': disk.used, 'total_bytes': disk.total, 'free_bytes': disk.free},
                'network': {'sent_bytes': network.bytes_sent if network else None, 'received_bytes': network.bytes_recv if network else None,
                            'send_bytes_sec': tx_rate, 'receive_bytes_sec': rx_rate,
                            'errors_in': getattr(network, 'errin', None), 'errors_out': getattr(network, 'errout', None),
                            'drops_in': getattr(network, 'dropin', None), 'drops_out': getattr(network, 'dropout', None)},
                'uptime_sec': max(0, time.time() - psutil.boot_time()),
                'battery': {'percent': battery.percent, 'plugged': battery.power_plugged,
                            'remaining_sec': remaining} if battery else None,
                'gpus': self._gpu_snapshot(now),
                'hardware': dict(self._hardware_sample), 'process': process_info,
                'disk_io': {'read_bytes_sec':read_rate,'write_bytes_sec':write_rate,
                            'read_bytes': getattr(io_counts, 'read_bytes', None),
                            'write_bytes': getattr(io_counts, 'write_bytes', None)},
                'swap': {'used_bytes':swap.used,'total_bytes':swap.total,'usage_percent':swap.percent} if swap else None,
            }
            self._sampled = time.monotonic()
            return self._cached


system_monitor = SystemMonitor()
