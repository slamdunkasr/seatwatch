# Seat watch

Checks CSUF's public class search every ~2 minutes and sends a phone alert (ntfy) when a watched
section changes to **Open** or **Wait List**. Edit `watch.yaml` to change which classes are watched.

- Status only (Open / Closed / Wait List), not exact seat counts. You still enroll yourself in Titan Online.
- Needs one repo secret: `NTFY_TOPIC`.
- To stop it: Actions tab → seatwatch → "..." → Disable workflow.
