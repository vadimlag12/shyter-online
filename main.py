import asyncio
import json
import random
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

# --- СЕРВЕРНАЯ АРХИТЕКТУРА ---

class GameServer:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.players = {}
        self.current_round = 1
        self.landscapes = [
            {"ground": "#080911", "neon": "#00ffcc", "name": "КИБЕР-СЕКТОР А"},
            {"ground": "#0b0514", "neon": "#ff0055", "name": "НЕОНОВЫЕ ДОКИ"},
            {"ground": "#020d04", "neon": "#39ff14", "name": "ЯДЕРНАЯ ЗОНА"}
        ]
        self.current_landscape = self.landscapes[0]

    async def connect(self, websocket: WebSocket, player_id: str):
        await websocket.accept()
        self.active_connections[player_id] = websocket
        x, z = random.uniform(-25, 25), random.uniform(-25, 25)
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
        await asyncio.sleep(90)
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
                        nx, nz = random.uniform(-25, 25), random.uniform(-25, 25)
                        server.players[tid]["x"], server.players[tid]["z"] = nx, nz
                        await server.broadcast({
                            "type": "respawn", "id": tid, "x": nx, "z": nz, "killer": server.players[player_id]["name"],
                            "victim": server.players[tid]["name"],
                            "score_update": {"id": player_id, "score": server.players[player_id]["score"]}
                        })
                    await server.broadcast({"type": "hp_update", "id": tid, "hp": server.players[tid]["hp"]})
            elif msg["type"] == "chat":
                await server.broadcast({"type": "chat_msg", "sender": server.players[player_id]["name"], "text": msg["text"]})
    except WebSocketDisconnect:
        server.disconnect(player_id)
        await server.broadcast({"type": "leave", "id": player_id})

# --- КЛИЕНТСКИЙ ИНТЕРФЕЙС И ГРАФИКА ДВИЖКА ---

