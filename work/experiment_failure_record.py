from pathlib import Path
p=Path('run_experiment.py');s=p.read_text(encoding='utf-8');s=s.replace('from urllib.request import Request, urlopen','from urllib.request import Request, urlopen\nfrom urllib.error import HTTPError')
s=s.replace("    with urlopen(req,timeout=timeout) as res:return json.loads(res.read().decode('utf-8'))", """    try:
        with urlopen(req,timeout=timeout) as res:return json.loads(res.read().decode('utf-8'))
    except HTTPError as error:
        try:
            data=json.loads(error.read().decode('utf-8'))
        except (ValueError,UnicodeError):
            raise error
        if not isinstance(data,dict):raise error
        data['ok']=False
        return data""",1)
p.write_text(s,encoding='utf-8')
