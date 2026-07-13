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
