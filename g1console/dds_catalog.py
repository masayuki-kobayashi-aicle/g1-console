"""List of DDS topics / RPC services observed on the G1, and how this console handles them.

The topics are the part left after removing service request/response topics from the 104 discovered
from the Jetson in 2026-09 (BuiltinTopicDcpsPublication). Types are the type names at discovery time.
Status:
  displayed ... subscribed by remote_helper.py and shown on screen
  todo      ... not subscribed (looks obtainable, not implemented)
  excluded  ... out of scope (large point clouds, video, maps, or command topics that are never published)
"""

DISPLAYED, TODO, EXCLUDED = "displayed", "todo", "excluded"

# (topic, type, status, description)
TOPICS = (
    # --- displayed ---
    ("rt/lf/bmsstate", "BmsState_", DISPLAYED, "Battery (SOC, voltage, current, temperature)"),
    ("rt/lowstate", "LowState_", DISPLAYED, "IMU and state of 29 joints (angle, velocity, torque, temperature)"),
    ("rt/odommodestate", "SportModeState_", DISPLAYED, "Odometry (position, velocity, body height, mode)"),
    ("rt/lowcmd", "LowCmd_", DISPLAYED, "Commands to the joints (flows at about 200 Hz even in debug mode. Publisher unidentified)"),
    ("rt/secondary_imu", "IMUState_", DISPLAYED, "Second IMU"),
    ("rt/lf/mainboardstate", "MainBoardState_", DISPLAYED, "Main board state (meaning of the value array unknown)"),
    ("rt/lf/emergency_stop", "Error_", DISPLAYED, "Emergency stop event (event type. Nothing is received in normal operation)"),
    ("rt/wirelesscontroller", "WirelessController_", DISPLAYED, "Wireless remote controller input (only while operated)"),
    ("rt/rtc/state", "String_", DISPLAYED, "RTC state (JSON string)"),
    ("rt/public_network_status", "String_", DISPLAYED, "Network status (JSON string)"),
    ("rt/arm/action/state", "String_", DISPLAYED, "Arm action state"),
    ("rt/gpt_state", "String_", DISPLAYED, "Voice dialogue (GPT) state"),
    ("rt/servicestate", "String_", DISPLAYED, "Service state (nothing received when measured)"),
    ("rt/servicestateactivate", "String_", DISPLAYED, "Service activation state"),
    ("rt/lf/battery_alarm", "String_", DISPLAYED, "Battery alarm (event type. Nothing received when measured)"),
    ("rt/rtc_status", "String_", DISPLAYED, "RTC status (nothing received when measured)"),
    ("rt/multiplestate", "String_", DISPLAYED, "Combined state (nothing received when measured)"),
    ("rt/selftest", "String_", DISPLAYED, "Self-test (nothing received when measured)"),
    # --- not subscribed (looks obtainable. Not implemented) ---
    ("rt/audio_msg", "String_", TODO, "Presumed to be speech recognition (ASR) results or text of audio events. A clue to microphone input. Contents unverified"),
    ("rt/audio_msg/filter", "String_", TODO, "Presumed to be the filtered version of the above. Unverified"),
    ("rt/dex3/left/state", "HandState_", TODO, "Dex3 hand (left) state. Nothing received if no hand is connected"),
    ("rt/dex3/right/state", "HandState_", TODO, "Dex3 hand (right) state"),
    ("rt/lf/dex3/left/state", "HandState_", TODO, "Same (lf family. Presumed to be the low-frequency version)"),
    ("rt/lf/dex3/right/state", "HandState_", TODO, "Same (lf family)"),
    ("rt/lf/lowstate", "LowState_", TODO, "lf family of lowstate (presumed low-frequency version). rt/lowstate is enough for display"),
    ("rt/lf/odommodestate", "SportModeState_", TODO, "lf family of odommodestate"),
    ("rt/lf/secondary_imu", "IMUState_", TODO, "lf family of secondary_imu"),
    ("rt/config_change_status", "ConfigChangeStatus_", TODO, "Configuration change notification"),
    ("rt/slam_info", "String_", TODO, "SLAM state"),
    ("rt/slam_key_info", "String_", TODO, "SLAM key information"),
    ("rt/unitree_slam/waypoints", "String_", TODO, "SLAM waypoints"),
    ("rt/event/action_store", "String_", TODO, "Action store event"),
    ("rt/gpt_cmd", "String_", TODO, "Commands to the voice dialogue"),
    ("rt/gptflowfeedback", "String_", TODO, "Voice dialogue feedback"),
    ("rt/log_system_inbound", "String_", TODO, "Logging (inbound side)"),
    ("rt/log_system_outbound", "String_", TODO, "Logging (outbound side)"),
    ("rt/videohub/inner", "String_", TODO, "Internal notification of the video hub (not the video itself)"),
    ("rt/webrtcreq", "String_", TODO, "WebRTC request (app integration)"),
    ("rt/webrtcres", "String_", TODO, "WebRTC response"),
    ("rt/xfk_webrtcreq", "String_", TODO, "WebRTC request (xfk)"),
    ("rt/xfk_webrtcres", "String_", TODO, "WebRTC response (xfk)"),
    ("rt/SymState", "SymState_", TODO, "Purpose unknown"),
    ("rt/dog_imu_raw", "Imu_", TODO, "Raw IMU data (name derived from the Go family). Purpose unknown"),
    ("rt/dog_odom", "Odometry_", TODO, "Odometry (nav_msgs). Purpose unknown"),
    ("rt/utlidar/imu_livox_mid360", "Imu_", TODO, "IMU built into the LiDAR (not the point cloud. Presumed high frequency)"),
    ("rt/unitree/slam_mapping/odom", "Odometry_", TODO, "Odometry during SLAM mapping"),
    ("rt/unitree/slam_relocation/odom", "Odometry_", TODO, "Odometry during SLAM relocalization"),
    # --- excluded ---
    ("rt/arm_sdk", "LowCmd_", EXCLUDED, "For commands to the arms. Never published (subscribing to view is possible)"),
    ("rt/frontvideostream", "Go2FrontVideoData_", EXCLUDED, "Camera video (not needed, per instruction)"),
    ("rt/utlidar/cloud_livox_mid360", "PointCloud2_", EXCLUDED, "LiDAR point cloud (not needed, per instruction)"),
    ("rt/collision_clouds", "PointCloud2_", EXCLUDED, "Point cloud (collision avoidance)"),
    ("rt/ele_clouds", "PointCloud2_", EXCLUDED, "Point cloud"),
    ("rt/grid_clouds", "PointCloud2_", EXCLUDED, "Point cloud"),
    ("rt/no_warning_clouds", "PointCloud2_", EXCLUDED, "Point cloud"),
    ("rt/pre_collision_clouds", "PointCloud2_", EXCLUDED, "Point cloud"),
    ("rt/pre_safe_clouds", "PointCloud2_", EXCLUDED, "Point cloud"),
    ("rt/safe_clouds", "PointCloud2_", EXCLUDED, "Point cloud"),
    ("rt/warning_clouds", "PointCloud2_", EXCLUDED, "Point cloud"),
    ("rt/global_map", "OccupancyGrid_", EXCLUDED, "Map (large)"),
    ("rt/gridmap", "GridMap_", EXCLUDED, "Map (large)"),
    ("rt/planner_map", "GridMap_", EXCLUDED, "Map (large)"),
    ("rt/unitree/slam_mapping/points", "PointCloud2_", EXCLUDED, "SLAM point cloud"),
    ("rt/unitree/slam_relocation/points", "PointCloud2_", EXCLUDED, "SLAM point cloud"),
    ("rt/unitree/slam_relocation/global_map", "PointCloud2_", EXCLUDED, "SLAM map"),
    ("rt/unitree/slam_relocation/web_points", "PointCloud2_", EXCLUDED, "SLAM point cloud"),
)

