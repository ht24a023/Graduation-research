from functions.weather import _major_event_text
from functions.time_func import get_time
import datetime

print("get_time():", get_time())
print("_major_event_text(2026-02-14):", _major_event_text(datetime.date(2026,2,14)))
print("_major_event_text(2026-12-25):", _major_event_text(datetime.date(2026,12,25)))
print("_major_event_text(today):", _major_event_text(datetime.date.today()))
