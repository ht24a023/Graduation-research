import sys
sys.path.insert(0,str(__import__("pathlib").Path.cwd()))
import runpy,tempfile,traceback
from pathlib import Path
import pytest
ns=runpy.run_path('tests/test_operations_browser.py')
mp=pytest.MonkeyPatch()
with tempfile.TemporaryDirectory(dir='work') as td:
    gen=ns['browser_ui'].__wrapped__(Path(td).resolve(),mp)
    print('starting browser',flush=True)
    data=next(gen)
    print('browser ready',flush=True)
    data[0].on('pageerror',lambda error:print('PAGE ERROR:',str(error),flush=True))
    try:
        ns['test_permanent_left_clean_composer_and_real_execution'](data)
        print('first test passed',flush=True)
    except BaseException:
        traceback.print_exc()
    finally:
        print('closing',flush=True)
        gen.close();mp.undo()
