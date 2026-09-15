from __future__ import annotations
import numpy as np
from typing import Optional, List, Tuple
from ..utils.logger import logger

INPUT_DEVICE_KEYWORDS = ["FYSP003"]
OUTPUT_DEVICE_KEYWORDS = ["UACDemoV10"]


def find_audio_device(device_name: str, device_type: str = "input") -> Optional[int]:
    try:
        import sounddevice as sd
        
        devices = sd.query_devices()
        target_name = device_name.lower().strip()
        
        logger.info(f"Searching for {device_type} device: '{device_name}' (lower: '{target_name}')")
        logger.info(f"Total devices: {len(devices)}")
        
        exact_matches: List[int] = []
        partial_matches: List[int] = []
        keyword_matches: List[Tuple[int, str]] = []
        
        target_keywords = INPUT_DEVICE_KEYWORDS if device_type == "input" else OUTPUT_DEVICE_KEYWORDS
        
        for i, device in enumerate(devices):
            dev_name = device["name"].lower().strip()
            is_input = device["max_input_channels"] > 0
            is_output = device["max_output_channels"] > 0
            
            if device_type == "input" and is_input:
                logger.debug(f"Input device {i}: '{device['name']}'")
                if target_name == dev_name:
                    exact_matches.append(i)
                elif target_name in dev_name:
                    partial_matches.append(i)
                    logger.debug(f"  -> Partial match: '{target_name}' in device name")
                elif dev_name in target_name:
                    partial_matches.append(i)
                    logger.debug(f"  -> Partial match: device name in '{target_name}'")
                
                for keyword in target_keywords:
                    if keyword.lower() in dev_name:
                        keyword_matches.append((i, keyword))
                        logger.debug(f"  -> Keyword match: '{keyword}' found in device name")
                        break
            elif device_type == "output" and is_output:
                logger.debug(f"Output device {i}: '{device['name']}'")
                if target_name == dev_name:
                    exact_matches.append(i)
                elif target_name in dev_name:
                    partial_matches.append(i)
                    logger.debug(f"  -> Partial match: '{target_name}' in device name")
                elif dev_name in target_name:
                    partial_matches.append(i)
                    logger.debug(f"  -> Partial match: device name in '{target_name}'")
                
                for keyword in target_keywords:
                    if keyword.lower() in dev_name:
                        keyword_matches.append((i, keyword))
                        logger.debug(f"  -> Keyword match: '{keyword}' found in device name")
                        break
        
        logger.info(f"Exact matches: {exact_matches}, Partial matches: {partial_matches}, Keyword matches: {[(idx, kw) for idx, kw in keyword_matches]}")
        
        if exact_matches:
            result = exact_matches[0]
            logger.info(f"Found exact match at index {result}: {devices[result]['name']}")
            return result
        
        if keyword_matches:
            result, matched_keyword = keyword_matches[0]
            logger.info(f"Found keyword match '{matched_keyword}' at index {result}: {devices[result]['name']}")
            return result
        
        if partial_matches:
            result = partial_matches[0]
            logger.info(f"Found partial match at index {result}: {devices[result]['name']}")
            return result
        
        fallback_result = None
        for i, device in enumerate(devices):
            dev_name = device["name"].lower()
            
            if device_type == "input" and device["max_input_channels"] > 0:
                if any(keyword in dev_name for keyword in ["mic", "microphone", "input", "audio"]):
                    fallback_result = i
                    break
            elif device_type == "output" and device["max_output_channels"] > 0:
                if any(keyword in dev_name for keyword in ["output", "speaker", "headphone", "hdmi", "spdif"]):
                    fallback_result = i
                    break
        
        if fallback_result is not None:
            logger.warning(f"No match for '{device_name}', using fallback: device {fallback_result} - {devices[fallback_result]['name']}")
            return fallback_result
        
        default_device = sd.default.device[device_type]
        logger.warning(f"No match for '{device_name}', using system default: device {default_device} - {devices[default_device]['name']}")
        return default_device
    
    except ImportError:
        logger.warning(f"sounddevice not available, cannot find {device_type} device '{device_name}'")
        return None


