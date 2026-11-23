# Third-party components

This repository contains **no third-party code**. The hub (`server.py`, `g1console/`) uses only the Python standard library. The components below are used at run time on the Jetson or on a development machine. They are installed by you, not distributed here, and keep their own licenses. Check each license (and its current version) before you use or redistribute them.

| Component | Used by | Role | License (as published by the project) |
|---|---|---|---|
| `unitree_sdk2_python` | `jetson/*_helper.py`, `jetson/*_stream.py` | Talk to the robot over DDS | BSD-3-Clause |
| `cyclonedds` | via `unitree_sdk2_python` | DDS implementation | EPL-2.0 / EDL-1.0 |
| `numpy` | `jetson/lidar_stream.py` (optional) | Point cloud processing | BSD-3-Clause |
| `opencv-python` | `jetson/camera_stream.py` (optional) | Video encoding | Apache-2.0 (OpenCV) |
| `pyrealsense2` | `jetson/camera_stream.py` (optional) | Depth camera access | Apache-2.0 |
| Node.js | `tests/*.cjs` (development only) | UI regression checks | MIT |

## Protocols implemented from public documents

- `g1console/lidar_sensor.py` talks to the LiDAR unit over its published control protocol. It is an independent implementation written for interoperability. No vendor code or SDK is included.

## Artwork

The robot illustration and the icons are inline SVG in `web/index.html`. They were generated with an AI assistant, are not copied from another project or from Unitree, and are offered under this repository's MIT license. No external image files, fonts or icon sets are included.

## Trademarks

"Unitree" and "G1" are trademarks of their respective owners. They are used only to say which robot this works with. This project is not affiliated with or endorsed by Unitree Robotics.
