from pathlib import Path
p=Path('functions/work_memory.py');s=p.read_text(encoding='utf-8');s=s.replace("        main,_=self.titles(key)\n        source=", "        main,proposal=self.titles(key)\n        source=",1);s=s.replace("'previous_user_edited':bool(base[main] and base[main].get('user_edited')),", "'previous_user_edited':bool(base[main] and base[main].get('user_edited')),\n                'previous_update_proposal':base[proposal].get('content','') if base[proposal] else '',",1)
a=s.index('    def status(self,session_id):');b=s.index('\n    def enqueue(',a)
s=s[:a]+'''    def status(self,session_id):
        key=self.key(session_id)
        with self._condition:
            state=dict(self._states.get(key,{'state':'idle'}))
            if not state.get('note'):
                candidates=[note for note in self._base(key).values() if note is not None]
                if candidates:
                    latest=max(candidates,key=lambda n:n.get('updated_at',''))
                    state['note']={'id':note_id(latest['title']),'title':latest['title'],'revision':latest.get('summary_revision',1)}
                    if state['state']=='idle':state['state']='saved'
            return {'ok':True,'enabled':self.is_enabled(),'session_key':key,
                    **state,'counts':dict(self._counts),
                    'can_retry':bool(self._contexts.get(key)),'extra_cloud_request':True}
'''+s[b:];p.write_text(s,encoding='utf-8')
