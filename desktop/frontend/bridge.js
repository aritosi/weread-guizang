// Compatibility shim for the existing ui.html. The original page is served unchanged.
(() => {
  if (window.top !== window || location.hostname !== '127.0.0.1') return;
  const invoke = window.__TAURI_INTERNALS__ && window.__TAURI_INTERNALS__.invoke;
  if (!invoke) return;
  const report = error => { if (typeof window.whisper === 'function') window.whisper(String(error)); };
  const bridge = { postMessage(message) {
    if (message && message.cmd === 'pickExportDir') {
      invoke('pick_export_dir').then(path => {
        if (path && typeof window.gzExportDir === 'function') window.gzExportDir(path);
      }).catch(report);
    }
  }};
  window.webkit = window.webkit || {};
  window.webkit.messageHandlers = window.webkit.messageHandlers || {};
  window.webkit.messageHandlers.guizang = bridge;
  const saved = __GUIZANG_WEB_STATE__;
  const storage = window.localStorage;
  const rawSet = Storage.prototype.setItem;
  const rawRemove = Storage.prototype.removeItem;
  const rawClear = Storage.prototype.clear;
  // The listener's random port changes on every launch. Keep the same logical origin state.
  try {
    if (sessionStorage.getItem('__guizang_desktop_session__') !== '__GUIZANG_SESSION__') {
      rawClear.call(storage);
      for (const [key,value] of Object.entries(saved)) rawSet.call(storage,key,value);
      sessionStorage.setItem('__guizang_desktop_session__','__GUIZANG_SESSION__');
    }
  } catch (_) {}
  let writeQueue = Promise.resolve();
  const flush = () => {
    const values = {};
    try { for(let i=0;i<storage.length;i++){const key=storage.key(i); values[key]=storage.getItem(key);} }
    catch (_) { return writeQueue; }
    writeQueue = writeQueue.catch(() => {}).then(() => invoke('save_web_state', {values}));
    writeQueue.catch(report);
    return writeQueue;
  };
  // Persist user actions immediately; postponing this until idle loses the last
  // preference change when the user closes the window straight after clicking.
  const changed = flush;
  Storage.prototype.setItem = function(key,value){rawSet.call(this,key,value); if(this===storage)changed();};
  Storage.prototype.removeItem = function(key){rawRemove.call(this,key); if(this===storage)changed();};
  Storage.prototype.clear = function(){rawClear.call(this); if(this===storage)changed();};
  window.addEventListener('pagehide',flush);
  window.gzDesktopClose = () => flush().catch(report).finally(() => invoke('finish_close').catch(report));
})();
