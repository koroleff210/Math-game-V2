(() => {
  'use strict';

  // Send descriptions after gathering so offers and answers carry their ICE candidates.
  async function localDescription(peer, description) {
    await peer.setLocalDescription(description);
    if (peer.iceGatheringState !== 'complete') {
      await new Promise(resolve => {
        function done() {
          clearTimeout(timeout);
          peer.removeEventListener('icegatheringstatechange', check);
          resolve();
        }
        function check() {
          if (peer.iceGatheringState === 'complete') done();
        }
        const timeout = setTimeout(done, 5000);
        peer.addEventListener('icegatheringstatechange', check);
        check();
      });
    }
    return peer.localDescription.toJSON();
  }

  function player(frame) {
    const dialog = document.getElementById('proctor-pause');
    const status = document.getElementById('proctor-status');
    const resume = document.getElementById('proctor-resume');
    const cancel = document.getElementById('proctor-cancel');
    let sessionId, form, stream, socket, peer, shareTimer;
    let boundDocument;
    let active = false;
    let captureInProgress = false;

    function pause(message) {
      status.textContent = message;
      cancel.hidden = !form;
      resume.textContent = stream ? 'Share again' : 'Share screen';
      if (!dialog.open) dialog.showModal();
    }

    function stop() {
      clearTimeout(shareTimer);
      if (peer) peer.close();
      if (socket) {
        socket.removeAllListeners();
        socket.disconnect();
      }
      if (stream) stream.getTracks().forEach(track => track.stop());
      peer = socket = stream = null;
      active = false;
    }

    function loseShare(message) {
      stop();
      pause(message);
    }

    function requirementEnded() {
      const join = form;
      stop();
      sessionId = form = null;
      if (dialog.open) dialog.close();
      if (join) {
        delete join.dataset.proctorJoin;
        join.requestSubmit();
      }
    }

    async function share() {
      if (captureInProgress || stream) return;
      const target = sessionId;
      if (!navigator.mediaDevices?.getDisplayMedia || !window.RTCPeerConnection || typeof io !== 'function') {
        pause('Screen sharing is unavailable in this browser. Use a desktop browser with screen sharing enabled.');
        return;
      }
      captureInProgress = true;
      resume.disabled = true;
      try {
        const captured = await navigator.mediaDevices.getDisplayMedia({
          video: { displaySurface: 'monitor', frameRate: { ideal: 5, max: 10 } },
          audio: false,
          surfaceSwitching: 'exclude'
        });
        const track = captured.getVideoTracks()[0];
        if (target !== sessionId || track?.getSettings().displaySurface !== 'monitor') {
          captured.getTracks().forEach(item => item.stop());
          if (target === sessionId) pause('Choose Entire Screen in the browser picker.');
          return;
        }
        stream = captured;
        track.addEventListener('ended', () => loseShare('Sharing stopped. Share again to continue.'), { once: true });
        pause('Screen selected. Waiting for the teacher’s monitoring tab…');
        const wire = io({ forceNew: true });
        socket = wire;
        let iceServers = [];

        wire.on('connect', () => {
          wire.timeout(8000).emit('proctor_share', { session_id: target, surface: 'monitor' }, (err, reply) => {
            if (wire !== socket) return;
            if (err || !reply?.ok) {
              loseShare(reply?.message || 'Could not connect to the monitoring session. Try again.');
              return;
            }
            iceServers = reply.ice_servers;
            wire.emit('proctor_share_ready', { session_id: target });
          });
        });

        wire.on('proctor_negotiate', async () => {
          if (wire !== socket) return;
          if (peer) peer.close();
          const connection = new RTCPeerConnection({ iceServers });
          peer = connection;
          connection.addTrack(track, captured);
          connection.addEventListener('connectionstatechange', () => {
            if (connection === peer && ['failed', 'closed'].includes(connection.connectionState)) {
              loseShare('The screen connection failed. Share again to retry.');
            }
          });
          try {
            const description = await localDescription(connection, await connection.createOffer());
            if (connection === peer) wire.emit('proctor_signal', { session_id: target, description });
          } catch {
            if (connection === peer) loseShare('Could not start the screen connection. Try again.');
          }
        });

        wire.on('proctor_signal', async ({ description }) => {
          const connection = peer;
          if (!connection || description.type !== 'answer' || connection.signalingState !== 'have-local-offer') return;
          try {
            await connection.setRemoteDescription(description);
          } catch {
            if (connection === peer) loseShare('Could not connect to the teacher. Try again.');
          }
        });

        wire.on('proctor_status', reply => {
          clearTimeout(shareTimer);
          active = reply.active;
          if (!active) {
            pause('The teacher is reconnecting. Your progress is saved.');
            return;
          }
          shareTimer = setTimeout(() => {
            active = false;
            pause('Waiting for the teacher’s screen connection. Your progress is saved.');
          }, 12000);
          if (dialog.open) dialog.close();
          if (form) {
            const join = form;
            form = null;
            join.requestSubmit();
          }
        });
        wire.on('disconnect', () => loseShare('The screen connection was lost. Share again to continue.'));
        wire.on('connect_error', () => loseShare('Could not reach the screen sharing service. Try again.'));
        wire.on('proctor_replaced', () => loseShare('This session is sharing from another tab. Continue there or share again here.'));
        wire.on('proctor_ended', requirementEnded);
      } catch {
        if (target === sessionId) pause('Screen sharing was cancelled or blocked. Allow it and try again.');
      } finally {
        captureInProgress = false;
        resume.disabled = false;
      }
    }

    resume.addEventListener('click', () => {
      if (stream) stop();
      share();
    });
    cancel.addEventListener('click', () => {
      stop();
      sessionId = form = null;
      dialog.close();
    });
    dialog.addEventListener('cancel', event => event.preventDefault());
    window.addEventListener('pagehide', stop);
    setInterval(async () => {
      const target = sessionId;
      if (!target || !dialog.open) return;
      try {
        const response = await fetch('/proctoring/' + target + '/status', { cache: 'no-store' });
        if (response.ok && (await response.json()).required === false && target === sessionId) {
          requirementEnded();
        }
      } catch { /* Keep the pause while the network is unavailable. */ }
    }, 4000);

    function bindFrame() {
      const child = frame.contentDocument;
      if (!child || child === boundDocument || child.URL === 'about:blank') return;
      boundDocument = child;
      const marker = child.querySelector('[data-proctored-session]');
      if (marker) {
        const next = Number(marker.dataset.proctoredSession);
        if (sessionId !== next) stop();
        sessionId = next;
        if (!active) pause('Share your entire screen to continue. Your place in the game is saved.');
      } else if (sessionId) {
        stop();
        sessionId = form = null;
        if (dialog.open) dialog.close();
      }
      child.addEventListener('submit', event => {
        const target = Number(event.target.dataset.proctorJoin);
        if (!target || (target === sessionId && active)) return;
        event.preventDefault();
        if (sessionId !== target) stop();
        sessionId = target;
        form = event.target;
        share();
      });
    }
    frame.addEventListener('load', bindFrame);
    bindFrame();
    window.addEventListener('pageshow', event => {
      if (event.persisted) {
        boundDocument = null;
        bindFrame();
      }
    });
  }

  function monitor(root) {
    const sessionId = Number(root.dataset.sessionId);
    const grid = document.getElementById('proctor-grid');
    const status = document.getElementById('proctor-monitor-status');
    const socket = io({ forceNew: true });
    const peers = new Map();
    let iceServers = [];
    let ready = false;

    function report() {
      if (!ready || !socket.connected) return;
      const active = [];
      for (const [id, entry] of peers) {
        const receiving = entry.peer?.connectionState === 'connected' && entry.video.readyState >= 2;
        entry.state.textContent = receiving ? 'Sharing' : 'Connecting…';
        if (receiving) active.push(id);
      }
      socket.emit('proctor_viewed', { session_id: sessionId, peers: active });
    }

    function remove(id) {
      const entry = peers.get(id);
      if (!entry) return;
      peers.delete(id);
      if (entry.peer) entry.peer.close();
      entry.video.srcObject = null;
      entry.video.hidden = true;
      entry.state.textContent = 'Sharing stopped';
    }

    function reset(message) {
      ready = false;
      for (const id of peers.keys()) remove(id);
      status.textContent = message;
    }

    socket.on('connect', () => {
      socket.timeout(8000).emit('proctor_watch', { session_id: sessionId }, (error, reply) => {
        if (error || !reply?.ok) {
          status.textContent = reply?.message || 'Could not open this monitoring session.';
          return;
        }
        iceServers = reply.ice_servers;
        ready = true;
        status.textContent = 'Monitoring is ready. Students can now share and join.';
        socket.emit('proctor_watch_ready', { session_id: sessionId });
      });
    });
    socket.on('disconnect', () => reset('Disconnected from the session.'));
    socket.on('proctor_ended', () => {
      socket.disconnect();
      reset('Screen sharing has ended for this session.');
    });
    socket.on('proctor_peer_left', ({ peer }) => remove(peer));
    socket.on('proctor_peer', data => {
      remove(data.peer);
      let tile = grid.querySelector('[data-player-id="' + Number(data.player_id) + '"]');
      if (!tile) {
        tile = document.createElement('article');
        tile.dataset.playerId = data.player_id;
        const name = document.createElement('strong');
        name.textContent = data.name;
        const state = document.createElement('p');
        state.setAttribute('role', 'status');
        const video = document.createElement('video');
        video.muted = video.autoplay = video.playsInline = video.controls = true;
        video.hidden = true;
        video.setAttribute('aria-label', data.name + ' screen');
        tile.append(name, state, video);
        grid.append(tile);
      }
      const state = tile.querySelector('[role="status"]');
      state.textContent = 'Connecting…';
      peers.set(data.peer, { state, video: tile.querySelector('video'), peer: null });
    });
    socket.on('proctor_signal', async ({ peer: id, description }) => {
      const entry = peers.get(id);
      if (!entry || description.type !== 'offer') return;
      if (entry.peer) entry.peer.close();
      const peer = new RTCPeerConnection({ iceServers });
      entry.peer = peer;
      peer.ontrack = event => {
        entry.video.srcObject = event.streams[0];
        entry.video.hidden = false;
        entry.video.addEventListener('loadeddata', report, { once: true });
      };
      peer.onconnectionstatechange = report;
      try {
        await peer.setRemoteDescription(description);
        const answer = await localDescription(peer, await peer.createAnswer());
        if (peers.get(id)?.peer === peer) socket.emit('proctor_signal', { session_id: sessionId, peer: id, description: answer });
      } catch {
        if (peers.get(id)?.peer === peer) {
          remove(id);
          entry.state.textContent = 'Connection failed. Ask the student to share again.';
        }
      }
    });
    const timer = setInterval(report, 3000);
    window.addEventListener('pagehide', () => {
      clearInterval(timer);
      reset('Monitoring closed.');
      socket.disconnect();
    });
  }

  const frame = document.getElementById('player-page-frame');
  const root = document.getElementById('proctor-monitor');
  if (frame) player(frame);
  if (root && typeof io === 'function') monitor(root);
})();
