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
        
        # Сброс HP и позиций для всех игроков при новом раунде
        for pid in server.players:
            server.players[pid]["hp"] = 100
            server.players[pid]["x"] = random.uniform(-20, 20)
            server.players[pid]["z"] = random.uniform(-20, 20)
            
        await server.broadcast({
            "type": "new_round", 
            "round": server.current_round, 
            "map": server.current_map,
            "players": server.players # Передаем обновленное состояние игроков
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
            elif msg["type"] == "shoot":
                # Транслируем выстрел другим игрокам для отображения эффектов
                await server.broadcast({"type": "enemy_shoot", "id": player_id})
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
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; user-select: none; background: #000; color: #fff; touch-action: none; }
        
        #login_screen { position: fixed; inset: 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 100; }
        .menu-card { background: rgba(255, 255, 255, 0.1); backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.2); padding: 40px; border-radius: 20px; text-align: center; box-shadow: 0 20px 50px rgba(0,0,0,0.3); width: 340px; }
        .menu-card h1 { font-size: 32px; font-weight: 900; margin: 0 0 30px 0; letter-spacing: 2px; color: #fff; text-shadow: 0 2px 10px rgba(0,0,0,0.2); }
        .input-field { width: 100%; padding: 15px; font-size: 18px; border: none; background: rgba(255,255,255,0.9); color: #333; border-radius: 10px; outline: none; box-sizing: border-box; text-align: center; font-weight: 700; margin-bottom: 20px; }
        .btn-submit { width: 100%; padding: 18px; font-size: 18px; cursor: pointer; background: #ff4757; color: white; border: none; border-radius: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; transition: all 0.2s; box-shadow: 0 5px 15px rgba(255,71,87,0.4); }
        .btn-submit:hover { background: #ff6b81; transform: translateY(-2px); }
        
        #hud_top_left { position: absolute; top: 20px; left: 20px; display: flex; gap: 15px; pointer-events: none; z-index: 10; display: none; }
        .stat-box { background: rgba(0,0,0,0.6); backdrop-filter: blur(5px); padding: 10px 20px; border-radius: 12px; display: flex; align-items: center; gap: 10px; border: 1px solid rgba(255,255,255,0.1); }
        .stat-icon { width: 24px; height: 24px; }
        .stat-val { font-size: 22px; font-weight: 900; font-family: 'Arial Black', sans-serif; }
        
        #map_display { position: absolute; top: 20px; right: 20px; text-align: right; pointer-events: none; z-index: 10; display: none; }
        #map_name { font-weight: 900; font-size: 18px; color: #fff; text-transform: uppercase; text-shadow: 0 2px 5px rgba(0,0,0,0.5); }
        #round_info { font-size: 14px; color: #ff4757; font-weight: 800; }

        #crosshair_container { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); pointer-events: none; z-index: 10; display:none; }
        .crosshair-line { position: absolute; background: #00ff00; box-shadow: 0 0 5px rgba(0,255,0,0.5); }
        .ch-v { width: 2px; height: 12px; left: -1px; }
        .ch-h { width: 12px; height: 2px; top: -1px; }
        .ch-t { top: -15px; } .ch-b { bottom: -15px; } .ch-l { left: -15px; } .ch-r { right: -15px; }
        
        #hp_container { display: none; } /* Old HP hidden */
        
        #damage_flash { position: absolute; inset: 0; background: radial-gradient(circle, transparent 40%, rgba(255,0,0,0.4) 100%); pointer-events: none; opacity: 0; transition: opacity 0.1s; z-index: 5; }
        
        #killfeed { position: absolute; bottom: 100px; left: 20px; display: flex; flex-direction: column-reverse; gap: 8px; pointer-events: none; z-index: 10; }
        .kill-msg { background: rgba(0,0,0,0.5); padding: 8px 15px; border-radius: 8px; color: #fff; font-size: 14px; font-weight: 700; border-left: 4px solid #ff4757; animation: slideUp 0.3s ease-out; }
        @keyframes slideUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
        
        /* TOUCH CONTROLS - REWRITTEN V3 */
        #touch_controls { position: absolute; inset: 0; z-index: 20; display: none; pointer-events: none; }
        .touch-zone { position: absolute; bottom: 0; height: 100%; width: 50%; pointer-events: auto; }
        #zone_move { left: 0; }
        #zone_look { right: 0; }
        
        .joystick-base { position: absolute; width: 120px; height: 120px; background: rgba(255,255,255,0.1); border: 2px solid rgba(255,255,255,0.2); border-radius: 50%; display: none; pointer-events: none; transform: translate(-50%, -50%); backdrop-filter: blur(5px); }
        .joystick-stick { position: absolute; width: 50px; height: 50px; background: #fff; border-radius: 50%; top: 35px; left: 35px; box-shadow: 0 5px 15px rgba(0,0,0,0.3); }
        
        #mobile_buttons { position: absolute; bottom: 40px; right: 40px; display: flex; flex-direction: column; gap: 20px; pointer-events: none; }
        .m-btn { width: 85px; height: 85px; background: rgba(255,255,255,0.1); border: 3px solid rgba(255,255,255,0.3); border-radius: 50%; display: flex; justify-content: center; align-items: center; font-weight: 900; font-size: 18px; color: #fff; pointer-events: auto; backdrop-filter: blur(5px); transition: transform 0.1s, background 0.1s; user-select: none; -webkit-tap-highlight-color: transparent; }
        .m-btn:active { transform: scale(0.9); background: rgba(255,71,87,0.5); border-color: #ff4757; }
        #btn_fire { background: rgba(255,71,87,0.3); border-color: #ff4757; width: 100px; height: 100px; }
        #btn_jump { font-size: 24px; }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
    <div id="login_screen">
        <div class="menu-card">
            <h1>POLY STRIKE</h1>
            <input type="text" id="nickname_input" class="input-field" placeholder="YOUR NAME" value="Player" maxlength="12">
            <button id="play_btn" class="btn-submit">BATTLE START</button>
        </div>
    </div>

    <div id="hud_top_left">
        <div class="stat-box">
            <div style="color: #ff4757; font-size: 24px;">❤</div>
            <div id="hp_val" class="stat-val">100</div>
        </div>
        <div class="stat-box">
            <div style="color: #ffa502; font-size: 24px;">★</div>
            <div id="score_val" class="stat-val">0</div>
        </div>
    </div>

    <div id="map_display">
        <div id="map_name">ARENA</div>
        <div id="round_info">ROUND 1</div>
    </div>

    <div id="killfeed">
    </div>
    
    <div id="crosshair_container">
        <div class="crosshair-line ch-v ch-t"></div>
        <div class="crosshair-line ch-v ch-b"></div>
        <div class="crosshair-line ch-h ch-l"></div>
        <div class="crosshair-line ch-h ch-r"></div>
        <div id="hitmarker"></div>
    </div>
    
    <div id="damage_flash"></div>

    <div id="touch_controls">
        <div id="zone_move" class="touch-zone"></div>
        <div id="zone_look" class="touch-zone"></div>
        <div id="joy_move" class="joystick-base"><div class="joystick-stick"></div></div>
        
        <div id="mobile_buttons">
            <div id="btn_jump" class="m-btn">JUMP</div>
            <div id="btn_fire" class="m-btn">FIRE</div>
        </div>
    </div>

    <script>
        let scene, camera, renderer, sunLight, hemiLight;
        let players = {}, myId = null, myName = "Player", ws;
        let keys = { KeyW:0, KeyA:0, KeyS:0, KeyD:0, Space:0 };
        let moveSpeed = 0.18, yaw = 0, pitch = 0;
        let myHp = 100, myScore = 0, isMobile = false;

        // Физика
        let velocityY = 0;
        const gravity = -0.012;
        const jumpForce = 0.25;
        let canJump = true;

        let weapon, isShooting = false;
        let mapGroup = new THREE.Group(), collidableObjects = [], raycastTargets = [];

        let idMove = null, idLook = null;
        let dataMove = { startX: 0, startY: 0, curX: 0, curY: 0 };
        let dataLook = { startX: 0, startY: 0 };
        let lastPos = new THREE.Vector3(), lastYaw = 0;

        function checkMobile() {
            isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || (window.innerWidth < 900);
            if(isMobile) {
                document.getElementById("touch_controls").style.display = "block";
            }
        }

        function init3D() {
            scene = new THREE.Scene();
            camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
            
            renderer = new THREE.WebGLRenderer({ antialias: true });
            renderer.setSize(window.innerWidth, window.innerHeight);
            renderer.shadowMap.enabled = true;
            renderer.shadowMap.type = THREE.PCFSoftShadowMap;
            renderer.toneMapping = THREE.ReinhardToneMapping;
            renderer.outputEncoding = THREE.sRGBEncoding;
            document.body.appendChild(renderer.domElement);

            // МЯГКИЙ ГРАДИЕНТНЫЙ СВЕТ (как на картинке)
            const ambient = new THREE.AmbientLight(0xffffff, 0.5);
            scene.add(ambient);

            sunLight = new THREE.DirectionalLight(0xffffff, 1.2);
            sunLight.position.set(50, 100, 50);
            sunLight.castShadow = true;
            sunLight.shadow.mapSize.width = 2048;
            sunLight.shadow.mapSize.height = 2048;
            sunLight.shadow.camera.near = 0.5;
            sunLight.shadow.camera.far = 500;
            sunLight.shadow.camera.left = -100;
            sunLight.shadow.camera.right = 100;
            sunLight.shadow.camera.top = 100;
            sunLight.shadow.camera.bottom = -100;
            scene.add(sunLight);

            scene.add(mapGroup);
            buildWeapon();
            camera.position.y = 1.7;

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
                
                window.addEventListener('keydown', (e) => { 
                    if(e.code in keys) keys[e.code] = 1; 
                });
                window.addEventListener('keyup', (e) => { 
                    if(e.code in keys) keys[e.code] = 0; 
                });
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
            scene.fog = new THREE.Fog(mapData.sky, 10, 150);
            
            // ПОЛ (Стилизованные плитки)
            const floorGeo = new THREE.PlaneGeometry(200, 200);
            const floorMat = new THREE.MeshStandardMaterial({ color: mapData.ground, roughness: 0.8 });
            const floor = new THREE.Mesh(floorGeo, floorMat);
            floor.rotation.x = -Math.PI / 2;
            floor.receiveShadow = true;
            mapGroup.add(floor);

            // Сетка на полу для стиля
            const grid = new THREE.GridHelper(200, 50, 0x000000, 0x000000);
            grid.position.y = 0.05;
            grid.material.opacity = 0.1;
            grid.material.transparent = true;
            mapGroup.add(grid);

            // ГЕНЕРАЦИЯ СТИЛИЗОВАННОЙ КАРТЫ (как на картинке)
            const colors = [0xff4757, 0x2ed573, 0x1e90ff, 0xffa502, 0x747d8c];
            
            // Арка в центре
            const archGroup = new THREE.Group();
            for(let a=0; a<Math.PI; a+=0.2) {
                const block = new THREE.Mesh(
                    new THREE.BoxGeometry(4, 4, 6),
                    new THREE.MeshStandardMaterial({ color: 0xffa502, roughness: 0.6 })
                );
                block.position.set(Math.cos(a)*15, Math.sin(a)*15, 0);
                block.rotation.z = a + Math.PI/2;
                block.castShadow = true;
                block.receiveShadow = true;
                archGroup.add(block);
                collidableObjects.push(block);
            }
            archGroup.position.set(0, 2, -20);
            mapGroup.add(archGroup);

            // Разбросанные геометрические фигуры
            for(let i=0; i<40; i++) {
                const size = 2 + Math.random() * 5;
                const type = Math.floor(Math.random() * 3);
                let geo;
                if(type === 0) geo = new THREE.BoxGeometry(size, size, size);
                else if(type === 1) geo = new THREE.TetrahedronGeometry(size);
                else geo = new THREE.OctahedronGeometry(size);

                const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ 
                    color: colors[i % colors.length],
                    roughness: 0.5 
                }));
                
                mesh.position.set(
                    (Math.random()-0.5) * 100,
                    size/2,
                    (Math.random()-0.5) * 100
                );
                // Избегаем центра
                if(mesh.position.length() < 15) mesh.position.multiplyScalar(3);

                mesh.rotation.set(Math.random(), Math.random(), Math.random());
                mesh.castShadow = true;
                mesh.receiveShadow = true;
                mapGroup.add(mesh);
                collidableObjects.push(mesh);
                raycastTargets.push(mesh);
            }

            // Границы карты
            const wallMat = new THREE.MeshStandardMaterial({ color: 0x2f3542 });
            const wallGeo = [
                {w:200, h:20, d:5, x:0, z:100}, {w:200, h:20, d:5, x:0, z:-100},
                {w:5, h:20, d:200, x:100, z:0}, {w:5, h:20, d:200, x:-100, z:0}
            ];
            wallGeo.forEach(w => {
                const mesh = new THREE.Mesh(new THREE.BoxGeometry(w.w, w.h, w.d), wallMat);
                mesh.position.set(w.x, w.h/2, w.z);
                mapGroup.add(mesh);
                collidableObjects.push(mesh);
            });
        }

        // --- МГНОВЕННЫЙ ХИТСКАН И ТРАССЕРЫ ---
        function performShoot() {
            if(isShooting) return;
            isShooting = true;

            // Отдача затвора
            weapon.position.z = -0.24;
            setTimeout(() => weapon.position.z = -0.28, 60);
            
            // Вспышка (Muzzle Flash)
            const flash = new THREE.PointLight(0xffff00, 2, 5);
            flash.position.set(0, 0, -0.3).applyMatrix4(weapon.matrixWorld);
            scene.add(flash);
            setTimeout(() => scene.remove(flash), 40);

            // Контрастный трассер пули
            const points = [
                new THREE.Vector3(0, 0, -0.2).applyMatrix4(weapon.matrixWorld),
                new THREE.Vector3(0, 0, -100).applyMatrix4(weapon.matrixWorld)
            ];
            const tracerGeo = new THREE.BufferGeometry().setFromPoints(points);
            const tracer = new THREE.Line(tracerGeo, new THREE.LineBasicMaterial({ color: 0xffff00, transparent: true, opacity: 0.8 }));
            scene.add(tracer);
            setTimeout(() => scene.remove(tracer), 40);

            if(ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: "shoot" }));
            }

            // Хитскан луча
            const dir = new THREE.Vector3();
            camera.getWorldDirection(dir);
            const ray = new THREE.Raycaster(camera.position, dir, 0, 150);
            const hits = ray.intersectObjects(raycastTargets, false);

            if(hits.length > 0) {
                let targetMesh = hits[0].object;
                if(targetMesh.userData.playerId) {
                    ws.send(JSON.stringify({ type: "hit", target: targetMesh.userData.playerId }));
                }
            }
            setTimeout(() => { isShooting = false; }, 120);
        }

        function performEnemyShoot(id) {
            const p = players[id];
            if(!p || !p.weapon) return;

            // Вспышка у врага
            const flash = new THREE.PointLight(0xffff00, 2, 5);
            flash.position.set(0, 0, -0.4).applyMatrix4(p.weapon.matrixWorld);
            scene.add(flash);
            setTimeout(() => scene.remove(flash), 40);

            // Трассер у врага
            const start = new THREE.Vector3(0, 0, -0.4).applyMatrix4(p.weapon.matrixWorld);
            const end = new THREE.Vector3(0, 0, -100).applyMatrix4(p.weapon.matrixWorld);
            const tracerGeo = new THREE.BufferGeometry().setFromPoints([start, end]);
            const tracer = new THREE.Line(tracerGeo, new THREE.LineBasicMaterial({ color: 0xffff00, transparent: true, opacity: 0.5 }));
            scene.add(tracer);
            setTimeout(() => scene.remove(tracer), 40);
        }

        function triggerHitmarker() {
            const hm = document.getElementById("hitmarker");
            hm.style.opacity = "1";
            setTimeout(() => hm.style.opacity = "0", 70);
            
            // Звуковой эффект (имитация) или легкая вибрация пушки
            weapon.position.z -= 0.02;
            setTimeout(() => weapon.position.z += 0.02, 50);
        }

        // --- УЛУЧШЕННЫЕ ВИЗУАЛЬНЫЕ ЭФФЕКТЫ ---
        function createExplosion(pos) {
            const count = 12;
            for(let i=0; i<count; i++) {
                const part = new THREE.Mesh(
                    new THREE.BoxGeometry(0.1, 0.1, 0.1),
                    new THREE.MeshBasicMaterial({ color: 0xff1744 })
                );
                part.position.copy(pos);
                scene.add(part);
                
                const vel = new THREE.Vector3(
                    (Math.random()-0.5)*0.2,
                    Math.random()*0.2,
                    (Math.random()-0.5)*0.2
                );
                
                const anim = () => {
                    part.position.add(vel);
                    vel.y -= 0.01;
                    part.scale.multiplyScalar(0.95);
                    if(part.scale.x > 0.01) requestAnimationFrame(anim);
                    else scene.remove(part);
                };
                anim();
            }
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
            
            // ТЕЛО (Blocky Stylized)
            const body = new THREE.Mesh(
                new THREE.BoxGeometry(0.8, 1.2, 0.5), 
                new THREE.MeshStandardMaterial({ color: 0x2ed573, roughness: 0.4 })
            );
            body.position.y = 0.9;
            body.castShadow = true;
            
            // НОГИ
            const legGeo = new THREE.BoxGeometry(0.3, 0.8, 0.3);
            const legMat = new THREE.MeshStandardMaterial({ color: 0xff4757, roughness: 0.4 });
            const legL = new THREE.Mesh(legGeo, legMat);
            legL.position.set(-0.2, 0.4, 0);
            const legR = new THREE.Mesh(legGeo, legMat);
            legR.position.set(0.2, 0.4, 0);
            
            // ГОЛОВА (Boxy)
            const headGroup = new THREE.Group();
            const head = new THREE.Mesh(
                new THREE.BoxGeometry(0.5, 0.5, 0.5), 
                new THREE.MeshStandardMaterial({ color: 0x2f3542, roughness: 0.3 })
            );
            
            // ГЛАЗА (Светящиеся)
            const eyeGeo = new THREE.BoxGeometry(0.4, 0.1, 0.1);
            const eyeMat = new THREE.MeshBasicMaterial({ color: 0x00ff00 });
            const eyes = new THREE.Mesh(eyeGeo, eyeMat);
            eyes.position.set(0, 0.1, -0.21);
            headGroup.add(head, eyes);
            headGroup.position.y = 1.7;

            // ОРУЖИЕ ВРАГА
            const enemyWeapon = new THREE.Group();
            const wBody = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.2, 0.6), new THREE.MeshStandardMaterial({ color: 0x333333 }));
            const wBarrel = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.2), new THREE.MeshStandardMaterial({ color: 0x111111 }));
            wBarrel.rotation.x = Math.PI/2; wBarrel.position.z = -0.3;
            enemyWeapon.add(wBody, wBarrel);
            enemyWeapon.position.set(0.4, 1.2, -0.4);
            group.add(enemyWeapon);
            
            const hitbox = new THREE.Mesh(new THREE.BoxGeometry(1, 2, 1), new THREE.MeshBasicMaterial({ visible: false }));
            hitbox.position.y = 1;
            hitbox.userData.playerId = id;

            group.add(body, legL, legR, headGroup, hitbox);
            group.position.set(info.x, 0, info.z);
            scene.add(group);

            players[id] = { 
                group: group, head: headGroup, weapon: enemyWeapon, hitbox: hitbox, name: info.name, hp: info.hp,
                targetX: info.x, targetZ: info.z, targetRy: info.ry 
            };
            raycastTargets.push(hitbox);
            updatePlayerLabel(id);
        }

        // --- МОБИЛЬНЫЙ МУЛЬТИТАЧ (REWRITTEN V3) ---
        function initMobileControls() {
            const zMove = document.getElementById("zone_move");
            const zLook = document.getElementById("zone_look");
            const jMove = document.getElementById("joy_move");
            const sMove = jMove.querySelector(".joystick-stick");

            const activeTouches = {};

            const handleTouch = (e) => {
                // Не предотвращаем default для всех событий, чтобы кнопки работали
                const rectMove = zMove.getBoundingClientRect();

                for(let t of e.changedTouches) {
                    if(e.type === "touchstart") {
                        // Если касание в зоне кнопок, не обрабатываем его как движение/обзор
                        if (t.target.closest('.m-btn')) continue;
                        
                        e.preventDefault();
                        if(t.clientX < rectMove.right) {
                            activeTouches[t.identifier] = { type: 'move', startX: t.clientX, startY: t.clientY };
                            jMove.style.display = "block";
                            jMove.style.left = t.clientX + "px";
                            jMove.style.top = t.clientY + "px";
                        } else {
                            activeTouches[t.identifier] = { type: 'look', lastX: t.clientX, lastY: t.clientY };
                        }
                    } else if(e.type === "touchmove") {
                        const touchData = activeTouches[t.identifier];
                        if(!touchData) continue;
                        e.preventDefault();

                        if(touchData.type === 'move') {
                            let dx = t.clientX - touchData.startX;
                            let dy = t.clientY - touchData.startY;
                            let dist = Math.min(50, Math.sqrt(dx*dx + dy*dy));
                            let angle = Math.atan2(dy, dx);
                            dataMove.curX = Math.cos(angle) * (dist / 50);
                            dataMove.curY = Math.sin(angle) * (dist / 50);
                            sMove.style.transform = `translate(${Math.cos(angle)*dist}px, ${Math.sin(angle)*dist}px)`;
                        } else if(touchData.type === 'look') {
                            let dx = t.clientX - touchData.lastX;
                            let dy = t.clientY - touchData.lastY;
                            yaw -= dx * 0.007;
                            pitch -= dy * 0.007;
                            pitch = Math.max(-Math.PI/2.3, Math.min(Math.PI/2.3, pitch));
                            camera.rotation.set(pitch, yaw, 0, 'YXZ');
                            touchData.lastX = t.clientX;
                            touchData.lastY = t.clientY;
                        }
                    } else if(e.type === "touchend" || e.type === "touchcancel") {
                        const touchData = activeTouches[t.identifier];
                        if(!touchData) continue;
                        
                        if(touchData.type === 'move') {
                            dataMove.curX = 0; dataMove.curY = 0;
                            jMove.style.display = "none";
                            sMove.style.transform = "translate(0,0)";
                        }
                        delete activeTouches[t.identifier];
                    }
                }
            };

            // Добавляем слушатели на конкретные зоны
            document.addEventListener("touchstart", handleTouch, {passive: false});
            document.addEventListener("touchmove", handleTouch, {passive: false});
            document.addEventListener("touchend", handleTouch, {passive: false});
            document.addEventListener("touchcancel", handleTouch, {passive: false});

            // Кнопки управления
            document.getElementById("btn_fire").addEventListener("touchstart", (e) => { 
                e.preventDefault(); 
                performShoot(); 
            });
            
            document.getElementById("btn_jump").addEventListener("touchstart", (e) => { 
                e.preventDefault(); 
                if (canJump) {
                    velocityY = jumpForce;
                    canJump = false;
                }
            });
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
                    // Исправлено: ID элементов HUD теперь соответствуют новым стилизованным блокам
                    if(document.getElementById("score_val")) document.getElementById("score_val").innerText = myScore;
                    if(document.getElementById("round_info")) document.getElementById("round_info").innerText = "ROUND " + data.round;
                    if(document.getElementById("map_name")) document.getElementById("map_name").innerText = data.map.name;
                    generateMapStructure(data.map);
                    camera.position.set(data.x, 1.65, data.z);
                    for (let id in data.players) if(id !== myId) spawnEnemyCharacter(id, data.players[id]);
                } 
                else if (data.type === "new_player" && data.id !== myId) {
                    spawnEnemyCharacter(data.id, data.info);
                }
                else if (data.type === "new_round") {
                    if(document.getElementById("round_info")) document.getElementById("round_info").innerText = "ROUND " + data.round;
                    if(document.getElementById("map_name")) document.getElementById("map_name").innerText = data.map.name;
                    generateMapStructure(data.map);
                    setHpAmount(100);
                    
                    // Синхронизация игроков при новом раунде
                    if (data.players) {
                        for (let id in data.players) {
                            if (id === myId) {
                                camera.position.set(data.players[id].x, 1.65, data.players[id].z);
                            } else {
                                if (!players[id]) {
                                    spawnEnemyCharacter(id, data.players[id]);
                                } else {
                                    players[id].group.position.set(data.players[id].x, 0, data.players[id].z);
                                    players[id].targetX = data.players[id].x;
                                    players[id].targetZ = data.players[id].z;
                                    players[id].hp = 100;
                                    updatePlayerLabel(id);
                                }
                            }
                        }
                    }
                }
                else if (data.type === "update" && data.id !== myId && players[data.id]) {
                    players[data.id].targetX = data.x; players[data.id].targetZ = data.z; players[data.id].targetRy = data.ry;
                }
                else if (data.type === "hp_update") {
                    if(data.id === myId) { 
                        setHpAmount(data.hp); 
                        triggerFlinch(); 
                    }
                    else if(players[data.id]) { 
                        players[data.id].hp = data.hp; 
                        updatePlayerLabel(data.id); 
                        
                        // Эффект попадания по врагу
                        const p = players[data.id];
                        const body = p.group.children[0];
                        const oldColor = body.material.color.getHex();
                        body.material.color.set(0xffffff);
                        setTimeout(() => body.material.color.set(oldColor), 50);
                    }
                    if(data.by === myId) { triggerHitmarker(); } 
                }
                else if (data.type === "enemy_shoot") {
                    if(data.id !== myId) performEnemyShoot(data.id);
                }
                else if (data.type === "respawn") {
                    if(data.id === myId) { camera.position.set(data.x, 1.65, data.z); setHpAmount(100); }
                    if(data.score_update && data.score_update.id === myId) {
                        myScore = data.score_update.score;
                        if(document.getElementById("score_val")) document.getElementById("score_val").innerText = myScore;
                    }
                    if(players[data.id]) {
                        createExplosion(players[data.id].group.position.clone().add(new THREE.Vector3(0, 1, 0)));
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
            const playerRadius = 0.4;
            const playerHeight = 1.8;
            
            for(let i=0; i<collidableObjects.length; i++) {
                let box = new THREE.Box3().setFromObject(collidableObjects[i]);
                
                // Простая проверка пересечения сферы игрока с AABB объекта
                let closestPoint = new THREE.Vector3(
                    Math.max(box.min.x, Math.min(pos.x, box.max.x)),
                    Math.max(box.min.y, Math.min(pos.y - 1, box.max.y)), // Центр игрока по высоте
                    Math.max(box.min.z, Math.min(pos.z, box.max.z))
                );
                
                let distance = pos.clone().setComponent(1, pos.y - 1).distanceTo(closestPoint);
                if(distance < playerRadius) return true;
            }
            return false;
        }

        function getFloorY(pos) {
            let floorY = 0;
            const ray = new THREE.Raycaster(new THREE.Vector3(pos.x, 20, pos.z), new THREE.Vector3(0, -1, 0));
            const hits = ray.intersectObjects(collidableObjects, false);
            if(hits.length > 0) {
                // Ищем самую высокую точку под игроком, но ниже его текущей позиции головы
                for(let hit of hits) {
                    if(hit.point.y <= pos.y - 1.6 + 0.5) { // 0.5 - высота ступеньки
                        floorY = Math.max(floorY, hit.point.y);
                    }
                }
            }
            return floorY;
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

        function setHpAmount(hp) { 
            myHp = hp; 
            document.getElementById("hp_val").innerText = Math.max(0, hp);
            if(hp < 30) document.getElementById("hp_val").style.color = "#ff4757";
            else document.getElementById("hp_val").style.color = "#fff";
        }

        document.getElementById("play_btn").addEventListener("click", () => {
            let n = document.getElementById("nickname_input").value.trim(); if(n) myName = n;
            checkMobile();
            document.getElementById("login_screen").style.display = "none";
            document.getElementById("hud_top_left").style.display = "flex";
            document.getElementById("map_display").style.display = "block";
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
                if (keys.KeyW) { nextPos.addScaledVector(forward, moveSpeed); isMoving = true; }
                if (keys.KeyS) { nextPos.addScaledVector(forward, -moveSpeed); isMoving = true; }
                if (keys.KeyA) { nextPos.addScaledVector(side, -moveSpeed); isMoving = true; }
                if (keys.KeyD) { nextPos.addScaledVector(side, moveSpeed); isMoving = true; }
                
                if (keys.Space && canJump) {
                    velocityY = jumpForce;
                    canJump = false;
                }
            } else {
                if(idMove !== null) {
                    nextPos.addScaledVector(forward, -dataMove.curY * moveSpeed);
                    nextPos.addScaledVector(side, dataMove.curX * moveSpeed);
                    isMoving = true;
                }
            }

            // Гравитация и прыжки
            velocityY += gravity;
            nextPos.y += velocityY;

            // Проверка пола и забирание на объекты
            let floorY = getFloorY(nextPos);
            let targetY = floorY + 1.7; // 1.7 - высота глаз

            if (nextPos.y < targetY) {
                nextPos.y = targetY;
                velocityY = 0;
                canJump = true;
            }

            // Коллизии по горизонтали (X и Z раздельно для скольжения вдоль стен)
            let horizontalPos = camera.position.clone();
            horizontalPos.x = nextPos.x;
            if (checkCollisions(horizontalPos)) {
                nextPos.x = camera.position.x;
            }

            horizontalPos = camera.position.clone();
            horizontalPos.z = nextPos.z;
            if (checkCollisions(horizontalPos)) {
                nextPos.z = camera.position.z;
            }

            camera.position.copy(nextPos);
            
            if (isMoving) {
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
