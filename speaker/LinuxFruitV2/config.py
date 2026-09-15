import os

SCREEN_WIDTH = int(os.environ.get('SCREEN_WIDTH', 960))
SCREEN_HEIGHT = int(os.environ.get('SCREEN_HEIGHT', 540))

# 全局缩放因子：基于基准分辨率 960×540
# 所有游戏元素尺寸按此比例自动缩放
SCALE = SCREEN_HEIGHT / 540.0

CAMERA_DEVICE = "/dev/video0"

# 双目摄像头输出 2560×720 (左右各 1280×720 拼接)
# 驱动固定此分辨率，OpenCV set() 不生效
# 实际使用单目裁剪后的分辨率
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FPS = 30

# 选择使用左镜头还是右镜头
# "left"  = 使用物理左镜头 (原始图像左侧 1280×720)
# "right" = 使用物理右镜头 (原始图像右侧 1280×720)
CAMERA_SIDE = os.environ.get("CAMERA_SIDE", "left")

MEDIAPIPE_MODEL_COMPLEXITY = 0
MEDIAPIPE_MAX_HANDS = 2

POSE_MIN_DETECTION_CONFIDENCE = 0.5
POSE_MIN_TRACKING_CONFIDENCE = 0.5

GAME_FPS = 60

USE_GPU = True

GRAVITY = 800
PARTICLE_GRAVITY = 300

SPAWN_INTERVAL = 1.0
FRUITS_PER_SPAWN = 3

BOMB_SPAWN_CHANCE = 0.15
INITIAL_LIVES = 3

SLASH_MODE_FRUIT_MULTIPLIER = 3
SUPER_FRUIT_SPAWN_INTERVAL = 30.0
SUPER_FRUIT_SIZE_MULTIPLIER = 3.0
SUPER_FRUIT_SLOW_FACTOR = 5.0
SUPER_FRUIT_POINTS_PER_HIT = 1

COMBO_THRESHOLD = 3
BASE_SCORE = 10

SOUND_VOLUME = 0.5

SCORE_SAVE_PATH = "scores.json"

FRUIT_COLORS = {
    "watermelon": {"main": (255, 107, 138), "juice": (255, 51, 85)},
    "orange": {"main": (255, 179, 71), "juice": (255, 140, 0)},
    "lemon": {"main": (255, 242, 117), "juice": (238, 208, 0)},
    "lime": {"main": (184, 255, 107), "juice": (136, 221, 34)},
    "berry": {"main": (126, 184, 255), "juice": (68, 102, 204)},
}

FRUIT_TEXTURE_MAP = {
    "watermelon": {"full": "sandia.png", "slice1": "sandia-1.png", "slice2": "sandia-2.png"},
    "orange": {"full": "basaha.png", "slice1": "basaha-1.png", "slice2": "basaha-2.png"},
    "lemon": {"full": "banana.png", "slice1": "banana-1.png", "slice2": "banana-2.png"},
    "lime": {"full": "peach.png", "slice1": "peach-1.png", "slice2": "peach-2.png"},
    "berry": {"full": "apple.png", "slice1": "apple-1.png", "slice2": "apple-2.png"},
}