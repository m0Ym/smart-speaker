class Renderer {
    constructor(canvasId, width, height) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        
        this.logicalWidth = width;
        this.logicalHeight = height;
        
        this.canvas.width = width;
        this.canvas.height = height;
        
        this._images = {};
        this._loadingImages = {};
        
        this._currentState = null;
        this._toastText = '';
        this._toastTimer = 0;
        
        this._highScores = { limited_lives: 0, slash_mode: 0 };
        this._currentMode = 'limited_lives';
        
        this._init();
    }
    
    _init() {
        this._loadImages();
    }
    
    _loadImages() {
        const images = [
            { name: 'sandia.png', path: 'images/fruit/sandia.png' },
            { name: 'sandia-1.png', path: 'images/fruit/sandia-1.png' },
            { name: 'sandia-2.png', path: 'images/fruit/sandia-2.png' },
            { name: 'basaha.png', path: 'images/fruit/basaha.png' },
            { name: 'basaha-1.png', path: 'images/fruit/basaha-1.png' },
            { name: 'basaha-2.png', path: 'images/fruit/basaha-2.png' },
            { name: 'banana.png', path: 'images/fruit/banana.png' },
            { name: 'banana-1.png', path: 'images/fruit/banana-1.png' },
            { name: 'banana-2.png', path: 'images/fruit/banana-2.png' },
            { name: 'peach.png', path: 'images/fruit/peach.png' },
            { name: 'peach-1.png', path: 'images/fruit/peach-1.png' },
            { name: 'peach-2.png', path: 'images/fruit/peach-2.png' },
            { name: 'apple.png', path: 'images/fruit/apple.png' },
            { name: 'apple-1.png', path: 'images/fruit/apple-1.png' },
            { name: 'apple-2.png', path: 'images/fruit/apple-2.png' },
            { name: 'boom.png', path: 'images/fruit/boom.png' },
            { name: 'flash.png', path: 'images/flash.png' },
            { name: 'background.jpg', path: 'images/background.jpg' },
        ];
        
        images.forEach(img => {
            const image = new Image();
            image.onload = () => {
                this._images[img.name] = image;
            };
            image.onerror = () => {
                console.warn(`Failed to load image: ${img.path}`);
            };
            image.src = img.path;
        });
    }
    
    render(state) {
        this._currentState = state;
        
        this._clear();
        
        if (!state.show_start_screen && !state.is_game_over) {
            this._drawFruits(state.fruits);
            this._drawBombs(state.bombs);
            this._drawSuperFruits(state.super_fruits);
            this._drawParticles(state.particles);
            this._drawHands(state.hands);
            this._drawCenterCombo(state.combo);
        }
        
        this._updateUI(state);
        this._updateToast();
    }
    
    _drawCenterCombo(combo) {
        if (combo <= 1) return;
        
        this.ctx.save();
        this.ctx.font = 'bold 60px Arial';
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        
        const gradient = this.ctx.createLinearGradient(
            this.logicalWidth / 2 - 100, this.logicalHeight / 2,
            this.logicalWidth / 2 + 100, this.logicalHeight / 2
        );
        gradient.addColorStop(0, '#ffd700');
        gradient.addColorStop(0.5, '#ffaa00');
        gradient.addColorStop(1, '#ffd700');
        
        this.ctx.fillStyle = gradient;
        this.ctx.shadowColor = 'rgba(0, 0, 0, 0.8)';
        this.ctx.shadowBlur = 10;
        this.ctx.shadowOffsetX = 3;
        this.ctx.shadowOffsetY = 3;
        
        this.ctx.fillText(`x${combo}`, this.logicalWidth / 2, this.logicalHeight / 2 - 50);
        
        this.ctx.restore();
    }
    
    _clear() {
        const bg = this._images['background.jpg'];
        if (bg) {
            this.ctx.drawImage(bg, 0, 0, this.logicalWidth, this.logicalHeight);
        } else {
            this.ctx.fillStyle = '#1a1a1a';
            this.ctx.fillRect(0, 0, this.logicalWidth, this.logicalHeight);
        }
    }
    
    _drawFruits(fruits) {
        fruits.forEach(fruit => {
            const img = this._images[fruit.texture_name];
            
            this.ctx.save();
            this.ctx.translate(fruit.x, fruit.y);
            this.ctx.rotate(fruit.rotation);
            
            const size = fruit.radius * 2;
            
            if (img) {
                this.ctx.drawImage(img, -size/2, -size/2, size, size);
            } else {
                this.ctx.fillStyle = this._getFruitColor(fruit.type);
                this.ctx.beginPath();
                this.ctx.arc(0, 0, fruit.radius, 0, Math.PI * 2);
                this.ctx.fill();
            }
            
            this.ctx.restore();
        });
    }
    
    _drawBombs(bombs) {
        bombs.forEach(bomb => {
            const img = this._images[bomb.texture_name];
            const size = bomb.radius * 2;
            
            if (img) {
                this.ctx.drawImage(img, bomb.x - size/2, bomb.y - size/2, size, size);
            } else {
                this.ctx.fillStyle = '#000000';
                this.ctx.beginPath();
                this.ctx.arc(bomb.x, bomb.y, bomb.radius, 0, Math.PI * 2);
                this.ctx.fill();
            }
        });
    }
    
    _drawSuperFruits(superFruits) {
        superFruits.forEach(fruit => {
            const img = this._images[fruit.texture_name];
            
            this.ctx.save();
            this.ctx.translate(fruit.x, fruit.y);
            this.ctx.rotate(fruit.rotation);
            
            const size = fruit.radius * 2;
            
            if (img) {
                this.ctx.drawImage(img, -size/2, -size/2, size, size);
            } else {
                this.ctx.fillStyle = '#ff0000';
                this.ctx.beginPath();
                this.ctx.arc(0, 0, fruit.radius, 0, Math.PI * 2);
                this.ctx.fill();
            }
            
            this.ctx.restore();
        });
    }
    
    _drawParticles(particles) {
        particles.forEach(particle => {
            const alpha = particle.life / particle.max_life;
            
            if (alpha <= 0) return;
            
            this.ctx.save();
            this.ctx.globalAlpha = alpha;
            this.ctx.fillStyle = `rgb(${particle.color[0]}, ${particle.color[1]}, ${particle.color[2]})`;
            this.ctx.beginPath();
            this.ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
            this.ctx.fill();
            this.ctx.restore();
        });
    }
    
    _drawHands(hands) {
        this._drawHand(hands.left);
        this._drawHand(hands.right);
    }
    
    _drawHand(hand) {
        if (!hand.is_tracking) return;
        
        if (hand.trail && hand.trail.length > 1) {
            this.ctx.strokeStyle = `rgb(${hand.color[0]}, ${hand.color[1]}, ${hand.color[2]})`;
            this.ctx.lineWidth = 3;
            this.ctx.lineCap = 'round';
            this.ctx.lineJoin = 'round';
            
            this.ctx.beginPath();
            this.ctx.moveTo(hand.trail[0][0], hand.trail[0][1]);
            
            for (let i = 1; i < hand.trail.length; i++) {
                this.ctx.lineTo(hand.trail[i][0], hand.trail[i][1]);
            }
            
            this.ctx.stroke();
        }
        
        if (hand.predicted_position) {
            const [x, y] = hand.predicted_position;
            const bladeRadius = 15;
            
            const gradient = this.ctx.createRadialGradient(x, y, 0, x, y, bladeRadius);
            gradient.addColorStop(0, `rgba(${hand.color[0]}, ${hand.color[1]}, ${hand.color[2]}, 0.8)`);
            gradient.addColorStop(1, `rgba(${hand.color[0]}, ${hand.color[1]}, ${hand.color[2]}, 0)`);
            
            this.ctx.fillStyle = gradient;
            this.ctx.beginPath();
            this.ctx.arc(x, y, bladeRadius, 0, Math.PI * 2);
            this.ctx.fill();
        }
    }
    
    _updateUI(state) {
        const scoreEl = document.getElementById('score');
        const comboEl = document.getElementById('combo');
        const livesEl = document.getElementById('lives');
        const modeEl = document.getElementById('mode');
        
        if (scoreEl) scoreEl.textContent = state.score;
        if (comboEl) comboEl.textContent = `x${state.combo}`;
        
        if (livesEl) {
            if (state.mode === 'limited_lives') {
                livesEl.textContent = '❤️'.repeat(state.lives);
                livesEl.style.display = 'block';
            } else {
                livesEl.style.display = 'none';
            }
        }
        
        if (modeEl) {
            modeEl.textContent = state.mode === 'limited_lives' ? 'Limited Lives' : 'Slash Mode';
        }
        
        if (state.mode !== this._currentMode) {
            this._currentMode = state.mode;
            this._updateStartScreen();
        }
        
        const pauseBtn = document.getElementById('btn-pause');
        if (state.show_start_screen || state.is_game_over) {
            pauseBtn.classList.add('hidden');
        } else {
            pauseBtn.classList.remove('hidden');
        }
        
        const startScreen = document.getElementById('start-screen');
        const gameOverScreen = document.getElementById('game-over-screen');
        const pauseScreen = document.getElementById('pause-screen');
        
        startScreen.classList.add('hidden');
        gameOverScreen.classList.add('hidden');
        pauseScreen.classList.add('hidden');
        
        if (state.show_start_screen) {
            startScreen.classList.remove('hidden');
        } else if (state.is_game_over) {
            gameOverScreen.classList.remove('hidden');
        } else if (state.is_paused) {
            pauseScreen.classList.remove('hidden');
        }
    }
    
    _updateStartScreen() {
        const modeEl = document.getElementById('current-mode');
        const highScoreEl = document.getElementById('high-score');
        
        if (modeEl) {
            modeEl.textContent = this._currentMode === 'limited_lives' ? 'Limited Lives' : 'Slash Mode';
        }
        
        if (highScoreEl) {
            const score = this._highScores[this._currentMode] || 0;
            highScoreEl.textContent = `High Score: ${score}`;
        }
    }
    
    showToast(message) {
        this._toastText = message;
        this._toastTimer = 1.0;
        
        const toastEl = document.getElementById('toast');
        if (toastEl) {
            toastEl.textContent = message;
            toastEl.classList.remove('hidden');
        }
    }
    
    _updateToast() {
        if (this._toastTimer <= 0) return;
        
        this._toastTimer -= 1/60;
        
        if (this._toastTimer <= 0) {
            const toastEl = document.getElementById('toast');
            if (toastEl) {
                toastEl.classList.add('hidden');
            }
        }
    }
    
    showGameOver(data) {
        const screen = document.getElementById('game-over-screen');
        const title = document.getElementById('game-over-title');
        const score = document.getElementById('final-score');
        const combo = document.getElementById('final-combo');
        
        screen.classList.remove('hidden');
        
        if (data.is_new_record) {
            title.textContent = 'New Record!';
            title.style.color = '#ffd700';
        } else {
            title.textContent = 'Game Over';
            title.style.color = '#ff4444';
        }
        
        if (score) score.textContent = `Final Score: ${data.score}`;
        if (combo) combo.textContent = `Max Combo: x${data.max_combo}`;
    }
    
    updateHighScores(scores) {
        this._highScores = scores;
        this._updateStartScreen();
    }
    
    _getFruitColor(type) {
        const colors = {
            watermelon: '#ff6b8a',
            orange: '#ffb347',
            lemon: '#fff44f',
            lime: '#7fff00',
            berry: '#7eb8da'
        };
        return colors[type] || '#ffffff';
    }
    
    start() {
        this._animate();
    }
    
    _animate() {
        requestAnimationFrame(() => this._animate());
    }
}