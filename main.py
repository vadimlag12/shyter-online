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
        self.maps = [
            {"sky": "#b3e5fc", "ground": "#e0e0e0", "wall": "#78909c", "name": "ДНЕВНОЙ ПОЛИГОН"},
            {"sky": "#ffe0b2", "ground": "#d7ccc8", "wall": "#a1887f", "name": "ПЕСЧАНЫЙ КАНЬОН"},
            {"sky": "#c8e6c9", "ground": "#cfd8dc", "wall": "#546e7a", "name": "ИНДУСТРИАЛЬНЫЙ СЕКТОР"}
        ]
        self.current_map = self.maps[0]

    async def connect(self, websocket: WebSocket, player_id: str):
        await websocket.accept()
        self.active_connections[player_id] = websocket
        x, z = random.uniform(-20, 20), random.uniform(-20, 20)
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
        await asyncio.sleep(120)
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
                    server.players[tid]["hp"] -= 25
                    if server.players[tid]["hp"] <= 0:
                        server.players[player_id]["score"] += 1
                        server.players[tid]["hp"] = 100
                        nx, nz = random.uniform(-20, 20), random.uniform(-20, 20)
                        server.players[tid]["x"], server.players[tid]["z"] = nx, nz
                        await server.broadcast({
                            "type": "respawn", "id": tid, "x": nx, "z": nz, 
                            "killer": server.players[player_id]["name"], "victim": server.players[tid]["name"],
                            "score_update": {"id": player_id, "score": server.players[player_id]["score"]}
                        })
                    await server.broadcast({"type": "hp_update", "id": tid, "hp": server.players[tid]["hp"], "by": player_id})
    except WebSocketDisconnect:
        server.disconnect(player_id)
        await server.broadcast({"type": "leave", "id": player_id})

# --- ИНТЕРФЕЙС И КЛИЕНТСКИЙ КОД ---

