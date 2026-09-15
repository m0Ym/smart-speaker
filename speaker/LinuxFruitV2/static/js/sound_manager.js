class SoundManager {
    constructor() {
        this._audioContext = null;
        this._sounds = {};
        this._volume = 0.5;
        this._initialized = false;
    }
    
    _initialize() {
        if (this._initialized) return;
        
        try {
            this._audioContext = new (window.AudioContext || window.webkitAudioContext)();
            this._initialized = true;
        } catch (e) {
            console.warn('Web Audio API not supported');
            return;
        }
        
        this._loadSounds();
    }
    
    _loadSounds() {
        const sounds = [
            { name: 'slice', path: 'sound/splatter.mp3' },
            { name: 'explode', path: 'sound/boom.mp3' },
            { name: 'start', path: 'sound/start.mp3' },
            { name: 'gameover', path: 'sound/over.mp3' },
            { name: 'menu', path: 'sound/menu.mp3' },
        ];
        
        sounds.forEach(sound => {
            const audio = new Audio(sound.path);
            audio.volume = this._volume;
            audio.preload = 'auto';
            this._sounds[sound.name] = audio;
        });
    }
    
    play(soundType) {
        if (!this._initialized) {
            this._initialize();
        }
        
        if (!this._audioContext) return;
        
        const sound = this._sounds[soundType];
        if (!sound) {
            console.warn(`Sound not found: ${soundType}`);
            return;
        }
        
        try {
            sound.currentTime = 0;
            sound.play().catch(e => {
                console.warn('Failed to play sound:', e);
            });
        } catch (e) {
            console.warn('Error playing sound:', e);
        }
    }
    
    playSlice() {
        this.play('slice');
    }
    
    playExplode() {
        this.play('explode');
    }
    
    playStart() {
        this.play('start');
    }
    
    playGameOver() {
        this.play('gameover');
    }
    
    playMenu() {
        this.play('menu');
    }
    
    setVolume(volume) {
        this._volume = Math.max(0, Math.min(1, volume));
        
        Object.values(this._sounds).forEach(sound => {
            sound.volume = this._volume;
        });
    }
}