# RPC services (rt/api/<name>/request|response). In use / in the SDK but not implemented / no client in the SDK
SERVICES = (
    ("voice", "In use", "Volume, LED, TTS (AudioClient). PlayStream / PlayStop are not implemented"),
    ("motion_switcher", "In use", "CheckMode (display). SelectMode / ReleaseMode / SetSilent are not implemented"),
    ("sport", "In use", "G1 LocoClient (GetFsmId / SetFsmId). Movement and motion calls are not implemented"),
    ("arm", "SDK available, not implemented", "ExecuteAction / GetActionList (arm motions)"),
    ("audiohub", "No SDK", "Audio hub (presumed to manage the microphone and playback)"),
    ("gpt", "No SDK", "Voice dialogue"),
    ("bashrunner", "No SDK", "Presumed remote command execution. Handle with care"),
    ("config", "No SDK", "Configuration"),
    ("robot_state", "No SDK", "Robot state"),
    ("robot_type_service", "No SDK", "Model information"),
    ("slam_operate", "No SDK", "SLAM operation"),
    ("videohub", "No SDK", "Video hub"),
    ("action_store", "No SDK", "Action store"),
    ("dex3_msg_controller", "No SDK", "Dex3 hand control"),
    ("gesture", "No SDK", "Gestures"),
    ("basic_demarcate", "No SDK", "Calibration family. Do not touch"),
    ("basic_demarcate_lease", "No SDK", "Calibration family (lease). Do not touch"),
    ("basic_softlimit", "No SDK", "Presumed joint soft limit settings. Do not touch"),
    ("basic_softlimit_lease", "No SDK", "Same (lease). Do not touch"),
    ("basic_taumax", "No SDK", "Presumed maximum torque settings. Do not touch"),
    ("basic_taumax_lease", "No SDK", "Same (lease). Do not touch"),
    ("basic_clearoip", "No SDK", "Purpose unknown (settings family). Do not touch"),
    ("basic_clearoip_lease", "No SDK", "Same (lease). Do not touch"),
    ("rm_con", "No SDK", "Purpose unknown"),
    ("vui", "No SDK", "Voice UI"),
)
