import asyncio
import json
import random
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

# --- ЛОГИКА СЕРВЕРА ---

class GameServer:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.players = {}
        self.current_round = 1
        self.landscapes = [
            {"ground": "#2d3436", "fog": "#636e72", "name": "Тёмная Зона"},
            {"ground": "#27ae60", "fog": "#2ecc71", "name": "Зеленый Полигон"},
            {"ground": "#d35400", "fog": "#e67e22", "name": "Марсианская База"}
        ]
        self.current_landscape = self.landscapes[0]

    async def connect(self, websocket: WebSocket, player_id: str):
        await websocket.accept()
        self.active_connections[player_id] = websocket
        
        # Начальные безопасные координаты
        x, z = random.uniform(-15, 15), random.uniform(-15, 15)
        self.players[player_id] = {
            "name": "Anonym",
            "x": x, "z": z, "ry": 0,
            "color": f"#{random.randint(0, 0xFFFFFF):06x}",
            "hp": 100, "score": 0
        }

    def disconnect(self, player_id: str):
        if player_id in self.active_connections: del self.active_connections[player_id]
        if player_id in self.players: del self.players[player_id]

    async def broadcast(self, data: dict):
        message = json.dumps(data)
        for connection in list(self.active_connections.values()):
            try:
                await connection.send_text(message)
            except:
                pass

server = GameServer()

async def round_manager():
    while True:
        await asyncio.sleep(90) # Раунд 90 секунд
        server.current_round += 1
        server.current_landscape = server.landscapes[(server.current_round - 1) % len(server.landscapes)]
        
        for pid in server.players:
            server.players[pid]["hp"] = 100
            
        await server.broadcast({
            "type": "new_round",
            "round": server.current_round,
            "landscape": server.current_landscape
        })

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(round_manager())

@app.websocket("/ws/{player_id}")
async def websocket_endpoint(websocket: WebSocket, player_id: str):
    await server.connect(websocket, player_id)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            
            if msg["type"] == "join":
                server.players[player_id]["name"] = msg.get("name", "Anonym")
                # Отправляем инфо новому игроку
                await websocket.send_text(json.dumps({
                    "type": "init",
                    "id": player_id,
                    "landscape": server.current_landscape,
                    "round": server.current_round,
                    "players": server.players,
                    "x": server.players[player_id]["x"], 
                    "z": server.players[player_id]["z"]
                }))
                # Оповещаем остальных
                await server.broadcast({
                    "type": "new_player",
                    "id": player_id,
                    "info": server.players[player_id]
                })
                
            elif msg["type"] == "move":
                server.players[player_id]["x"] = msg["x"]
                server.players[player_id]["z"] = msg["z"]
                server.players[player_id]["ry"] = msg.get("ry", 0)
                await server.broadcast({
                    "type": "update",
                    "id": player_id,
                    "x": msg["x"], "z": msg["z"], "ry": msg.get("ry", 0)
                })
                
            elif msg["type"] == "hit":
                target_id = msg["target"]
                if target_id in server.players:
                    server.players[target_id]["hp"] -= 20
                    
                    if server.players[target_id]["hp"] <= 0:
                        server.players[player_id]["score"] += 1
                        server.players[target_id]["hp"] = 100
                        nx, nz = random.uniform(-15, 15), random.uniform(-15, 15)
                        server.players[target_id]["x"] = nx
                        server.players[target_id]["z"] = nz
                        
                        await server.broadcast({
                            "type": "respawn",
                            "id": target_id,
                            "x": nx, "z": nz,
                            "killer": player_id,
                            "score_update": {"id": player_id, "score": server.players[player_id]["score"]}
                        })
                    
                    await server.broadcast({
                        "type": "hp_update",
                        "id": target_id,
                        "hp": server.players[target_id]["hp"]
                    })
                    
            elif msg["type"] == "chat":
                await server.broadcast({
                    "type": "chat_msg",
                    "sender": server.players[player_id]["name"],
                    "text": msg["text"]
                })
                    
    except WebSocketDisconnect:
        server.disconnect(player_id)
        await server.broadcast({"type": "leave", "id": player_id})

# --- ТРЁХМЕРНАЯ ГРАФИКА ДЛЯ БРАУЗЕРА (FRONTEND) ---

