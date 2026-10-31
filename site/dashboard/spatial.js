/* Bounded OBJ/STL wireframe inspection, entirely in this browser. */
(() => {
 'use strict';
 const $=id=>document.getElementById(id);
 let vertices=[],edges=[],angleX=.35,angleY=.55,scale=1,drag=null,frame=null,lastFrame=0;
 const MAX_VERTICES=180000,MAX_EDGES=12000;
 function parseOBJ(text){
  const points=[],lines=[];for(const line of text.split(/\r?\n/)){
   if(line.startsWith('v ')){const value=line.trim().split(/\s+/).slice(1,4).map(Number);if(value.length!==3||!value.every(Number.isFinite))throw new Error('頂点が不正です。');points.push(value);if(points.length>MAX_VERTICES)throw new Error('頂点数が多すぎます。');}
   else if(/^[fl] /.test(line)){const indices=line.trim().split(/\s+/).slice(1).map(token=>{let value=Number(token.split('/')[0]);return value<0?points.length+value:value-1;});if(indices.length>2000)throw new Error('面が複雑すぎます。');for(let i=1;i<indices.length;i++)lines.push([indices[i-1],indices[i]]);if(line[0]==='f'&&indices.length>2)lines.push([indices[indices.length-1],indices[0]]);if(lines.length>360000)throw new Error('辺の数が多すぎます。');}
  }
  if(!points.length||!lines.length)throw new Error('頂点と面を含むOBJを選択してください。');
  if(lines.some(pair=>pair.some(index=>!Number.isInteger(index)||index<0||index>=points.length)))throw new Error('頂点の参照が不正です。');
  return {points,lines};
 }
 function parseSTL(buffer){const view=new DataView(buffer);let points=[];
  if(buffer.byteLength>=84&&84+view.getUint32(80,true)*50===buffer.byteLength){const count=view.getUint32(80,true);if(count>60000)throw new Error('STLは6万三角形までです。');for(let i=0;i<count;i++){const at=84+i*50+12;for(let j=0;j<3;j++)points.push([view.getFloat32(at+j*12,true),view.getFloat32(at+j*12+4,true),view.getFloat32(at+j*12+8,true)]);}}
  else{const text=new TextDecoder().decode(buffer);for(const match of text.matchAll(/\bvertex\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)/g)){points.push(match.slice(1).map(Number));if(points.length>MAX_VERTICES)throw new Error('STLは6万三角形までです。');}}
  if(!points.length||points.length%3||points.some(p=>!p.every(Number.isFinite)))throw new Error('STLの形式が不正です。');
  const lines=[];for(let i=0;i<points.length;i+=3)lines.push([i,i+1],[i+1,i+2],[i+2,i]);return {points,lines};
 }
 function loadModel(result){const {points,lines}=result;const min=[Infinity,Infinity,Infinity],max=[-Infinity,-Infinity,-Infinity];for(const p of points)for(let k=0;k<3;k++){min[k]=Math.min(min[k],p[k]);max[k]=Math.max(max[k],p[k]);}
  const sizes=max.map((n,k)=>n-min[k]);if(sizes.some(n=>!Number.isFinite(n))||!sizes.some(n=>n>0))throw new Error('モデルのサイズが不正です。');const extent=Math.max(...sizes),center=max.map((n,k)=>(n+min[k])/2);
  const stride=Math.max(1,Math.ceil(lines.length/MAX_EDGES)),sampled=lines.filter((_,i)=>i%stride===0),lookup=new Map();vertices=[];edges=sampled.map(pair=>pair.map(index=>{if(!lookup.has(index)){lookup.set(index,vertices.length);vertices.push(points[index].map((n,k)=>(n-center[k])/extent));}return lookup.get(index);}));
  $('mc-spatial-info').textContent=`頂点 ${points.length.toLocaleString()} / 辺 ${lines.length.toLocaleString()}（描画 ${edges.length.toLocaleString()}）\n範囲 X ${sizes[0].toPrecision(5)} / Y ${sizes[1].toPrecision(5)} / Z ${sizes[2].toPrecision(5)}\n単位はファイル内で保証されません。設計寸法・体積・強度の解析値ではありません。`;
  angleX=.35;angleY=.55;scale=1;$('mc-spatial-zoom').value='1';draw();
 }
 function draw(){const canvas=$('mc-spatial-canvas'),ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height;ctx.clearRect(0,0,w,h);ctx.fillStyle='#03141f';ctx.fillRect(0,0,w,h);ctx.strokeStyle='#17394a';ctx.lineWidth=1;for(let x=0;x<w;x+=40){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();}for(let y=0;y<h;y+=40){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}
  const cx=Math.cos(angleX),sx=Math.sin(angleX),cy=Math.cos(angleY),sy=Math.sin(angleY);const transformed=vertices.map(p=>{const x=p[0]*cy+p[2]*sy,z=-p[0]*sy+p[2]*cy;const y=p[1]*cx-z*sx;return [w/2+x*w*.55*scale,h/2-y*w*.55*scale];});
  ctx.strokeStyle='#59cfe6';ctx.lineWidth=.8;ctx.beginPath();for(const[a,b]of edges){ctx.moveTo(...transformed[a]);ctx.lineTo(...transformed[b]);}ctx.stroke();ctx.fillStyle='#65b8d0';ctx.font='12px Consolas';ctx.fillText(vertices.length?'LOCAL GEOMETRY / WIREFRAME':'OBJ / STL を選択',15,24);
 }
 function animate(at){frame=null;if(!$('mc-spatial-spin').checked||document.hidden||document.querySelector('[data-info-panel="spatial"]').hidden)return;if(at-lastFrame>=66){angleY+=.01;draw();lastFrame=at;}frame=requestAnimationFrame(animate);}
 function startSpin(){if(frame!==null)cancelAnimationFrame(frame);frame=null;if($('mc-spatial-spin').checked&&!document.hidden&&!document.querySelector('[data-info-panel="spatial"]').hidden)frame=requestAnimationFrame(animate);}
 window.initSpatialViewer=()=>{const canvas=$('mc-spatial-canvas');draw();
  $('mc-model-file').addEventListener('change',async event=>{const file=event.target.files[0];if(!file)return;try{if(file.size>10000000||! /\.(obj|stl)$/i.test(file.name))throw new Error('10MB以下のOBJ/STLを選択してください。');const result=/\.obj$/i.test(file.name)?parseOBJ(await file.text()):parseSTL(await file.arrayBuffer());loadModel(result);$('mc-spatial-status').textContent=file.name+' を端末内で読み込みました。';}catch(error){$('mc-spatial-status').textContent=error.message;}});
  canvas.addEventListener('pointerdown',event=>{drag={x:event.clientX,y:event.clientY};canvas.setPointerCapture(event.pointerId);});canvas.addEventListener('pointermove',event=>{if(!drag)return;angleY+=(event.clientX-drag.x)*.01;angleX+=(event.clientY-drag.y)*.01;drag={x:event.clientX,y:event.clientY};draw();});for(const type of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(type,()=>drag=null);
  canvas.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;event.preventDefault();if(event.key==='ArrowLeft')angleY-=.1;if(event.key==='ArrowRight')angleY+=.1;if(event.key==='ArrowUp')angleX-=.1;if(event.key==='ArrowDown')angleX+=.1;draw();});
  $('mc-spatial-zoom').addEventListener('input',event=>{scale=Number(event.target.value);draw();});$('mc-spatial-spin').addEventListener('change',startSpin);
  $('mc-spatial-reset').addEventListener('click',()=>{angleX=.35;angleY=.55;scale=1;$('mc-spatial-zoom').value='1';draw();});
  $('mc-spatial-clear').addEventListener('click',()=>{vertices=[];edges=[];$('mc-spatial-spin').checked=false;startSpin();$('mc-model-file').value='';$('mc-spatial-info').textContent='';$('mc-spatial-status').textContent='モデルを消去しました。';draw();});
  new MutationObserver(startSpin).observe(document.querySelector('[data-info-panel="spatial"]'),{attributes:true,attributeFilter:['hidden']});document.addEventListener('visibilitychange',startSpin);window.addEventListener('pagehide',()=>{if(frame!==null)cancelAnimationFrame(frame);frame=null;});
 };
})();
