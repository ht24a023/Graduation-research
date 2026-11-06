from pathlib import Path
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8');s=s.replace('def _detect_required_clarification(message: str, conversation_history: list[dict[str, str]], intent: str) -> dict[str, Any] | None:', 'def _detect_required_clarification(message: str, conversation_history: list[dict[str, str]], intent: str, program_only: bool = False) -> dict[str, Any] | None:',1)
a=s.index('  if any(keyword in message for keyword in _COMPARISON_KEYWORDS):',s.index('def _detect_required_clarification'))
s=s[:a]+'  if program_only:\n    return None\n\n'+s[a:]
s=s.replace("clarification_decision = run_stage('intent', _detect_required_clarification, effective_message, history, intent)", "clarification_decision = run_stage('intent', _detect_required_clarification, effective_message, history, intent, **({'program_only':True} if policy is not None else {}))",1)
p.write_text(s,encoding='utf-8')
