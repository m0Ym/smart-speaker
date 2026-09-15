import os
os.environ['QT_LOGGING_RULES'] = '*.debug=false;qt.qpa.*=false'

import sys
import time
import json
import asyncio
import websockets
import threading
import socket
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler

DEFAULT_HTTP_PORT = int(os.environ.get('GAME_HTTP_PORT', 8080))
DEFAULT_WS_PORT = int(os.environ.get('GAME_WS_PORT', 8765))

def find_available_port(start_port, max_attempts=100):
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('', port))
                return port
            except OSError:
                continue
    return None

class ThreadedHTTPServer(threading.Thread):
    def __init__(self, port):
        super().__init__(daemon=True)
        self._port = port
        self._server = None
    
    def run(self):
        handler = StaticHTTPHandler
        self._server = HTTPServer(('0.0.0.0', self._port), handler)
        self._server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        print(f"HTTP server running on http://0.0.0.0:{self._port}")
        self._server.serve_forever()
    
    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()

def open_browser(http_port, delay=1):
    time.sleep(delay)
    url = f"http://localhost:{http_port}/index.html"
    print(f"[Browser] Opening {url}")
    webbrowser.open(url)

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from config import SCREEN_WIDTH, SCREEN_HEIGHT, GAME_FPS
from game.fruit_game import FruitGame
from game.models import GameMode
from game.assets import FruitAssets
from game.sound import SoundManager
from game.score import ScoreManager

try:
    from camera.camera_manager import CameraManager
    from tracking.hand_tracker import HandTracker
    CAMERA_AVAILABLE = True
except ImportError as e:
    print(f"Camera/tracking modules not available: {e}")
    CAMERA_AVAILABLE = False
    CameraManager = None
    HandTracker = None

from input.hand_controller import HandController


