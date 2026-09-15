class GameClient {
    constructor(url) {
        this.url = url;
        this.ws = null;
        this.isConnected = false;
        
        this.onStateUpdate = null;
        this.onToast = null;
        this.onGameOver = null;
        this.onHighScores = null;
        this.onSound = null;
        
        this._reconnectAttempts = 0;
        this._maxReconnectAttempts = 5;
    }
    
    connect() {
        this._updateStatus('connecting');
        
        this.ws = new WebSocket(this.url);
        
        this.ws.onopen = () => {
            this.isConnected = true;
            this._reconnectAttempts = 0;
            this._updateStatus('connected');
            console.log('WebSocket connected');
        };
        
        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this._handleMessage(data);
            } catch (e) {
                console.error('Invalid JSON:', event.data);
            }
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
        
        this.ws.onclose = () => {
            this.isConnected = false;
            this._updateStatus('disconnected');
            console.log('WebSocket closed');
            
            if (this._reconnectAttempts < this._maxReconnectAttempts) {
                this._reconnectAttempts++;
                setTimeout(() => this.connect(), 2000 * this._reconnectAttempts);
            }
        };
    }
    
    _updateStatus(status) {
        const statusEl = document.getElementById('ws-status');
        if (statusEl) {
            statusEl.className = `status-${status}`;
            statusEl.textContent = status.charAt(0).toUpperCase() + status.slice(1);
        }
    }
    
    _handleMessage(data) {
        switch (data.type) {
            case 'game_state':
                if (this.onStateUpdate) {
                    this.onStateUpdate(data);
                }
                break;
                
            case 'toast':
                if (this.onToast) {
                    this.onToast(data.message);
                }
                break;
                
            case 'game_over':
                if (this.onGameOver) {
                    this.onGameOver(data);
                }
                break;
                
            case 'high_scores':
                if (this.onHighScores) {
                    this.onHighScores(data.high_scores);
                }
                break;
                
            case 'sound':
                if (this.onSound) {
                    this.onSound(data.sound_type);
                }
                break;
                
            default:
                console.log('Unknown message type:', data.type);
        }
    }
    
    sendCommand(type, data = {}) {
        if (!this.isConnected || !this.ws) {
            return;
        }
        
        const message = { type, ...data };
        
        try {
            this.ws.send(JSON.stringify(message));
        } catch (e) {
            console.error('Failed to send message:', e);
        }
    }
    
    startGame(mode = 'limited_lives') {
        this.sendCommand('start', { mode });
    }
    
    pauseGame() {
        this.sendCommand('pause');
    }
    
    resumeGame() {
        this.sendCommand('resume');
    }
    
    restartGame() {
        this.sendCommand('restart');
    }
    
    switchMode() {
        this.sendCommand('switch_mode');
    }
    
    returnToMenu() {
        this.sendCommand('return_to_menu');
    }
    
    exitToSpeaker() {
        this.sendCommand('exit_to_speaker');
    }
    
    getHighScores() {
        this.sendCommand('get_high_scores');
    }
    
    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.isConnected = false;
    }
}