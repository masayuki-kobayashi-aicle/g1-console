# Contributing

Thanks for your interest in g1-console. This project can move a real robot, so
the rules below are stricter than usual about safety and about what has actually
been tested.

## Ground rules

- **Safety first.** Do not add code that sends motion, mode or actuator commands
  without a guard: operator lock, server-side clamping, a liveness check and the
  caution dialog. Anything that can move the robot needs a review by a maintainer
  and a description of how it was tested.
- **Say what you tested.** In a pull request, state whether you tested with
  `--mock` only or on a real robot (robot model, firmware, how it was mounted:
  hanging, seated, standing). Untested hardware behavior must be marked
  "unverified" in the UI (`g1console/modes.py`, `FEATURES`) and in the docs.
- **No hardware dumps.** Do not commit robot logs, serial numbers, MAC or IP
  addresses of your network, tokens, or photos of your environment.
- **English only** for code comments, UI text, error messages and docs.
- **Standard library only** for the hub (`server.py`, `g1console/`). The Jetson
  helpers may import `unitree_sdk2py`, `numpy`, `cv2` and `pyrealsense2` at run
  time, but never vendor them into this repository.

## Setup

Python 3.8 or newer. No packages are needed for the hub or the tests.

```bash
git clone <this repository>
cd g1-console
python3 server.py --mock          # open http://127.0.0.1:18790/
bash tests/run_tests.sh           # needs no robot
```

Some tests need `node` (web UI checks) or `numpy` (lidar); they are skipped when
those are missing.

## Changing the API

`docs/API.md` and `docs/openapi.yaml` are generated from `g1console/api_spec.py`.
Edit that file, then run:

```bash
python3 g1console/api_spec.py
```

A test fails if the generated files are out of date.

## Pull requests

1. Open an issue first for anything larger than a small fix.
2. Keep the change focused. Add or update tests.
3. Run `bash tests/run_tests.sh` and make sure it passes.
4. Commit messages follow `<type>: <description>` (`feat`, `fix`, `refactor`,
   `docs`, `test`, `chore`, `perf`, `ci`).
5. By contributing you agree that your contribution is licensed under the MIT
   License of this project.

## Reporting security problems

Do not open a public issue. See [SECURITY.md](SECURITY.md).
