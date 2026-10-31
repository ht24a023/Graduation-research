"""Bounded presentation preferences; style does not change routing or API consent."""
STYLES = {
    'standard': '',
    'concise': '回答は日本語で結論を先に述べ、原則2〜4文で簡潔にしてください。重要な条件や不確実性は省略しないでください。',
    'detailed': '回答は日本語で結論、理由、具体例の順に説明してください。必要な条件や不確実性を明示してください。',
}


def normalize_style(value):
    if value is None:
        return 'standard'
    if not isinstance(value, str) or value not in STYLES:
        raise ValueError('reply_style は standard / concise / detailed から選んでください。')
    return value


def style_prompt(prompt, style):
    instruction = STYLES[normalize_style(style)]
    return prompt if not instruction else prompt + '\n\n【回答の表示形式】\n' + instruction
