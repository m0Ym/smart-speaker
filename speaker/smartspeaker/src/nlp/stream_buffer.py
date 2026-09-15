from __future__ import annotations
import time
import threading
import queue
from typing import Optional, Callable, Generator, List
from ..utils.logger import logger


class SentenceChunk:
    def __init__(self, text: str, index: int):
        self.text = text
        self.index = index
        self.audio_data = None
        self.sample_rate = 0
        self.synthesized = False
        self.lock = threading.Lock()


class StreamBuffer:
    def __init__(self, tts_callback: Callable[[str], tuple], bus_callback: Callable[[str], None]):
        self._tts_callback = tts_callback
        self._bus_callback = bus_callback
        self._text_buffer = ""
        self._sentence_queue: queue.Queue[SentenceChunk] = queue.Queue(maxsize=10)
        self._playback_queue: queue.Queue[SentenceChunk] = queue.Queue(maxsize=5)
        self._current_index = 0
        self._lock = threading.RLock()
        self._is_streaming = False
        self._synthesis_thread = None
        self._playback_thread = None
        self._stream_done = threading.Event()
        self._synthesis_done = threading.Event()
        self._playback_done = threading.Event()
        self._min_chunk_length = 3
        self._max_wait_time = 0.3
        self._last_push_time = 0.0

        self._punctuation_marks = {'，', '。', '？', '！', '；', '：', '.', '?', '!', ';', ':'}
        self._closing_marks = {'）', '】', ')', ']', '"', '”', "'", "’", '}'}

        logger.info("StreamBuffer initialized")

    def _is_complete_sentence(self, text: str) -> bool:
        if len(text) < self._min_chunk_length:
            return False

        stripped = text.strip()
        if not stripped:
            return False

        last_char = stripped[-1]
        if last_char in self._punctuation_marks:
            return True

        if last_char in self._closing_marks and len(stripped) > 1:
            prev_char = stripped[-2]
            if prev_char in self._punctuation_marks:
                return True

        return False

    def _split_sentences(self, text: str) -> List[str]:
        sentences = []
        current = []

        for char in text:
            current.append(char)
            if char in self._punctuation_marks:
                sentence = "".join(current).strip()
                if sentence:
                    sentences.append(sentence)
                current = []
            elif char in self._closing_marks and current:
                prev_char = current[-2] if len(current) >= 2 else ''
                if prev_char in self._punctuation_marks:
                    sentence = "".join(current).strip()
                    if sentence:
                        sentences.append(sentence)
                    current = []

        if current:
            sentence = "".join(current).strip()
            if sentence:
                sentences.append(sentence)

        return sentences

    def _synthesis_worker(self):
        logger.debug("Synthesis worker started")
        while not self._stream_done.is_set() or not self._sentence_queue.empty():
            try:
                chunk = self._sentence_queue.get(timeout=0.5)
                if chunk is None:
                    break

                try:
                    audio_data, sample_rate = self._tts_callback(chunk.text)
                    with chunk.lock:
                        chunk.audio_data = audio_data
                        chunk.sample_rate = sample_rate
                        chunk.synthesized = True
                    self._playback_queue.put(chunk)
                    logger.debug(f"Synthesized chunk {chunk.index}: {chunk.text[:30]}...")
                except Exception as e:
                    logger.error(f"Synthesis error for chunk {chunk.index}: {e}")
                    with chunk.lock:
                        chunk.synthesized = False

                self._sentence_queue.task_done()
            except queue.Empty:
                continue

        self._synthesis_done.set()
        logger.debug("Synthesis worker finished")

    def _playback_worker(self):
        logger.debug("Playback worker started")
        while not self._synthesis_done.is_set() or not self._playback_queue.empty():
            try:
                chunk = self._playback_queue.get(timeout=0.5)
                if chunk is None:
                    break

                if chunk.audio_data is not None:
                    self._bus_callback(chunk.text)
                    logger.debug(f"Playback chunk {chunk.index}: {chunk.text[:30]}...")

                self._playback_queue.task_done()
            except queue.Empty:
                continue

        self._playback_done.set()
        logger.debug("Playback worker finished")

    def push(self, text: str):
        with self._lock:
            self._text_buffer += text
            self._last_push_time = time.time()

            while self._text_buffer:
                if self._is_complete_sentence(self._text_buffer):
                    sentences = self._split_sentences(self._text_buffer)
                    if sentences:
                        first_sentence = sentences[0]
                        self._text_buffer = "".join(sentences[1:])

                        chunk = SentenceChunk(first_sentence, self._current_index)
                        self._current_index += 1
                        self._sentence_queue.put(chunk, block=False)
                        logger.debug(f"Pushed sentence chunk: {first_sentence}")
                    else:
                        break
                else:
                    elapsed = time.time() - self._last_push_time
                    if elapsed >= self._max_wait_time and len(self._text_buffer) >= self._min_chunk_length:
                        sentences = self._split_sentences(self._text_buffer)
                        if sentences:
                            first_sentence = sentences[0]
                            self._text_buffer = "".join(sentences[1:])

                            chunk = SentenceChunk(first_sentence, self._current_index)
                            self._current_index += 1
                            self._sentence_queue.put(chunk, block=False)
                            logger.debug(f"Timeout push chunk: {first_sentence}")
                    break

    def flush(self):
        with self._lock:
            if self._text_buffer.strip():
                sentences = self._split_sentences(self._text_buffer)
                for sentence in sentences:
                    chunk = SentenceChunk(sentence, self._current_index)
                    self._current_index += 1
                    self._sentence_queue.put(chunk, block=False)
                self._text_buffer = ""
                logger.debug(f"Flushed remaining text: {sentences}")

    def start(self):
        if self._is_streaming:
            return

        self._is_streaming = True
        self._stream_done.clear()
        self._synthesis_done.clear()
        self._playback_done.clear()
        self._text_buffer = ""
        self._current_index = 0
        self._last_push_time = time.time()

        self._synthesis_thread = threading.Thread(target=self._synthesis_worker, daemon=True)
        self._synthesis_thread.start()

        self._playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self._playback_thread.start()

        logger.info("StreamBuffer streaming started")

    def stop(self):
        if not self._is_streaming:
            return

        self._stream_done.set()

        if self._synthesis_thread:
            self._synthesis_thread.join(timeout=5.0)

        if self._playback_thread:
            self._playback_thread.join(timeout=5.0)

        self._is_streaming = False
        logger.info("StreamBuffer streaming stopped")

    def wait(self, timeout: float = 30.0):
        self._playback_done.wait(timeout=timeout)

    @property
    def is_streaming(self) -> bool:
        return self._is_streaming

    @property
    def buffer_length(self) -> int:
        with self._lock:
            return len(self._text_buffer)

    @property
    def pending_chunks(self) -> int:
        return self._sentence_queue.qsize()

    @property
    def waiting_chunks(self) -> int:
        return self._playback_queue.qsize()