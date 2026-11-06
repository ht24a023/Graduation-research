"""Conservative program routing for a cloud-first conversation policy."""
import re


def decide(message, parsed_tool=None):
    text=message.strip()
    explanatory=bool(re.search(r'とは|仕組み|原理|なぜ|比較|違い|おすすめ|考察|相談|説明|改善|使い方|目安|適正|原因|対策|下げたい|減らしたい',text))
    if parsed_tool and (not explanatory or re.match(r'^(タスク追加|文書検索)[：:]',text)):
        return {'intent':'tool','tool':parsed_tool,'reason':'対応する専用機能をプログラムで実行'}
    if re.fullmatch(r'(こんにちは|こんばんは|おはよう(?:ございます)?|やあ|はじめまして)[。！!\s]*',text):
        return {'intent':'greeting','reason':'定型のあいさつ'}
    if re.fullmatch(r'(?:今|現在)(?:の)?(?:時刻|時間|何時)(?:は|を)?(?:教えて|表示して|ですか|？|\?)?[。？?\s]*',text) or re.fullmatch(r'今何時(?:ですか)?[？?。\s]*',text):
        return {'intent':'time','reason':'OSの現在日時を取得'}
    if re.fullmatch(r'(?:今日|現在)(?:の|は)?(?:日付|何日)(?:は|を)?(?:教えて|表示して|ですか)?[。？?\s]*',text):
        return {'intent':'time','reason':'OSの現在日時を取得'}
    if re.fullmatch(r'(?:今日|今)(?:は|の)?(?:何曜日|曜日)(?:は|を)?(?:教えて|ですか)?[。？?\s]*',text):
        return {'intent':'weekday','reason':'日付から曜日を計算'}
    if re.fullmatch(r'(?:明日|明後日|昨日|一昨日|\d+日後|\d+日前)(?:は|の)?(?:何曜日|曜日)(?:は|を)?(?:教えて|ですか)?[。？?\s]*',text):
        return {'intent':'relative_weekday','reason':'指定日から曜日を計算'}
    expression=re.sub(r'^(?:計算(?:して)?[：:]\s*)','',text)
    expression=re.sub(r'(?:を)?(?:計算して|計算してください|は|ですか|？|\?)[。\s]*$','',expression).strip()
    if re.fullmatch(r'[\d０-９\s.+\-*/×÷％%（）()^＝=]+',expression) and re.search(r'[+\-*/×÷^]',expression):
        return {'intent':'calculate','reason':'数式を専用計算プログラムで評価'}
    if not explanatory and re.search(r'天気|気温|降水確率',text) and (re.search(r'教えて|調べて|予報|ですか|は[？?]?$',text) or re.fullmatch(r'.{0,30}(?:の天気|の気温|天気予報)[？?。\s]*',text)):
        return {'intent':'weather','reason':'天気の専用取得機能（外部通信あり）'}
    if not explanatory and re.search(r'行き方|までの経路|までのルート',text):
        return {'intent':'navigation','reason':'経路の専用取得機能（外部通信あり）'}
    if not explanatory and re.search(r'検索して|検索してください|調べて|調査して',text):
        return {'intent':'search','reason':'明示的な検索要求（外部通信あり）'}
    return {'intent':'chat','reason':'専用機能に該当しないためクラウドで対話'}
