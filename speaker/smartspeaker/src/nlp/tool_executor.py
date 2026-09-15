from __future__ import annotations
from typing import Dict, Any
from ..core.message_bus import MessageBus, Event, EventType
from ..utils.logger import logger
from ..skills.system_tools import execute_tool, get_tools_descriptions


class ToolExecutor:
    def __init__(self, bus: MessageBus) -> None:
        self._bus = bus
        self._running = False
        self._subscribe_events()
        logger.info("ToolExecutor initialized")

    def _subscribe_events(self) -> None:
        self._bus.subscribe(
            EventType.FUNCTION_CALL,
            self._on_function_call,
            "tool_executor",
            priority=1,
        )
        self._bus.subscribe(
            EventType.SYSTEM_STATUS,
            self._on_system_status,
            "tool_executor",
        )

    def _on_system_status(self, event: Event) -> None:
        status = event.data.get("status")
        if status == "shutdown":
            self.stop()

    def _on_function_call(self, event: Event) -> None:
        tool_name = event.data.get("name")
        arguments = event.data.get("arguments", {})
        user_text = event.data.get("user_text", "")
        
        if not tool_name:
            logger.error("Tool call received without tool name")
            return

        logger.info(f"Executing tool: {tool_name} with args: {arguments}")

        result = execute_tool(tool_name, arguments)
        
        logger.info(f"Tool execution result: {result[:50]}...")

        self._bus.publish(
            Event(
                event_type=EventType.FUNCTION_RESULT,
                data={
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "result": result,
                    "user_text": user_text,
                    "success": "成功" in result or "完成" in result,
                },
                source="ToolExecutor",
                priority=1,
            )
        )

    @staticmethod
    def get_tools_descriptions() -> list:
        return get_tools_descriptions()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        logger.info("ToolExecutor started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        logger.info("ToolExecutor stopped")

    @property
    def is_running(self) -> bool:
        return self._running