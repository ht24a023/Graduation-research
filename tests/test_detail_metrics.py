"""Extended real counters expose values, not invented per-device estimates."""
from functions.system_monitor import SystemMonitor, _numeric_fields
from types import SimpleNamespace
from unittest.mock import patch


def test_numeric_counter_fields_exclude_text_and_unknowns():
    assert _numeric_fields(None) is None
    assert _numeric_fields(SimpleNamespace(read_count=3,read_bytes=4096,name='private',cmdline=['secret'],flag=True))=={'read_count':3,'read_bytes':4096}


def test_real_snapshot_has_drilldown_counter_groups_and_units():
    data=SystemMonitor().snapshot()
    assert data['cpu']['time_seconds']['idle']>=0
    assert data['memory']['os_reported']['total']==data['memory']['total_bytes']
    assert data['network']['sample_interval_sec'] is None
    assert data['process']['cpu_time_seconds'] is None or 'user' in data['process']['cpu_time_seconds']
    for adapter in data['hardware']['network_adapters']:
        assert {'name','is_up','speed_mbps','mtu_bytes','duplex'}<=set(adapter)
    assert data['disk_io']['os_counters'] is None or data['disk_io']['os_counters']['read_bytes']==data['disk_io']['read_bytes']


def test_unavailable_optional_counters_are_not_filled_with_zero():
    with patch('functions.system_monitor.psutil.cpu_freq',return_value=None),patch('functions.system_monitor.psutil.disk_io_counters',return_value=None):
        data=SystemMonitor().snapshot()
    assert data['hardware']['cpu_frequency_detail_mhz'] is None
    assert data['disk_io']['os_counters'] is None
