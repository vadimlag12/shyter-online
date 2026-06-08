import asyncio
import json
import random
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

# --- СЕРВЕРНАЯ ЛОГИКА ---

class GameServer:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.players = {}
        self.current_round = 1
        self.landscapes = [
            {"ground": "#0d0e15", "neon": "#00ffcc", "name": "НЕОНОВЫЙ ГОРОД"},
            {"ground": "#0f0813", "neon": "#ff007f", "name": "КИБЕР-ПУСТОШЬ"},
            {"ground": "#051105", "neon": "#39ff14", "name": "МАТРИЦА"}
        ]
        self.current_landscape = self.landscapes[0]

    async def connect(self, websocket: WebSocket, player_id: str):
        await websocket.accept()
        self.active_connections[player_id] = websocket
        x, z = random.uniform(-20, 20), random.uniform(-20, 20)
        self.players[player_id] = {
            "name": "Anonym", "x": x, "z": z, "ry": 0,
            "color": self.current_landscape["neon"],
            "hp": 100, "score": 0
        }

    def disconnect(self, player_id: str):
        if player_id in self.active_connections: del self.active_connections[player_id]
        if player_id in self.players: del self.players[player_id]

    async def broadcast(self, data: dict):
        message = json.dumps(data)
        for connection in list(self.active_connections.values()):
            try: await connection.send_text(message)
            except: pass

server = GameServer()

