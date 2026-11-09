/* Shared connection setup for the live Classic screens and Hub. */
(function () {
  'use strict';
  window.GameRealtime = {
    connect: function () {
      // Avoid the HTTP polling handshake on networks that support WebSockets.
      // Socket.IO 4.7 needs an explicit fallback when WebSocket-first fails.
      const socket = io({ transports: ['websocket'], timeout: 4000 });
      let fallback = false;
      socket.on('connect_error', function () {
        if (!fallback) {
          fallback = true;
          socket.io.opts.transports = ['polling', 'websocket'];
          socket.connect();
        }
      });
      return socket;
    }
  };
})();
