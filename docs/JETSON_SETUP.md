# Deploying to the Jetson and running

Last updated: 2026-10-18 (camera and LiDAR start/stop with `--local`). **The whole procedure has not yet been run end to end on a real Jetson** (see the checks in each step). The items to verify on a real robot are the J rows of [REAL_ROBOT_CHECKLIST.md](REAL_ROBOT_CHECKLIST.md).

## 0. Prerequisites (check on the Jetson first)
| What | Check command | Notes |
|---|---|---|
| Python 3.8 or later | `python3 --version` | The hub uses only the standard library. No pip needed |
| Unitree SDK | `ls ~/unitree_sdk2_python` | If it is elsewhere, point to it with `UNITREE_SDK_DIR` |
| Joined to the same Wi-Fi | `ip -4 -o addr show dev wlan0` | Only needed to open the console from a phone. The hub does not listen on eth0 (the robot's internal LAN) |

The helper processes in `jetson/` import `unitree_sdk2py` and `cyclonedds`. The camera and LiDAR streamers optionally use `numpy`, `opencv-python` and `pyrealsense2`. None of these are included in this repository; install them yourself.

## 1. What to copy to the Jetson
**The whole repository.** From your own PC:

```bash
rsync -av --exclude '__pycache__' --exclude 'tests/' --exclude 'docs/' \
  ./ <user>@<jetson-ip>:~/g1-console/
```

- The expected location is `~/g1-console` (the same as `WorkingDirectory` in `jetson/g1-console.service`). If you use another location, edit the service file too.
- Required: `server.py`, `g1console/`, `web/`, `jetson/`, `tasks/`.
- `tests/` is needed only if you use the task `run-tests`. `docs/` is not needed to run.

### 1.1 Camera and LiDAR (no extra placement needed)
With `--local`, the hub calls `camera_ctl.sh` and `lidar_ctl.sh` in `jetson/` directly. Copying them to `~/g1_console_*` is not needed. (Only the ssh mode uses `~/g1_console_camera` and similar on the Jetson, as before.)

- **Off by default.** Starting the hub does not start a streamer. A streaming port is used only after you press "Start" for the camera or LiDAR in the console and pass the caution dialog ("Stop" frees it).
- A streamer listens on **`127.0.0.1` only** (passed as `CAMERA_BIND` / `LIDAR_BIND`). A phone views the stream through the hub (`/camera`, `/lidar`), so the streaming ports (default 8081 / 8082) are not exposed on wlan0 or eth0. A port clash with other projects on the same Jetson can only happen while a streamer is running. The ports can be changed in the settings screen.
- The pid files and logs are in `~/.g1console/run/` (`camera_stream.log`, `lidar_stream.log`). Nothing is created inside the repository.
- Stopping the hub does not stop a streamer (intended; use "Stop" in the console). Restarting a resident hub also leaves an already running streamer as it is.

## 2. Start command
On the Jetson:

```bash
cd ~/g1-console
python3 server.py --local --bind-iface wlan0
```

- `--local` means no ssh: the helpers, camera, LiDAR and tasks run on this Jetson.
- `--bind-iface wlan0` also listens on the IPv4 address of wlan0 (it always listens on 127.0.0.1 too). Because it listens on a non-loopback address, **token authentication is mandatory**.
- Only on a closed, trusted network, adding `--no-auth` stops the token from being required (a phone just opens the URL). Anyone on the same network can then operate the robot. The default is with authentication.
- The startup log prints a login URL of the form `http://<IP>:18790/login?token=...`. The token is in `~/.g1console/token` (generated on first start).
- If you only need the browser on the Jetson itself, use `python3 server.py --local` (`http://127.0.0.1:18790`, no authentication).
- If the SDK is elsewhere: `UNITREE_SDK_DIR=/path/to/unitree_sdk2_python python3 server.py --local ...`.

Options (only when needed):
| Option | Purpose |
|---|---|
| `--topics-file <path>` | Allowlist for publishing from the DDS screen (default is empty, so nothing can be published) |
| `--port <n>` | Default 18790 |

## 3. Opening it from a phone or another PC
1. On a phone on the same Wi-Fi, open `http://<wlan0 IP of the Jetson>:18790/` (no token is needed with `--no-auth`). If you started with authentication, open the login URL from the startup log once (a cookie is set and the token is no longer needed after that).
2. Warning: this is plain HTTP. Without authentication (`--no-auth`), anyone on the same network can **switch modes (damping, zero torque and so on)** from the screen. With authentication, anyone who knows the token can do the same. The physical remote controller is the last line of defense.
3. The eth0 address is not reachable (intended).

## 4. Making it resident (2026-10-18 decision: **only the hub starts automatically**; a person installs it with sudo)
First, starting and stopping by hand (before installation, or when you want to stop it temporarily):
```bash
# Start (on the Jetson; no authentication, also listening on wlan0)
cd ~/g1-console && setsid nohup env UNITREE_SDK_DIR=$HOME/unitree_sdk2_python \
  python3 -u server.py --local --port 18790 --bind-iface wlan0 --no-auth > ~/.g1console/hub.log 2>&1 < /dev/null &
# Stop
pkill -f "server.py --local --por[t] 18790"
```
Installing the automatic start (the template is `jetson/g1-console.service`; it has no `--no-auth`, so add it at installation if you want no authentication). If a hub started by hand is still running the port will clash, so run "Stop" above first.
```bash
sudo cp ~/g1-console/jetson/g1-console.service /etc/systemd/system/
sudo sed -i 's|--bind-iface wlan0$|--bind-iface wlan0 --no-auth|' /etc/systemd/system/g1-console.service   # only if you want no authentication
grep ExecStart /etc/systemd/system/g1-console.service
sudo systemctl daemon-reload
sudo systemctl enable --now g1-console
journalctl -u g1-console -n 20      # check the startup log
```
To stop it from the screen: "Stop the hub" in the settings screen (it does not restart even under systemd; to bring it back, `sudo systemctl start g1-console`).
To stop it temporarily: `sudo systemctl stop g1-console` (it comes back at the next boot). To turn off the automatic start: `sudo systemctl disable --now g1-console`.
Adjust `User`, `WorkingDirectory` and `UNITREE_SDK_DIR` to your environment before installing. Only the hub is resident; the camera, LiDAR and tasks are started and stopped with buttons in the console (no automatic restart).

## 5. Checks before use
A button for an unverified function opens a caution dialog when pressed.
(No robot needed; this also works on the Jetson.)
```bash
cd ~/g1-console
python3 server.py --mock          # screens only, simulated state
bash tests/run_tests.sh           # if you copied tests/; does not touch the robot
```

## 6. Unverified (nothing is filled in by guesswork)
- That `--local` starts on the Jetson (Python 3.8), and that `--bind-iface wlan0` obtains the IP (J1, J2).
- Camera and LiDAR start/stop on the Jetson was checked once on 2026-10-18 (one run, J23: loopback-only listening and port release as expected). Still unverified: the phone layout, whether a streamer remains after the hub restarts, the `std` camera, and any other Jetson or firmware.
- The `rsync` command above has not been run as written (the ssh target and user name are examples).