async def round_manager():
    while True:
        await asyncio.sleep(60)
        server.current_round += 1
        server.current_landscape = server.landscapes[(server.current_round - 1) % len(server.landscapes)]
        for pid in server.players:
            server.players[pid]["hp"] = 100
            server.players[pid]["color"] = server.current_landscape["neon"]
        await server.broadcast({
            "type": "new_round", "round": server.current_round, "landscape": server.current_landscape
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
                server.players[player_id]["name"] = msg.get("name", "Anonym")[:12]
                await websocket.send_text(json.dumps({
                    "type": "init", "id": player_id, "landscape": server.current_landscape,
                    "round": server.current_round, "players": server.players,
                    "x": server.players[player_id]["x"], "z": server.players[player_id]["z"]
                }))
                await server.broadcast({"type": "new_player", "id": player_id, "info": server.players[player_id]})
            elif msg["type"] == "move":
                server.players[player_id]["x"] = msg["x"]
                server.players[player_id]["z"] = msg["z"]
                server.players[player_id]["ry"] = msg["ry"]
                await server.broadcast({"type": "update", "id": player_id, "x": msg["x"], "z": msg["z"], "ry": msg["ry"]})
            elif msg["type"] == "hit":
                tid = msg["target"]
                if tid in server.players:
                    server.players[tid]["hp"] -= 20
                    if server.players[tid]["hp"] <= 0:
                        server.players[player_id]["score"] += 1
                        server.players[tid]["hp"] = 100
                        nx, nz = random.uniform(-20, 20), random.uniform(-20, 20)
                        server.players[tid]["x"], server.players[tid]["z"] = nx, nz
                        await server.broadcast({
                            "type": "respawn", "id": tid, "x": nx, "z": nz, "killer": player_id,
                            "score_update": {"id": player_id, "score": server.players[player_id]["score"]}
                        })
                    await server.broadcast({"type": "hp_update", "id": tid, "hp": server.players[tid]["hp"]})
            elif msg["type"] == "chat":
                await server.broadcast({"type": "chat_msg", "sender": server.players[player_id]["name"], "text": msg["text"]})
    except WebSocketDisconnect:
        server.disconnect(player_id)
        await server.broadcast({"type": "leave", "id": player_id})

# --- ИНТЕРФЕЙС И 3D ГРАФИКА ДЛЯ БРАУЗЕРА ---

html_content = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>CYBERARENA 2026</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; font-family: 'Courier New', monospace; user-select: none; background: #050508; color: #fff; }
        #login_screen { position: fixed; inset: 0; background: radial-gradient(circle, #1a1025 0%, #050508 100%); display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 100; border: 4px solid #00ffcc; box-sizing: border-box; }
        #login_screen h1 { color: #00ffcc; font-size: 3.5rem; text-shadow: 0 0 20px #00ffcc; margin-bottom: 20px; letter-spacing: 5px; text-align: center;}
        #nickname_input { padding: 15px; font-size: 20px; width: 280px; text-align: center; border: 2px solid #ff007f; background: #111; color: #00ffcc; border-radius: 0; outline: none; box-shadow: 0 0 10px #ff007f; font-family: inherit;}
        #play_btn { margin-top: 25px; padding: 15px 50px; font-size: 22px; cursor: pointer; background: #ff007f; color: white; border: none; font-weight: bold; box-shadow: 0 0 15px #ff007f; font-family: inherit; }
        #play_btn:hover { background: #00ffcc; color: black; box-shadow: 0 0 25px #00ffcc; }
        
        #ui { position: absolute; top: 15px; left: 15px; background: rgba(5,5,10,0.85); padding: 15px; border: 1px solid #00ffcc; box-shadow: 0 0 10px rgba(0,255,204,0.3); display: none; pointer-events: none; }
        #crosshair { position: absolute; top: 50%; left: 50%; width: 6px; height: 6px; border: 2px solid #00ffcc; border-radius: 50%; transform: translate(-50%, -50%); pointer-events: none; z-index: 10; display:none; }
        #hp_bar_container { position: absolute; bottom: 25px; left: 25px; width: 250px; height: 16px; background: rgba(0,0,0,0.5); border: 2px solid #ff007f; display: none; box-shadow: 0 0 10px #ff007f; }
        #hp_bar { width: 100%; height: 100%; background: #ff007f; transition: width 0.1s; }
        #damage_overlay { position: absolute; inset: 0; background: rgba(255,0,50,0.4); pointer-events: none; opacity: 0; transition: opacity 0.1s; z-index: 5; }
        
        /* Чат */
        #chat_container { position: absolute; bottom: 70px; left: 25px; width: 300px; display: none; flex-direction: column; pointer-events: none; }
        #chat_log { height: 120px; overflow: hidden; font-size: 13px; color: #00ffcc; display: flex; flex-direction: column; justify-content: flex-end;}
        #chat_input { width: 100%; padding: 8px; background: #000; color: #fff; border: 1px solid #ff007f; outline: none; pointer-events: auto; font-family: inherit;}
        
        /* МОБИЛЬНЫЙ ИНТЕРФЕЙС (Тачпады) */
        .joystick { position: absolute; bottom: 30px; width: 120px; height: 120px; background: rgba(255,255,255,0.05); border: 2px dashed rgba(0,255,204,0.4); border-radius: 50%; display: none; touch-action: none; z-index: 20;}
        #stick_move { left: 40px; }
        #stick_look { right: 40px; }
        .stick_knob { position: absolute; top: 45px; left: 45px; width: 30px; height: 30px; background: #00ffcc; border-radius: 50%; box-shadow: 0 0 10px #00ffcc; }
        #mobile_fire { position: absolute; bottom: 170px; right: 55px; width: 70px; height: 70px; background: rgba(255,0,127,0.3); border: 3px solid #ff007f; border-radius: 50%; display: none; justify-content: center; align-items: center; font-weight: bold; font-size: 14px; touch-action: none; z-index: 20; box-shadow: 0 0 10px #ff007f;}
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
    <div id="login_screen">
        <h1>CYBER_ARENA</h1>
        <input type="text" id="nickname_input" placeholder="NICKNAME" maxlength="10">
        <button id="play_btn">CONNECT</button>
    </div>

    <div id="ui">
        <div id="map_name" style="color: #ff007f; font-weight: bold; font-size: 18px;">LOADING...</div>
        <div id="round_info">ROUND: 1</div>
        <div id="score_info">KILLS: 0</div>
    </div>
    
    <div id="chat_container">
        <div id="chat_log"></div>
        <input type="text" id="chat_input" placeholder="[T] TO CHAT..." maxlength="50">
    </div>

    <div id="hp_bar_container"><div id="hp_bar"></div></div>
    <div id="crosshair"></div>
    <div id="damage_overlay"></div>

    <div id="stick_move" class="joystick"><div class="stick_knob"></div></div>
    <div id="stick_look" class="joystick"><div class="stick_knob"></div></div>
    <div id="mobile_fire">FIRE</div>

    <script>
        let scene, camera, renderer, ground, grid;
        let players = {};
        let myId = null, myName = "Anonym", ws;
        let keys = { w:0, a:0, s:0, d:0 };
        let moveSpeed = 0.2, yaw = 0, pitch = 0;
        let myHp = 100, myScore = 0;
        let isMobile = false;

        let weapon, isShooting = false, bullets = [];
        let mapGroup = new THREE.Group(), collidableWalls = [];
        let targetsForBullets = []; // Фикс зависания: отдельный плоский массив hitbox-объектов
        let chatActive = false;

        // Мобильные переменные тачпада
        let moveTouchData = { active: false, startX: 0, startY: 0, curX: 0, curY: 0 };
        let lookTouchData = { active: false, startX: 0, startY: 0, curX: 0, curY: 0 };

        function checkDevice() {
            isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || (window.innerWidth < 800);
            if(isMobile) {
                document.getElementById("stick_move").style.display = "block";
                document.getElementById("stick_look").style.display = "block";
                document.getElementById("mobile_fire").style.display = "flex";
            }
        }

        function startGame() {
            let val = document.getElementById("nickname_input").value.trim();
            if(val) myName = val;
            checkDevice();
            
            document.getElementById("login_screen").style.display = "none";
            document.getElementById("ui").style.display = "block";
            document.getElementById("hp_bar_container").style.display = "block";
            document.getElementById("chat_container").style.display = "flex";
            if(!isMobile) document.getElementById("crosshair").style.display = "block";
            
            init3D();
            initNetwork();
            if(!isMobile) document.body.requestPointerLock();
        }

        document.getElementById("play_btn").addEventListener("click", startGame);

        function init3D() {
            scene = new THREE.Scene();
            camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
            
            renderer = new THREE.WebGLRenderer({ antialias: true });
            renderer.setSize(window.innerWidth, window.innerHeight);
            document.body.appendChild(renderer.domElement);

            // Пол в стиле Киберпанк (Темный металл + Неоновая Сетка)
            const groundGeo = new THREE.PlaneGeometry(120, 120);
            const groundMat = new THREE.MeshBasicMaterial({ color: 0x0d0e15 });
            ground = new THREE.Mesh(groundGeo, groundMat);
            ground.rotation.x = -Math.PI / 2;
            scene.add(ground);

            grid = new THREE.GridHelper(120, 60, 0xff007f, 0x221133);
            grid.position.y = 0.01;
            scene.add(grid);

            scene.add(mapGroup);
            createWeapon();
            camera.position.y = 1.6;

            // Настройка управления ПК
            if(!isMobile) {
                document.addEventListener('click', () => { 
                    if(!chatActive) {
                        if(document.pointerLockElement !== document.body) document.body.requestPointerLock();
                        else shoot();
                    }
                });
                document.addEventListener('mousemove', (e) => {
                    if (document.pointerLockElement === document.body && !chatActive) {
                        yaw -= e.movementX * 0.0025;
                        pitch -= e.movementY * 0.0025;
                        pitch = Math.max(-Math.PI/2.2, Math.min(Math.PI/2.2, pitch));
                        camera.rotation.set(pitch, yaw, 0, 'YXZ');
                    }
                });
                window.addEventListener('keydown', (e) => {
                    if(chatActive) {
                        if(e.key === "Enter") sendChat();
                        if(e.key === "Escape") closeChat();
                        return;
                    }
                    if(e.key.toLowerCase() === 't') { e.preventDefault(); openChat(); return; }
                    if(e.key.toLowerCase() in keys) keys[e.key.toLowerCase()] = 1;
                });
                window.addEventListener('keyup', (e) => { if(e.key.toLowerCase() in keys) keys[e.key.toLowerCase()] = 0; });
            } else {
                setupMobileControls();
            }

            window.addEventListener('resize', () => {
                camera.aspect = window.innerWidth / window.innerHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(window.innerWidth, window.innerHeight);
            });

            animate();
        }

        function generateArena(theme) {
            while(mapGroup.children.length > 0){ mapGroup.remove(mapGroup.children[0]); }
            collidableWalls = [];
            targetsForBullets = []; // Сброс списка целей пуль

            const neonColor = new THREE.Color(theme.neon);
            grid.material.color.set(neonColor);
            scene.fog = new THREE.FogExp2(theme.ground, 0.025);
            renderer.setClearColor(theme.ground);

            // Внешний забор
            const wallMat = new THREE.MeshBasicMaterial({ color: 0x11111d });
            const borders = [
                {x:0, z:-50, w:100, d:2}, {x:0, z:50, w:100, d:2},
                {x:-50, z:0, w:2, d:100}, {x:50, z:0, w:2, d:100}
            ];
            
            // Застройка неоновыми башнями
            let seed = round_info.innerText.charCodeAt(0) || 5;
            for(let i=0; i<18; i++) {
                let size = 3 + (i % 3) * 2;
                borders.push({
                    x: Math.sin(i * seed) * 35,
                    z: Math.cos(i * 12) * 35,
                    w: size, d: size, h: 12, isTower: true
                });
            }

            borders.forEach(b => {
                const h = b.h || 6;
                const mesh = new THREE.Mesh(new THREE.BoxGeometry(b.w, h, b.d), wallMat);
                mesh.position.set(b.x, h/2, b.z);
                mapGroup.add(mesh);
                collidableWalls.push(mesh);
                targetsForBullets.push(mesh); // Стены — препятствия для пуль

                if(b.isTower) {
                    // Контурная неоновая подсветка башен для красоты
                    const edges = new THREE.EdgesGeometry(mesh.geometry);
                    const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: neonColor }));
                    line.position.copy(mesh.position);
                    mapGroup.add(line);
                }
            });
        }

        function createWeapon() {
            weapon = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.08, 0.5), new THREE.MeshBasicMaterial({ color: 0x222233 }));
            weapon.position.set(0.2, -0.2, -0.35);
            camera.add(weapon);
            scene.add(camera);
        }

        // --- МОБИЛЬНЫЕ ДЖОЙСТИКИ (ФИЗИКА ТАЧА) ---
        function setupMobileControls() {
            const mMove = document.getElementById("stick_move");
            const mLook = document.getElementById("stick_look");
            const knobM = mMove.querySelector(".stick_knob");
            const knobL = mLook.querySelector(".stick_knob");

            mMove.addEventListener("touchstart", (e) => {
                moveTouchData.active = true;
                moveTouchData.startX = e.touches[0].clientX;
                moveTouchData.startY = e.touches[0].clientY;
            });
            mMove.addEventListener("touchmove", (e) => {
                if(!moveTouchData.active) return;
                let dx = e.touches[0].clientX - moveTouchData.startX;
                let dy = e.touches[0].clientY - moveTouchData.startY;
                let len = Math.min(40, Math.sqrt(dx*dx + dy*dy));
                let angle = Math.atan2(dy, dx);
                moveTouchData.curX = Math.cos(angle) * (len / 40);
                moveTouchData.curY = Math.sin(angle) * (len / 40);
                knobM.style.transform = `translate(${Math.cos(angle)*len}px, ${Math.sin(angle)*len}px)`;
            });
            mMove.addEventListener("touchend", () => {
                moveTouchData.active = false;
                moveTouchData.curX = 0; moveTouchData.curY = 0;
                knobM.style.transform = "none";
            });

            mLook.addEventListener("touchstart", (e) => {
                lookTouchData.active = true;
                lookTouchData.startX = e.touches[0].clientX;
                lookTouchData.startY = e.touches[0].clientY;
            });
            mLook.addEventListener("touchmove", (e) => {
                if(!lookTouchData.active) return;
                let dx = e.touches[0].clientX - lookTouchData.startX;
                let dy = e.touches[0].clientY - lookTouchData.startY;
                yaw -= dx * 0.001;
                pitch -= dy * 0.001;
                pitch = Math.max(-Math.PI/2.2, Math.min(Math.PI/2.2, pitch));
                camera.rotation.set(pitch, yaw, 0, 'YXZ');
                lookTouchData.startX = e.touches[0].clientX;
                lookTouchData.startY = e.touches[0].clientY;
            });
            mLook.addEventListener("touchend", () => { lookTouchData.active = false; });
            document.getElementById("mobile_fire").addEventListener("touchstart", (e) => { e.preventDefault(); shoot(); });
        }

        // --- ОПТИМИЗИРОВАННАЯ СТРЕЛЬБА БЕЗ ЗАВИСАНИЙ ---
        function shoot() {
            if(isShooting) return;
            isShooting = true;
            weapon.position.z = -0.25; setTimeout(() => weapon.position.z = -0.35, 60);

            const bMesh = new THREE.Mesh(new THREE.SphereGeometry(0.12, 4, 4), new THREE.MeshBasicMaterial({ color: 0xffffff }));
            const startPos = new THREE.Vector3(0,0,-0.5).applyMatrix4(weapon.matrixWorld);
            bMesh.position.copy(startPos);
            
            const dir = new THREE.Vector3();
            camera.getWorldDirection(dir);
            
            scene.add(bMesh);
            bullets.push({ mesh: bMesh, dir: dir, life: 0 });
            setTimeout(() => { isShooting = false; }, 180);
        }

        function updateBullets() {
            for(let i = bullets.length - 1; i >= 0; i--) {
                let b = bullets[i];
                let speed = 1.8;
                b.mesh.position.addScaledVector(b.dir, speed);
                b.life += 1;

                // Луч летит ровно по траектории шага пули
                const ray = new THREE.Raycaster(b.mesh.position, b.dir, 0, speed + 0.1);
                const hits = ray.intersectObjects(targetsForBullets, false); // false = без рекурсии, моментально!

                let hitDel = false;
                if(hits.length > 0) {
                    hitDel = true;
                    let targetObj = hits[0].object;
                    if(targetObj.userData.playerId && ws) {
                        ws.send(JSON.stringify({ type: "hit", target: targetObj.userData.playerId }));
                    }
                }

                if(hitDel || b.life > 40) {
                    scene.remove(b.mesh);
                    bullets.splice(i, 1);
                }
            }
        }

        // --- ТЕКСТ И ХП БАРЫ НАД ИГРОКАМИ ---
        function makePlayerLabel(name, hp, colorHex) {
            const canvas = document.createElement('canvas');
            canvas.width = 256; canvas.height = 80;
            const ctx = canvas.getContext('2d');
            
            // Ник
            ctx.font = "bold 26px monospace";
            ctx.fillStyle = "#ffffff";
            ctx.textAlign = "center";
            ctx.fillText(name, 128, 30);
            
            // Рамка здоровья
            ctx.fillStyle = "#222233";
            ctx.fillRect(28, 45, 200, 16);
            
            // Заполнение здоровья
            ctx.fillStyle = colorHex;
            ctx.fillRect(28, 45, Math.max(0, hp) * 2, 16);
            
            const texture = new THREE.CanvasTexture(canvas);
            const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, depthTest: true }));
            sprite.scale.set(2.2, 0.7, 1);
            return sprite;
        }

        function refreshLabel(id) {
            let p = players[id];
            if(!p) return;
            if(p.label) p.group.remove(p.label);
            p.label = makePlayerLabel(p.name, p.hp, p.color);
            p.label.position.y = 2.4;
            p.group.add(p.label);
        }

        // --- СЕТЕВАЯ СИНХРОНИЗАЦИЯ ---
        function initNetwork() {
            const proto = location.protocol === "https:" ? "wss://" : "ws://";
            ws = new WebSocket(proto + location.host + "/ws/p_" + Math.floor(Math.random()*100000));
            ws.onopen = () => ws.send(JSON.stringify({ type: "join", name: myName }));
            ws.onmessage = (e) => {
                const data = JSON.parse(e.data);
                if (data.type === "init") {
                    myId = data.id;
                    document.getElementById("score_info").innerText = "KILLS: " + myScore;
                    document.getElementById("round_info").innerText = "ROUND: " + data.round;
                    generateArena(data.landscape);
                    camera.position.set(data.x, 1.6, data.z);
                    for (let id in data.players) if(id !== myId) createEnemy(id, data.players[id]);
                } 
                else if (data.type === "new_player" && data.id !== myId) {
                    createEnemy(data.id, data.info);
                }
                else if (data.type === "new_round") {
                    document.getElementById("round_info").innerText = "ROUND: " + data.round;
                    generateArena(data.landscape);
                    updateHp(100);
                    for(let id in players) { players[id].hp = 100; refreshLabel(id); }
                }
                else if (data.type === "update" && data.id !== myId && players[data.id]) {
                    players[data.id].group.position.set(data.x, 0, data.z);
                    players[data.id].group.rotation.y = data.ry;
                }
                else if (data.type === "hp_update") {
                    if(data.id === myId) { updateHp(data.hp); flashDamage(); }
                    else if(players[data.id]) { players[data.id].hp = data.hp; refreshLabel(data.id); }
                }
                else if (data.type === "respawn") {
                    if(data.id === myId) {
                        camera.position.set(data.x, 1.6, data.z);
                        updateHp(100);
                    }
                    if(data.score_update && data.score_update.id === myId) {
                        myScore = data.score_update.score;
                        document.getElementById("score_info").innerText = "KILLS: " + myScore;
                    }
                    if(players[data.id]) {
                        players[data.id].group.position.set(data.x, 0, data.z);
                        players[data.id].hp = 100;
                        refreshLabel(data.id);
                    }
                }
                else if (data.type === "chat_msg") {
                    const log = document.getElementById("chat_log");
                    log.innerHTML += `<div><b>${data.sender}:</b> ${data.text}</div>`;
                    setTimeout(() => { if(log.children.length > 5) log.removeChild(log.children[0]); }, 6000);
                }
                else if (data.type === "leave" && players[data.id]) {
                    // Удаляем хитбокс из целей пуль, чтобы не стрелять в пустоту
                    targetsForBullets = targetsForBullets.filter(t => t !== players[data.id].hitbox);
                    scene.remove(players[data.id].group);
                    delete players[data.id];
                }
            };
        }

        function createEnemy(id, info) {
            const group = new THREE.Group();
            
            // Визуальный неоновый аватар
            const body = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.35, 1.4, 8), new THREE.MeshBasicMaterial({ color: 0x111122 }));
            body.position.y = 0.7;
            const edges = new THREE.EdgesGeometry(body.geometry);
            const glow = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: info.color }));
            glow.position.y = 0.7;
            
            // Фикс зависания: Четкий, выделенный хитбокс для лучей пуль
            const hitbox = new THREE.Mesh(new THREE.BoxGeometry(0.8, 1.8, 0.8), new THREE.MeshBasicMaterial({ visible: false }));
            hitbox.position.y = 0.9;
            hitbox.userData.playerId = id; // Привязываем ID игрока прямо к мешу

            group.add(body); group.add(glow); group.add(hitbox);
            group.position.set(info.x, 0, info.z);
            scene.add(group);

            players[id] = { group: group, hitbox: hitbox, name: info.name, hp: info.hp, color: info.color };
            targetsForBullets.push(hitbox); // Добавляем хитбокс в обработчик попаданий
            refreshLabel(id);
        }

        // --- ФИЗИКА КОЛЛИЗИЙ ИГРОКА (СТЕНЫ) ---
        function isColliding(targetPos) {
            for(let i=0; i<collidableWalls.length; i++) {
                let wall = collidableWalls[i];
                let bbox = new THREE.Box3().setFromObject(wall);
                // Простая проверка границ сферы игрока
                let playerBox = new THREE.Box3(
                    new THREE.Vector3(targetPos.x - 0.5, 0, targetPos.z - 0.5),
                    new THREE.Vector3(targetPos.x + 0.5, 2, targetPos.z + 0.5)
                );
                if(bbox.intersectsBox(playerBox)) return true;
            }
            return false;
        }

        function openChat() { chatActive = true; document.exitPointerLock(); document.getElementById("chat_input").focus(); }
        function closeChat() { chatActive = false; document.getElementById("chat_input").blur(); document.body.requestPointerLock(); }
        function sendChat() {
            let val = document.getElementById("chat_input").value.trim();
            if(val && ws) ws.send(JSON.stringify({ type: "chat", text: val }));
            document.getElementById("chat_input").value = "";
            closeChat();
        }

        function updateHp(hp) {
            myHp = hp;
            document.getElementById("hp_bar").style.width = hp + "%";
        }
        function flashDamage() {
            document.getElementById("damage_overlay").style.opacity = "1";
            setTimeout(() => document.getElementById("damage_overlay").style.opacity = "0", 100);
        }

        // --- ГЛАВНЫЙ ИГРОВОЙ ЦИКЛ ---
        function animate() {
            requestAnimationFrame(animate);
            if(!scene || !camera) return;

            updateBullets();

            // Поворот ников ко мне
            for(let id in players) {
                if(players[id].label) players[id].label.lookAt(camera.position);
            }

            // Направление взгляда
            const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion); forward.y = 0; forward.normalize();
            const side = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion); side.y = 0; side.normalize();
            
            let nextPos = camera.position.clone();
            let moved = false;

            if(!isMobile) {
                // Движение ПК
                if (keys.w) { nextPos.addScaledVector(forward, moveSpeed); moved = true; }
                if (keys.s) { nextPos.addScaledVector(forward, -moveSpeed); moved = true; }
                if (keys.a) { nextPos.addScaledVector(side, -moveSpeed); moved = true; }
                if (keys.d) { nextPos.addScaledVector(side, moveSpeed); moved = true; }
            } else {
                // Движение Смартфон (Джойстик)
                if(moveTouchData.active) {
                    nextPos.addScaledVector(forward, -moveTouchData.curY * moveSpeed);
                    nextPos.addScaledVector(side, moveTouchData.curX * moveSpeed);
                    moved = true;
                }
            }

            if(moved && !isColliding(nextPos)) {
                camera.position.copy(nextPos);
                weapon.position.y = -0.2 + Math.sin(Date.now() * 0.015) * 0.01;
            }

            // Отправка координат (постоянно или при движении/вращении)
            if (ws && ws.readyState === WebSocket.OPEN && myId) {
                ws.send(JSON.stringify({
                    type: "move", x: camera.position.x, z: camera.position.z, ry: yaw
                }));
            }

            renderer.render(scene, camera);
        }
    </script>
</body>
</html>
"""

@app.get("/")
async def get():
    return HTMLResponse(html_content)
