/* Opt-in, local-only diagnostics. No metrics are transmitted or persisted. */
(() => {
  if (!new URLSearchParams(location.search).has('ui_measure') || document.getElementById('player-page-frame')) return;
  const longTasks = [], lcp = [];
  for (const [type, list] of [['longtask', longTasks], ['largest-contentful-paint', lcp]]) {
    try { new PerformanceObserver(records => list.push(...records.getEntries())).observe({type, buffered:true}); } catch (_) {}
  }
  const panel = document.createElement('details');
  panel.id = 'ui-measure-panel';
  panel.style.cssText = 'position:fixed;bottom:8px;left:8px;z-index:2147483647;max-width:min(660px,95vw);max-height:60vh;overflow:auto;background:#fffdf5;color:#263640;border:2px solid #38737d;border-radius:8px;padding:8px;font:12px/1.4 monospace;box-shadow:0 4px 20px #0003';
  const summary = document.createElement('summary'); summary.textContent = 'Loading measurements';
  const snapshot = document.createElement('button'); snapshot.type = 'button'; snapshot.textContent = 'Capture timings';
  const output = document.createElement('pre'); output.id = 'ui-measure-data'; output.style.whiteSpace = 'pre-wrap';
  panel.append(summary, snapshot, output); document.body.append(panel);
  const round = n => Math.round(n || 0);
  const navigation = n => n ? ({ttfbMs:round(n.responseStart-n.startTime), requestWaitMs:round(n.responseStart-n.requestStart), downloadMs:round(n.responseEnd-n.responseStart), domReadyMs:round(n.domContentLoadedEventEnd), loadMs:round(n.loadEventEnd), responseBytes:n.transferSize, htmlBytes:n.decodedBodySize}) : null;
  function capture() {
    const resources = performance.getEntriesByType('resource').filter(r => !r.name.includes('/socket.io/?'));
    const rows = resources.map(r => ({url:r.name.replace(location.origin,''), type:r.initiatorType, startMs:round(r.startTime), durationMs:round(r.duration), waitMs:r.requestStart ? round(r.responseStart-r.requestStart) : null, downloadMs:r.responseStart ? round(r.responseEnd-r.responseStart) : null, transferredBytes:r.transferSize, decodedBytes:r.decodedBodySize}));
    const own = performance.getEntriesByType('navigation')[0];
    let container = null;
    try { if (parent !== window) container = navigation(parent.performance.getEntriesByType('navigation')[0]); } catch (_) {}
    const data = {page:location.pathname, capturedAt:new Date().toISOString(), navigation:navigation(own), container,
      paint:performance.getEntriesByType('paint').map(p => ({name:p.name, ms:round(p.startTime)})),
      largestPaintMs:lcp.length ? round(lcp[lcp.length-1].startTime) : null,
      readiness:performance.getEntriesByType('mark').filter(m=>/player-|studio-/.test(m.name)).map(m=>({name:m.name,ms:round(m.startTime)})),
      longTasks:{count:longTasks.length,totalMs:round(longTasks.reduce((sum,t)=>sum+t.duration,0)),maxMs:round(Math.max(0,...longTasks.map(t=>t.duration)))},
      resources:{count:rows.length,transferredBytes:rows.reduce((sum,r)=>sum+r.transferredBytes,0),decodedBytes:rows.reduce((sum,r)=>sum+r.decodedBytes,0),slowest:rows.sort((a,b)=>b.durationMs-a.durationMs).slice(0,15)}};
    output.textContent = JSON.stringify(data,null,2);
  }
  snapshot.onclick = capture;
  const status = document.getElementById('studio-status');
  if (status) {
    let ready = false;
    const check = () => { if (!ready && !/Loading|Saving/.test(status.textContent)) {ready=true;performance.mark('studio-first-ready');} };
    new MutationObserver(check).observe(status,{childList:true,subtree:true}); check();
  }
  window.addEventListener('load',capture,{once:true});
  setTimeout(capture,5000);
})();
