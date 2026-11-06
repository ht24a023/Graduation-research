const {app, BrowserWindow, WebContentsView, ipcMain, session} = require('electron');
const path = require('node:path');
const base = process.env.SOTUKEN_URL || 'http://127.0.0.1:8000/';
const origin = new URL(base).origin;
if (!['127.0.0.1','localhost','[::1]'].includes(new URL(base).hostname)) throw Error('Local dashboard required');
let win, view;
app.setPath('userData', path.join(__dirname, 'profile'));
app.setPath('crashDumps', path.join(__dirname, 'profile', 'crashes'));
function valid(value) { try {const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password;} catch {return false;} }
if (!app.requestSingleInstanceLock()) app.quit();
else {
 app.on('second-instance', () => {if(win){win.restore();win.focus();}});
 app.whenReady().then(async () => {
  const remote = session.fromPartition('persist:sotuken-web');
  remote.setPermissionRequestHandler((_wc, permission, callback) => callback(permission === 'fullscreen'));
  remote.setPermissionCheckHandler((_wc, permission) => permission === 'fullscreen');
  remote.on('will-download', (_event, item) => {item.setSaveDialogOptions({title:'ダウンロードの保存先'});});
  win = new BrowserWindow({width:1600,height:1050,title:'sotuken — Chat + Browser',webPreferences:{preload:path.join(__dirname,'preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true}});
  win.setMenuBarVisibility(false);
  view = new WebContentsView({webPreferences:{session:remote,nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true}});
  win.contentView.addChildView(view); view.setVisible(false);
  const wc = view.webContents;
  wc.setWindowOpenHandler(({url}) => {if(valid(url)) wc.loadURL(url).catch(()=>{});return {action:'deny'};});
  wc.on('will-navigate',(event,url)=>{if(!valid(url))event.preventDefault();});
  wc.on('will-redirect',(event,url)=>{if(!valid(url))event.preventDefault();});
  const state = (error='') => {if(!win.isDestroyed())win.webContents.send('browser-state',{url:wc.getURL(),title:wc.getTitle(),back:wc.navigationHistory.canGoBack(),forward:wc.navigationHistory.canGoForward(),error});};
  wc.on('did-navigate',()=>state());wc.on('did-navigate-in-page',()=>state());wc.on('page-title-updated',()=>state());
  wc.on('did-fail-load',(_event,code,description,_url,main)=>{if(main&&code!==-3)state(description);});
  function trusted(event) {return event.sender===win.webContents && event.senderFrame===win.webContents.mainFrame && new URL(event.senderFrame.url).origin===origin;}
  ipcMain.handle('browser-command', async(event,command,value)=>{
   if(!trusted(event))throw Error('Untrusted sender');
   if(command==='navigate'){if(!valid(value))throw Error('HTTPSのURLを入力してください');await wc.loadURL(value);}
   else if(command==='back'&&wc.navigationHistory.canGoBack())wc.navigationHistory.goBack();
   else if(command==='forward'&&wc.navigationHistory.canGoForward())wc.navigationHistory.goForward();
   else if(command==='reload')wc.reload();
   else if(command==='bounds'){
    if(!value || !['x','y','width','height'].every(k=>Number.isFinite(value[k])))return;
    const [width,height]=win.getContentSize();
    const x=Math.max(0,Math.min(width,Math.round(value.x))),y=Math.max(0,Math.min(height,Math.round(value.y)));
    view.setBounds({x,y,width:Math.max(0,Math.min(width-x,Math.round(value.width))),height:Math.max(0,Math.min(height-y,Math.round(value.height)))});
    view.setVisible(value.width>10&&value.height>10);
   } else if(command==='hide')view.setVisible(false);
   state();return {ok:true};
  });
  win.webContents.on('will-navigate',(event,url)=>{if(new URL(url).origin!==origin)event.preventDefault();});
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  win.on('closed',()=>{wc.close();});
  await win.loadURL(base);
 });
 app.on('window-all-closed',()=>app.quit());
}
