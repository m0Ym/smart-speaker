from pydantic import BaseModel, Field
from typing import Dict, Any, Optional


class AudioConfig(BaseModel):
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024
    wake_word: str = "你好小智"
    vad_mode: int = 1
    silence_threshold: float = 0.01
    min_silence_duration: float = 1.5
    input_device: Optional[int] = None
    output_device: Optional[int] = None
    input_device_name: Optional[str] = None
    output_device_name: Optional[str] = None
    porcupine_access_key: Optional[str] = None
    porcupine_model_path: Optional[str] = None
    aec_enabled: bool = True
    barge_in_enabled: bool = True
    barge_in_threshold: float = 0.5
    tts_engine: str = "auto"
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_voice_gender: str = "female"
    tts_rate: str = "+0%"
    tts_volume: str = "+0%"
    sherpa_onnx_model: Optional[str] = None
    asr_engine: str = "sherpa_onnx"
    sherpa_asr_model: str = ""
    sherpa_asr_type: str = "paraformer"
    faster_whisper_model: str = "base"
    asr_auto_download: bool = False

    vad_energy_threshold: float = 0.02
    vad_energy_multiplier: float = 2.0
    vad_min_speech_frames: int = 3
    vad_min_silence_frames: int = 15
    vad_zcr_threshold: float = 0.05
    vad_hysteresis_ratio: float = 0.5

    preprocessor_enabled: bool = True
    gate_enabled: bool = True
    stream_enabled: bool = False
    min_speech_duration: float = 0.5
    max_speech_duration: float = 30.0

    enable_filter: bool = True
    filter_low_cut: float = 300.0
    filter_high_cut: float = 8000.0
    enable_noise_suppression: bool = True
    noise_history_size: int = 20
    noise_decay_factor: float = 0.95
    noise_calibration_frames: int = 50
    noise_threshold_multiplier: float = 3.0
    min_speech_duration_ms: int = 200
    energy_gate_threshold: float = 0.002

    gate_mode: str = "controlled"
    gate_resume_delay_ms: int = 300
    gate_enable_aec: bool = False


class VisionConfig(BaseModel):
    enabled: bool = False
    camera_index: int = 0
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 30
    stereo_baseline: float = 0.06
    focal_length: float = 500.0
    min_detection_distance: float = 0.3
    max_detection_distance: float = 5.0
    gesture_enabled: bool = True


class NLPConfig(BaseModel):
    class Config:
        protected_namespaces = ()
    model_path: str = "models/LLM/qwen2.5-1.5b-instruct-q4_k_m.gguf"
    max_context_length: int = 2048
    max_response_length: int = 512
    llm_max_tokens: int = 150
    temperature: float = 0.7
    top_p: float = 0.9
    language: str = "zh-CN"
    offline_mode: bool = True
    model_type: str = "llama"
    n_gpu_layers: int = 30
    num_threads: int = 4
    function_calling_enabled: bool = True
    lora_adapter_path: Optional[str] = None


class UIConfig(BaseModel):
    main_screen_width: int = 1280
    main_screen_height: int = 800
    eink_screen_width: int = 296
    eink_screen_height: int = 128
    theme: str = "dark"
    animation_enabled: bool = True
    eink_enabled: bool = True
    eink_spi_bus: int = 0
    eink_spi_device: int = 0


class SystemConfig(BaseModel):
    class Config:
        protected_namespaces = ()
    device_name: str = "SmartSpeaker-Pro"
    device_id: str = "RC-AISH-II-001"
    log_level: str = "INFO"
    data_dir: str = "./data"
    model_dir: str = "./models"
    music_dir: str = "./data/music"
    enable_data_collection: bool = True
    ota_enabled: bool = True
    shadow_mode_enabled: bool = True
    shadow_cases_path: str = "data/logs/shadow_cases.json"
    max_shadow_cases: int = 1000
    repeat_wake_threshold: float = 0.5
    environment: str = "auto"


