from __future__ import annotations
import time
import threading
import re
import json
from typing import Generator, Optional, List, Dict, Any
from dataclasses import dataclass, field
from ..utils.logger import logger

from ..core.message_bus import MessageBus, Event, EventType
from ..core.observer import Subject, Observer
from ..config import NLPConfig


@dataclass
class ChatMessage:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class IntentResult:
    intent: str
    confidence: float
    entities: Dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""


@dataclass
class FunctionCall:
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


class SemanticChunker:
    def __init__(self, punctuation: str = "。！？.!?", min_chunk: int = 10, max_chunk: int = 100):
        self._buffer = ""
        self._punctuation = punctuation
        self._min_chunk_size = min_chunk
        self._max_chunk_size = max_chunk
        self._lock = threading.RLock()

    def push(self, token: str) -> Optional[str]:
        with self._lock:
            self._buffer += token
            return self._check_and_split()

    def flush(self) -> Optional[str]:
        with self._lock:
            chunk = self._buffer.strip()
            self._buffer = ""
            return chunk if chunk else None

    def _check_and_split(self) -> Optional[str]:
        # 检查是否有结束标点
        for p in self._punctuation:
            if p in self._buffer:
                idx = self._buffer.rfind(p)
                # 只要有标点就分块，不限制最小长度
                chunk = self._buffer[:idx + 1]
                self._buffer = self._buffer[idx + 1:]
                return chunk.strip()

        # 超过最大长度强制分块
        if len(self._buffer) >= self._max_chunk_size:
            chunk = self._buffer[:self._max_chunk_size]
            self._buffer = self._buffer[self._max_chunk_size:]
            return chunk.strip()

        return None

    @property
    def buffer_size(self) -> int:
        with self._lock:
            return len(self._buffer)


