#!/usr/bin/env bash
# Console tests. No real robot or ssh is needed.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m unittest -v test_console test_camera_proc test_lidar test_lidar_sensor test_local test_auth test_web test_motion test_tasks test_topics test_caution test_ctl_local test_hub_stop test_control test_mobile