class AppConfig(BaseModel):
    audio: AudioConfig = Field(default_factory=AudioConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    nlp: NLPConfig = Field(default_factory=NLPConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    system: SystemConfig = Field(default_factory=SystemConfig)

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "AppConfig":
        import os

        config = cls()

        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

        try:
            from dotenv import load_dotenv
            if config_path and os.path.exists(config_path):
                load_dotenv(config_path)
            else:
                env_path = os.path.join(project_root, ".env")
                if os.path.exists(env_path):
                    load_dotenv(env_path)
                else:
                    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
                    if os.path.exists(env_path):
                        load_dotenv(env_path)
                    else:
                        env_path = ".env"
                        if os.path.exists(env_path):
                            load_dotenv(env_path)
        except ImportError:
            pass

        audio = config.audio
        audio.sample_rate = int(os.getenv("AUDIO_SAMPLE_RATE", audio.sample_rate))
        audio.wake_word = os.getenv("WAKE_WORD", audio.wake_word)
        audio.input_device_name = os.getenv("INPUT_DEVICE_NAME", audio.input_device_name)
        audio.output_device_name = os.getenv("OUTPUT_DEVICE_NAME", audio.output_device_name)
        audio.porcupine_access_key = os.getenv("PORCUPINE_ACCESS_KEY", audio.porcupine_access_key)
        audio.porcupine_model_path = os.getenv("PORCUPINE_MODEL_PATH", audio.porcupine_model_path)
        audio.aec_enabled = os.getenv("AEC_ENABLED", str(audio.aec_enabled)).lower() == "true"
        audio.barge_in_enabled = os.getenv("BARGE_IN_ENABLED", str(audio.barge_in_enabled)).lower() == "true"
        audio.tts_engine = os.getenv("TTS_ENGINE", audio.tts_engine)
        audio.tts_voice = os.getenv("TTS_VOICE", audio.tts_voice)
        audio.tts_voice_gender = os.getenv("TTS_VOICE_GENDER", audio.tts_voice_gender)
        audio.tts_rate = os.getenv("TTS_RATE", audio.tts_rate)
        audio.tts_volume = os.getenv("TTS_VOLUME", audio.tts_volume)
        audio.sherpa_onnx_model = os.getenv("SHERPA_ONNX_MODEL", audio.sherpa_onnx_model)
        if audio.sherpa_onnx_model and not os.path.isabs(audio.sherpa_onnx_model):
            audio.sherpa_onnx_model = os.path.normpath(os.path.join(project_root, audio.sherpa_onnx_model))
        audio.asr_engine = os.getenv("ASR_ENGINE", audio.asr_engine)
        audio.sherpa_asr_model = os.getenv("SHERPA_ASR_MODEL", audio.sherpa_asr_model)
        if audio.sherpa_asr_model and not os.path.isabs(audio.sherpa_asr_model):
            audio.sherpa_asr_model = os.path.normpath(os.path.join(project_root, audio.sherpa_asr_model))
        audio.sherpa_asr_type = os.getenv("SHERPA_ASR_TYPE", audio.sherpa_asr_type)
        audio.faster_whisper_model = os.getenv("FASTER_WHISPER_MODEL", audio.faster_whisper_model)
        audio.asr_auto_download = os.getenv("ASR_AUTO_DOWNLOAD", str(audio.asr_auto_download)).lower() == "true"

        audio.vad_mode = int(os.getenv("VAD_MODE", audio.vad_mode))
        audio.vad_energy_threshold = float(os.getenv("VAD_ENERGY_THRESHOLD", audio.vad_energy_threshold))
        audio.vad_energy_multiplier = float(os.getenv("VAD_ENERGY_MULTIPLIER", audio.vad_energy_multiplier))
        audio.vad_min_speech_frames = int(os.getenv("VAD_MIN_SPEECH_FRAMES", audio.vad_min_speech_frames))
        audio.vad_min_silence_frames = int(os.getenv("VAD_MIN_SILENCE_FRAMES", audio.vad_min_silence_frames))
        audio.vad_zcr_threshold = float(os.getenv("VAD_ZCR_THRESHOLD", audio.vad_zcr_threshold))
        audio.vad_hysteresis_ratio = float(os.getenv("VAD_HYSTERESIS_RATIO", audio.vad_hysteresis_ratio))

        audio.preprocessor_enabled = os.getenv("PREPROCESSOR_ENABLED", str(audio.preprocessor_enabled)).lower() == "true"
        audio.gate_enabled = os.getenv("GATE_ENABLED", str(audio.gate_enabled)).lower() == "true"
        audio.stream_enabled = os.getenv("STREAM_ENABLED", str(audio.stream_enabled)).lower() == "true"
        audio.min_speech_duration = float(os.getenv("MIN_SPEECH_DURATION", audio.min_speech_duration))
        audio.max_speech_duration = float(os.getenv("MAX_SPEECH_DURATION", audio.max_speech_duration))

        audio.enable_filter = os.getenv("ENABLE_FILTER", str(audio.enable_filter)).lower() == "true"
        audio.filter_low_cut = float(os.getenv("FILTER_LOW_CUT", audio.filter_low_cut))
        audio.filter_high_cut = float(os.getenv("FILTER_HIGH_CUT", audio.filter_high_cut))
        audio.enable_noise_suppression = os.getenv("ENABLE_NOISE_SUPPRESSION", str(audio.enable_noise_suppression)).lower() == "true"

        audio.gate_mode = os.getenv("GATE_MODE", audio.gate_mode)
        audio.gate_resume_delay_ms = int(os.getenv("GATE_RESUME_DELAY_MS", audio.gate_resume_delay_ms))
        audio.gate_enable_aec = os.getenv("GATE_ENABLE_AEC", str(audio.gate_enable_aec)).lower() == "true"

        input_dev = os.getenv("INPUT_DEVICE")
        if input_dev is not None and input_dev.strip():
            audio.input_device = int(input_dev)
        output_dev = os.getenv("OUTPUT_DEVICE")
        if output_dev is not None and output_dev.strip():
            audio.output_device = int(output_dev)

        vision = config.vision
        vision.enabled = os.getenv("VISION_ENABLED", str(vision.enabled)).lower() == "true"
        vision.camera_index = int(os.getenv("CAMERA_INDEX", vision.camera_index))
        vision.camera_width = int(os.getenv("CAMERA_WIDTH", vision.camera_width))
        vision.camera_height = int(os.getenv("CAMERA_HEIGHT", vision.camera_height))

        nlp = config.nlp
        nlp.model_path = os.getenv("NLP_MODEL_PATH", nlp.model_path)
        if nlp.model_path and not os.path.isabs(nlp.model_path):
            nlp.model_path = os.path.normpath(os.path.join(project_root, nlp.model_path))
        nlp.offline_mode = os.getenv("OFFLINE_MODE", str(nlp.offline_mode)).lower() == "true"
        nlp.model_type = os.getenv("NLP_MODEL_TYPE", nlp.model_type)
        nlp.n_gpu_layers = int(os.getenv("NLP_N_GPU_LAYERS", nlp.n_gpu_layers))
        nlp.function_calling_enabled = os.getenv("FUNCTION_CALLING_ENABLED", str(nlp.function_calling_enabled)).lower() == "true"
        nlp.lora_adapter_path = os.getenv("LORA_ADAPTER_PATH", nlp.lora_adapter_path)
        if nlp.lora_adapter_path and not os.path.isabs(nlp.lora_adapter_path):
            nlp.lora_adapter_path = os.path.normpath(os.path.join(project_root, nlp.lora_adapter_path))
        nlp.llm_max_tokens = int(os.getenv("LLM_MAX_TOKENS", nlp.llm_max_tokens))

        ui = config.ui
        ui.eink_enabled = os.getenv("EINK_ENABLED", str(ui.eink_enabled)).lower() == "true"

        system = config.system
        system.log_level = os.getenv("LOG_LEVEL", system.log_level)
        system.device_name = os.getenv("DEVICE_NAME", system.device_name)
        system.shadow_mode_enabled = os.getenv("SHADOW_MODE_ENABLED", str(system.shadow_mode_enabled)).lower() == "true"
        system.enable_data_collection = os.getenv("ENABLE_DATA_COLLECTION", str(system.enable_data_collection)).lower() == "true"
        system.environment = os.getenv("ENVIRONMENT", system.environment).lower()

        system.data_dir = os.getenv("DATA_DIR", system.data_dir)
        if system.data_dir and not os.path.isabs(system.data_dir):
            system.data_dir = os.path.normpath(os.path.join(project_root, system.data_dir))

        system.model_dir = os.getenv("MODEL_DIR", system.model_dir)
        if system.model_dir and not os.path.isabs(system.model_dir):
            system.model_dir = os.path.normpath(os.path.join(project_root, system.model_dir))

        system.music_dir = os.getenv("MUSIC_DIR", system.music_dir)
        if system.music_dir and not os.path.isabs(system.music_dir):
            system.music_dir = os.path.normpath(os.path.join(project_root, system.music_dir))

        system.shadow_cases_path = os.getenv("SHADOW_CASES_PATH", system.shadow_cases_path)
        if system.shadow_cases_path and not os.path.isabs(system.shadow_cases_path):
            system.shadow_cases_path = os.path.normpath(os.path.join(project_root, system.shadow_cases_path))

        return config