class NLPProcessor(Subject, Observer):
    def __init__(self, config: NLPConfig, bus: MessageBus) -> None:
        super().__init__()
        self._config = config
        self._bus = bus
        self._running = False
        self._context: List[ChatMessage] = []
        self._model = None
        self._tokenizer = None
        self._model_loaded = False
        self._model_tried = False
        self._model_load_failed = False  # 标记模型加载失败，避免反复重试
        self._function_descriptions: List[Dict[str, Any]] = []
        self._tool_executor = None
        self._context_lock = threading.RLock()
        self._model_lock = threading.Lock()
        self._is_streaming = False
        self._stream_lock = threading.Lock()
        self._stream_buffer = None
        self._chunker = SemanticChunker()

        self._intent_patterns = self._build_intent_patterns()
        self._register_functions()
        self._subscribe_events()
        logger.info("NLPProcessor initialized")

    def set_tool_executor(self, executor) -> None:
        self._tool_executor = executor

    def _build_intent_patterns(self) -> Dict[str, List[str]]:
        return {
            "weather": [r"天气", r"气温", r"下雨", r"晴天", r"阴天", r"今天.*怎么样", r"明天.*天气"],
            "music": [r"播放.*歌", r"音乐", r"来一首", r"放歌", r"听歌", r"下一首", r"切歌", r"暂停", r"继续播放", r"继续听", r"上一首"],
            "alarm": [r"闹钟", r"提醒", r"定时", r"几点", r"时间"],
            "joke": [r"笑话", r"讲个.*笑", r"逗我", r"开心"],
            "chat": [r"你好", r"在吗", r"你是谁", r"你叫什么"],
            # 收紧smarthome：必须同时有动作词+设备词，避免"打开文件"误判
            "smarthome": [r"打开.*(灯|空调|窗帘|电视|风扇|台灯|设备)", r"关闭.*(灯|空调|窗帘|电视|风扇|台灯|设备)", r"开灯", r"关灯", r"调亮.*灯", r"调暗.*灯", r"(空调|窗帘|电视|风扇|台灯).*(开|关|打开|关闭)", r"(灯|空调).*(调|温度|亮度)"],
            "fruit_ninja": [r"水果忍者", r"游戏", r"切水果", r"开始游戏", r"玩游戏", r"打开游戏", r"启动游戏", r"摄像头游戏", r"关闭游戏", r"退出游戏", r"停止游戏"],
            "system_command": [
                r"创建.*文件夹", r"新建.*文件夹", r"建.*文件夹", r"创建.*目录", r"新建.*目录", r"建.*目录",
                r"创建.*文件", r"新建.*文件", r"建.*文件",
                r"重命名", r"改名", r"删除", r"移除", r"复制", r"移动",
                r"列出", r"查看.*目录", r"查看.*文件", r"读取.*文件",
                r"切换.*目录", r"进入.*目录", r"当前目录", r"当前路径",
                r"写入.*文件", r"执行.*命令", r"运行.*命令", r"权限",
                r"终端", r"terminal", r"shell", r"linux",
            ],
            "exit": [r"再见", r"拜拜", r"退出程序", r"退出系统", r"关机", r"shutdown", r"结束程序", r"关闭程序", r"关闭系统"],
        }

    def _register_functions(self) -> None:
        self._function_descriptions = [
            {"name": "query_weather", "description": "查询天气信息", "parameters": {"type": "object", "properties": {"city": {"type": "string"}, "date": {"type": "string"}}, "required": ["city"]}},
            {"name": "control_music", "description": "控制音乐播放", "parameters": {"type": "object", "properties": {"action": {"type": "string"}, "song": {"type": "string"}}, "required": ["action"]}},
            {"name": "set_alarm", "description": "设置闹钟", "parameters": {"type": "object", "properties": {"hour": {"type": "integer"}, "minute": {"type": "integer"}, "message": {"type": "string"}}, "required": ["hour", "minute"]}},
            {"name": "tell_joke", "description": "讲笑话", "parameters": {"type": "object", "properties": {}}},
            {"name": "chat", "description": "闲聊对话", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
            {"name": "control_device", "description": "控制智能家居", "parameters": {"type": "object", "properties": {"device": {"type": "string"}, "action": {"type": "string"}, "value": {"type": "integer"}}, "required": ["device", "action"]}},
        ]

    def _filter_asr_result(self, text: str) -> str:
        if not text:
            return ""
        text = text.strip()
        if len(text) < 2:
            return ""

        meaningless_words = ["嗯", "啊", "哦", "呃", "呀", "哈", "嘿", "哼", "哎", "嗯啊", "啊哈", "嗯嗯", "啊啊", "哦哦"]
        clean_text = text
        for word in meaningless_words:
            clean_text = clean_text.replace(word, "")
        clean_text = clean_text.strip()
        if not clean_text:
            return ""

        filtered_chars = []
        prev_char = None
        repeat_count = 0
        for char in clean_text:
            if char == prev_char:
                repeat_count += 1
                if repeat_count < 3:
                    filtered_chars.append(char)
            else:
                filtered_chars.append(char)
                prev_char = char
                repeat_count = 1
        return "".join(filtered_chars)

    def _load_model(self) -> bool:
        with self._model_lock:
            if self._model_loaded:
                return True
            if self._model_load_failed:
                return False
            self._model_tried = True

            try:
                import os
                import glob
                from llama_cpp import Llama

                model_path = self._config.model_path
                if not model_path or not os.path.exists(model_path):
                    logger.info("Configured model path invalid, searching for GGUF files...")
                    from ..utils import get_project_root
                    project_root = get_project_root()
                    search_patterns = [
                        os.path.join(project_root, "models", "LLM", "*.gguf"),
                        os.path.join(project_root, "models", "llm", "*.gguf"),
                        os.path.join(project_root, "models", "*.gguf"),
                    ]
                    found_models = []
                    for pattern in search_patterns:
                        found_models.extend(glob.glob(pattern))
                    if found_models:
                        model_path = found_models[0]
                        logger.info(f"Auto-discovered LLM model: {model_path}")
                    else:
                        logger.warning("No GGUF model found anywhere, using mock mode")
                        self._model_load_failed = True
                        return False

                if not os.path.exists(model_path):
                    logger.warning(f"LLM model file not found: {model_path}, using mock mode")
                    self._model_load_failed = True
                    return False

                logger.info(f"Loading LLM model: {model_path}...")
                start_time = time.time()

                try:
                    self._model = Llama(
                        model_path=model_path,
                        n_ctx=self._config.max_context_length,
                        n_threads=self._config.num_threads or 4,
                        n_gpu_layers=self._config.n_gpu_layers,
                        verbose=False,
                        n_batch=512,
                        use_mlock=False,
                    )
                except Exception as e:
                    logger.error(f"Failed to create Llama instance: {e}")
                    self._model_load_failed = True
                    return False

                load_time = time.time() - start_time
                logger.info(f"LLM model loaded in {load_time:.2f}s")

                if self._config.lora_adapter_path and os.path.exists(self._config.lora_adapter_path):
                    try:
                        self._model.load_lora(self._config.lora_adapter_path)
                        logger.info(f"LoRA adapter loaded")
                    except Exception as e:
                        logger.warning(f"Failed to load LoRA adapter: {e}")

                self._model_loaded = True
                self._model_load_failed = False
                return True
            except ImportError:
                logger.warning("llama-cpp-python not installed, using mock mode")
                self._model_load_failed = True
                return False
            except Exception as e:
                logger.error(f"Failed to load LLM model: {e}")
                self._model_load_failed = True
                return False

    def _subscribe_events(self) -> None:
        self._bus.subscribe(EventType.NLP_TRANSCRIBE_DONE, self._on_transcribe_done, "nlp_processor", priority=3)
        self._bus.subscribe(EventType.SYSTEM_STATUS, self._on_system_status, "nlp_processor")
        self._bus.subscribe(EventType.SKILL_RESULT, self._on_skill_result, "nlp_processor", priority=2)
        self._bus.subscribe(EventType.FUNCTION_RESULT, self._on_function_result, "nlp_processor", priority=1)

    def _on_system_status(self, event: Event) -> None:
        if event.data.get("status") == "shutdown":
            self.stop()

    def _on_skill_result(self, event: Event) -> None:
        success = event.data.get("success", False)
        message = event.data.get("message", "")
        if success and message:
            self.manageContext(ChatMessage(role="function", content=message))

    def _on_transcribe_done(self, event: Event) -> None:
        text = event.data.get("text", "")
        if not text:
            return

        filtered_text = self._filter_asr_result(text)
        if not filtered_text:
            logger.debug(f"ASR result filtered out: '{text}'")
            return

        logger.info(f"Processing text: {filtered_text}")

        intent = self.recognizeIntent(filtered_text)
        if intent.confidence >= 0.3:
            self._bus.publish(Event(
                event_type=EventType.INTENT_RECOGNIZED,
                data={"text": filtered_text, "intent": intent.intent, "confidence": intent.confidence, "entities": intent.entities},
                source="NLPProcessor",
                priority=2,
            ))
            return

        if self._config.function_calling_enabled:
            # 模型懒加载：首次调用时主动加载，避免第一次 function calling 失效
            if not self._model_loaded:
                self._load_model()
            if self._model_loaded:
                function_call = self._detect_function_call(filtered_text)
                if function_call:
                    self._bus.publish(Event(
                        event_type=EventType.FUNCTION_CALL,
                        data={"name": function_call.name, "arguments": function_call.arguments, "user_text": filtered_text},
                        source="NLPProcessor",
                        priority=1,
                    ))
                    return

        self._stream_llm_response(filtered_text)

    def _on_function_result(self, event: Event) -> None:
        tool_name = event.data.get("tool_name")
        result = event.data.get("result", "")
        user_text = event.data.get("user_text", "")

        logger.info(f"Function result received: {tool_name} -> {result[:50]}...")
        self.manageContext(ChatMessage(role="system", content=f"工具执行结果：{result}"))

        llm_response = self._generate_final_response(user_text, result)
        if llm_response:
            logger.info(f"Final LLM response: {llm_response[:60]}...")
            self._bus.publish(Event(
                event_type=EventType.AUDIO_OUTPUT,
                data={"text": llm_response, "intent": "function_result"},
                source="NLPProcessor",
                priority=1,
            ))

    def _generate_final_response(self, user_text: str, tool_result: str) -> Optional[str]:
        if not self._load_model():
            return tool_result

        try:
            messages = [
                {"role": "system", "content": "你是小音，一个智能音箱助手。以下是工具执行结果，请根据结果用自然语言回答用户。回答要简洁、口语化，适合语音播放。"},
                {"role": "user", "content": user_text},
                {"role": "system", "content": f"工具执行结果：{tool_result}"},
            ]

            with self._model_lock:
                output = self._model.create_chat_completion(
                    messages=messages,
                    max_tokens=self._config.llm_max_tokens,
                    temperature=self._config.temperature,
                    top_p=self._config.top_p,
                )

            response = output["choices"][0]["message"]["content"].strip()
            self.manageContext(ChatMessage(role="assistant", content=response))
            return response
        except Exception as e:
            logger.error(f"Generate final response error: {e}")
            return tool_result

    def _detect_function_call(self, text: str) -> Optional[FunctionCall]:
        try:
            tools_list = self._build_simple_tools_list()
            messages = [
                {"role": "system", "content": f"你是一个智能音箱助手。你可以调用以下工具：\n{tools_list}\n如果需要调用工具，输出格式为：TOOL:工具名(参数=值)\n如果不需要调用工具，直接回答用户问题。"},
                {"role": "user", "content": text},
            ]

            with self._model_lock:
                output = self._model.create_chat_completion(
                    messages=messages,
                    max_tokens=100,
                    temperature=0.1,
                    top_p=0.9,
                )

            response_text = output["choices"][0]["message"]["content"].strip()

            if response_text.startswith("TOOL:"):
                tool_part = response_text[5:].strip()
                match = re.match(r"(\w+)\((.*)\)", tool_part)
                if match:
                    func_name = match.group(1)
                    args_str = match.group(2)
                    args = {}
                    for arg in args_str.split(","):
                        arg = arg.strip()
                        if "=" in arg:
                            key, val = arg.split("=", 1)
                            args[key.strip()] = val.strip().strip("'\"")
                    return FunctionCall(name=func_name, arguments=args)

            return None
        except Exception as e:
            logger.error(f"Function calling error: {e}")
            return None

    def _build_simple_tools_list(self) -> str:
        from ..skills.system_tools import get_tools_descriptions
        system_tools = get_tools_descriptions()
        all_functions = self._function_descriptions + system_tools

        tools_list = ""
        for func in all_functions:
            params = func.get("parameters", {}).get("properties", {})
            param_list = ", ".join([f"{p}" for p in params.keys()])
            tools_list += f"- {func['name']}({param_list}): {func['description']}\n"

        return tools_list

    def _stream_llm_response(self, text: str) -> None:
        if not self._model_loaded:
            logger.info("[NLP] 模型未加载，尝试加载...")
            if not self._load_model():
                import os
                model_path = self._config.model_path
                exists_msg = ""
                if model_path and os.path.exists(model_path):
                    exists_msg = "但模型文件存在，可能是格式不兼容或内存不足。"
                else:
                    exists_msg = "模型文件不存在，请检查路径配置。"
                logger.warning(f"[NLP] 大模型加载失败: {exists_msg}")
                self._bus.publish(Event(
                    event_type=EventType.AUDIO_OUTPUT,
                    data={"text": f"抱歉，大模型加载失败，{exists_msg}", "intent": "llm_error"},
                    source="NLPProcessor",
                ))
                return
            logger.info("[NLP] 大模型加载成功，开始生成回答...")

        with self._stream_lock:
            if self._is_streaming:
                logger.warning("LLM stream already in progress, ignoring request")
                return
            self._is_streaming = True

        # 修复：移除外层try-finally，_is_streaming重置移到子线程finally中
        self._chunker = SemanticChunker()
        self.manageContext(ChatMessage(role="user", content=text))

        with self._context_lock:
            context_copy = list(self._context[-5:])

        messages = [
            {"role": "system", "content": "你是小音，一个智能音箱助手。回答要简洁、口语化，适合语音播放，每次回答控制在两三句话以内。不要使用markdown格式，不要列出编号，直接说自然的话。"},
            *[{"role": m.role, "content": m.content} for m in context_copy],
        ]

        self._bus.publish(Event(
            event_type=EventType.NLP_RESPONSE_START,
            data={"text": text},
            source="NLPProcessor",
        ))

        def generate_and_stream():
            full_response = []
            try:
                with self._model_lock:
                    for token in self._model.create_chat_completion(
                        messages=messages,
                        max_tokens=self._config.llm_max_tokens,
                        temperature=self._config.temperature,
                        top_p=self._config.top_p,
                        stream=True,
                    ):
                        content = token["choices"][0]["delta"].get("content", "")
                        if content:
                            full_response.append(content)

                            self._bus.publish(Event(
                                event_type=EventType.NLP_RESPONSE_CHUNK,
                                data={"text": content},
                                source="NLPProcessor",
                            ))

                            chunk = self._chunker.push(content)
                            if chunk:
                                logger.debug(f"Semantic chunk: '{chunk}'")
                                self._bus.publish(Event(
                                    event_type=EventType.NLP_SENTENCE_CHUNK,
                                    data={"text": chunk},
                                    source="NLPProcessor",
                                ))

                remaining = self._chunker.flush()
                if remaining:
                    self._bus.publish(Event(
                        event_type=EventType.NLP_SENTENCE_CHUNK,
                        data={"text": remaining},
                        source="NLPProcessor",
                    ))

                final_response = "".join(full_response)
                if final_response:
                    self.manageContext(ChatMessage(role="assistant", content=final_response))
                    self._bus.publish(Event(
                        event_type=EventType.NLP_RESPONSE_DONE,
                        data={"text": final_response},
                        source="NLPProcessor",
                    ))

            except Exception as e:
                logger.error(f"LLM stream error: {e}")
                error_text = "抱歉，我现在有点累了，请稍后再试。"
                self._bus.publish(Event(
                    event_type=EventType.NLP_RESPONSE_DONE,
                    data={"text": error_text},
                    source="NLPProcessor",
                ))
            finally:
                # 修复防抖：在子线程结束时才重置标志，避免主线程立即重置导致防抖失效
                with self._stream_lock:
                    self._is_streaming = False

        thread = threading.Thread(target=generate_and_stream, daemon=True)
        thread.start()

        # 修复：不要在主线程finally中重置_is_streaming，否则防抖失效
        # 重置逻辑已移到 generate_and_stream 子线程的 finally 中

    def set_stream_buffer(self, stream_buffer) -> None:
        self._stream_buffer = stream_buffer

    def _try_llm_chat(self, text: str) -> Optional[str]:
        if not self._model_loaded:
            return None

        try:
            self.manageContext(ChatMessage(role="user", content=text))

            messages = [
                {"role": "system", "content": "你是小音，一个智能音箱助手。回答要简洁、口语化，适合语音播放，每次回答控制在两三句话以内。不要使用markdown格式，不要列出编号，直接说自然的话。"},
                *[{"role": m.role, "content": m.content} for m in self._context[-5:]],
            ]

            with self._model_lock:
                output = self._model.create_chat_completion(
                    messages=messages,
                    max_tokens=self._config.llm_max_tokens,
                    temperature=self._config.temperature,
                    top_p=self._config.top_p,
                )

            response = output["choices"][0]["message"]["content"].strip()
            if response:
                self.manageContext(ChatMessage(role="assistant", content=response))
                return response

            return None
        except Exception as e:
            logger.error(f"LLM chat error: {e}")
            return None

    def generateResponse(self, prompt: str) -> Generator[str, None, None]:
        self._bus.publish(Event(
            event_type=EventType.NLP_RESPONSE_START,
            data={"prompt": prompt},
            source="NLPProcessor",
        ))

        self.manageContext(ChatMessage(role="user", content=prompt))

        response = ""
        if self._config.offline_mode and self._load_model():
            response = self._generate_llm_response(prompt)
        else:
            intent = self.recognizeIntent(prompt)
            response = self._generate_intent_response(intent, prompt)

        chunk_size = 5
        for i in range(0, len(response), chunk_size):
            time.sleep(0.05)
            yield response[i : i + chunk_size]

        self.manageContext(ChatMessage(role="assistant", content=response))

    def _generate_llm_response(self, prompt: str) -> str:
        try:
            messages = [
                {"role": "system", "content": "你是一个友好的智能音箱助手，回答要简洁明了。"},
                *[{"role": m.role, "content": m.content} for m in self._context[-10:]],
            ]

            with self._model_lock:
                output = self._model.create_chat_completion(
                    messages=messages,
                    max_tokens=self._config.max_response_length,
                    temperature=self._config.temperature,
                    top_p=self._config.top_p,
                )

            return output["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"LLM generation error: {e}")
            intent = self.recognizeIntent(prompt)
            return self._generate_intent_response(intent, prompt)

    def _generate_intent_response(self, intent: IntentResult, prompt: str) -> str:
        responses = {
            "weather": "今天天气晴朗，气温25度，空气质量优，适合户外活动。",
            "music": "好的，正在为您播放轻音乐，希望您喜欢。",
            "alarm": "已为您设置明天早上7点的闹钟，需要我再提醒您什么吗？",
            "joke": "为什么程序员喜欢黑暗？因为他们怕光...不对，因为黑暗中可以编译bug！哈哈~",
            "chat": "你好呀！我是智能音箱小智，很高兴为您服务。有什么我可以帮您的吗？",
            "unknown": "抱歉，我不太明白您的意思。您可以问我天气、音乐、闹钟、笑话等问题。",
        }
        return responses.get(intent.intent, responses["unknown"])

    def manageContext(self, message: Optional[ChatMessage] = None) -> List[ChatMessage]:
        with self._context_lock:
            if message is not None:
                self._context.append(message)
                max_ctx = self._config.max_context_length
                total_len = sum(len(m.content) for m in self._context)
                while total_len > max_ctx and len(self._context) > 2:
                    removed = self._context.pop(0)
                    total_len -= len(removed.content)
            return list(self._context)

    def streamOutput(self, text: str) -> Generator[str, None, None]:
        for char in text:
            time.sleep(0.03)
            yield char

    def recognizeIntent(self, text: str) -> IntentResult:
        text_lower = text.lower()
        best_intent = "unknown"
        best_score = 0.0
        best_entities: Dict[str, Any] = {}

        for intent, patterns in self._intent_patterns.items():
            score = 0.0
            entities: Dict[str, Any] = {}
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    score += 0.3
                    matches = re.findall(pattern, text_lower)
                    if matches:
                        entities["matches"] = matches
            if score > best_score:
                best_score = score
                best_intent = intent
                best_entities = entities

        confidence = min(1.0, best_score)
        return IntentResult(
            intent=best_intent,
            confidence=confidence,
            entities=best_entities,
            raw_text=text,
        )

    def clearContext(self) -> None:
        self._context.clear()
        logger.info("NLP context cleared")

    def update(self, subject, event: str, data: Any = None) -> None:
        pass

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.clearContext()

        if self._config.offline_mode:
            self._load_model()

        logger.info("NLPProcessor started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        logger.info("NLPProcessor stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def context_length(self) -> int:
        return len(self._context)

    @property
    def available_intents(self) -> List[str]:
        return list(self._intent_patterns.keys())

    @property
    def model_loaded(self) -> bool:
        return self._model_loaded