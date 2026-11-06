const {contextBridge,ipcRenderer} = require('electron');
contextBridge.exposeInMainWorld('sotukenBrowser',{
 command:(name,value)=>ipcRenderer.invoke('browser-command',name,value),
 onState:callback=>ipcRenderer.on('browser-state',(_event,state)=>callback(state))
});
