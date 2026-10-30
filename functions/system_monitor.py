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
            now = time.monotonic()
            if self._cached is not None and now - self._sampled < 2:
                return self._cached
            cpu_times = psutil.cpu_times()
            previous = self._cpu_times
            total = sum(cpu_times) - sum(previous)
            idle = (cpu_times.idle + getattr(cpu_times, 'iowait', 0)) - (previous.idle + getattr(previous, 'iowait', 0))
            cpu_usage = round(max(0, min(100, (1 - idle / total) * 100)), 1) if total > 0 else None
            self._cpu_times = cpu_times
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage(Path(__file__).resolve().anchor or os.sep)
            network = psutil.net_io_counters()
            tx_rate = rx_rate = None
            if self._network and network:
                last_time, last_tx, last_rx = self._network
                elapsed = now - last_time
                tx_rate = max(0, network.bytes_sent - last_tx) / elapsed
                rx_rate = max(0, network.bytes_recv - last_rx) / elapsed
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
            self._cached = {
                'ok': True, 'source': 'backend_pc', 'hostname': platform.node(), 'sampled_at': time.time(),
                'cpu': {'usage_percent': cpu_usage, 'physical_cores': psutil.cpu_count(logical=False),
                        'logical_cores': psutil.cpu_count(), 'temperature_c': temperature},
                'memory': {'usage_percent': memory.percent, 'used_bytes': memory.total - memory.available,
                           'total_bytes': memory.total, 'available_bytes': memory.available},
                'disk': {'path': str(Path(__file__).resolve().anchor), 'usage_percent': disk.percent,
                         'used_bytes': disk.used, 'total_bytes': disk.total, 'free_bytes': disk.free},
                'network': {'sent_bytes': network.bytes_sent if network else None, 'received_bytes': network.bytes_recv if network else None,
                            'send_bytes_sec': tx_rate, 'receive_bytes_sec': rx_rate},
                'uptime_sec': max(0, time.time() - psutil.boot_time()),
                'battery': {'percent': battery.percent, 'plugged': battery.power_plugged} if battery else None,
                'gpus': self._gpu_snapshot(now),
            }
            self._sampled = now
            return self._cached


system_monitor = SystemMonitor()
