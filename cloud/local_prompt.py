PROMPT_CONTRACT_VERSION = "v2"
MAX_PROMPT_HISTORY_TURNS = 12

LOCAL_ASSISTANT_SYSTEM_PROMPT = """あなたはローカルで動作する会話型エッジAIアシスタントです。

目的:
- 簡単な質問には短く、自然に、すぐ答える
- 雑談は親しみやすく、長すぎない返答にする
- 分からないことは無理に断定せず、必要なら確認を求める

対応方針:
- 時間、天気、現在地、計算などの簡単な処理はローカル優先
- 会話の流れを踏まえて、前の発話と矛盾しないようにする
- 返答は原則として1〜3文に収める
- 事実が不確かなときは、推測と明示する

出力契約:
- 日本語で答える
- 余計な前置き、自己紹介、謝罪の繰り返しはしない
- 箇条書きは本当に必要な場合だけ使う
- 1つの質問には1つの主回答を先に返す
- 回答できない場合は、理由を1文で簡潔に述べる
"""


def _coerce_text(value):
    if value is None:
        return ""

    return str(value).strip()


def _normalize_turn(turn):
    if not isinstance(turn, dict):
        return None

    role = _coerce_text(turn.get("role", "user"))
    if role not in {"user", "assistant", "system"}:
        role = "user"

    content = _coerce_text(turn.get("content", ""))
    if not content:
        return None

    return {"role": role, "content": content}


def _format_history(conversation_history):
    normalized_history = []
    for turn in conversation_history[-MAX_PROMPT_HISTORY_TURNS:]:
        normalized_turn = _normalize_turn(turn)
        if normalized_turn is not None:
            normalized_history.append(normalized_turn)

    lines = ["会話履歴:"]
    if not normalized_history:
        lines.append("(なし)")
        return lines

    for turn in normalized_history:
        speaker = "ユーザー" if turn["role"] == "user" else "アシスタント"
        lines.append(f"{speaker}: {turn['content']}")

    return lines


def build_local_prompt(user_text, conversation_history=None, current_location=None, mode="chat", user_profile_context=None):
    conversation_history = conversation_history or []
    user_text = _coerce_text(user_text)
    current_location = _coerce_text(current_location)
    mode = _coerce_text(mode) or "chat"
    user_profile_context = _coerce_text(user_profile_context)

    lines = [
        LOCAL_ASSISTANT_SYSTEM_PROMPT.strip(),
        "",
        f"プロンプト契約: {PROMPT_CONTRACT_VERSION}",
        f"モード: {mode}",
    ]

    lines.extend(_format_history(conversation_history))

    if user_profile_context:
        lines.extend([
            "",
            user_profile_context,
        ])

    if current_location:
        lines.extend([
            "",
            f"現在地情報: {current_location}",
        ])

    lines.extend([
        "",
        f"ユーザー入力: {user_text}",
        "返答方針: 結論を先に、短く自然な日本語で答える",
        "アシスタント:",
    ])

    return "\n".join(lines)