def find_input_device_by_keyword(keyword: str = None) -> Optional[int]:
    try:
        import sounddevice as sd
        
        devices = sd.query_devices()
        target_keyword = keyword.lower().strip() if keyword else INPUT_DEVICE_KEYWORDS[0]
        
        logger.info(f"Searching for input device with keyword: '{target_keyword}'")
        
        for i, device in enumerate(devices):
            if device["max_input_channels"] > 0:
                dev_name = device["name"].lower()
                if target_keyword in dev_name:
                    logger.info(f"Found input device '{device['name']}' at index {i}")
                    return i
        
        return find_audio_device(target_keyword, "input")
    
    except ImportError:
        logger.warning("sounddevice not available, cannot find input device")
        return None


def find_output_device_by_keyword(keyword: str = None) -> Optional[int]:
    try:
        import sounddevice as sd
        
        devices = sd.query_devices()
        target_keyword = keyword.lower().strip() if keyword else OUTPUT_DEVICE_KEYWORDS[0]
        
        logger.info(f"Searching for output device with keyword: '{target_keyword}'")
        
        for i, device in enumerate(devices):
            if device["max_output_channels"] > 0:
                dev_name = device["name"].lower()
                if target_keyword in dev_name:
                    logger.info(f"Found output device '{device['name']}' at index {i}")
                    return i
        
        return find_audio_device(target_keyword, "output")
    
    except ImportError:
        logger.warning("sounddevice not available, cannot find output device")
        return None


def list_audio_devices() -> str:
    try:
        import sounddevice as sd
        
        devices = sd.query_devices()
        result = "可用音频设备:\n"
        result += "=" * 60 + "\n"
        
        for i, device in enumerate(devices):
            is_input = device["max_input_channels"] > 0
            is_output = device["max_output_channels"] > 0
            is_default_input = i == sd.default.device["input"]
            is_default_output = i == sd.default.device["output"]
            
            result += f"\n设备 {i}:\n"
            result += f"  名称: {device['name']}\n"
            if is_input:
                result += f"  输入通道: {device['max_input_channels']}\n"
            if is_output:
                result += f"  输出通道: {device['max_output_channels']}\n"
            result += f"  默认采样率: {int(device['default_samplerate'])}Hz\n"
            
            dev_name_lower = device["name"].lower()
            if is_input:
                for keyword in INPUT_DEVICE_KEYWORDS:
                    if keyword.lower() in dev_name_lower:
                        result += f"  🔍 匹配输入设备关键词: {keyword}\n"
            if is_output:
                for keyword in OUTPUT_DEVICE_KEYWORDS:
                    if keyword.lower() in dev_name_lower:
                        result += f"  🔍 匹配输出设备关键词: {keyword}\n"
            
            if is_default_input:
                result += "  ⭐ 默认输入\n"
            if is_default_output:
                result += "  ⭐ 默认输出\n"
        
        return result
    
    except ImportError:
        return "sounddevice 未安装，无法列出设备"


def test_microphone(device_index: int = None, duration: int = 3) -> dict:
    try:
        import sounddevice as sd
        
        print(f"测试麦克风设备 {device_index}...")
        recording = sd.rec(int(duration * 16000), samplerate=16000, channels=1, device=device_index)
        sd.wait()
        
        energy = np.sqrt(np.mean(recording ** 2))
        max_val = np.max(np.abs(recording))
        min_val = np.min(np.abs(recording))
        std_val = np.std(recording)
        
        return {
            "success": True,
            "energy": float(energy),
            "max_value": float(max_val),
            "min_value": float(min_val),
            "std": float(std_val),
            "has_signal": energy > 0.001,
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def test_speaker(device_index: int = None) -> dict:
    try:
        import sounddevice as sd
        
        print(f"测试扬声器设备 {device_index}...")
        t = np.linspace(0, 1, 16000, dtype=np.float32)
        test_audio = 0.3 * np.sin(2 * np.pi * 440 * t)
        sd.play(test_audio, 16000, device=device_index)
        sd.wait()
        
        return {"success": True}
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }