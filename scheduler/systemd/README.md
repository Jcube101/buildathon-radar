# Systemd scheduling

Buildathon Radar runs on jobpi (Raspberry Pi 5, Debian 13) as a `systemctl --user`
service and timer. No sudo is used; user lingering is already enabled for jcube,
so the timer fires even with no active login session.

## Install

```
cp scheduler/systemd/buildathon-radar.service ~/.config/systemd/user/
cp scheduler/systemd/buildathon-radar.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now buildathon-radar.timer
```

## Verify

```
systemctl --user list-timers
```

Should show `buildathon-radar.timer` with NEXT set to the coming Sunday 17:00
(system local time, which is Asia/Kolkata on this machine, so this is 5:00 PM IST).

## Logs

```
journalctl --user -u buildathon-radar.service
```

## Notes

- `Type=oneshot`: the service runs the pipeline once and exits; the timer decides when.
- `Persistent=true`: if the Pi was off at the scheduled time, the run fires at next boot.
- `ExecStart` uses the absolute path to the venv Python, since a scheduled unit
  does not inherit an activated venv.
- `WantedBy=default.target` (a user target), not `multi-user.target`.

## Tracker service (buildathon-tracker.service)

The v2 tracker (Track/Applied click endpoints) runs as a second, independent
`systemctl --user` unit, `buildathon-tracker.service`. Unlike the digest, this
is a long-running `Type=simple` FastAPI app (uvicorn) on `127.0.0.1:8015`,
exposed publicly through the existing Cloudflare Tunnel as
`https://radar.job-joseph.com`. It shares no process with the digest timer;
the two only share the `tracker.db` SQLite file at the repo root (WAL mode,
so both can write safely).

### Install

```
cp scheduler/systemd/buildathon-tracker.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now buildathon-tracker.service
```

### Verify

```
systemctl --user status buildathon-tracker.service
curl -s http://127.0.0.1:8015/
```

The health page confirms the service is up. It carries no event data.

### Logs

```
journalctl --user -u buildathon-tracker.service
```

### Notes

- `Type=simple`: a long-running process, not a one-shot job; no timer pairs
  with this unit.
- `Restart=on-failure`, `RestartSec=5`: the service is expected to run
  continuously; if it crashes, systemd restarts it after a short delay.
- Requires `TRACKER_SECRET` in `.env` (repo root, same file the digest reads).
  The service fails fast at startup if it is missing.
- This unit is independent of `buildathon-radar.timer`/`.service`; installing,
  starting, or restarting it never touches the digest schedule.
