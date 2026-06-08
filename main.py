import asyncio
import json
import random
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

# --- СЕРВЕРНАЯ АРХИТЕКТУРА (ОПТИМИЗИРОВАННАЯ) ---

class GameServer:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.players = {}
        self.current_round = 1
        self.maps = [
            {"sky": "#1a1c23", "ground": "#22252c", "wall": "#4a4f5a", "name": "ВОЕННЫЙ СКЛАД"},
            {"sky": "#2d2621", "ground": "#3a312a", "wall": "#5c4e43", "name": "ПЕСЧАНЫЙ БЛОКПОСТ"},
            {"sky": "#12181a", "ground": "#1c2427", "wall": "#334146", "name": "ПРОМЗОНА"}
        ]
        self.current_map = self.maps[0]

    async def connect(self, websocket: WebSocket, player_id: str):
        await websocket.accept()
        self.active_connections[player_id] = websocket
        x, z = random.uniform(-25, 25), random.uniform(-25, 25)
        self.players[player_id] = {
            "name": "Operator", "x": x, "z": z, "ry": 0,
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
        await asyncio.sleep(120)  # Раунд 2 минуты
        server.current_round += 1
        server.current_map = server.maps[(server.current_round - 1) % len(server.maps)]
        for pid in server.players:
            server.players[pid]["hp"] = 100
        await server.broadcast({
            "type": "new_round", "round": server.current_round, "map": server.current_map
        })

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(round_manager())

@app.websocket("/ws/live/{player_id}")
async def websocket_endpoint(websocket: WebSocket, player_id: str):
    await server.connect(websocket, player_id)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg["type"] == "join":
                server.players[player_id]["name"] = msg.get("name", "Player")[:12]
                await websocket.send_text(json.dumps({
                    "type": "init", "id": player_id, "map": server.current_map,
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
                    server.players[tid]["hp"] -= 25  # 4 выстрела до килла
                    if server.players[tid]["hp"] <= 0:
                        server.players[player_id]["score"] += 1
                        server.players[tid]["hp"] = 100
                        nx, nz = random.uniform(-25, 25), random.uniform(-25, 25)
                        server.players[tid]["x"], server.players[tid]["z"] = nx, nz
                        await server.broadcast({
                            "type": "respawn", "id": tid, "x": nx, "z": nz, 
                            "killer": server.players[player_id]["name"], "victim": server.players[tid]["name"],
                            "score_update": {"id": player_id, "score": server.players[player_id]["score"]}
                        })
                    await server.broadcast({"type": "hp_update", "id": tid, "hp": server.players[tid]["hp"]})
    except WebSocketDisconnect:
        server.disconnect(player_id)
        await server.broadcast({"type": "leave", "id": player_id})

# --- ИНТЕРФЕЙС, СВЕТ И 3D ДВИЖОК ---

html_content = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>TACTICAL ARENA 3D</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; user-select: none; background: #111; color: #fff; touch-action: none; }
        
        /* Меню авторизации */
        #login_screen { position: fixed; inset: 0; background: linear-gradient(135deg, #1f2326 0%, #0f1011 100%); display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 100; }
        .menu-card { background: #282c30; border: 1px solid #3f444a; padding: 35px; border-radius: 12px; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.5); width: 320px; max-width: 85%; }
        .menu-card h1 { font-size: 24px; font-weight: 700; margin: 0 0 20px 0; letter-spacing: 1px; color: #eceff1; }
        .input-field { width: 100%; padding: 12px; font-size: 16px; border: 1px solid #4f565e; background: #1e2124; color: #fff; border-radius: 6px; outline: none; box-sizing: border-box; text-align: center; }
        .input-field:focus { border-color: #5c6bc0; }
        .btn-submit { width: 100%; margin-top: 15px; padding: 14px; font-size: 16px; cursor: pointer; background: #3f51b5; color: white; border: none; border-radius: 6px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; transition: background 0.2s; }
        .btn-submit:hover { background: #4f5bbf; }
        
        /* Боевой HUD */
        #hud { position: absolute; top: 20px; left: 20px; background: rgba(30,33,36,0.85); padding: 12px 18px; border-radius: 6px; border-left: 4px solid #3f51b5; pointer-events: none; display: none; z-index: 10; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
        #map_name { font-weight: 700; font-size: 15px; color: #fff; text-transform: uppercase; }
        #round_info, #score_info { font-size: 13px; margin-top: 3px; color: #b0bec5; font-family: monospace; }
        
        /* Прицел (Традиционный шутерный) */
        #crosshair { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); pointer-events: none; z-index: 10; display:none; }
        .ch-dot { width: 4px; height: 4px; background: #fff; border-radius: 50%; box-shadow: 0 0 2px #000; }
        
        /* Здоровье */
        #hp_container { position: absolute; bottom: 30px; left: 50%; transform: translateX(-50%); width: 240px; height: 10px; background: rgba(0,0,0,0.5); border-radius: 5px; overflow: hidden; display: none; box-shadow: 0 2px 8px rgba(0,0,0,0.4); z-index: 10; border: 1px solid #444;}
        #hp_bar { width: 100%; height: 100%; background: #e53935; transition: width 0.15s; }
        #damage_flash { position: absolute; inset: 0; background: rgba(229,57,53,0.3); pointer-events: none; opacity: 0; transition: opacity 0.1s; z-index: 5; }
        
        /* Киллфид */
        #killfeed { position: absolute; top: 20px; right: 20px; display: flex; flex-direction: column; gap: 6px; pointer-events: none; z-index: 10; font-family: monospace;}
        .kill-msg { background: rgba(40,44,48,0.9); border: 1px solid #3a3f44; padding: 6px 12px; border-radius: 4px; color: #cfd8dc; font-size: 12px; animation: slideIn 0.2s ease-out; }
        @keyframes slideIn { from { opacity: 0; transform: translateX(30px); } to { opacity: 1; transform: translateX(0); } }
        
        /* МОБИЛЬНЫЕ ТАЧ-ЗОНЫ */
        .touch-pad { position: absolute; bottom: 0; top: 35%; width: 45%; z-index: 20; display: none; }
        #pad_left { left: 0; }
        #pad_right { right: 0; }
        .joystick-base { position: absolute; width: 90px; height: 90px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.15); border-radius: 50%; display: none; pointer-events: none; transform: translate(-50%, -50%); }
        .joystick-stick { position: absolute; width: 30px; height: 30px; background: #fff; border-radius: 50%; top: 30px; left: 30px; box-shadow: 0 2px 6px rgba(0,0,0,0.5); }
        #btn_fire { position: absolute; bottom: 50px; right: 50px; width: 76px; height: 76px; background: rgba(255,255,255,0.1); border: 2px solid rgba(255,255,255,0.4); border-radius: 50%; display: none; justify-content: center; align-items: center; font-weight: 700; font-size: 14px; z-index: 30; box-shadow: 0 4px 10px rgba(0,0,0,0.3); text-shadow: 1px 1px 2px #000; }
        #btn_fire:active { background: rgba(255,255,255,0.3); transform: scale(0.95); }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
    <div id="login_screen">
        <div class="menu-card">
            <h1>TACTICAL OPERATIONS</h1>
            <input type="text" id="nickname_input" class="input-field" placeholder="CALLSIGN" value="Operator" maxlength="12">
            <button id="play_btn" class="btn-submit">DEPLOY</button>
        </div>
    </div>

    <div id="hud">
        <div id="map_name">LOADING MAP...</div>
        <div id="round_info">ROUND: 1</div>
        <div id="score_info">KILLS: 0</div>
    </div>

    <div id="killfeed"></div>
    <div id="hp_container"><div id="hp_bar"></div></div>
    <div id="crosshair"><div class="ch-dot"></div></div>
    <div id="damage_flash"></div>

    <div id="pad_left" class="touch-pad"></div>
    <div id="pad_right" class="touch-pad"></div>
    <div id="joy_left" class="joystick-base"><div class="joystick-stick"></div></div>
    <div id="joy_right" class="joystick-base"><div class="joystick-stick"></div></div>
    <div id="btn_fire">FIRE</div>

    <script>
        let scene, camera, renderer, sunLight, ambientLight, floorGrid;
        let players = {}, myId = null, myName = "Operator", ws;
        let keys = { w:0, a:0, s:0, d:0 };
        let moveSpeed = 0.14, yaw = 0, pitch = 0;
        let myHp = 100, myScore = 0, isMobile = false;

        let weapon, muzzleLight, isShooting = false, bullets = [];
        let mapGroup = new THREE.Group(), collidableObjects = [], raycastTargets = [];

        // Раздельный мультитач
        let idMove = null, idLook = null;
        let dataMove = { startX: 0, startY: 0, curX: 0, curY: 0 };
        let dataLook = { startX: 0, startY: 0 };

        // Оптимизация сети
        let lastPos = new THREE.Vector3(), lastYaw = 0;

        function checkMobile() {
            isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || (window.innerWidth < 900);
            if(isMobile) {
                document.getElementById("pad_left").style.display = "block";
                document.getElementById("pad_right").style.display = "block";
                document.getElementById("btn_fire").style.display = "flex";
            }
        }

        function init3D() {
            scene = new THREE.Scene();
            camera = new THREE.PerspectiveCamera(65, window.innerWidth / window.innerHeight, 0.1, 1000);
            
            renderer = new THREE.WebGLRenderer({ antialias: true });
            renderer.setSize(window.innerWidth, window.innerHeight);
            renderer.shadowMap.enabled = true;
            document.body.appendChild(renderer.domElement);

            // Релистичное освещение (Солнечный свет + заполняющий свет неба)
            ambientLight = new THREE.AmbientLight(0x7f8c8d, 0.6);
            scene.add(ambientLight);

            sunLight = new THREE.DirectionalLight(0xfffdfa, 0.8);
            sunLight.position.set(30, 40, 20);
            scene.add(sunLight);

            // Земля (Асфальтово-бетонное покрытие)
            const floorMat = new THREE.MeshStandardMaterial({ color: 0x2c3e50, roughness: 0.8, metalness: 0.2 });
            const floor = new THREE.Mesh(new THREE.PlaneGeometry(160, 160), floorMat);
            floor.rotation.x = -Math.PI / 2;
            scene.add(floor);

            scene.add(mapGroup);
            buildTacticalWeapon();
            camera.position.y = 1.65; // Средний рост человека

            if(!isMobile) {
                document.addEventListener('click', () => {
                    if(document.pointerLockElement !== document.body) document.body.requestPointerLock();
                    else performShoot();
                });
                document.addEventListener('mousemove', (e) => {
                    if (document.pointerLockElement === document.body) {
                        yaw -= e.movementX * 0.002;
                        pitch -= e.movementY * 0.002;
                        pitch = Math.max(-Math.PI/2.4, Math.min(Math.PI/2.4, pitch));
                        camera.rotation.set(pitch, yaw, 0, 'YXZ');
                    }
                });
                window.addEventListener('keydown', (e) => { if(e.key.toLowerCase() in keys) keys[e.key.toLowerCase()] = 1; });
                window.addEventListener('keyup', (e) => { if(e.key.toLowerCase() in keys) keys[e.key.toLowerCase()] = 0; });
            } else {
                initMobileTouchHandlers();
            }

            window.addEventListener('resize', () => {
                camera.aspect = window.innerWidth / window.innerHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(window.innerWidth, window.innerHeight);
            });

            setInterval(sendNetworkPosition, 35); // 30Hz Сетевой тикрейт
            animate();
        }

        function buildTacticalWeapon() {
            weapon = new THREE.Group();
            
            // Ствольная коробка (матовая сталь)
            const body = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.05, 0.4), new THREE.MeshStandardMaterial({ color: 0x1c1d21, roughness: 0.5 }));
            // Обойма
            const mag = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.12, 0.05), new THREE.MeshStandardMaterial({ color: 0x111215 }));
            mag.position.set(0, -0.07, -0.05);
            // Прицел
            const sight = new THREE.Mesh(new THREE.BoxGeometry(0.01, 0.02, 0.02), new THREE.MeshStandardMaterial({ color: 0x050505 }));
            sight.position.set(0, 0.035, -0.15);

            muzzleLight = new THREE.PointLight(0xffaa44, 0, 3);
            muzzleLight.position.set(0, 0, -0.22);

            weapon.add(body, mag, sight, muzzleLight);
            weapon.position.set(0.16, -0.18, -0.3);
            camera.add(weapon);
            scene.add(camera);
        }

        function generateMapStructure(mapData) {
            while(mapGroup.children.length > 0){ mapGroup.remove(mapGroup.children[0]); }
            collidableObjects = [];
            raycastTargets = [];

            scene.background = new THREE.Color(mapData.sky);
            scene.fog = new THREE.FogExp2(mapData.sky, 0.015);
            
            const wallMaterial = new THREE.MeshStandardMaterial({ color: mapData.wall, roughness: 0.9, metalness: 0.1 });

            // Периметр карты
            const layout = [
                {x:0, z:-60, w:120, d:3, h:6}, {x:0, z:60, w:120, d:3, h:6},
                {x:-60, z:0, w:3, d:120, h:6}, {x:60, z:0, w:3, d:120, h:6}
            ];
            
            // Генерация укрытий (Тактические блоки и стены)
            let seed = mapData.name.charCodeAt(1) || 5;
            for(let i=0; i<30; i++) {
                let w = 4 + (i % 2) * 4;
                let d = 4 + (i % 3) * 2;
                let h = 3 + (i % 2) * 2;
                layout.push({
                    x: Math.sin(i * seed * 0.5) * 42,
                    z: Math.cos(i * 17) * 42,
                    w: w, d: d, h: h
                });
            }

            layout.forEach(l => {
                const mesh = new THREE.Mesh(new THREE.BoxGeometry(l.w, l.h, l.d), wallMaterial);
                mesh.position.set(l.x, l.h/2, l.z);
                mapGroup.add(mesh);
                collidableObjects.push(mesh);
                raycastTargets.push(mesh);
            });
        }

        // --- МОБИЛЬНЫЙ СТАК УПРАВЛЕНИЯ (ИДЕАЛЬНЫЙ ТРЭКИНГ) ---
        function initMobileTouchHandlers() {
            const pLeft = document.getElementById("pad_left");
            const pRight = document.getElementById("pad_right");
            const jLeft = document.getElementById("joy_left");
            const jRight = document.getElementById("joy_right");
            const sLeft = jLeft.querySelector(".joystick-stick");
            const sRight = jRight.querySelector(".joystick-stick");

            pLeft.addEventListener("touchstart", (e) => {
                e.preventDefault();
                let t = e.changedTouches[0];
                idMove = t.identifier;
                dataMove.startX = t.clientX; dataMove.startY = t.clientY;
                jLeft.style.display = "block";
                jLeft.style.left = t.clientX + "px"; jLeft.style.top = t.clientY + "px";
                sLeft.style.transform = "none";
            });
            pLeft.addEventListener("touchmove", (e) => {
                e.preventDefault();
                for(let t of e.touches) {
                    if(t.identifier === idMove) {
                        let dx = t.clientX - dataMove.startX;
                        let dy = t.clientY - dataMove.startY;
                        let len = Math.min(30, Math.sqrt(dx*dx + dy*dy));
                        let ang = Math.atan2(dy, dx);
                        dataMove.curX = Math.cos(ang) * (len / 30);
                        dataMove.curY = Math.sin(ang) * (len / 30);
                        sLeft.style.transform = `translate(${Math.cos(ang)*len}px, ${Math.sin(ang)*len}px)`;
                    }
                }
            });
            const endMove = (e) => {
                for(let t of e.changedTouches) {
                    if(t.identifier === idMove) { idMove = null; dataMove.curX = 0; dataMove.curY = 0; jLeft.style.display = "none"; }
                }
            };
            pLeft.addEventListener("touchend", endMove); pLeft.addEventListener("touchcancel", endMove);

            pRight.addEventListener("touchstart", (e) => {
                e.preventDefault();
                let t = e.changedTouches[0];
                idLook = t.identifier;
                dataLook.startX = t.clientX; dataLook.startY = t.clientY;
                jRight.style.display = "block";
                jRight.style.left = t.clientX + "px"; jRight.style.top = t.clientY + "px";
                sRight.style.transform = "none";
            });
            pRight.addEventListener("touchmove", (e) => {
                e.preventDefault();
                for(let t of e.touches) {
                    if(t.identifier === idLook) {
                        let dx = t.clientX - dataLook.startX;
                        let dy = t.clientY - dataLook.startY;
                        yaw -= dx * 0.004;
                        pitch -= dy * 0.004;
                        pitch = Math.max(-Math.PI/2.4, Math.min(Math.PI/2.4, pitch));
                        camera.rotation.set(pitch, yaw, 0, 'YXZ');
                        
                        let len = Math.min(20, Math.sqrt(dx*dx + dy*dy));
                        let ang = Math.atan2(dy, dx);
                        sRight.style.transform = `translate(${Math.cos(ang)*len}px, ${Math.sin(ang)*len}px)`;
                        
                        dataLook.startX = t.clientX; dataLook.startY = t.clientY;
                    }
                }
            });
            const endLook = (e) => {
                for(let t of e.changedTouches) { if(t.identifier === idLook) { idLook = null; jRight.style.display = "none"; } }
            };
            pRight.addEventListener("touchend", endLook); pRight.addEventListener("touchcancel", endLook);

            document.getElementById("btn_fire").addEventListener("touchstart", (e) => { e.preventDefault(); performShoot(); });
        }

        // --- МГНОВЕННЫЙ СТРЕЛКОВЫЙ ФИЗИЧЕСКИЙ РАСЧЕТ ---
        function performShoot() {
            if(isShooting) return;
            isShooting = true;

            // Импакт отдачи (смещение ствола)
            weapon.position.z = -0.25;
            muzzleLight.intensity = 1.5;
            setTimeout(() => { weapon.position.z = -0.3; muzzleLight.intensity = 0; }, 50);

            // Визуальный трассер (быстро исчезающая тонкая линия пули)
            const tracerGeo = new THREE.BufferGeometry().setFromPoints([
                new THREE.Vector3(0,0,-0.2).applyMatrix4(weapon.matrixWorld),
                new THREE.Vector3(0,0,-20).applyMatrix4(weapon.matrixWorld)
            ]);
            const tracer = new THREE.Line(tracerGeo, new THREE.LineBasicMaterial({ color: 0xffeaa7 }));
            scene.add(tracer);
            setTimeout(() => scene.remove(tracer), 30);

            // Математический расчет попадания луча
            const dir = new THREE.Vector3();
            camera.getWorldDirection(dir);
            const ray = new THREE.Raycaster(camera.position, dir, 0, 100);
            const hits = ray.intersectObjects(raycastTargets, false);

            if(hits.length > 0) {
                let hitObj = hits[0].object;
                if(hitObj.userData.playerId && ws) {
                    ws.send(JSON.stringify({ type: "hit", target: hitObj.userData.playerId }));
                }
            }
            setTimeout(() => { isShooting = false; }, 130); // Темп стрельбы
        }

        // --- ХУД И ТЕКСТОВЫЕ МАРКЕРЫ НАД БОЙЦАМИ ---
        function generateNameplate(name, hp) {
            const canvas = document.createElement('canvas');
            canvas.width = 240; canvas.height = 60;
            const ctx = canvas.getContext('2d');
            
            ctx.font = "bold 20px sans-serif";
            ctx.fillStyle = "#ffffff";
            ctx.textAlign = "center";
            ctx.fillText(name, 120, 22);
            
            ctx.fillStyle = "#1e2124";
            ctx.fillRect(40, 35, 160, 10);
            ctx.fillStyle = "#4caf50";
            ctx.fillRect(40, 35, Math.max(0, hp) * 1.6, 10);
            
            const tex = new THREE.CanvasTexture(canvas);
            const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex }));
            sprite.scale.set(1.8, 0.45, 1);
            return sprite;
        }

        function updatePlayerLabel(id) {
            let p = players[id];
            if(!p) return;
            if(p.label) p.group.remove(p.label);
            p.label = generateNameplate(p.name, p.hp);
            p.label.position.y = 2.2;
            p.group.add(p.label);
        }

        // --- СЕТЕВОЙ СТАК И ИНТЕРПОЛЯЦИЯ ЛЕГКОВЫХ ТИКАНИЙ ---
        function sendNetworkPosition() {
            if (ws && ws.readyState === WebSocket.OPEN && myId) {
                if (camera.position.distanceTo(lastPos) > 0.01 || Math.abs(yaw - lastYaw) > 0.005) {
                    ws.send(JSON.stringify({ type: "move", x: camera.position.x, z: camera.position.z, ry: yaw }));
                    lastPos.copy(camera.position); lastYaw = yaw;
                }
            }
        }

        function initNetwork() {
            const proto = location.protocol === "https:" ? "wss://" : "ws://";
            ws = new WebSocket(proto + location.host + "/ws/live/" + Math.floor(Math.random()*999999));
            
            ws.onopen = () => ws.send(JSON.stringify({ type: "join", name: myName }));
            ws.onmessage = (e) => {
                const data = JSON.parse(e.data);
                
                if (data.type === "init") {
                    myId = data.id;
                    document.getElementById("score_info").innerText = "KILLS: " + myScore;
                    document.getElementById("round_info").innerText = "ROUND: " + data.round;
                    document.getElementById("map_name").innerText = data.map.name;
                    generateMapStructure(data.map);
                    camera.position.set(data.x, 1.65, data.z);
                    for (let id in data.players) if(id !== myId) spawnEnemyCharacter(id, data.players[id]);
                } 
                else if (data.type === "new_player" && data.id !== myId) {
                    spawnEnemyCharacter(data.id, data.info);
                }
                else if (data.type === "new_round") {
                    document.getElementById("round_info").innerText = "ROUND: " + data.round;
                    document.getElementById("map_name").innerText = data.map.name;
                    generateMapStructure(data.map);
                    setHpAmount(100);
                    for(let id in players) { players[id].hp = 100; updatePlayerLabel(id); }
                }
                else if (data.type === "update" && data.id !== myId && players[data.id]) {
                    // Записываем целевую точку (для интерполяции на кадре)
                    players[data.id].targetX = data.x;
                    players[data.id].targetZ = data.z;
                    players[data.id].targetRy = data.ry;
                }
                else if (data.type === "hp_update") {
                    if(data.id === myId) { setHpAmount(data.hp); triggerFlinch(); }
                    else if(players[data.id]) { players[data.id].hp = data.hp; updatePlayerLabel(data.id); }
                }
                else if (data.type === "respawn") {
                    if(data.id === myId) { camera.position.set(data.x, 1.65, data.z); setHpAmount(100); }
                    if(data.score_update && data.score_update.id === myId) {
                        myScore = data.score_update.score;
                        document.getElementById("score_info").innerText = "KILLS: " + myScore;
                    }
                    if(players[data.id]) {
                        players[data.id].group.position.set(data.x, 0, data.z);
                        players[data.id].targetX = data.x; players[data.id].targetZ = data.z;
                        players[data.id].hp = 100; updatePlayerLabel(data.id);
                    }
                    pushToKillfeed(data.killer, data.victim);
                }
                else if (data.type === "leave" && players[data.id]) {
                    raycastTargets = raycastTargets.filter(t => t !== players[data.id].hitbox);
                    scene.remove(players[data.id].group);
                    delete players[data.id];
                }
            };
        }

        function spawnEnemyCharacter(id, info) {
            const group = new THREE.Group();
            
            // Военная форма (серо-зеленый глухой мат)
            const body = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, 1.6, 10), new THREE.MeshStandardMaterial({ color: 0x34495e, roughness: 0.9 }));
            body.position.y = 0.8;
            body.castShadow = true;
            
            // Защитный тактический шлем
            const helmet = new THREE.Mesh(new THREE.SphereGeometry(0.2, 8, 8), new THREE.MeshStandardMaterial({ color: 0x2c3e50 }));
            helmet.position.y = 1.6;
            
            const hitbox = new THREE.Mesh(new THREE.BoxGeometry(0.6, 1.7, 0.6), new THREE.MeshBasicMaterial({ visible: false }));
            hitbox.position.y = 0.85;
            hitbox.userData.playerId = id;

            group.add(body, helmet, hitbox);
            group.position.set(info.x, 0, info.z);
            scene.add(group);

            players[id] = { 
                group: group, hitbox: hitbox, name: info.name, hp: info.hp,
                targetX: info.x, targetZ: info.z, targetRy: info.ry 
            };
            raycastTargets.push(hitbox);
            updatePlayerLabel(id);
        }

        // --- КОЛЛИЗИИ, ВСПЫШКА И КИЛЛФИД ---
        function checkCollisions(pos) {
            for(let i=0; i<collidableObjects.length; i++) {
                let box = new THREE.Box3().setFromObject(collidableObjects[i]);
                let pBox = new THREE.Box3(
                    new THREE.Vector3(pos.x - 0.4, 0, pos.z - 0.4),
                    new THREE.Vector3(pos.x + 0.4, 2, pos.z + 0.4)
                );
                if(box.intersectsBox(pBox)) return true;
            }
            return false;
        }

        function pushToKillfeed(killer, victim) {
            const kf = document.getElementById("killfeed");
            const div = document.createElement("div");
            div.className = "kill-msg";
            div.innerHTML = `<b>${killer}</b> ➔ <b>${victim}</b>`;
            kf.appendChild(div);
            setTimeout(() => div.remove(), 4000);
        }

        function triggerFlinch() {
            document.getElementById("damage_flash").style.opacity = "1";
            setTimeout(() => document.getElementById("damage_flash").style.opacity = "0", 80);
            
            // Легкая встряска камеры от попадания (Тряска экрана)
            camera.position.y += 0.08;
            setTimeout(() => camera.position.y = 1.65, 40);
        }

        function setHpAmount(hp) { myHp = hp; document.getElementById("hp_bar").style.width = hp + "%"; }

        function startDeployment() {
            let n = document.getElementById("nickname_input").value.trim();
            if(n) myName = n;
            checkMobile();
            document.getElementById("login_screen").style.display = "none";
            document.getElementById("hud").style.display = "block";
            document.getElementById("hp_container").style.display = "block";
            if(!isMobile) document.getElementById("crosshair").style.display = "block";
            
            init3D();
            initNetwork();
        }
        document.getElementById("play_btn").addEventListener("click", startDeployment);

        // --- ГЛАВНЫЙ ИГРОВОЙ ЦИКЛ (ИНТЕРПОЛЯЦИЯ КАДРОВ) ---
        function animate() {
            requestAnimationFrame(animate);
            if(!scene || !camera) return;

            // Сглаживание движения врагов (LERP). Интерполируем текущую позицию к целевой на 20% каждый кадр
            for(let id in players) {
                let p = players[id];
                if(id !== myId) {
                    p.group.position.x += (p.targetX - p.group.position.x) * 0.22;
                    p.group.position.z += (p.targetZ - p.group.position.z) * 0.22;
                    // Сглаживание вращения
                    let diff = p.targetRy - p.group.rotation.y;
                    p.group.rotation.y += diff * 0.22;
                    
                    if(p.label) p.label.lookAt(camera.position);
                }
            }

            const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion); forward.y = 0; forward.normalize();
            const side = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion); side.y = 0; side.normalize();
            
            let nextPos = camera.position.clone();
            let isMoving = false;

            if(!isMobile) {
                if (keys.w) { nextPos.addScaledVector(forward, moveSpeed); isMoving = true; }
                if (keys.s) { nextPos.addScaledVector(forward, -moveSpeed); isMoving = true; }
                if (keys.a) { nextPos.addScaledVector(side, -moveSpeed); isMoving = true; }
                if (keys.d) { nextPos.addScaledVector(side, moveSpeed); isMoving = true; }
            } else {
                if(idMove !== null) {
                    nextPos.addScaledVector(forward, -dataMove.curY * moveSpeed);
                    nextPos.addScaledVector(side, dataMove.curX * moveSpeed);
                    isMoving = true;
                }
            }

            if(isMoving && !checkCollisions(nextPos)) {
                camera.position.copy(nextPos);
                // Реалистичный оружейный Breathing/Bobbing эффект при движении
                weapon.position.y = -0.18 + Math.sin(Date.now() * 0.01) * 0.008;
                weapon.position.x = 0.16 + Math.cos(Date.now() * 0.005) * 0.004;
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
