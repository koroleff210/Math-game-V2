(function () {
  'use strict';
  const pending = new Map();
  const warmQueue = [];
  const queued = new Set();
  let warming = false;

  function imageReady(url, priority) {
    if (!url) return Promise.resolve();
    if (pending.has(url)) return pending.get(url);
    const task = new Promise(function (resolve, reject) {
      const image = new Image();
      let settled = false;
      const timeout = setTimeout(function () { finish(new Error('Image load timed out')); }, 8000);
      function finish(error) {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        image.onload = image.onerror = null;
        if (error) reject(error); else resolve();
      }
      image.decoding = 'async';
      image.fetchPriority = typeof priority === 'string' ? priority : 'high';
      image.onload = function () {
        if (image.decode) image.decode().then(function () { finish(); }, finish);
        else finish();
      };
      image.onerror = function () { finish(new Error('Image unavailable')); };
      image.src = url;
    });
    pending.set(url, task);
    task.catch(function () { pending.delete(url); });
    return task;
  }

  async function prepareNodes(nodes) {
    const images = new Set();
    nodes.filter(Boolean).forEach(function (node) {
      if (node.matches && node.matches('img')) images.add(node);
      if (node.querySelectorAll) node.querySelectorAll('img').forEach(function (img) { images.add(img); });
    });
    await Promise.all(Array.from(images).map(async function (img) {
      const source = img.currentSrc || img.src;
      if (!source) return;
      img.setAttribute('data-ui-pending', '');
      try {
        await imageReady(source);
        if (img.decode) await img.decode();
        img.removeAttribute('data-ui-pending');
        img.removeAttribute('data-ui-image-failed');
      } catch (error) {
        img.removeAttribute('data-ui-pending');
        img.setAttribute('data-ui-image-failed', '');
        throw error;
      }
    }));
  }

  function cssImages(node) {
    const value = [getComputedStyle(node).backgroundImage, getComputedStyle(node, '::before').backgroundImage,
      getComputedStyle(node, '::after').backgroundImage].join(',');
    return Array.from(value.matchAll(/url\(["']?([^"')]+)["']?\)/g), function (match) { return match[1]; });
  }

  function prefetch(urls) {
    if (navigator.connection && navigator.connection.saveData) return;
    (urls || []).forEach(function (url) {
      if (url && !queued.has(url) && !pending.has(url)) { queued.add(url); warmQueue.push(url); }
    });
    if (warming) return;
    warming = true;
    const start = async function () {
      while (warmQueue.length) {
        await Promise.all(warmQueue.splice(0, 2).map(function (url) { return imageReady(url, 'low').catch(function () {}); }));
      }
      warming = false;
    };
    if (window.requestIdleCallback) requestIdleCallback(start, { timeout: 1000 }); else setTimeout(start, 100);
  }

  function preloadFrom(root) {
    const node = root.querySelector('[data-ui-preloads]');
    if (!node) return;
    function urls(value) {
      if (typeof value === 'string') return [value];
      return value && typeof value === 'object' ? Object.values(value).flatMap(urls) : [];
    }
    try { prefetch(urls(JSON.parse(node.textContent))); } catch (error) { /* Optional warmup only. */ }
  }

  function setBusy(busy) {
    let status = document.getElementById('ui-shell-status');
    if (busy && !status) {
      status = document.createElement('div');
      status.id = 'ui-shell-status';
      status.className = 'ui-shell-status';
      status.setAttribute('role', 'status');
      status.textContent = 'Preparing your selection…';
      document.body.appendChild(status);
    }
    if (!busy && status) status.remove();
  }

  function initFullscreen() {
    if (document.documentElement.classList.contains('ui-embedded')) {
      function activate(event) {
        if (window.parent.PlayerUI && window.parent.PlayerUI.activateFullscreen) window.parent.PlayerUI.activateFullscreen(event);
      }
      document.addEventListener('click', activate, true);
      document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape' && !event.ctrlKey && !event.altKey && !event.metaKey) activate(event);
      }, true);
      // Keep the address bar accurate for the Hub's existing AJAX selection URLs.
      ['pushState', 'replaceState'].forEach(function (name) {
        const original = history[name];
        history[name] = function () {
          const result = original.apply(this, arguments);
          if (window.parent.PlayerScreen) window.parent.PlayerScreen.sync();
          return result;
        };
      });
      return;
    }
    const buttons = document.querySelectorAll('[data-ui-fullscreen]');
    const target = document.documentElement;
    const request = target.requestFullscreen || target.webkitRequestFullscreen;
    const exit = document.exitFullscreen || document.webkitExitFullscreen;
    let entering = false;
    let leavingPage = false;
    let autoAttempted = false;
    let automatic = true;
    try { automatic = sessionStorage.getItem('player-fullscreen') !== 'off'; } catch (error) { /* Storage can be disabled. */ }
    function remember(enabled) {
      automatic = enabled;
      try { sessionStorage.setItem('player-fullscreen', enabled ? 'on' : 'off'); } catch (error) { /* Optional preference. */ }
    }
    function active() { return !!(document.fullscreenElement || document.webkitFullscreenElement); }
    function update() {
      buttons.forEach(function (button) {
        button.hidden = !request;
        const label = active() ? 'Exit fullscreen' : 'Fullscreen';
        button.textContent = document.body.classList.contains('ui-player-screen') ? '⛶' : label;
        button.title = label;
        button.setAttribute('aria-label', label);
        button.setAttribute('aria-pressed', String(active()));
      });
    }
    async function enter() {
      if (!request || active() || entering) return;
      entering = true;
      try { await request.call(target); remember(true); }
      catch (error) { /* The visible control remains available if the browser blocks automatic entry. */ }
      finally { entering = false; update(); }
    }
    function automaticEntry(event) {
      if (!automatic || autoAttempted || active() || entering || !document.hasFocus()) return;
      if (event && (!event.isTrusted || event.target.closest?.('[data-ui-fullscreen]'))) return;
      if (!navigator.userActivation || !navigator.userActivation.isActive) return;
      autoAttempted = true;
      enter();
    }
    buttons.forEach(function (button) {
      button.addEventListener('click', async function () {
        if (active()) {
          remember(false);
          try { await exit.call(document); } catch (error) { /* Keep the current state. */ }
        } else await enter();
        update();
      });
    });
    function changed() {
      if (active()) remember(true);
      else if (!leavingPage && document.visibilityState === 'visible') remember(false);
      update();
    }
    document.addEventListener('fullscreenchange', changed);
    document.addEventListener('webkitfullscreenchange', changed);
    document.addEventListener('click', automaticEntry, true);
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape' && !event.ctrlKey && !event.altKey && !event.metaKey) automaticEntry(event);
    }, true);
    window.addEventListener('focus', function () { autoAttempted = false; automaticEntry(); });
    window.addEventListener('pagehide', function () { leavingPage = true; });
    window.addEventListener('pageshow', function () { leavingPage = false; update(); });
    window.PlayerUI.activateFullscreen = automaticEntry;
    update();
  }

  async function revealPage() {
    initFullscreen();
    if (document.getElementById('player-page-frame')) return;
    const inventory = document.querySelector('[data-smith-inventory]');
    if (inventory && matchMedia('(max-width: 980px)').matches) inventory.open = false;
    function watchImage(img) {
      if (img.hasAttribute('data-ui-watched')) return;
      img.setAttribute('data-ui-watched', '');
      img.setAttribute('data-ui-pending', '');
      async function ready() {
        try {
          if (img.decode) await img.decode();
          img.removeAttribute('data-ui-pending');
        } catch (error) { img.setAttribute('data-ui-image-failed', ''); }
      }
      if (img.complete && img.naturalWidth) ready();
      else {
        img.addEventListener('load', ready, { once: true });
        img.addEventListener('error', function () { img.setAttribute('data-ui-image-failed', ''); }, { once: true });
      }
    }
    document.querySelectorAll('img').forEach(watchImage);
    new MutationObserver(function (records) {
      records.forEach(function (record) {
        record.addedNodes.forEach(function (node) {
          if (node.nodeType !== 1) return;
          if (node.matches('img')) watchImage(node);
          node.querySelectorAll('img').forEach(watchImage);
        });
      });
    }).observe(document.body, { childList: true, subtree: true });
    const images = Array.from(document.images).filter(function (img) {
      return img.getClientRects().length && img.getBoundingClientRect().top < innerHeight + 150 && img.loading !== 'lazy';
    });
    const backgrounds = Array.from(document.querySelectorAll('body, main, .smith-panel, .boss-rush-page, #game-layout, [data-ui-scene]'));
    const scenePreload = document.querySelector('link[rel="preload"][as="image"]');
    const preparation = Promise.allSettled([
      ...(scenePreload ? [imageReady(scenePreload.href).catch(function () {
        document.body.setAttribute('data-ui-background-failed', '');
      })] : []),
      ...images.map(function (img) { return prepareNodes([img]); }),
      ...backgrounds.map(async function (node) {
        try { await Promise.all(cssImages(node).map(imageReady)); }
        catch (error) { node.setAttribute('data-ui-background-failed', ''); }
      })
    ]);
    // Artwork may continue decoding independently; a slow decorative request
    // must not keep the whole screen in its loading state for eight seconds.
    await Promise.race([preparation, new Promise(function (resolve) { setTimeout(resolve, 1200); })]);
    preparation.then(function () { document.querySelectorAll('[data-gear-avatar-composite-region]').forEach(function (stage) {
      if (!stage.querySelector('[data-ui-image-failed]')) return;
      stage.setAttribute('data-ui-avatar-failed', '');
      const label = document.createElement('button');
      label.className = 'ui-avatar-error';
      label.textContent = 'Character image unavailable. Retry';
      label.type = 'button';
      label.onclick = function () { location.reload(); };
      stage.appendChild(label);
    }); });
    document.documentElement.classList.remove('ui-loading');
    clearTimeout(window.uiPageFallback);
    const loader = document.getElementById('ui-page-loader');
    if (loader) loader.remove();
    preloadFrom(document);
    prefetch(window.UIBackgroundPreloads || []);
    if (window.performance && performance.mark) {
      performance.mark('player-ui-ready');
      preparation.then(function () { performance.mark('player-artwork-ready'); });
    }
  }

  window.PlayerUI = { prepareNodes: prepareNodes, imageReady: imageReady, prefetch: prefetch, preloadFrom: preloadFrom, setBusy: setBusy };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', revealPage);
  else revealPage();
})();

/* Optional loading measurement panel. */
if (new URLSearchParams(location.search).has('ui_measure')) { const timingScript = document.createElement('script'); timingScript.src = '/static/js/ui_measure.js?v=20261018-1'; document.head.appendChild(timingScript); }