html_content = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>CYBERPUNK ARENA 3D</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; font-family: 'Segoe UI', Roboto, sans-serif; user-select: none; background: #030305; color: #fff; touch-action: none; }
        
        /* Главное меню */
        #login_screen { position: fixed; inset: 0; background: radial-gradient(circle at center, #150d22 0%, #030305 100%); display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 100; transition: opacity 0.5s; }
        #login_box { background: rgba(10, 10, 18, 0.85); border: 2px solid #00ffcc; padding: 40px; border-radius: 16px; text-align: center; box-shadow: 0 0 30px rgba(0, 255, 204, 0.2); max-width: 90%; width: 360px; }
        #login_screen h1 { color: #00ffcc; font-size: 2.5rem; font-weight: 900; letter-spacing: 4px; margin: 0 0 25px 0; text-shadow: 0 0 15px #00ffcc; }
        #nickname_input { width: 100%; padding: 14px; font-size: 18px; border: 1px solid #ff0055; background: #08080f; color: #00ffcc; text-align: center; border-radius: 8px; outline: none; box-shadow: 0 0 10px rgba(255,0,85,0.1); box-sizing: border-box; font-family: inherit; }
        #nickname_input:focus { border-color: #00ffcc; box-shadow: 0 0 15px rgba(0,255,204,0.3); }
        #play_btn { width: 100%; margin-top: 20px; padding: 14px; font-size: 18px; cursor: pointer; background: #ff0055; color: white; border: none; border-radius: 8px; font-weight: bold; text-transform: uppercase; letter-spacing: 2px; box-shadow: 0 0 15px #ff0055; transition: all 0.2s; }
        #play_btn:hover { background: #00ffcc; color: #000; box-shadow: 0 0 25px #00ffcc; transform: translateY(-2px); }
        
        /* Игровой интерфейс */
        #ui { position: absolute; top: 20px; left: 20px; background: rgba(5,5,10,0.75); padding: 15px 20px; border-radius: 10px; border-left: 5px solid #00ffcc; backdrop-filter: blur(5px); pointer-events: none; display: none; z-index: 10; }
        #map_name { color: #ff0055; font-weight: 800; font-size: 16px; letter-spacing: 1px; }
        #round_info, #score_info { font-size: 14px; margin-top: 4px; color: #ccc; font-family: monospace; }
        
        /* Прицел */
        #crosshair { position: absolute; top: 50%; left: 50%; width: 16px; height: 16px; transform: translate(-50%, -50%); pointer-events: none; z-index: 10; display:none; }
        #crosshair::before, #crosshair::after { content: ''; position: absolute; background: #00ffcc; }
        #crosshair::before { top: 7px; left: 0; width: 16px; height: 2px; }
        #crosshair::after { top: 0; left: 7px; width: 2px; height: 16px; }

        /* Индикаторы урона и ХП */
        #hp_bar_container { position: absolute; bottom: 30px; left: 50%; transform: translateX(-50%); width: 280px; height: 14px; background: rgba(0,0,0,0.6); border: 2px solid #ff0055; border-radius: 7px; overflow: hidden; display: none; box-shadow: 0 0 15px rgba(255,0,85,0.3); z-index: 10;}
        #hp_bar { width: 100%; height: 100%; background: linear-gradient(90deg, #ff0055, #ff5500); transition: width 0.1s; }
        #damage_overlay { position: absolute; inset: 0; background: rgba(255,0,55,0.35); pointer-events: none; opacity: 0; transition: opacity 0.1s; z-index: 5; }
        
        /* Чат */
        #chat_container { position: absolute; bottom: 70px; left: 20px; width: 280px; display: none; flex-direction: column; z-index: 10; }
        #chat_log { height: 110px; overflow: hidden; font-size: 13px; color: #00ffcc; display: flex; flex-direction: column; justify-content: flex-end; text-shadow: 1px 1px 2px #000; margin-bottom: 5px; pointer-events: none;}
        #chat_input { width: 100%; padding: 10px; background: rgba(0,0,0,0.8); color: #fff; border: 1px solid #ff0055; border-radius: 6px; outline: none; font-family: inherit; box-sizing: border-box;}
        #chat_input:focus { border-color: #00ffcc; }

        /* Бегущая строка убийств (Killfeed) */
        #killfeed { position: absolute; top: 20px; right: 20px; width: 240px; height: 150px; display: flex; flex-direction: column; gap: 5px; align-items: flex-end; pointer-events: none; font-family: monospace; font-size: 12px; z-index: 10; }
        .kill-item { background: rgba(255, 0, 85, 0.15); border-right: 3px solid #ff0055; padding: 6px 12px; border-radius: 4px 0 0 4px; animation: fadeInRight 0.2s both; }
        @keyframes fadeInRight { from { opacity: 0; transform: translateX(20px); } to { opacity: 1; transform: translateX(0); } }
        
        /* МОБИЛЬНЫЕ ТАЧ-ПАНЕЛИ */
        .joystick-zone { position: absolute; bottom: 0; top: 40%; width: 45%; z-index: 20; display: none; }
        #zone_move { left: 0; }
        #zone_look { right: 0; }
        .visual-joystick { position: absolute; width: 100px; height: 100px; background: rgba(255,255,255,0.03); border: 2px dashed rgba(0,255,204,0.3); border-radius: 50%; display: none; pointer-events: none; transform: translate(-50%, -50%); }
        .joystick-knob { position: absolute; width: 34px; height: 34px; background: #00ffcc; border-radius: 50%; top: 33px; left: 33px; box-shadow: 0 0 15px #00ffcc; }
        #mobile_fire_btn { position: absolute; bottom: 40px; right: 60px; width: 80px; height: 80px; background: rgba(255,0,85,0.25); border: 3px solid #ff0055; border-radius: 50%; display: none; justify-content: center; align-items: center; font-weight: 900; font-size: 15px; letter-spacing: 1px; z-index: 30; box-shadow: 0 0 15px rgba(255,0,85,0.4); }
        #mobile_fire_btn:active { background: #ff0055; transform: scale(0.95); }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
    <div id="login_screen">
        <div id="login_box">
            <h1>CYBER_ARENA</h1>
            <input type="text" id="nickname_input" placeholder="ENTER NICKNAME" value="Anonym" maxlength="10">
            <button id="play_btn">START GAME</button>
        </div>
    </div>

    <div id="ui">
        <div id="map_name">LOADING SECTOR...</div>
        <div id="round_info">ROUND: 1</div>
        <div id="score_info">KILLS: 0</div>
    </div>

    <div id="killfeed"></div>
    
    <div id="chat_container">
        <div id="chat_log"></div>
        <input type="text" id="chat_input" placeholder="Press T to talk..." autocomplete="off">
    </div>

    <div id="hp_bar_container"><div id="hp_bar"></div></div>
    <div id="crosshair"></div>
    <div id="damage_overlay"></div>

    <div id="zone_move" class="joystick-zone"></div>
    <div id="zone_look" class="joystick-zone"></div>
    <div id="v_joy_move" class="visual-joystick"><div class="joystick-knob"></div></div>
    <div id="v_joy_look" class="visual-joystick"><div class="joystick-knob"></div></div>
    <div id="mobile_fire_btn">FIRE</div>

    <script>
        let scene, camera, renderer, ground, gridFloor;
        let players = {}, myId = null, myName = "Anonym", ws;
        let keys = { w:0, a:0, s:0, d:0 };
        let moveSpeed = 0.18, yaw = 0, pitch = 0;
        let myHp = 100, myScore = 0, isMobile = false;

        let weapon, muzzleFlash, isShooting = false, bullets = [];
        let mapGroup = new THREE.Group(), collidableWalls = [], targetsForBullets = [];
        let chatActive = false;

        // Переменные для раздельного мобильного тача
        let touchMoveId = null, touchLookId = null;
        let moveData = { startX: 0, startY: 0, curX: 0, curY: 0 };
        let lookData = { startX: 0, startY: 0, lastX: 0, lastY: 0 };

        // Переменные оптимизации сети
        let lastSentPos = new THREE.Vector3();
        let lastSentYaw = 0;

        function checkDevice() {
            isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || (window.innerWidth < 900);
            if(isMobile) {
                document.getElementById("zone_move").style.display = "block";
                document.getElementById("zone_look").style.display = "block";
                document.getElementById("mobile_fire_btn").style.display = "flex";
            }
        }

        function startGame() {
            let val = document.getElementById("nickname_input").value.trim();
            if(val) myName = val;
            checkDevice();
            
            document.getElementById("login_screen").style.opacity = "0";
            setTimeout(() => document.getElementById("login_screen").style.display = "none", 500);
            
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
            
            renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
            renderer.setSize(window.innerWidth, window.innerHeight);
            renderer.toneMapping = THREE.ACESFilmicToneMapping;
            document.body.appendChild(renderer.domElement);

            // Пол
            ground = new THREE.Mesh(new THREE.PlaneGeometry(150, 150), new THREE.MeshBasicMaterial({ color: 0x05050a }));
            ground.rotation.x = -Math.PI / 2;
            scene.add(ground);

            gridFloor = new THREE.GridHelper(150, 50, 0xff0055, 0x111122);
            gridFloor.position.y = 0.01;
            scene.add(gridFloor);

            scene.add(mapGroup);
            createWeapon();
            camera.position.y = 1.6;

            // Обработка ввода (ПК)
            if(!isMobile) {
                document.addEventListener('click', () => {
                    if(!chatActive) {
                        if(document.pointerLockElement !== document.body) document.body.requestPointerLock();
                        else shoot();
                    }
                });
                document.addEventListener('mousemove', (e) => {
                    if (document.pointerLockElement === document.body && !chatActive) {
                        yaw -= e.movementX * 0.0022;
                        pitch -= e.movementY * 0.0022;
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
                setupMobileTouch();
            }

            window.addEventListener('resize', () => {
                camera.aspect = window.innerWidth / window.innerHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(window.innerWidth, window.innerHeight);
            });

            // Запуск сетевого тикрейта (30 раз в секунду вместо спама 60фпс)
            setInterval(networkTick, 33);
            animate();
        }

        function generateArena(theme) {
            while(mapGroup.children.length > 0){ mapGroup.remove(mapGroup.children[0]); }
            collidableWalls = [];
            targetsForBullets = [];

            gridFloor.material.color.set(new THREE.Color(theme.neon));
            scene.fog = new THREE.FogExp2(theme.ground, 0.02);
            renderer.setClearColor(theme.ground);

            const wallMat = new THREE.MeshBasicMaterial({ color: 0x090a10 });
            const neonMat = new THREE.MeshBasicMaterial({ color: theme.neon });

            // Границы карты
            const blocks = [
                {x:0, z:-60, w:120, d:2, h:8}, {x:0, z:60, w:120, d:2, h:8},
                {x:-60, z:0, w:2, d:120, h:8}, {x:60, z:0, w:2, d:120, h:8}
            ];
            
            // Псевдогенерация неонового мегаполиса
            let hash = theme.name.charCodeAt(0) || 7;
            for(let i=0; i<24; i++) {
                let sizeW = 4 + (i % 3) * 3;
                let sizeD = 4 + (i % 2) * 3;
                let height = 8 + ((i * hash) % 12);
                blocks.push({
                    x: Math.sin(i * hash * 0.7) * 40,
                    z: Math.cos(i * 19) * 40,
                    w: sizeW, d: sizeD, h: height, tower: true
                });
            }

            blocks.forEach(b => {
                const mesh = new THREE.Mesh(new THREE.BoxGeometry(b.w, b.h, b.d), wallMat);
                mesh.position.set(b.x, b.h/2, b.z);
                mapGroup.add(mesh);
                collidableWalls.push(mesh);
                targetsForBullets.push(mesh);

                if(b.tower) {
                    // Светящиеся неоновые ребра зданий
                    const edgeGeo = new THREE.EdgesGeometry(mesh.geometry);
                    const wires = new THREE.LineSegments(edgeGeo, new THREE.LineBasicMaterial({ color: theme.neon }));
                    wires.position.copy(mesh.position);
                    mapGroup.add(wires);
                    
                    // Декоративные неоновые полосы (окна)
                    if(b.h > 12) {
                        const band = new THREE.Mesh(new THREE.BoxGeometry(b.w + 0.05, 0.2, b.d + 0.05), neonMat);
                        band.position.set(b.x, b.h * 0.7, b.z);
                        mapGroup.add(band);
                    }
                }
            });
        }

        function createWeapon() {
            weapon = new THREE.Group();
            const body = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.07, 0.45), new THREE.MeshBasicMaterial({ color: 0x161722 }));
            const laserLine = new THREE.Mesh(new THREE.BoxGeometry(0.01, 0.01, 0.3), new THREE.MeshBasicMaterial({ color: 0xff0055 }));
            laserLine.position.set(0, 0.04, -0.1);
            
            // Вспышка выстрела
            muzzleFlash = new THREE.Mesh(new THREE.SphereGeometry(0.08, 8, 8), new THREE.MeshBasicMaterial({ color: 0xffffff, visible: false }));
            muzzleFlash.position.set(0, 0, -0.25);

            weapon.add(body);
            weapon.add(laserLine);
            weapon.add(muzzleFlash);
            
            weapon.position.set(0.18, -0.18, -0.32);
            camera.add(weapon);
            scene.add(camera);
        }

        // --- УЛЬТИМАТИВНЫЙ МУЛЬТИ-ТАЧ ДЛЯ СМАРТФОНОВ ---
        function setupMobileTouch() {
            const zMove = document.getElementById("zone_move");
            const zLook = document.getElementById("zone_look");
            const vJoyM = document.getElementById("v_joy_move");
            const vJoyL = document.getElementById("v_joy_look");
            const knobM = vJoyM.querySelector(".joystick-knob");
            const knobL = vJoyL.querySelector(".joystick-knob");

            // Зона Ходьбы
            zMove.addEventListener("touchstart", (e) => {
                e.preventDefault();
                let t = e.changedTouches[0];
                touchMoveId = t.identifier;
                moveData.startX = t.clientX; moveData.startY = t.clientY;
                vJoyM.style.display = "block";
                vJoyM.style.left = t.clientX + "px"; vJoyM.style.top = t.clientY + "px";
                knobM.style.transform = "none";
            });
            zMove.addEventListener("touchmove", (e) => {
                e.preventDefault();
                for(let t of e.touches) {
                    if(t.identifier === touchMoveId) {
                        let dx = t.clientX - moveData.startX;
                        let dy = t.clientY - moveData.startY;
                        let dist = Math.min(35, Math.sqrt(dx*dx + dy*dy));
                        let angle = Math.atan2(dy, dx);
                        moveData.curX = Math.cos(angle) * (dist / 35);
                        moveData.curY = Math.sin(angle) * (dist / 35);
                        knobM.style.transform = `translate(${Math.cos(angle)*dist}px, ${Math.sin(angle)*dist}px)`;
                    }
                }
            });
            const stopMove = (e) => {
                for(let t of e.changedTouches) {
                    if(t.identifier === touchMoveId) {
                        touchMoveId = null; moveData.curX = 0; moveData.curY = 0;
                        vJoyM.style.display = "none";
                    }
                }
            };
            zMove.addEventListener("touchend", stopMove); zMove.addEventListener("touchcancel", stopMove);

            // Зона Обзора
            zLook.addEventListener("touchstart", (e) => {
                e.preventDefault();
                let t = e.changedTouches[0];
                touchLookId = t.identifier;
                lookData.startX = t.clientX; lookData.startY = t.clientY;
                vJoyL.style.display = "block";
                vJoyL.style.left = t.clientX + "px"; vJoyL.style.top = t.clientY + "px";
                knobL.style.transform = "none";
            });
            zLook.addEventListener("touchmove", (e) => {
                e.preventDefault();
                for(let t of e.touches) {
                    if(t.identifier === touchLookId) {
                        let dx = t.clientX - lookData.startX;
                        let dy = t.clientY - lookData.startY;
                        yaw -= dx * 0.005;
                        pitch -= dy * 0.005;
                        pitch = Math.max(-Math.PI/2.2, Math.min(Math.PI/2.2, pitch));
                        camera.rotation.set(pitch, yaw, 0, 'YXZ');
                        
                        // Двигаем пипку джойстика обзора ради визуала
                        let dist = Math.min(35, Math.sqrt(dx*dx + dy*dy));
                        let angle = Math.atan2(dy, dx);
                        knobL.style.transform = `translate(${Math.cos(angle)*dist}px, ${Math.sin(angle)*dist}px)`;
                        
                        lookData.startX = t.clientX; lookData.startY = t.clientY;
                    }
                }
            });
            const stopLook = (e) => {
                for(let t of e.changedTouches) {
                    if(t.identifier === touchLookId) {
                        touchLookId = null; vJoyL.style.display = "none";
                    }
                }
            };
            zLook.addEventListener("touchend", stopLook); zLook.addEventListener("touchcancel", stopLook);

            document.getElementById("mobile_fire_btn").addEventListener("touchstart", (e) => { e.preventDefault(); shoot(); });
        }

        // --- СОЧНАЯ СТРЕЛЬБА И ЛАЗЕРЫ-ТРАССЕРЫ ---
        function shoot() {
            if(isShooting) return;
            isShooting = true;

            // Визуальный импакт выстрела
            weapon.position.z = -0.24; 
            muzzleFlash.visible = true;
            setTimeout(() => { weapon.position.z = -0.32; muzzleFlash.visible = false; }, 40);

            // Лазерная пуля (Вытянутый светящийся капсюль)
            const bGeo = new THREE.CylinderGeometry(0.04, 0.04, 0.6, 4);
            bGeo.rotateX(Math.PI / 2); // разворачиваем по направлению полета
            const bMesh = new THREE.Mesh(bGeo, new THREE.MeshBasicMaterial({ color: 0xffffff }));
            
            const startPos = new THREE.Vector3(0, 0, -0.4).applyMatrix4(weapon.matrixWorld);
            bMesh.position.copy(startPos);
            
            const dir = new THREE.Vector3();
            camera.getWorldDirection(dir);
            bMesh.lookAt(bMesh.position.clone().add(dir)); // пуля смотрит вперед

            scene.add(bMesh);
            bullets.push({ mesh: bMesh, dir: dir, steps: 0 });
            setTimeout(() => { isShooting = false; }, 160);
        }

        function updateBullets() {
            for(let i = bullets.length - 1; i >= 0; i--) {
                let b = bullets[i];
                let speed = 2.2;
                b.mesh.position.addScaledVector(b.dir, speed);
                b.steps += 1;

                // Быстрая точечная проверка без прострела сквозь меши
                const ray = new THREE.Raycaster(b.mesh.position, b.dir, 0, speed + 0.1);
                const hits = ray.intersectObjects(targetsForBullets, false); // Без рекурсии = мгновенный расчет!

                let destroyBullet = false;
                if(hits.length > 0) {
                    destroyBullet = true;
                    let obj = hits[0].object;
                    if(obj.userData.playerId && ws) {
                        ws.send(JSON.stringify({ type: "hit", target: obj.userData.playerId }));
                    }
                }

                if(destroyBullet || b.steps > 35) {
                    scene.remove(b.mesh);
                    bullets.splice(i, 1);
                }
            }
        }

        // --- СВЕТЯЩИЙСЯ ИНТЕРФЕЙС НАД ГОЛОВАМИ ---
        function makeLabelSprite(name, hp, color) {
            const canvas = document.createElement('canvas');
            canvas.width = 256; canvas.height = 70;
            const ctx = canvas.getContext('2d');
            
            ctx.font = "bold 24px monospace";
            ctx.fillStyle = "#ffffff";
            ctx.textAlign = "center";
            ctx.fillText(name, 128, 25);
            
            // Фон ХП бара
            ctx.fillStyle = "rgba(10,10,20,0.8)";
            ctx.fillRect(38, 40, 180, 12);
            // Заполнение ХП
            ctx.fillStyle = color;
            ctx.fillRect(38, 40, Math.max(0, hp) * 1.8, 12);
            
            const texture = new THREE.CanvasTexture(canvas);
            const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, depthTest: true }));
            sprite.scale.set(2.0, 0.55, 1);
            return sprite;
        }

        function redrawPlayerLabel(id) {
            let p = players[id];
            if(!p) return;
            if(p.label) p.group.remove(p.label);
            p.label = makeLabelSprite(p.name, p.hp, p.color);
            p.label.position.y = 2.4;
            p.group.add(p.label);
        }

        // --- СЕТЕВОЙ ТИКРЕЙТ (Убирает фризы) ---
        function networkTick() {
            if (ws && ws.readyState === WebSocket.OPEN && myId) {
                let posChanged = camera.position.distanceTo(lastSentPos) > 0.02;
                let rotChanged = Math.abs(yaw - lastSentYaw) > 0.01;
                
                if (posChanged || rotChanged) {
                    ws.send(JSON.stringify({
                        type: "move", x: camera.position.x, z: camera.position.z, ry: yaw
                    }));
                    lastSentPos.copy(camera.position);
                    lastSentYaw = yaw;
                }
            }
        }

        function initNetwork() {
            const proto = location.protocol === "https:" ? "wss://" : "ws://";
            ws = new WebSocket(proto + location.host + "/ws/game_" + Math.floor(Math.random()*100000));
            
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
                    for(let id in players) { players[id].hp = 100; redrawPlayerLabel(id); }
                }
                else if (data.type === "update" && data.id !== myId && players[data.id]) {
                    players[data.id].group.position.set(data.x, 0, data.z);
                    players[data.id].group.rotation.y = data.ry;
                }
                else if (data.type === "hp_update") {
                    if(data.id === myId) { updateHp(data.hp); triggerScreenShake(); }
                    else if(players[data.id]) { players[data.id].hp = data.hp; redrawPlayerLabel(data.id); }
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
                        redrawPlayerLabel(data.id);
                    }
                    // Вызов Киллфида
                    showKillNotification(data.killer, data.victim);
                }
                else if (data.type === "chat_msg") {
                    const log = document.getElementById("chat_log");
                    log.innerHTML += `<div><span style="color:#ff0055">${data.sender}:</span> ${data.text}</div>`;
                    setTimeout(() => { if(log.children.length > 5) log.removeChild(log.children[0]); }, 5000);
                }
                else if (data.type === "leave" && players[data.id]) {
                    targetsForBullets = targetsForBullets.filter(t => t !== players[data.id].hitbox);
                    scene.remove(players[data.id].group);
                    delete players[data.id];
                }
            };
        }

        function createEnemy(id, info) {
            const group = new THREE.Group();
            
            // Кибер-аватар игрока (Цилиндр в неоновой оплетке)
            const body = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.3, 1.5, 8), new THREE.MeshBasicMaterial({ color: 0x05050e }));
            body.position.y = 0.75;
            const edges = new THREE.EdgesGeometry(body.geometry);
            const frame = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: info.color }));
            frame.position.y = 0.75;
            
            // Стабильный скрытый хитбокс пуль (Никаких зависаний Three.js)
            const hitbox = new THREE.Mesh(new THREE.BoxGeometry(0.7, 1.6, 0.7), new THREE.MeshBasicMaterial({ visible: false }));
            hitbox.position.y = 0.8;
            hitbox.userData.playerId = id;

            group.add(body); group.add(frame); group.add(hitbox);
            group.position.set(info.x, 0, info.z);
            scene.add(group);

            players[id] = { group: group, hitbox: hitbox, name: info.name, hp: info.hp, color: info.color };
            targetsForBullets.push(hitbox); // Пуля реагирует только на этот конкретный меш
            redrawPlayerLabel(id);
        }

        // --- ФИЗИКА ИГРОКА И КИЛЛФИД ---
        function checkWallCollisions(targetPos) {
            for(let i=0; i<collidableWalls.length; i++) {
                let box = new THREE.Box3().setFromObject(collidableWalls[i]);
                let pBox = new THREE.Box3(
                    new THREE.Vector3(targetPos.x - 0.45, 0, targetPos.z - 0.45),
                    new THREE.Vector3(targetPos.x + 0.45, 2, targetPos.z + 0.45)
                );
                if(box.intersectsBox(pBox)) return true;
            }
            return false;
        }

        function showKillNotification(killer, victim) {
            const kf = document.getElementById("killfeed");
            const div = document.createElement("div");
            div.className = "kill-item";
            div.innerHTML = `<span style="color:#00ffcc">${killer}</span> ➔ <span style="color:#ff0055">${victim}</span>`;
            kf.appendChild(div);
            setTimeout(() => div.remove(), 4000);
        }

        function triggerScreenShake() {
            document.getElementById("damage_overlay").style.opacity = "1";
            setTimeout(() => document.getElementById("damage_overlay").style.opacity = "0", 80);
            
            let originalY = camera.position.y;
            camera.position.y += (Math.random() - 0.5) * 0.2;
            setTimeout(() => camera.position.y = originalY, 50);
        }

        function openChat() { chatActive = true; document.exitPointerLock(); document.getElementById("chat_input").focus(); }
        function closeChat() { chatActive = false; document.getElementById("chat_input").blur(); document.body.requestPointerLock(); }
        function sendChat() {
            let val = document.getElementById("chat_input").value.trim();
            if(val && ws) ws.send(JSON.stringify({ type: "chat", text: val }));
            document.getElementById("chat_input").value = "";
            closeChat();
        }

        function updateHp(hp) { myHp = hp; document.getElementById("hp_bar").style.width = hp + "%"; }

        // --- ОСНОВНОЙ ЦИКЛ РЕНДЕРА ---
        function animate() {
            requestAnimationFrame(animate);
            if(!scene || !camera) return;

            updateBullets();

            // Разворот всех ников к камере игрока
            for(let id in players) if(players[id].label) players[id].label.lookAt(camera.position);

            const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion); forward.y = 0; forward.normalize();
            const side = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion); side.y = 0; side.normalize();
            
            let nextPos = camera.position.clone();
            let walking = false;

            if(!isMobile) {
                if (keys.w) { nextPos.addScaledVector(forward, moveSpeed); walking = true; }
                if (keys.s) { nextPos.addScaledVector(forward, -moveSpeed); walking = true; }
                if (keys.a) { nextPos.addScaledVector(side, -moveSpeed); walking = true; }
                if (keys.d) { nextPos.addScaledVector(side, moveSpeed); walking = true; }
            } else {
                if(touchMoveId !== null) {
                    nextPos.addScaledVector(forward, -moveData.curY * moveSpeed);
                    nextPos.addScaledVector(side, moveData.curX * moveSpeed);
                    walking = true;
                }
            }

            if(walking && !checkWallCollisions(nextPos)) {
                camera.position.copy(nextPos);
                // Динамическое покачивание оружия при ходьбе
                weapon.position.y = -0.18 + Math.sin(Date.now() * 0.012) * 0.012;
                weapon.position.x = 0.18 + Math.cos(Date.now() * 0.006) * 0.006;
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