class GameServer:
    def __init__(self):
        self._game = FruitGame()
        self._camera = CameraManager() if CAMERA_AVAILABLE else None
        self._hand_tracker = HandTracker() if CAMERA_AVAILABLE else None
        self._hand_controller = HandController()
        
        self._current_mode = GameMode.LIMITED_LIVES
        self._game_over = False
        self._show_start_screen = True
        
        self._score = 0
        self._combo = 1
        self._lives = 3
        self._is_new_record = False
        
        self._websocket_connections = set()
        self._websocket_lock = asyncio.Lock()
        
        self._game_thread = None
        self._is_running = False
        self._last_frame_time = time.time()
        self._frame_count = 0
        
        self._pending_events = []
        self._events_lock = threading.Lock()

    def initialize(self):
        resources_dir = os.path.join(current_dir, "resources")
        
        FruitAssets.initialize(resources_dir)
        SoundManager.initialize(resources_dir)
        
        if CAMERA_AVAILABLE and self._hand_tracker:
            self._hand_tracker.initialize()
        
        self._hand_controller.on_slash = self._on_slash
        self._hand_controller.on_hand_moved = self._on_hand_moved
        
        self._game.initialize(SCREEN_WIDTH, SCREEN_HEIGHT, self._current_mode)
        self._game.on_stats_changed = self._on_stats_changed
        self._game.on_toast = self._on_toast
        self._game.on_game_over = self._on_game_over
        self._game.on_lives_changed = self._on_lives_changed
        self._game.on_sound = self._on_sound
        
        if CAMERA_AVAILABLE and self._camera:
            if not self._camera.initialize():
                print("Warning: Camera initialization failed.")
        else:
            print("Warning: Camera/tracking not available. Running in simulation mode.")

    def _on_slash(self, slash_event, hand_id):
        self._game.handle_slash(slash_event)
    
    def _on_hand_moved(self, hand_id, position, speed):
        pass
    
    def _on_stats_changed(self, score, combo):
        self._score = score
        self._combo = combo
    
    def _on_toast(self, message):
        self._add_event({'type': 'toast', 'message': message, 'duration': 1.0})
    
    def _on_game_over(self):
        self._game_over = True
        
        is_new_record = ScoreManager.update_high_score(
            self._current_mode,
            self._game.score,
            self._game.max_combo
        )
        
        self._is_new_record = is_new_record
        
        self._add_event({
            'type': 'game_over',
            'score': self._game.score,
            'max_combo': self._game.max_combo,
            'is_new_record': is_new_record
        })
    
    def _on_lives_changed(self, lives):
        self._lives = lives
    
    def _on_sound(self, sound_type):
        self._add_event({'type': 'sound', 'sound_type': sound_type})
    
    def _add_event(self, event):
        with self._events_lock:
            self._pending_events.append(event)
    
    def _get_pending_events(self):
        with self._events_lock:
            events = self._pending_events.copy()
            self._pending_events.clear()
            return events
    
    def _serialize_state(self):
        state = {
            'type': 'game_state',
            'timestamp': time.time(),
            'score': self._score,
            'combo': self._combo,
            'lives': self._lives,
            'mode': self._current_mode,
            'is_paused': self._game.is_paused,
            'is_game_over': self._game_over,
            'show_start_screen': self._show_start_screen,
            'fruits': [],
            'bombs': [],
            'particles': [],
            'super_fruits': [],
            'hands': {
                'left': {
                    'is_tracking': False,
                    'trail': [],
                    'predicted_position': None,
                    'color': [255, 0, 0]
                },
                'right': {
                    'is_tracking': False,
                    'trail': [],
                    'predicted_position': None,
                    'color': [255, 255, 0]
                }
            }
        }
        
        for fruit in self._game.get_fruits():
            fruit_data = {
                'id': id(fruit),
                'type': fruit.fruit_type,
                'x': fruit.x,
                'y': fruit.y,
                'radius': fruit.radius,
                'rotation': fruit.rotation,
                'is_sliced': fruit.is_sliced,
                'is_half': fruit.is_half,
                'texture_name': self._get_fruit_texture_name(fruit)
            }
            state['fruits'].append(fruit_data)
        
        for bomb in self._game.get_bombs():
            bomb_data = {
                'id': id(bomb),
                'x': bomb.x,
                'y': bomb.y,
                'radius': bomb.radius,
                'texture_name': 'boom.png'
            }
            state['bombs'].append(bomb_data)
        
        for particle in self._game.get_particles():
            particle_data = {
                'id': id(particle),
                'x': particle.x,
                'y': particle.y,
                'color': list(particle.color),
                'size': particle.size,
                'life': particle.life,
                'max_life': particle.max_life
            }
            state['particles'].append(particle_data)
        
        for super_fruit in self._game.get_super_fruits():
            super_data = {
                'id': id(super_fruit),
                'x': super_fruit.x,
                'y': super_fruit.y,
                'radius': super_fruit.radius,
                'rotation': super_fruit.rotation,
                'hit_count': super_fruit.hit_count,
                'texture_name': 'flash.png'
            }
            state['super_fruits'].append(super_data)
        
        left_hand = self._hand_controller.get_left_hand()
        right_hand = self._hand_controller.get_right_hand()
        
        if left_hand.is_tracking:
            state['hands']['left']['is_tracking'] = True
            state['hands']['left']['trail'] = [[p[0], p[1]] for p in left_hand.trail]
            if left_hand.predicted_position:
                state['hands']['left']['predicted_position'] = [
                    left_hand.predicted_position[0],
                    left_hand.predicted_position[1]
                ]
        
        if right_hand.is_tracking:
            state['hands']['right']['is_tracking'] = True
            state['hands']['right']['trail'] = [[p[0], p[1]] for p in right_hand.trail]
            if right_hand.predicted_position:
                state['hands']['right']['predicted_position'] = [
                    right_hand.predicted_position[0],
                    right_hand.predicted_position[1]
                ]
        
        return state
    
    def _get_fruit_texture_name(self, fruit):
        from config import FRUIT_TEXTURE_MAP
        texture_info = FRUIT_TEXTURE_MAP.get(fruit.fruit_type)
        if texture_info:
            if fruit.is_half:
                if hasattr(fruit, '_slice_side') and fruit._slice_side == -1:
                    return texture_info['slice1']
                else:
                    return texture_info['slice2']
            else:
                return texture_info['full']
        return None
    
    def _game_loop(self):
        frame_time = 1.0 / GAME_FPS
        self._is_running = True
        
        while self._is_running:
            frame_timestamp = time.time()
            delta_time = frame_timestamp - self._last_frame_time
            self._last_frame_time = frame_timestamp
            
            if delta_time > 0.1:
                delta_time = 0.1
            
            if not self._show_start_screen and not self._game_over:
                if CAMERA_AVAILABLE and self._camera and self._camera.is_running:
                    frame = self._camera.get_frame()
                    if frame is not None:
                        self._hand_tracker.submit_frame(frame)
                    
                    left_hand, right_hand = self._hand_tracker.get_latest_result()
                    
                    if left_hand.is_detected:
                        self._hand_controller.update_hand('left', left_hand.x, left_hand.y, left_hand.timestamp)
                    else:
                        self._hand_controller.track_lost('left')
                    
                    if right_hand.is_detected:
                        self._hand_controller.update_hand('right', right_hand.x, right_hand.y, right_hand.timestamp)
                    else:
                        self._hand_controller.track_lost('right')
                
                self._game.update(delta_time)
            
            self._frame_count += 1
            
            elapsed = time.time() - frame_timestamp
            if elapsed < frame_time:
                time.sleep(frame_time - elapsed)
    
    def start_game(self):
        self._game_over = False
        self._show_start_screen = False
        self._game.initialize(SCREEN_WIDTH, SCREEN_HEIGHT, self._current_mode)
        self._game.start()
        self._score = 0
        self._combo = 1
        self._lives = 3 if self._current_mode == GameMode.LIMITED_LIVES else 999
        self._add_event({'type': 'sound', 'sound_type': 'start'})
    
    def restart_game(self):
        self.start_game()
    
    def switch_mode(self):
        if self._current_mode == GameMode.LIMITED_LIVES:
            self._current_mode = GameMode.SLASH_MODE
        else:
            self._current_mode = GameMode.LIMITED_LIVES
    
    def return_to_menu(self):
        self._game_over = False
        self._show_start_screen = True
        if self._game.is_paused:
            self._game.resume()
        self._score = 0
        self._combo = 1
        self._lives = 3
    
    def pause_game(self):
        if not self._game.is_paused:
            self._game.pause()
    
    def resume_game(self):
        if self._game.is_paused:
            self._game.resume()
    
    def start(self):
        self._game_thread = threading.Thread(target=self._game_loop, daemon=True)
        self._game_thread.start()
        print("Game loop started")
    
    def stop(self):
        self._is_running = False
        if self._game_thread:
            self._game_thread.join(timeout=2.0)
        if CAMERA_AVAILABLE and self._camera:
            self._camera.release()
        if CAMERA_AVAILABLE and self._hand_tracker:
            self._hand_tracker.release()
    
    async def _broadcast(self, message):
        async with self._websocket_lock:
            for conn in self._websocket_connections:
                try:
                    await conn.send(json.dumps(message))
                except websockets.exceptions.ConnectionClosed:
                    pass
    
    async def _handle_websocket(self, websocket):
        async with self._websocket_lock:
            self._websocket_connections.add(websocket)
            print(f"New connection: {len(self._websocket_connections)}")
        
        try:
            high_scores = {
                'limited_lives': ScoreManager.get_high_score(GameMode.LIMITED_LIVES),
                'slash_mode': ScoreManager.get_high_score(GameMode.SLASH_MODE)
            }
            await websocket.send(json.dumps({'type': 'high_scores', 'high_scores': high_scores}))
            
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self._handle_command(data)
                except json.JSONDecodeError:
                    print(f"Invalid JSON: {message}")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            async with self._websocket_lock:
                self._websocket_connections.discard(websocket)
                print(f"Connection closed: {len(self._websocket_connections)}")
    
    async def _handle_command(self, data):
        cmd_type = data.get('type')
        
        if cmd_type == 'start':
            mode = data.get('mode', self._current_mode)
            if mode != self._current_mode:
                self._current_mode = mode
            self.start_game()
        
        elif cmd_type == 'pause':
            self.pause_game()
        
        elif cmd_type == 'resume':
            self.resume_game()
        
        elif cmd_type == 'restart':
            self.restart_game()
        
        elif cmd_type == 'switch_mode':
            self.switch_mode()
        
        elif cmd_type == 'return_to_menu':
            self.return_to_menu()
        
        elif cmd_type == 'exit_to_speaker':
            self.stop()
            asyncio.get_event_loop().stop()
            os._exit(0)
        
        elif cmd_type == 'get_high_scores':
            high_scores = {
                'limited_lives': ScoreManager.get_high_score(GameMode.LIMITED_LIVES),
                'slash_mode': ScoreManager.get_high_score(GameMode.SLASH_MODE)
            }
            await self._broadcast({'type': 'high_scores', 'high_scores': high_scores})
    
    async def _state_pusher(self):
        while self._is_running:
            try:
                state = self._serialize_state()
                await self._broadcast(state)
                
                events = self._get_pending_events()
                for event in events:
                    await self._broadcast(event)
                
                await asyncio.sleep(1/30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"State pusher error: {e}")


