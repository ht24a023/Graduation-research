"""Optional Windows performance counters, using language-neutral PDH paths."""
import atexit
import ctypes
import math
import os
from ctypes import wintypes


class _Value(ctypes.Union):
    _fields_=[('doubleValue',ctypes.c_double),('largeValue',ctypes.c_longlong)]


class _Formatted(ctypes.Structure):
    _anonymous_=('value',)
    _fields_=[('status',wintypes.DWORD),('value',_Value)]


class WindowsPerformanceCounters:
    def __init__(self, logical_cores):
        self.query=ctypes.c_void_p();self.counters={};self.samples=0;self.dll=None
        if os.name!='nt':return
        try:
            dll=ctypes.WinDLL('pdh');self.dll=dll
            dll.PdhOpenQueryW.argtypes=[wintypes.LPCWSTR,ctypes.c_size_t,ctypes.POINTER(ctypes.c_void_p)]
            dll.PdhOpenQueryW.restype=wintypes.LONG
            dll.PdhAddEnglishCounterW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR,ctypes.c_size_t,ctypes.POINTER(ctypes.c_void_p)]
            dll.PdhAddEnglishCounterW.restype=wintypes.LONG
            dll.PdhCollectQueryData.argtypes=[ctypes.c_void_p];dll.PdhCollectQueryData.restype=wintypes.LONG
            dll.PdhGetFormattedCounterValue.argtypes=[ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.POINTER(_Formatted)]
            dll.PdhGetFormattedCounterValue.restype=wintypes.LONG
            dll.PdhCloseQuery.argtypes=[ctypes.c_void_p];dll.PdhCloseQuery.restype=wintypes.LONG
            if dll.PdhOpenQueryW(None,0,ctypes.byref(self.query))!=0:return
            paths={'cpu_utility':r'\Processor Information(_Total)\% Processor Utility','disk_idle':r'\PhysicalDisk(_Total)\% Idle Time'}
            # Group/core naming follows Windows processor groups (up to 64 CPUs).
            for i in range(min(logical_cores or 0,512)):
                paths['core_'+str(i)]=rf'\Processor Information({i//64},{i%64})\% Processor Utility'
            for name,path in paths.items():
                handle=ctypes.c_void_p()
                if dll.PdhAddEnglishCounterW(self.query,path,0,ctypes.byref(handle))==0:self.counters[name]=handle
            atexit.register(self.close)
        except (OSError,AttributeError):
            self.close()

    def sample(self):
        if not self.query.value or not self.dll or not self.counters:return {}
        if self.dll.PdhCollectQueryData(self.query)!=0:return {}
        self.samples+=1
        if self.samples<2:return {}
        data={}
        for name,handle in self.counters.items():
            value=_Formatted()
            result=self.dll.PdhGetFormattedCounterValue(handle,0x200,None,ctypes.byref(value))
            if result==0 and value.status in (0,1) and math.isfinite(value.doubleValue) and value.doubleValue>=0:
                data[name]=max(0,min(100,value.doubleValue))
        return data

    def close(self):
        if self.query.value and self.dll:
            self.dll.PdhCloseQuery(self.query);self.query=ctypes.c_void_p()


class _PerformanceInfo(ctypes.Structure):
    _fields_=[('cb',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in (
        'CommitTotal','CommitLimit','CommitPeak','PhysicalTotal','PhysicalAvailable',
        'SystemCache','KernelTotal','KernelPaged','KernelNonpaged','PageSize')]+[
        ('HandleCount',wintypes.DWORD),('ProcessCount',wintypes.DWORD),('ThreadCount',wintypes.DWORD)]


def system_counts():
    if os.name!='nt':return {}
    try:
        api=ctypes.WinDLL('psapi').GetPerformanceInfo
        api.argtypes=[ctypes.POINTER(_PerformanceInfo),wintypes.DWORD];api.restype=wintypes.BOOL
        info=_PerformanceInfo();info.cb=ctypes.sizeof(info)
        if not api(ctypes.byref(info),info.cb):return {}
        return {'processes':info.ProcessCount,'threads':info.ThreadCount,'handles':info.HandleCount}
    except (OSError,AttributeError):return {}
