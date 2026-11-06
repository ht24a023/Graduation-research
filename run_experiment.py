"""Reproducible routing experiments; default execution never opts into cloud mode."""
from __future__ import annotations
import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4
from functions.research_report import build_report

MODES = ['CLOUD_FIRST','LOCAL_ONLY','FIXED_ROUTING','DYNAMIC_ROUTING']
DEFAULT_MODES = ['LOCAL_ONLY','DYNAMIC_ROUTING']


def post_json(url: str, payload: dict, timeout: float = 120.0) -> dict:
    req=Request(url,data=json.dumps(payload).encode('utf-8'),headers={'Content-Type':'application/json'},method='POST')
    try:
        with urlopen(req,timeout=timeout) as res:return json.loads(res.read().decode('utf-8'))
    except HTTPError as error:
        try:
            data=json.loads(error.read().decode('utf-8'))
        except (ValueError,UnicodeError):
            raise error
        if not isinstance(data,dict):raise error
        data['ok']=False
        return data


def get_json(url: str, timeout: float = 10.0) -> dict:
    with urlopen(Request(url,headers={'User-Agent':'experiment-runner'}),timeout=timeout) as res:return json.loads(res.read().decode('utf-8'))


def run_experiment(base_url: str, question_set_path: Path, session_prefix: str, *, modes=None, repetitions=1, allow_cloud=False, dry_run=False) -> dict:
    questions=json.loads(question_set_path.read_text(encoding='utf-8-sig'))
    modes=list(DEFAULT_MODES if modes is None else modes)
    if not modes or any(mode not in MODES for mode in modes) or len(set(modes))!=len(modes):raise ValueError('実験モードを正しく指定してください。')
    if not isinstance(repetitions,int) or not 1<=repetitions<=100:raise ValueError('繰り返し回数は1〜100です。')
    if not isinstance(questions,list) or not questions:raise ValueError('質問セットが空か、不正です。')
    ids=[]
    for item in questions:
        if not isinstance(item,dict) or not isinstance(item.get('message'),str) or not item['message'].strip() or not isinstance(item.get('test_case_id'),str) or not item['test_case_id'].strip():raise ValueError('各質問にmessageとtest_case_idが必要です。')
        ids.append(item['test_case_id'])
    if len(set(ids))!=len(ids):raise ValueError('test_case_idが重複しています。')
    protocol={'modes':modes,'repetitions':repetitions,'questions':len(questions),'planned_requests':len(modes)*repetitions*len(questions),'cloud_mode_explicitly_enabled':allow_cloud,'session_policy':'Separate session per run, mode and repetition; question order retained within each session.'}
    if dry_run:return {'dry_run':True,'protocol':protocol}
    if any(mode in modes for mode in ('CLOUD_FIRST','FIXED_ROUTING')) and not allow_cloud:raise ValueError('CLOUD_FIRST / FIXED_ROUTINGはクラウドAIを使用します。実行する場合だけ--allow-cloudを指定してください。')
    run_id=datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'-'+uuid4().hex[:6]
    out_dir=Path('data')/'experiment_runs'/run_id;out_dir.mkdir(parents=True,exist_ok=False)
    result_path=out_dir/'experiment_result.jsonl';rows=[];evaluations=[]
    try:environment=get_json(base_url.rstrip('/')+'/health')
    except Exception as error:environment={'unavailable':type(error).__name__}
    # Only reproducibility fields; never dump environment variables or credentials.
    environment={k:environment[k] for k in ('ok','model','local_model','ollama','unavailable') if k in environment and not isinstance(environment[k],dict)}
    with result_path.open('w',encoding='utf-8') as out:
        for mode in modes:
            for repetition in range(1,repetitions+1):
                session_id=f'{session_prefix}-{run_id}-{mode.lower()}-{repetition}'
                for item in questions:
                    payload={'message':item['message'],'session_id':session_id,'experiment_mode':mode,'test_case_id':item['test_case_id']}
                    try:response=post_json(base_url.rstrip('/')+'/chat',payload)
                    except Exception as error:response={'ok':False,'error':f'{type(error).__name__}: {error}'}
                    evaluation=response.get('evaluation')
                    if isinstance(evaluation,dict) and isinstance(evaluation.get('response_time_sec'),(int,float)):
                        evaluations.append({**evaluation,'experiment_mode':mode,'test_case_id':item['test_case_id'],'success':bool(response.get('ok'))})
                    row={'run_id':run_id,'mode':mode,'repetition':repetition,'session_id':session_id,'test_case_id':item['test_case_id'],'category':item.get('category',''),'message':item['message'],'ok':bool(response.get('ok')),'response':response.get('response',response.get('error','')),'evaluation':evaluation or {}}
                    rows.append(row);out.write(json.dumps(row,ensure_ascii=False)+'\n');out.flush()
                    print(f"[{mode} / {repetition}] {item['test_case_id']} ok={row['ok']}")
    csv_path=out_dir/'evaluation_log.csv'
    columns=['run_id','mode','repetition','test_case_id','ok','response_time_sec','local_time_sec','cloud_time_sec','api_called','request_id']
    with csv_path.open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=columns);writer.writeheader()
        for row in rows:writer.writerow({key:row.get(key,row['evaluation'].get(key,'')) for key in columns})
    final={'run_id':run_id,'protocol':protocol,'environment':environment,'total_requests':len(rows),'success_requests':sum(row['ok'] for row in rows),'missing_evaluation_count':len(rows)-len(evaluations),'result_jsonl':str(result_path),'evaluation_csv':str(csv_path),'summary':build_report(evaluations),'quality_status':'Human evaluation not performed by this runner. ok means processing completion, not answer correctness.'}
    (out_dir/'summary.json').write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf-8')
    return final


def main():
    parser=argparse.ArgumentParser(description='Run isolated routing comparisons. Cloud mode requires --allow-cloud.')
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    parser.add_argument('--question-set',default='data/experiment_question_set.json')
    parser.add_argument('--session-prefix',default='exp')
    parser.add_argument('--modes',nargs='+',choices=MODES,default=DEFAULT_MODES)
    parser.add_argument('--repetitions',type=int,default=1)
    parser.add_argument('--allow-cloud',action='store_true')
    parser.add_argument('--dry-run',action='store_true',help='Validate and show counts without network requests or model calls.')
    args=parser.parse_args()
    result=run_experiment(args.base_url,Path(args.question_set),args.session_prefix,modes=args.modes,repetitions=args.repetitions,allow_cloud=args.allow_cloud,dry_run=args.dry_run)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
