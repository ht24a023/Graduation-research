"""Real PC telemetry preserves unknown values and handles process/counter races."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from functions.system_monitor import SystemMonitor


@pytest.mark.parametrize(('current', 'previous', 'elapsed', 'expected'), [
    (150, 100, 2, 25), (100, 100, 2, 0), (20, 100, 2, None),
    (100, None, 2, None), (None, 100, 2, None), (100, 50, 0, None),
])
def test_counter_rate_does_not_fabricate_reset_measurements(current, previous, elapsed, expected):
    assert SystemMonitor._counter_rate(current, previous, elapsed) == expected


def test_process_summary_is_sorted_bounded_cached_and_excludes_sensitive_fields():
    monitor = SystemMonitor()
    processes = [SimpleNamespace(info={
        'pid': index, 'name': f'worker-{index}',
        'memory_info': SimpleNamespace(rss=index * 1024), 'num_threads': 2,
        'cmdline': ['SECRET'], 'environ': {'TOKEN': 'SECRET'},
    }) for index in range(10)]
    processes.append(SimpleNamespace(info={'pid': 100, 'memory_info': None}))
    with patch('functions.system_monitor.psutil.process_iter', return_value=processes) as scan:
        first = monitor._process_snapshot(100)
        assert [row['pid'] for row in first] == [9, 8, 7, 6, 5, 4]
        assert all(set(row) == {'pid', 'name', 'rss_bytes', 'threads'} for row in first)
        assert monitor._process_snapshot(110) is first
        assert scan.call_count == 1
        monitor._process_snapshot(116)
        assert scan.call_count == 2


def test_process_access_failure_is_unavailable_and_retried_after_cache_interval():
    monitor = SystemMonitor()
    with patch('functions.system_monitor.psutil.process_iter', side_effect=OSError('denied')):
        assert monitor._process_snapshot(100) == []
    with patch('functions.system_monitor.psutil.process_iter', return_value=[]) as scan:
        monitor._process_snapshot(116)
        assert scan.call_count == 1


@pytest.mark.parametrize('secsleft, expected', [(-1, None), (-2, None), (7200, 7200)])
def test_battery_unknown_and_unlimited_do_not_become_negative_seconds(secsleft, expected):
    battery = SimpleNamespace(percent=75, power_plugged=False, secsleft=secsleft)
    with patch('functions.system_monitor.psutil.sensors_battery', return_value=battery):
        data = SystemMonitor().snapshot()
    assert data['battery']['remaining_sec'] == expected


def test_missing_optional_network_and_disk_counters_are_unknown():
    with patch('functions.system_monitor.psutil.net_io_counters', side_effect=OSError('unsupported')), \
         patch('functions.system_monitor.psutil.disk_io_counters', return_value=None):
        data = SystemMonitor().snapshot()
    assert all(value is None for value in data['network'].values())
    assert all(value is None for value in data['disk_io'].values())
    assert data['process']['server_uptime_sec'] >= 0
    assert 'top_memory' in data['process']


def test_unavailable_process_count_is_not_claimed_as_zero():
    with patch('functions.system_monitor.psutil.pids', side_effect=OSError('unavailable')):
        data = SystemMonitor().snapshot()
    assert data['process']['system_process_count'] is None
