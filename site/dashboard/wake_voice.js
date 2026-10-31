/* Opt-in wake phrase input; stops on hidden tab and never starts on page load. */
(() => {
 'use strict';
 const $=id=>document.getElementById(id);
 let recognition=null,enabled=false,restart=null,failures=0,busy=false,lastText='',lastAt=0;
 const note=text=>$('mc-voice-status').textContent=text;
 function stop(text='呼びかけ待受を停止しました。'){
  window.aiSensory?.signal('idle');enabled=false;clearTimeout(restart);recognition?.abort();recognition=null;
  $('mc-voice-start').disabled=false;$('voice-start').disabled=false;$('mc-voice-stop').disabled=true;
  if(!$('send-btn').disabled)window.aiCore?.setState('idle');note(text);
 }
 function listen(){
  if(!enabled||document.hidden||busy||recognition)return;
  if(window.speechSynthesis?.speaking){restart=setTimeout(listen,1200);return;}
  const Engine=window.SpeechRecognition||window.webkitSpeechRecognition;
  const current=new Engine();recognition=current;current.lang='ja-JP';current.continuous=true;current.interimResults=false;
  current.onstart=()=>{if(enabled){note('呼びかけ待受中。録音内容はブラウザー提供元へ送信される場合があります。');}};
  current.onresult=event=>{
   if(!enabled||recognition!==current||busy||document.hidden)return;
   failures=0;
   for(let i=event.resultIndex;i<event.results.length;i++){
    if(!event.results[i].isFinal)continue;const transcript=event.results[i][0].transcript.trim();
    $('mc-voice-transcript').textContent=transcript; window.aiSensory?.transcript({text:transcript,final:true});
    const word=$('mc-wake-word').value.trim()||'AI';
    const names=word.toLocaleLowerCase()==='ai'?['AI','エーアイ','エイアイ']:[word];
    const matches=names.map(name=>({name,at:transcript.normalize('NFKC').toLocaleLowerCase().indexOf(name.toLocaleLowerCase())})).filter(item=>item.at>=0).sort((a,b)=>a.at-b.at);
    if(!matches.length)continue;const {name,at}=matches[0];
    const command=transcript.slice(at+name.length).replace(/^[、,。\s:：]+/,'').trim();if(!command){note('呼びかけを検出しました。名前に続けて用件を話してください。');continue;}
    if(lastText===command&&Date.now()-lastAt<4000)continue;lastText=command;lastAt=Date.now();
    if(command==='待受停止'||command==='停止して'){stop();return;}
    if($('message').value.trim()||$('send-btn').disabled){note('入力中または処理中のため、音声内容は送信していません。');continue;}
    const destinations={'予定を表示':'mission','今日の状況を表示':'briefing','天気を表示':'weather','地図を表示':'map','画像認識を表示':'vision','PC情報を表示':'system'};
    if(destinations[command]){window.missionControl.open(destinations[command]);note('表示を切り替えました。');continue;}
    $('message').value=command;$('message').dispatchEvent(new Event('input',{bubbles:true}));
    if($('mc-voice-autosend').checked){busy=true;current.abort();$('send-btn').click();note('呼びかけ後の用件を送信しました。');}
    else note('用件を入力欄に入れました。内容を確認して送信してください。');
   }
  };
  current.onerror=event=>{if(!enabled||recognition!==current)return;if(['not-allowed','service-not-allowed','audio-capture','language-not-supported'].includes(event.error)){stop('待受を開始できません：'+event.error);}else{failures++;note('音声認識が中断されました：'+event.error);}};
  current.onend=()=>{if(recognition!==current)return;recognition=null;if(!enabled||busy)return;window.aiSensory?.signal('recognition-wait');if(failures>=3){stop('音声認識が繰り返し失敗したため停止しました。');return;}restart=setTimeout(listen,1200);};
  try{current.start();}catch(error){stop('開始できません：'+error.message);}
 }
 window.initWakeVoice=()=>{
  $('mc-voice-start').addEventListener('click',()=>{if(!(window.SpeechRecognition||window.webkitSpeechRecognition)){note('このブラウザーは音声認識に対応していません。');return;}if(!window.isSecureContext){note('localhostまたはHTTPSで開いてください。');return;}if($('voice-start').disabled){note('通常の音声入力が終わってから開始してください。');return;}if(!$('message').value.trim()&&!$('send-btn').disabled){enabled=true;busy=false;failures=0;$('mc-voice-start').disabled=true;$('voice-start').disabled=true;$('mc-voice-stop').disabled=false;listen();}else note('チャットの処理・入力が終わってから開始してください。');});
  $('mc-voice-stop').addEventListener('click',()=>stop());
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&enabled)stop('画面が非表示になったため待受を停止しました。');});
  window.addEventListener('pagehide',()=>{enabled=false;clearTimeout(restart);recognition?.abort();});
  window.addEventListener('jarvis:request-start',()=>{if(enabled){window.aiSensory?.signal('idle');busy=true;recognition?.abort();clearTimeout(restart);}});
  for(const event of ['jarvis:request-finished','jarvis:request-failed'])window.addEventListener(event,()=>{busy=false;if(enabled){clearTimeout(restart);restart=setTimeout(listen,1500);}});
 };
})();
