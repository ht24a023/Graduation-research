"""Research summaries derived only from recorded results; no prompts in exports."""
from datetime import datetime
import math
import statistics

EXPERIMENT_MODES = ('LOCAL_ONLY', 'FIXED_ROUTING', 'DYNAMIC_ROUTING')
MODES = ('CLOUD_FIRST',) + EXPERIMENT_MODES


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError):
        return None


def aggregate(rows):
    times=sorted(v for row in rows if (v:=_number(row.get('response_time_sec'))) is not None)
    rated=[row for row in rows if row.get('user_rating') in ('good','partial','bad')]
    known_api=[row for row in rows if isinstance(row.get('api_called'),bool)]
    cloud=sum(row['api_called'] for row in known_api)
    success=[row for row in rows if isinstance(row.get('success'),bool)]
    return {'count':len(rows), 'completed':sum(row['success'] for row in success),
            'completion_rate':round(sum(row['success'] for row in success)/len(success)*100,1) if success else None,
            'measured':len(times), 'mean_sec':round(statistics.mean(times),3) if times else None,
            'median_sec':round(statistics.median(times),3) if times else None,
            'p95_sec':round(times[math.ceil(len(times)*.95)-1],3) if times else None,
            'cloud_count':cloud,'free_cloud_count':sum(r.get('api_fee_status')=='free' and r.get('api_called') is True for r in rows),'paid_cloud_count':sum(r.get('api_fee_status')=='paid' and r.get('api_called') is True for r in rows),'api_known':len(known_api),
            'cloud_avoidance_rate':round((len(known_api)-cloud)/len(known_api)*100,1) if known_api else None,
            'rated':len(rated),'unrated':len(rows)-len(rated),
            'good':sum(row.get('user_rating')=='good' for row in rated),
            'partial':sum(row.get('user_rating')=='partial' for row in rated),
            'bad':sum(row.get('user_rating')=='bad' for row in rated),
            'good_rate_among_rated':round(sum(row.get('user_rating')=='good' for row in rated)/len(rated)*100,1) if rated else None}


def build_report(records, mode='', experiments_only=False):
    if mode and mode not in MODES:
        raise ValueError('実験モードが不正です。')
    rows=[row for row in records if isinstance(row,dict) and (not mode or row.get('experiment_mode')==mode) and (not experiments_only or str(row.get('test_case_id','')).strip())]
    groups=[{'mode':key,**aggregate([r for r in rows if r.get('experiment_mode')==key])} for key in MODES]
    unknown=sum(row.get('experiment_mode') not in MODES for row in rows)
    cases={key:{str(r.get('test_case_id')) for r in rows if r.get('experiment_mode')==key and r.get('test_case_id')} for key in EXPERIMENT_MODES}
    shared=set.intersection(*cases.values())
    return {'ok':True,'generated_at':datetime.now().astimezone().isoformat(timespec='seconds'),
            'filters':{'mode':mode,'experiments_only':experiments_only},
            'overall':aggregate(rows),'modes':groups,'unknown_mode_count':unknown,
            'paired_case_count':len(shared),
            'definitions':{
                'completion':'ログのsuccessがtrueの割合。回答の正しさとは異なります。',
                'quality':'good / partial / badの人手評価。未評価を合格に含めません。',
                'latency':'サーバー処理時間。P95は昇順データのceil(n×0.95)番目。',
                'cloud':'クラウドLLMの利用。無料クラウドも利用ありとして計上し、API料金なしの件数を別集計します。検索・天気などの外部通信は含みません。',
                'comparison':'3モード共通のtest_case_id件数を表示。件数一致だけでは条件・品質の公平性を保証しません。',
                'background_memory':'作業要約は追加のAPI利用です。ここでの会話応答の件数・時間には含みません。自動要約の状態と別記録で確認できます。',
                'cost':'この研究レポートでは費用削減率を算出しません。新しい呼び出しの実測トークンと料金目安は「API利用状況」で確認できます。'},
            'privacy':'入力文・回答文・評価コメント・記憶本文は含みません。集計値のみです。'}
