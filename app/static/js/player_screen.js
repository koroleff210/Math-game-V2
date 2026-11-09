(function () {
  'use strict';
  const frame = document.getElementById('player-page-frame');
  if (!frame) return;

  function sync() {
    try {
      const child = frame.contentWindow;
      const url = new URL(child.location.href);
      if (url.origin !== location.origin || url.pathname === 'about:blank') return;
      // Authentication and teacher screens leave the player container normally.
      if (!/^\/(player|classic|boss-rush)(\/|$)/.test(url.pathname)) {
        location.replace(url.href);
        return;
      }
      if (location.href !== url.href) history.replaceState(null, '', url.href);
      document.title = child.document.title || 'KorePhysics';
    } catch (error) { /* An external target cannot control the player container. */ }
  }

  window.PlayerScreen = { sync: sync };
  frame.addEventListener('load', sync);
  sync();
})();