class StaticHTTPHandler(SimpleHTTPRequestHandler):
    _ws_port = DEFAULT_WS_PORT
    
    def __init__(self, *args, **kwargs):
        static_dir = os.path.join(current_dir, 'static')
        kwargs['directory'] = static_dir
        super().__init__(*args, **kwargs)
    
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self._serve_index()
        else:
            super().do_GET()
    
    def _serve_index(self):
        index_path = os.path.join(os.path.join(current_dir, 'static'), 'index.html')
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            content = content.replace(
                '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
                f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <meta name="game-ws-port" content="{self._ws_port}">'
            )
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(content.encode('utf-8')))
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))
        except Exception as e:
            self.send_error(500, str(e))


async def main():
    http_port = find_available_port(DEFAULT_HTTP_PORT)
    ws_port = find_available_port(DEFAULT_WS_PORT)
    
    if http_port is None or ws_port is None:
        print("Error: No available port found")
        return
    
    StaticHTTPHandler._ws_port = ws_port
    
    print("=" * 60)
    print("Fruit Ninja Game Server")
    print("=" * 60)
    print()
    
    server = GameServer()
    server.initialize()
    server.start()
    
    try:
        ws_server = await websockets.serve(
            server._handle_websocket,
            '0.0.0.0',
            ws_port
        )
        print(f"WebSocket server running on ws://0.0.0.0:{ws_port}")
    except OSError as e:
        print(f"Error: WebSocket port {ws_port} is occupied")
        print("Please free the port and restart")
        return
    
    http_server = ThreadedHTTPServer(http_port)
    http_server.start()
    
    # 不再自动打开浏览器，由外部控制（如智能音箱 Skill）
    # threading.Thread(target=open_browser, args=(http_port,), daemon=True).start()
    
    print()
    print(f"Game ready! Open http://localhost:{http_port}/index.html")
    print("Press Ctrl+C to stop the server")
    print("=" * 60)
    
    state_task = asyncio.create_task(server._state_pusher())
    
    try:
        await asyncio.Future()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.stop()
        ws_server.close()
        http_server.stop()
        state_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())