html_content = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>TACTICAL ARENA 3D</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; user-select: none; background: #eceff1; color: #333; touch-action: none; }
        
        #login_screen { position: fixed; inset: 0; background: radial-gradient(circle at center, #eceff1 0%, #cfd8dc 100%); display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 100; }
        .menu-card { background: #ffffff; border: 1px solid #b0bec5; padding: 35px; border-radius: 12px; text-align: center; box-shadow: 0 10px 25px rgba(0,0,0,0.08); width: 320px; max-width: 85%; }
        .menu-card h1 { font-size: 24px; font-weight: 800; margin: 0 0 20px 0; letter-spacing: 0.5px; color: #263238; }
        .input-field { width: 100%; padding: 12px; font-size: 16px; border: 2px solid #cfd8dc; background: #f8f9fa; color: #333; border-radius: 6px; outline: none; box-sizing: border-box; text-align: center; font-weight: 600; }
        .input-field:focus { border-color: #2196f3; }
        .btn-submit { width: 100%; margin-top: 15px; padding: 14px; font-size: 16px; cursor: pointer; background: #2196f3; color: white; border: none; border-radius: 6px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; box-shadow: 0 4px 12px rgba(33,150,243,0.3); transition: all 0.15s; }
        .btn-submit:hover { background: #1e88e5; transform: translateY(-1px); }
        
        #hud { position: absolute; top: 20px; left: 20px; background: rgba(255,255,255,0.9); padding: 14px 20px; border-radius: 8px; border-left: 5px solid #2196f3; pointer-events: none; display: none; z-index: 10; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }
        #map_name { font-weight: 800; font-size: 15px; color: #263238; text-transform: uppercase; }
        #round_info, #score_info { font-size: 13px; margin-top: 4px; color: #546e7a; font-family: monospace; font-weight: 600; }
        
        /* Переработанный четкий прицел с хитмаркером */
        #crosshair_container { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); pointer-events: none; z-index: 10; display:none; }
        .crosshair-dot { width: 4px; height: 4px; background: #2196f3; border-radius: 50%; border: 1px solid #fff; }
        #hitmarker { position: absolute; top: -10px; left: -10px; width: 24px; height: 24px; opacity: 0; transition: opacity 0.05s; }
        #hitmarker::before, #hitmarker::after { content: ''; position: absolute; background: #ff1744; }
        #hitmarker::before { top: 11px; left: 0; width: 24px; height: 2px; transform: rotate(45deg); }
        #hitmarker::after { top: 11px; left: 0; width: 24px; height: 2px; transform: rotate(-45deg); }
        
        #hp_container { position: absolute; bottom: 30px; left: 50%; transform: translateX(-50%); width: 240px; height: 12px; background: rgba(255,255,255,0.6); border-radius: 6px; overflow: hidden; display: none; box-shadow: 0 4px 10px rgba(0,0,0,0.05); z-index: 10; border: 2px solid #ffffff; }
        #hp_bar { width: 100%; height: 100%; background: #ff1744; transition: width 0.1s; }
        #damage_flash { position: absolute; inset: 0; background: rgba(255,23,68,0.25); pointer-events: none; opacity: 0; transition: opacity 0.08s; z-index: 5; }
        
        #killfeed { position: absolute; top: 20px; right: 20px; display: flex; flex-direction: column; gap: 6px; pointer-events: none; z-index: 10; font-family: monospace; }
        .kill-msg { background: rgba(255,255,255,0.9); border: 1px solid #cfd8dc; padding: 6px 14px; border-radius: 6px; color: #263238; font-size: 13px; font-weight: 600; box-shadow: 0 2px 8px rgba(0,0,0,0.04); animation: slideIn 0.2s cubic-bezier(0.1, 0.9, 0.2, 1) both; }
        @keyframes slideIn { from { opacity: 0; transform: translateX(40px); } to { opacity: 1; transform: translateX(0); } }
        
        /* МОБИЛЬНЫЕ СТИКЕРЫ */
        .touch-pad { position: absolute; bottom: 0; top: 30%; width: 45%; z-index: 20; display: none; }
        #pad_left { left: 0; }
        #pad_right { right: 0; }
        .joystick-base { position: absolute; width: 80px; height: 80px; background: rgba(0,0,0,0.03); border: 2px solid rgba(0,0,0,0.1); border-radius: 50%; display: none; pointer-events: none; transform: translate(-50%, -50%); }
        .joystick-stick { position: absolute; width: 30px; height: 30px; background: #2196f3; border-radius: 50%; top: 25px; left: 25px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
        #btn_fire { position: absolute; bottom: 40px; right: 40px; width: 80px; height: 80px; background: rgba(33,150,243,0.15); border: 2px solid #2196f3; border-radius: 50%; display: none; justify-content: center; align-items: center; font-weight: 800; font-size: 15px; color: #1e88e5; z-index: 30; }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
    <div id="login_screen">
        <div class="menu-card">
            <h1>TACTICAL STRIKE</h1>
            <input type="text" id="nickname_input" class="input-field" placeholder="OPERATOR CALLSIGN" value="Operator" maxlength="12">
            <button id="play_btn" class="btn-submit">ENTER ARENA</button>
        </div>
    </div>

    <div id="hud">
        <div id="map_name">LOADING MAP...</div>
        <div id="round_info">ROUND: 1</div>
        <div id="score_info">KILLS: 0</div>
    </div>

    <div id="killfeed"></div>
    <div id="hp_container"><div id="hp_bar"></div></div>
    
    <div id="crosshair_container">
        <div class="crosshair-dot"></div>
        <div id="hitmarker"></div>
    </div>
    
    <div id="damage_flash"></div>

    <div id="pad_left" class="touch-pad"></div>
    <div id="pad_right" class="touch-pad"></div>
    <div id="joy_left" class="joystick-base"><div class="joystick-stick"></div></div>
    <div id="joy_right" class="joystick-base"><div class="joystick-stick"></div></div>
    <div id="btn_fire">FIRE</div>

    <script>
        let scene, camera, renderer, sunLight, hemiLight;
        let players = {}, myId = null, myName = "Operator", ws;
        let keys = { w:0, a:0, s:0, d:0 };
        let moveSpeed = 0.15, yaw = 0, pitch = 0;
        let myHp = 100, myScore = 0, isMobile = false;

        let weapon, isShooting = false;
        let mapGroup = new THREE.Group(), collidableObjects = [], raycastTargets = [];

        let idMove = null, idLook = null;
        let dataMove = { startX: 0, startY: 0, curX: 0, curY: 0 };
        let dataLook = { startX: 0, startY: 0 };
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
            camera = new THREE.PerspectiveCamera(70, window.innerWidth / window.innerHeight, 0.1, 500);
            
            renderer = new THREE.WebGLRenderer({ antialias: true });
            renderer.setSize(window.innerWidth, window.innerHeight);
            renderer.outputEncoding = THREE.sRGBEncoding;
            document.body.appendChild(renderer.domElement);

            // КРИСТАЛЬНО ЧИСТЫЙ СВЕТ (Как на киберспортивных картах)
            hemiLight = new THREE.HemisphereLight(0xffffff, 0x444444, 0.7);
            hemiLight.position.set(0, 20, 0);
            scene.add(hemiLight);

            sunLight = new THREE.DirectionalLight(0xffffff, 0.8);
            sunLight.position.set(20, 40, 20);
            scene.add(sunLight);

            // Светлая бетонная подложка пола
            const floorMat = new THREE.MeshStandardMaterial({ color: 0xeeeeee, roughness: 0.6 });
            const floor = new THREE.Mesh(new THREE.PlaneGeometry(120, 120), floorMat);
            floor.rotation.x = -Math.PI / 2;
            scene.add(floor);

            // Контрастная сетка разметки полигона
            const grid = new THREE.GridHelper(120, 40, 0x90caf9, 0xe0e0e0);
            grid.position.y = 0.01;
            scene.add(grid);

            scene.add(mapGroup);
            buildWeapon();
            camera.position.y = 1.65;

            // ФИКС СТРЕЛЬБЫ НА ПК: Разделяем захват мыши и ведение огня
            if(!isMobile) {
                document.body.addEventListener('click', () => {
                    if(document.pointerLockElement !== document.body) {
                        document.body.requestPointerLock();
                    }
                });
                
                window.addEventListener('mousedown', (e) => {
                    // Стреляем только если мышка захвачена и нажат левый клик (button 0)
                    if (document.pointerLockElement === document.body && e.button === 0) {
                        performShoot();
                    }
                });

                document.addEventListener('mousemove', (e) => {
                    if (document.pointerLockElement === document.body) {
                        yaw -= e.movementX * 0.0022;
                        pitch -= e.movementY * 0.0022;
                        pitch = Math.max(-Math.PI/2.3, Math.min(Math.PI/2.3, pitch));
                        camera.rotation.set(pitch, yaw, 0, 'YXZ');
                    }
                });
                
                window.addEventListener('keydown', (e) => { if(e.key.toLowerCase() in keys) keys[e.key.toLowerCase()] = 1; });
                window.addEventListener('keyup', (e) => { if(e.key.toLowerCase() in keys) keys[e.key.toLowerCase()] = 0; });
            } else {
                initMobileControls();
            }

            window.addEventListener('resize', () => {
                camera.aspect = window.innerWidth / window.innerHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(window.innerWidth, window.innerHeight);
            });

            setInterval(sendNetworkPosition, 33);
            animate();
        }

        function buildWeapon() {
            weapon = new THREE.Group();
            const body = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.04, 0.35), new THREE.MeshStandardMaterial({ color: 0x37474f, roughness: 0.4 }));
            const barrel = new THREE.Mesh(new THREE.CylinderGeometry(0.01, 0.01, 0.1), new THREE.MeshStandardMaterial({ color: 0x212121 }));
            barrel.rotation.x = Math.PI / 2;
            barrel.position.set(0, 0, -0.2);
            weapon.add(body, barrel);
            
            weapon.position.set(0.15, -0.16, -0.28);
            camera.add(weapon);
            scene.add(camera);
        }

        function generateMapStructure(mapData) {
            while(mapGroup.children.length > 0){ mapGroup.remove(mapGroup.children[0]); }
            collidableObjects = [];
            raycastTargets = [];

            renderer.setClearColor(mapData.sky);
            scene.background = new THREE.Color(mapData.sky);
            scene.fog = new THREE.FogExp2(mapData.sky, 0.012);
            
            // Контрастные матовые тренировочные блоки
            const wallMaterial = new THREE.MeshStandardMaterial({ color: mapData.wall, roughness: 0.7 });

            const borders = [
                {x:0, z:-50, w:100, d:2, h:5}, {x:0, z:50, w:100, d:2, h:5},
                {x:-50, z:0, w:2, d:100, h:5}, {x:50, z:0, w:2, d:100, h:5}
            ];
            
            let seed = mapData.name.charCodeAt(0) || 3;
            for(let i=0; i<25; i++) {
                let w = 3 + (i % 3) * 3;
                let d = 3 + (i % 2) * 3;
                let h = 2 + (i % 3) * 1.5;
                borders.push({
                    x: Math.sin(i * seed) * 32,
                    z: Math.cos(i * 13) * 32,
                    w: w, d: d, h: h
                });
            }

            borders.forEach(b => {
                const mesh = new THREE.Mesh(new THREE.BoxGeometry(b.w, b.h, b.d), wallMaterial);
                mesh.position.set(b.x, b.h/2, b.z);
                mapGroup.add(mesh);
                collidableObjects.push(mesh);
                raycastTargets.push(mesh);
            });
        }

        // --- МГНОВЕННЫЙ ХИТСКАН И ТРАССЕРЫ ---
        function performShoot() {
            if(isShooting) return;
            isShooting = true;

            // Отдача затвора
            weapon.position.z = -0.24;
            setTimeout(() => weapon.position.z = -0.28, 60);

            // Контрастный красный трассер пули для дневного освещения
            const points = [
                new THREE.Vector3(0, -0.02, -0.2).applyMatrix4(weapon.matrixWorld),
                new THREE.Vector3(0, 0, -35).applyMatrix4(weapon.matrixWorld)
            ];
            const tracerGeo = new THREE.BufferGeometry().setFromPoints(points);
            const tracer = new THREE.Line(tracerGeo, new THREE.LineBasicMaterial({ color: 0xff1744, linewidth: 2 }));
            scene.add(tracer);
            setTimeout(() => scene.remove(tracer), 40);

            // Хитскан луча
            const dir = new THREE.Vector3();
            camera.getWorldDirection(dir);
            const ray = new THREE.Raycaster(camera.position, dir, 0, 120);
            const hits = ray.intersectObjects(raycastTargets, false);

            if(hits.length > 0) {
                let targetMesh = hits[0].object;
                if(targetMesh.userData.playerId && ws) {
                    ws.send(JSON.stringify({ type: "hit", target: targetMesh.userData.playerId }));
                }
            }
            setTimeout(() => { isShooting = false; }, 140);
        }

        function triggerHitmarker() {
            const hm = document.getElementById("hitmarker");
            hm.style.opacity = "1";
            setTimeout(() => hm.style.opacity = "0", 70);
        }

        // --- СВЕТЛЫЕ ТЕКСТОВЫЕ ТАБЛИЧКИ ИГРОКОВ ---
        function generateNameplate(name, hp) {
            const canvas = document.createElement('canvas');
            canvas.width = 240; canvas.height = 60;
            const ctx = canvas.getContext('2d');
            
            ctx.font = "bold 20px sans-serif";
            ctx.fillStyle = "#263238";
            ctx.textAlign = "center";
            ctx.fillText(name, 120, 22);
            
            ctx.fillStyle = "#cfd8dc";
            ctx.fillRect(40, 35, 160, 8);
            ctx.fillStyle = "#00e676"; // Яркий зеленый цвет здоровья врага
            ctx.fillRect(40, 35, Math.max(0, hp) * 1.6, 8);
            
            const tex = new THREE.CanvasTexture(canvas);
            const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex }));
            sprite.scale.set(1.6, 0.4, 1);
            return sprite;
        }

        function updatePlayerLabel(id) {
            let p = players[id];
            if(!p) return;
            if(p.label) p.group.remove(p.label);
            p.label = generateNameplate(p.name, p.hp);
            p.label.position.y = 2.1;
            p.group.add(p.label);
        }

        function spawnEnemyCharacter(id, info) {
            const group = new THREE.Group();
            
            // Яркая, контрастная форма оранжевого цвета (чтобы выделялась на фоне полигона)
            const body = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, 1.6, 12), new THREE.MeshStandardMaterial({ color:  0xffab40, roughness: 0.5 }));
            body.position.y = 0.8;
            
            const head = new THREE.Mesh(new THREE.SphereGeometry(0.2, 10, 10), new THREE.MeshStandardMaterial({ color: 0x263238 }));
            head.position.y = 1.6;
            
            const hitbox = new THREE.Mesh(new THREE.BoxGeometry(0.6, 1.7, 0.6), new THREE.MeshBasicMaterial({ visible: false }));
            hitbox.position.y = 0.85;
            hitbox.userData.playerId = id;

            group.add(body, head, hitbox);
            group.position.set(info.x, 0, info.z);
            scene.add(group);

            players[id] = { 
                group: group, hitbox: hitbox, name: info.name, hp: info.hp,
                targetX: info.x, targetZ: info.z, targetRy: info.ry 
            };
            raycastTargets.push(hitbox);
            updatePlayerLabel(id);
        }

        // --- МОБИЛЬНЫЙ МУЛЬТИТАЧ ---
        function initMobileControls() {
            const pLeft = document.getElementById("pad_left");
            const pRight = document.getElementById("pad_right");
            const jLeft = document.getElementById("joy_left");
            const jRight = document.getElementById("joy_right");
            const sLeft = jLeft.querySelector(".joystick-stick");
            const sRight = jRight.querySelector(".joystick-stick");

            pLeft.addEventListener("touchstart", (e) => {
                e.preventDefault(); let t = e.changedTouches[0]; idMove = t.identifier;
                dataMove.startX = t.clientX; dataMove.startY = t.clientY;
                jLeft.style.display = "block"; jLeft.style.left = t.clientX + "px"; jLeft.style.top = t.clientY + "px";
            });
            pLeft.addEventListener("touchmove", (e) => {
                e.preventDefault();
                for(let t of e.touches) {
                    if(t.identifier === idMove) {
                        let dx = t.clientX - dataMove.startX, dy = t.clientY - dataMove.startY;
                        let len = Math.min(25, Math.sqrt(dx*dx + dy*dy)), ang = Math.atan2(dy, dx);
                        dataMove.curX = Math.cos(ang) * (len / 25); dataMove.curY = Math.sin(ang) * (len / 25);
                        sLeft.style.transform = `translate(${Math.cos(ang)*len}px, ${Math.sin(ang)*len}px)`;
                    }
                }
            });
            pLeft.addEventListener("touchend", (e) => { for(let t of e.changedTouches) if(t.identifier === idMove) { idMove = null; dataMove.curX = 0; dataMove.curY = 0; jLeft.style.display = "none"; } });

            pRight.addEventListener("touchstart", (e) => {
                e.preventDefault(); let t = e.changedTouches[0]; idLook = t.identifier;
                dataLook.startX = t.clientX; dataLook.startY = t.clientY;
                jRight.style.display = "block"; jRight.style.left = t.clientX + "px"; jRight.style.top = t.clientY + "px";
            });
            pRight.addEventListener("touchmove", (e) => {
                e.preventDefault();
                for(let t of e.touches) {
                    if(t.identifier === idLook) {
                        let dx = t.clientX - dataLook.startX, dy = t.clientY - dataLook.startY;
                        yaw -= dx * 0.005; pitch -= dy * 0.005;
                        pitch = Math.max(-Math.PI/2.3, Math.min(Math.PI/2.3, pitch));
                        camera.rotation.set(pitch, yaw, 0, 'YXZ');
                        sRight.style.transform = `translate(${Math.min(20, dx)}px, ${Math.min(20, dy)}px)`;
                        dataLook.startX = t.clientX; dataLook.startY = t.clientY;
                    }
                }
            });
            pRight.addEventListener("touchend", (e) => { for(let t of e.changedTouches) if(t.identifier === idLook) { idLook = null; jRight.style.display = "none"; } });

            document.getElementById("btn_fire").addEventListener("touchstart", (e) => { e.preventDefault(); performShoot(); });
        }

        // --- СЕТЕВАЯ СИНХРОНИЗАЦИЯ ---
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
            ws = new WebSocket(proto + location.host + "/ws/live/" + Math.floor(Math.random()*99999));
            
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
                    players[data.id].targetX = data.x; players[data.id].targetZ = data.z; players[data.id].targetRy = data.ry;
                }
                else if (data.type === "hp_update") {
                    if(data.id === myId) { setHpAmount(data.hp); triggerFlinch(); }
                    else if(players[data.id]) { players[data.id].hp = data.hp; updatePlayerLabel(data.id); }
                    if(data.by === myId) { triggerHitmarker(); } // Если попали мы — запуск хитмаркера
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
                    scene.remove(players[data.id].group); delete players[data.id];
                }
            };
        }

        function checkCollisions(pos) {
            for(let i=0; i<collidableObjects.length; i++) {
                let box = new THREE.Box3().setFromObject(collidableObjects[i]);
                let pBox = new THREE.Box3(
                    new THREE.Vector3(pos.x - 0.35, 0, pos.z - 0.35),
                    new THREE.Vector3(pos.x + 0.35, 2, pos.z + 0.35)
                );
                if(box.intersectsBox(pBox)) return true;
            }
            return false;
        }

        function pushToKillfeed(killer, victim) {
            const kf = document.getElementById("killfeed");
            const div = document.createElement("div"); div.className = "kill-msg";
            div.innerHTML = `⚠️ <b>${killer}</b> ликвидировал <b>${victim}</b>`;
            kf.appendChild(div);
            setTimeout(() => div.remove(), 4000);
        }

        function triggerFlinch() {
            document.getElementById("damage_flash").style.opacity = "1";
            setTimeout(() => document.getElementById("damage_flash").style.opacity = "0", 80);
            camera.position.y += 0.05; setTimeout(() => camera.position.y = 1.65, 40);
        }

        function setHpAmount(hp) { myHp = hp; document.getElementById("hp_bar").style.width = hp + "%"; }

        document.getElementById("play_btn").addEventListener("click", () => {
            let n = document.getElementById("nickname_input").value.trim(); if(n) myName = n;
            checkMobile();
            document.getElementById("login_screen").style.display = "none";
            document.getElementById("hud").style.display = "block";
            document.getElementById("hp_container").style.display = "block";
            document.getElementById("crosshair_container").style.display = "block";
            init3D(); initNetwork();
        });

        // --- ИГРОВОЙ ТИК (ИНТЕРПОЛЯЦИЯ) ---
        function animate() {
            requestAnimationFrame(animate);
            if(!scene || !camera) return;

            for(let id in players) {
                let p = players[id];
                if(id !== myId) {
                    p.group.position.x += (p.targetX - p.group.position.x) * 0.25;
                    p.group.position.z += (p.targetZ - p.group.position.z) * 0.25;
                    p.group.rotation.y += (p.targetRy - p.group.rotation.y) * 0.25;
                    if(p.label) p.label.lookAt(camera.position);
                }
            }

            const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion); forward.y = 0; forward.normalize();
            const side = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion); side.y = 0; side.normalize();
            
            let nextPos = camera.position.clone(), isMoving = false;

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
                weapon.position.y = -0.16 + Math.sin(Date.now() * 0.01) * 0.005;
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