html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>3D Arena Pro</title>
    <style>
        body { margin: 0; overflow: hidden; font-family: 'Segoe UI', sans-serif; user-select: none; background: #111; color: white;}
        /* Стартовый экран */
        #login_screen { position: absolute; top:0; left:0; width:100%; height:100%; background: rgba(0,0,0,0.85); display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 100; }
        #login_screen h1 { color: #00ff88; font-size: 48px; margin-bottom: 20px; text-transform: uppercase; letter-spacing: 2px;}
        #nickname_input { padding: 15px; font-size: 20px; width: 300px; text-align: center; border-radius: 8px; border: 2px solid #555; background: #222; color: white; outline: none;}
        #nickname_input:focus { border-color: #00ff88; }
        #play_btn { margin-top: 20px; padding: 15px 40px; font-size: 20px; cursor: pointer; background: #00ff88; color: black; border: none; border-radius: 8px; font-weight: bold; transition: 0.2s; }
        #play_btn:hover { background: #00cc6a; transform: scale(1.05); }

        /* Игровой UI */
        #ui { position: absolute; top: 10px; left: 10px; background: rgba(0,0,0,0.6); padding: 15px; border-radius: 8px; border-left: 4px solid #00ff88; display: none;}
        #crosshair { position: absolute; top: 50%; left: 50%; width: 4px; height: 4px; background: #00ff88; border-radius: 50%; transform: translate(-50%, -50%); pointer-events: none; z-index: 10;}
        #hp_bar_container { position: absolute; bottom: 20px; left: 20px; width: 300px; height: 24px; background: rgba(0,0,0,0.6); border: 2px solid #333; border-radius: 12px; overflow: hidden; display: none;}
        #hp_bar { width: 100%; height: 100%; background: #00ff88; transition: width 0.2s; }
        #damage_overlay { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,0,0,0.3); pointer-events: none; opacity: 0; transition: opacity 0.1s; }
        
        /* Чат */
        #chat_container { position: absolute; bottom: 60px; left: 20px; width: 350px; display: none; flex-direction: column;}
        #chat_log { height: 150px; overflow-y: auto; background: rgba(0,0,0,0.4); padding: 10px; border-radius: 8px; font-size: 14px; text-shadow: 1px 1px 0 #000; margin-bottom: 5px; scrollbar-width: none;}
        #chat_log::-webkit-scrollbar { display: none; }
        #chat_input_wrapper { display: none; }
        #chat_input { width: 100%; padding: 10px; box-sizing: border-box; background: rgba(0,0,0,0.8); color: white; border: 1px solid #00ff88; border-radius: 5px; outline: none; font-family: inherit;}
        
        .chat-msg { margin-bottom: 5px; line-height: 1.4; }
        .chat-sender { color: #f1c40f; font-weight: bold; }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
    <div id="login_screen">
        <h1>Арена: Выживание</h1>
        <input type="text" id="nickname_input" placeholder="Введите никнейм" maxlength="12" autocomplete="off">
        <button id="play_btn">ИГРАТЬ</button>
    </div>

    <div id="ui">
        <h3 id="map_name" style="margin: 0 0 10px 0; color: #00ff88; font-size: 18px;">Загрузка...</h3>
        <div id="round_info">Раунд: 1</div>
        <div id="score_info">Фраги: 0</div>
        <div style="font-size: 11px; margin-top: 10px; color: #aaa;">[T] - Чат | WASD - Ходить | ЛКМ - Огонь</div>
    </div>
    
    <div id="chat_container">
        <div id="chat_log"></div>
        <div id="chat_input_wrapper"><input type="text" id="chat_input" placeholder="Сообщение (Enter для отправки)..." autocomplete="off"></div>
    </div>

    <div id="hp_bar_container"><div id="hp_bar"></div></div>
    <div id="crosshair" style="display:none;"></div>
    <div id="damage_overlay"></div>

    <script>
        let scene, camera, renderer, ground;
        let players = {};
        let myId = null;
        let ws;
        let myName = "Anonym";
        
        // Физика и управление
        let keys = { w:0, a:0, s:0, d:0 };
        let moveSpeed = 0.25;
        let playerRadius = 0.8;
        let myHp = 100;
        let myScore = 0;
        
        // Оружие и стрельба
        let weapon;
        let isShooting = false;
        let bullets = [];
        let bulletSpeed = 2.0;
        
        // Окружение
        let mapGroup = new THREE.Group();
        let collidableObjects = []; // Для проверки столкновений стен и пуль
        
        // Чат
        let chatActive = false;

        function startGame() {
            let inputVal = document.getElementById("nickname_input").value.trim();
            if(inputVal) myName = inputVal;
            
            document.getElementById("login_screen").style.display = "none";
            document.getElementById("ui").style.display = "block";
            document.getElementById("hp_bar_container").style.display = "block";
            document.getElementById("chat_container").style.display = "flex";
            document.getElementById("crosshair").style.display = "block";
            
            init3D();
            initNetwork();
            document.body.requestPointerLock();
        }

        document.getElementById("play_btn").addEventListener("click", startGame);
        document.getElementById("nickname_input").addEventListener("keypress", (e) => {
            if(e.key === "Enter") startGame();
        });

        function init3D() {
            scene = new THREE.Scene();
            scene.fog = new THREE.FogExp2(0x111111, 0.02);
            
            camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
            renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
            renderer.setSize(window.innerWidth, window.innerHeight);
            renderer.shadowMap.enabled = true;
            document.body.appendChild(renderer.domElement);
            
            // Освещение
            const hemiLight = new THREE.HemisphereLight(0xffffff, 0x444444, 0.6);
            hemiLight.position.set(0, 50, 0);
            scene.add(hemiLight);

            const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
            dirLight.position.set(20, 50, -20);
            dirLight.castShadow = true;
            dirLight.shadow.mapSize.width = 2048;
            dirLight.shadow.mapSize.height = 2048;
            scene.add(dirLight);

            // Земля
            const geometry = new THREE.PlaneGeometry(100, 100);
            const material = new THREE.MeshStandardMaterial({ color: 0x2d3436, roughness: 0.8 });
            ground = new THREE.Mesh(geometry, material);
            ground.rotation.x = -Math.PI / 2;
            ground.receiveShadow = true;
            scene.add(ground);
            
            scene.add(mapGroup);
            buildArena();

            createWeapon();
            camera.position.y = 1.6;

            // Обработчики ввода
            document.addEventListener('click', () => { 
                if(chatActive) return;
                if(document.pointerLockElement !== document.body) {
                    document.body.requestPointerLock(); 
                } else {
                    shoot();
                }
            });
            document.addEventListener('mousemove', onMouseMove);
            
            window.addEventListener('keydown', (e) => { 
                if(chatActive) {
                    if(e.key === "Enter") sendChat();
                    if(e.key === "Escape") closeChat();
                    return;
                }
                if(e.key.toLowerCase() === 't') {
                    e.preventDefault();
                    openChat();
                    return;
                }
                if(e.key.toLowerCase() in keys) keys[e.key.toLowerCase()] = 1; 
            });
            
            window.addEventListener('keyup', (e) => { 
                if(!chatActive && e.key.toLowerCase() in keys) keys[e.key.toLowerCase()] = 0; 
            });
            
            window.addEventListener('resize', () => {
                camera.aspect = window.innerWidth / window.innerHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(window.innerWidth, window.innerHeight);
            });
            
            animate();
        }

        function buildArena() {
            // Очистка старой карты
            while(mapGroup.children.length > 0){ mapGroup.remove(mapGroup.children[0]); }
            collidableObjects = [];

            const wallMat = new THREE.MeshStandardMaterial({ color: 0x636e72, roughness: 0.7 });
            
            // Внешние границы (невидимые или видимые)
            const borders = [
                {x: 0, z: -50, w: 100, d: 2}, {x: 0, z: 50, w: 100, d: 2},
                {x: -50, z: 0, w: 2, d: 100}, {x: 50, z: 0, w: 2, d: 100}
            ];
            
            // Внутренние укрытия (Крест в центре и блоки по углам)
            const blocks = [
                {x: 0, z: 0, w: 10, d: 10, h: 6}, // Центр
                {x: 20, z: 20, w: 8, d: 2, h: 4}, {x: 20, z: 20, w: 2, d: 8, h: 4},
                {x: -20, z: -20, w: 8, d: 2, h: 4},{x: -20, z: -20, w: 2, d: 8, h: 4},
                {x: 20, z: -20, w: 6, d: 6, h: 3}, {x: -20, z: 20, w: 6, d: 6, h: 3}
            ];

            const allObstacles = borders.concat(blocks);

            allObstacles.forEach(obs => {
                const h = obs.h || 10; // Высота стен по умолчанию 10
                const geo = new THREE.BoxGeometry(obs.w, h, obs.d);
                const mesh = new THREE.Mesh(geo, wallMat);
                mesh.position.set(obs.x, h/2, obs.z);
                mesh.castShadow = true;
                mesh.receiveShadow = true;
                mapGroup.add(mesh);
                collidableObjects.push(mesh);
            });
        }

        function createWeapon() {
            const gunGroup = new THREE.Group();
            
            // Модель пушки
            const barrelMat = new THREE.MeshStandardMaterial({ color: 0x111111, metalness: 0.8 });
            const barrel = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.1, 0.7), barrelMat);
            barrel.position.set(0, 0, -0.2);
            
            // Прицел
            const sight = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.05, 0.02), new THREE.MeshBasicMaterial({color: 0x00ff88}));
            sight.position.set(0, 0.07, -0.5);

            gunGroup.add(barrel);
            gunGroup.add(sight);
            
            gunGroup.position.set(0.25, -0.2, -0.4);
            weapon = gunGroup;
            camera.add(weapon);
            scene.add(camera);
        }

        // --- ЛОГИКА ЧАТА ---
        function openChat() {
            chatActive = true;
            document.exitPointerLock();
            keys = {w:0, a:0, s:0, d:0}; // Сбрасываем движение
            document.getElementById("chat_input_wrapper").style.display = "block";
            const inp = document.getElementById("chat_input");
            inp.focus();
            inp.value = "";
        }

        function closeChat() {
            chatActive = false;
            document.getElementById("chat_input_wrapper").style.display = "none";
            document.body.requestPointerLock();
        }

        function sendChat() {
            const text = document.getElementById("chat_input").value.trim();
            if(text && ws) {
                ws.send(JSON.stringify({ type: "chat", text: text }));
            }
            closeChat();
        }

        function addChatLine(sender, text) {
            const log = document.getElementById("chat_log");
            const div = document.createElement("div");
            div.className = "chat-msg";
            div.innerHTML = `<span class="chat-sender">${sender}:</span> ${text}`;
            log.appendChild(div);
            log.scrollTop = log.scrollHeight;
        }

        let yaw = 0, pitch = 0;
        function onMouseMove(e) {
            if (document.pointerLockElement === document.body && !chatActive) {
                yaw -= e.movementX * 0.002;
                pitch -= e.movementY * 0.002;
                pitch = Math.max(-Math.PI/2.1, Math.min(Math.PI/2.1, pitch));
                camera.rotation.set(pitch, yaw, 0, 'YXZ');
            }
        }

        // --- ЛОГИКА СТРЕЛЬБЫ И ПУЛЬ ---
        function shoot() {
            if(isShooting) return;
            isShooting = true;
            
            // Анимация отдачи
            weapon.rotation.x = 0.1;
            setTimeout(() => { weapon.rotation.x = 0; }, 50);

            // Создаем физическую пулю
            const bulletGeo = new THREE.SphereGeometry(0.1, 4, 4);
            const bulletMat = new THREE.MeshBasicMaterial({ color: 0xffff00 });
            const bullet = new THREE.Mesh(bulletGeo, bulletMat);
            
            // Начальная позиция - конец ствола
            const startPos = new THREE.Vector3(0, 0, -1).applyMatrix4(weapon.matrixWorld);
            bullet.position.copy(startPos);
            
            // Направление полета (из центра камеры)
            const direction = new THREE.Vector3();
            camera.getWorldDirection(direction);
            
            scene.add(bullet);
            bullets.push({ mesh: bullet, dir: direction, distance: 0 });

            setTimeout(() => { isShooting = false; }, 120); // Скорострельность
        }

        function updateBullets() {
            for(let i = bullets.length - 1; i >= 0; i--) {
                let b = bullets[i];
                let moveDist = bulletSpeed;
                
                // Raycast для проверки попадания на текущем шаге
                const raycaster = new THREE.Raycaster(b.mesh.position, b.dir);
                
                // Собираем цели: стены + враги
                const targets = [...collidableObjects];
                for(let id in players) targets.push(players[id].group);

                const intersects = raycaster.intersectObjects(targets, true);
                
                let hitSomething = false;

                if(intersects.length > 0 && intersects[0].distance <= moveDist) {
                    hitSomething = true;
                    let hitObj = intersects[0].object;
                    
                    // Проверяем, попали ли во врага
                    while(hitObj.parent && hitObj.parent.type !== "Scene") {
                        if(hitObj.userData.id) break;
                        hitObj = hitObj.parent;
                    }
                    
                    if(hitObj.userData.id && ws) {
                        ws.send(JSON.stringify({ type: "hit", target: hitObj.userData.id }));
                    }
                }

                if(hitSomething || b.distance > 150) {
                    // Уничтожаем пулю
                    scene.remove(b.mesh);
                    bullets.splice(i, 1);
                } else {
                    // Двигаем пулю
                    b.mesh.position.addScaledVector(b.dir, moveDist);
                    b.distance += moveDist;
                }
            }
        }

        // --- СОЗДАНИЕ ТЕКСТА НАД ГОЛОВОЙ (SPRITE) ---
        function makeTextSprite(message) {
            const canvas = document.createElement('canvas');
            canvas.width = 256; canvas.height = 64;
            const ctx = canvas.getContext('2d');
            
            ctx.fillStyle = "rgba(0,0,0,0.5)";
            ctx.roundRect(0, 0, 256, 64, 10);
            ctx.fill();
            
            ctx.font = "bold 32px sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillStyle = "white";
            ctx.fillText(message, 128, 32);
            
            const texture = new THREE.CanvasTexture(canvas);
            const spriteMat = new THREE.SpriteMaterial({ map: texture, depthTest: false });
            const sprite = new THREE.Sprite(spriteMat);
            sprite.scale.set(2, 0.5, 1);
            return sprite;
        }

        function updatePlayerLabel(id) {
            if(!players[id]) return;
            const p = players[id];
            const text = `${p.name} [${p.hp} HP]`;
            
            if(p.labelSprite) p.group.remove(p.labelSprite);
            
            p.labelSprite = makeTextSprite(text);
            p.labelSprite.position.y = 2.8;
            p.group.add(p.labelSprite);
        }

        // --- СЕТЬ И ИГРОКИ ---
        function initNetwork() {
            const proto = location.protocol === "https:" ? "wss://" : "ws://";
            const randomId = Math.floor(Math.random() * 100000);
            ws = new WebSocket(proto + location.host + "/ws/player_" + randomId);

            ws.onopen = () => {
                ws.send(JSON.stringify({ type: "join", name: myName }));
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);

                if (data.type === "init") {
                    myId = data.id;
                    updateEnvironment(data.landscape, data.round);
                    
                    camera.position.x = data.x;
                    camera.position.z = data.z;

                    for (let id in data.players) {
                        if (id !== myId) createEnemy(id, data.players[id]);
                    }
                    addChatLine("Система", "Добро пожаловать на Арену!");
                } 
                else if (data.type === "new_player") {
                    if (data.id !== myId) {
                        createEnemy(data.id, data.info);
                        addChatLine("Система", `${data.info.name} присоединился к игре.`);
                    }
                }
                else if (data.type === "new_round") {
                    updateEnvironment(data.landscape, data.round);
                    addChatLine("Система", `Начался раунд ${data.round}! Здоровье восстановлено.`);
                    // Обновляем HP визуально всем
                    for(let id in players) { players[id].hp = 100; updatePlayerLabel(id); }
                    updateHp(100);
                }
                else if (data.type === "update" && data.id !== myId && players[data.id]) {
                    players[data.id].group.position.x = data.x;
                    players[data.id].group.position.z = data.z;
                    players[data.id].group.rotation.y = data.ry;
                }
                else if (data.type === "hp_update") {
                    if(data.id === myId) {
                        updateHp(data.hp);
                        flashDamage();
                    } else if(players[data.id]) {
                        players[data.id].hp = data.hp;
                        updatePlayerLabel(data.id);
                    }
                }
                else if (data.type === "respawn") {
                    if(data.id === myId) {
                        camera.position.x = data.x;
                        camera.position.z = data.z;
                        updateHp(100);
                        addChatLine("Система", "Вас убили. Возрождение...");
                        document.body.style.background = "red";
                        setTimeout(() => document.body.style.background = "", 150);
                    } else if (data.killer === myId) {
                        document.getElementById("crosshair").style.background = "red";
                        setTimeout(() => document.getElementById("crosshair").style.background = "#00ff88", 200);
                    }
                    
                    if(data.score_update && data.score_update.id === myId) {
                        myScore = data.score_update.score;
                        document.getElementById("score_info").innerText = "Фраги: " + myScore;
                    }

                    if(players[data.id]) {
                        players[data.id].group.position.set(data.x, 0, data.z);
                        players[data.id].hp = 100;
                        updatePlayerLabel(data.id);
                    }
                }
                else if (data.type === "chat_msg") {
                    addChatLine(data.sender, data.text);
                }
                else if (data.type === "leave" && players[data.id]) {
                    addChatLine("Система", `${players[data.id].name} покинул игру.`);
                    scene.remove(players[data.id].group);
                    delete players[data.id];
                }
            };
        }

        function updateEnvironment(land, round) {
            ground.material.color.set(land.ground);
            scene.fog.color.set(land.fog);
            scene.background = new THREE.Color(land.fog);
            document.getElementById("map_name").innerText = land.name;
            document.getElementById("round_info").innerText = "Раунд: " + round;
        }

        function createEnemy(id, info) {
            const group = new THREE.Group();
            group.userData.id = id;

            // Тело
            const bodyMat = new THREE.MeshStandardMaterial({ color: info.color });
            const body = new THREE.Mesh(new THREE.CylinderGeometry(0.4, 0.4, 1.4, 12), bodyMat);
            body.position.y = 0.7;
            body.castShadow = true;
            body.userData.id = id;

            // Голова
            const head = new THREE.Mesh(new THREE.SphereGeometry(0.35, 16, 16), new THREE.MeshStandardMaterial({ color: 0xffccaa }));
            head.position.y = 1.7;
            head.castShadow = true;
            head.userData.id = id;

            // Очки (чтобы видеть где перед)
            const visor = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.15, 0.1), new THREE.MeshBasicMaterial({color: 0x111111}));
            visor.position.set(0, 1.7, -0.3);
            visor.userData.id = id;

            group.add(body); group.add(head); group.add(visor);
            group.position.set(info.x, 0, info.z);
            scene.add(group);
            
            players[id] = { group: group, name: info.name, hp: info.hp || 100 };
            updatePlayerLabel(id);
        }

        function updateHp(hp) {
            myHp = hp;
            const bar = document.getElementById("hp_bar");
            bar.style.width = hp + "%";
            if(hp > 50) bar.style.background = "#00ff88";
            else if(hp > 20) bar.style.background = "#f1c40f";
            else bar.style.background = "#e74c3c";
        }

        function flashDamage() {
            const overlay = document.getElementById("damage_overlay");
            overlay.style.opacity = "1";
            setTimeout(() => { overlay.style.opacity = "0"; }, 150);
        }

        // --- ПРОВЕРКА СТОЛКНОВЕНИЙ СО СТЕНАМИ ---
        function checkCollision(nextPos) {
            // Упрощенная проверка: пускаем луч от центра игрока в сторону движения
            const dir = new THREE.Vector3().subVectors(nextPos, camera.position);
            const dist = dir.length();
            if(dist === 0) return false;
            dir.normalize();

            // Поднимаем точку проверки немного над землей
            const startPos = camera.position.clone();
            startPos.y = 0.5; 

            const raycaster = new THREE.Raycaster(startPos, dir, 0, dist + playerRadius);
            const intersects = raycaster.intersectObjects(collidableObjects);
            
            return intersects.length > 0;
        }

        function animate() {
            requestAnimationFrame(animate);

            if(scene && camera) {
                // Обновление положения спрайтов (чтобы смотрели на камерu)
                for(let id in players) {
                    if(players[id].labelSprite) {
                        players[id].labelSprite.lookAt(camera.position);
                    }
                }

                updateBullets();

                // Движение игрока
                const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
                forward.y = 0; forward.normalize();
                const side = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion);
                side.y = 0; side.normalize();

                let moved = false;
                const nextPos = camera.position.clone();

                if (keys.w) { nextPos.addScaledVector(forward, moveSpeed); moved = true; }
                if (keys.s) { nextPos.addScaledVector(forward, -moveSpeed); moved = true; }
                if (keys.a) { nextPos.addScaledVector(side, -moveSpeed); moved = true; }
                if (keys.d) { nextPos.addScaledVector(side, moveSpeed); moved = true; }

                if (moved) {
                    // Проверяем столкновение перед перемещением
                    if(!checkCollision(nextPos)) {
                        camera.position.copy(nextPos);
                        
                        // Эффект шагов
                        weapon.position.y = -0.2 + Math.sin(Date.now() * 0.015) * 0.015;
                    }
                } else {
                    weapon.position.y = -0.2;
                }

                // Отправка координат на сервер
                if (ws && ws.readyState === WebSocket.OPEN && myId && moved) {
                    ws.send(JSON.stringify({
                        type: "move",
                        x: camera.position.x,
                        z: camera.position.z,
                        ry: yaw 
                    }));
                }

                renderer.render(scene, camera);
            }
        }
    </script>
</body>
</html>
"""

@app.get("/")
async def get():
    return HTMLResponse(html_content)
