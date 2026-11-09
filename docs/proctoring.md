# Optional live screen sharing

On the Classic or Boss Rush setup form, check **Require entire-screen sharing** to use proctoring for that session. The setting defaults to off. From Manage, open **Open proctoring** in a separate tab and keep it open. One admin tab can monitor the session at a time. For a class session, the grid shows roster members who have not shared as well as active shares.

Students click **Share screen and join** in the Hub and select **Entire Screen** in the browser picker. A tab, a window, or a browser that does not report the capture surface will be rejected. The lobby opens once the admin tab receives video. The player shell keeps the share running through round transitions. On a lost share the player remains in the game and can share again. Answer submission and other gameplay actions are blocked while the share is unverified. The admin can turn off proctoring from the monitoring page during a session.

There is no audio capture or video recording. Each student sends a WebRTC video stream directly to the monitoring tab, or through the configured TURN relay. Socket.IO carries signaling and live status. Screen type is reported by the browser. The feature supervises one selected display and does not verify other displays or physical devices.

## Deployment

Apply the Alembic migration before starting the updated application. Existing sessions get the default of false. Keep the game on HTTPS and its current single Socket.IO worker. Monitoring connections and short-lived admission status live in that worker and must be re-established after a restart.

For use across different networks or restrictive school networks, provision an authenticated TURN relay. For coturn with `use-auth-secret`, set `PROCTOR_TURN_URLS` to a JSON array of TURN URLs and keep the relay's shared secret in `PROCTOR_TURN_SECRET` in the private service environment. The game issues per-user credentials that expire after eight hours. For another ICE provider, use `PROCTOR_ICE_SERVERS` with its connection settings.

```json
[{"urls":["turns:relay.example.org:443?transport=tcp"],"username":"deployment-user","credential":"deployment-credential"}]
```

ICE credentials are delivered to authenticated eligible students and the monitoring admin. Use restricted credentials for this relay and rotate them. With no relay configured, peers must have a usable direct route. Test on the actual student MacBooks and school network before requiring screen sharing in class.
