import asyncio
import json
import random
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse

app = FastAPI()

# --- СЕРВЕРНАЯ АРХИТЕКТУРА ---

class GameServer:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.players = {}
        self.team_scores = {"RED": 0, "BLUE": 0}
        self.current_round = 1
        self.maps = [
            {"sky": "#b3e5fc", "ground": "#e0e0e0", "wall": "#78909c", "name": "ДНЕВНОЙ ПОЛИГОН", "seed": 123},
            {"sky": "#ffe0b2", "ground": "#d7ccc8", "wall": "#a1887f", "name": "ПЕСЧАНЫЙ КАНЬОН", "seed": 456},
            {"sky": "#c8e6c9", "ground": "#cfd8dc", "wall": "#546e7a", "name": "ИНДУСТРИАЛЬНЫЙ СЕКТОР", "seed": 789}
        ]
        self.current_map = self.maps[0]

    def get_spawn_pos(self, team):
        # RED спавнится слева (-180), BLUE справа (180)
        if team == "RED":
            return random.uniform(-180, -140), random.uniform(-50, 50)
        else:
            return random.uniform(140, 180), random.uniform(-50, 50)

    async def connect(self, websocket: WebSocket, player_id: str):
        await websocket.accept()
        self.active_connections[player_id] = websocket
        
        red_count = sum(1 for p in self.players.values() if p.get("team") == "RED")
        blue_count = sum(1 for p in self.players.values() if p.get("team") == "BLUE")
        team = "RED" if red_count <= blue_count else "BLUE"
        
        x, z = self.get_spawn_pos(team)
        self.players[player_id] = {
            "name": "Player", "x": x, "y": 0, "z": z, "ry": 0,
            "hp": 100, "score": 0, "team": team
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
        server.current_map["seed"] = random.randint(1, 999999)
        server.team_scores = {"RED": 0, "BLUE": 0}
        
        for pid in server.players:
            server.players[pid]["hp"] = 100
            nx, nz = server.get_spawn_pos(server.players[pid]["team"])
            server.players[pid]["x"], server.players[pid]["z"] = nx, nz
            server.players[pid]["y"] = 0
            
        await server.broadcast({
            "type": "new_round", 
            "round": server.current_round, 
            "map": server.current_map,
            "players": server.players,
            "team_scores": server.team_scores
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
                    "team": server.players[player_id]["team"],
                    "team_scores": server.team_scores,
                    "x": server.players[player_id]["x"], "z": server.players[player_id]["z"]
                }))
                await server.broadcast({"type": "new_player", "id": player_id, "info": server.players[player_id]})
            elif msg["type"] == "move":
                server.players[player_id]["x"] = msg["x"]
                server.players[player_id]["y"] = msg["y"]
                server.players[player_id]["z"] = msg["z"]
                server.players[player_id]["ry"] = msg["ry"]
                await server.broadcast({
                    "type": "update", "id": player_id, 
                    "x": msg["x"], "y": msg["y"], "z": msg["z"], "ry": msg["ry"]
                })
            elif msg["type"] == "shoot":
                await server.broadcast({"type": "enemy_shoot", "id": player_id})
            elif msg["type"] == "hit":
                tid = msg["target"]
                if tid in server.players:
                    if server.players[tid]["team"] == server.players[player_id]["team"]:
                        continue
                        
                    server.players[tid]["hp"] -= 25
                    if server.players[tid]["hp"] <= 0:
                        server.players[player_id]["score"] += 1
                        killer_team = server.players[player_id]["team"]
                        server.team_scores[killer_team] += 1
                        
                        server.players[tid]["hp"] = 100
                        nx, nz = server.get_spawn_pos(server.players[tid]["team"])
                        server.players[tid]["x"], server.players[tid]["z"] = nx, nz
                        
                        await server.broadcast({
                            "type": "respawn", "id": tid, "x": nx, "z": nz, 
                            "killer": server.players[player_id]["name"], "victim": server.players[tid]["name"],
                            "killer_team": killer_team,
                            "team_scores": server.team_scores,
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
    <title>POLY STRIKE 3D</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; user-select: none; background: #000; color: #fff; touch-action: none; }
        
        #login_screen { position: fixed; inset: 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 100; }
        .menu-card { background: rgba(255, 255, 255, 0.1); backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.2); padding: 40px; border-radius: 20px; text-align: center; box-shadow: 0 20px 50px rgba(0,0,0,0.3); width: 340px; }
        .menu-card h1 { font-size: 32px; font-weight: 900; margin: 0 0 30px 0; letter-spacing: 2px; color: #fff; text-shadow: 0 2px 10px rgba(0,0,0,0.2); }
        .input-field { width: 100%; padding: 15px; font-size: 18px; border: none; background: rgba(255,255,255,0.9); color: #333; border-radius: 10px; outline: none; box-sizing: border-box; text-align: center; font-weight: 700; margin-bottom: 20px; }
        .btn-submit { width: 100%; padding: 18px; font-size: 18px; cursor: pointer; background: #ff4757; color: white; border: none; border-radius: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; transition: all 0.2s; box-shadow: 0 5px 15px rgba(255,71,87,0.4); }
        .btn-submit:hover { background: #ff6b81; transform: translateY(-2px); }
        
        #hud_top_left { position: absolute; top: 20px; left: 20px; display: flex; flex-direction: column; gap: 10px; pointer-events: none; z-index: 10; display: none; }
        .stat-box { background: rgba(0,0,0,0.6); backdrop-filter: blur(5px); padding: 8px 15px; border-radius: 12px; display: flex; align-items: center; gap: 10px; border: 1px solid rgba(255,255,255,0.1); }
        .stat-val { font-size: 20px; font-weight: 900; font-family: 'Arial Black', sans-serif; }
        
        #team_scores { display: flex; gap: 10px; margin-bottom: 5px; }
        .score-box { padding: 5px 15px; border-radius: 8px; font-weight: 900; font-size: 18px; display: flex; align-items: center; gap: 8px; }
        .score-RED { background: rgba(255, 71, 87, 0.8); border: 2px solid #ff4757; }
        .score-BLUE { background: rgba(30, 144, 255, 0.8); border: 2px solid #1e90ff; }

        #team_indicator { font-weight: 900; font-size: 14px; padding: 4px 12px; border-radius: 6px; text-align: center; text-transform: uppercase; width: fit-content; }
        .team-RED { background: #ff4757; color: #fff; box-shadow: 0 0 10px rgba(255,71,87,0.4); }
        .team-BLUE { background: #1e90ff; color: #fff; box-shadow: 0 0 10px rgba(30,144,255,0.4); }

        #map_display { position: absolute; top: 20px; right: 20px; text-align: right; pointer-events: none; z-index: 10; display: none; }
        #map_name { font-weight: 900; font-size: 18px; color: #fff; text-transform: uppercase; text-shadow: 0 2px 5px rgba(0,0,0,0.5); }
        #round_info { font-size: 14px; color: #ff4757; font-weight: 800; }

        #crosshair_container { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); pointer-events: none; z-index: 10; display:none; }
        .crosshair-line { position: absolute; background: #00ff00; box-shadow: 0 0 5px rgba(0,255,0,0.5); }
        .ch-v { width: 2px; height: 12px; left: -1px; }
        .ch-h { width: 12px; height: 2px; top: -1px; }
        .ch-t { top: -15px; } .ch-b { bottom: -15px; } .ch-l { left: -15px; } .ch-r { right: -15px; }
        
        #damage_flash { position: absolute; inset: 0; background: radial-gradient(circle, transparent 40%, rgba(255,0,0,0.4) 100%); pointer-events: none; opacity: 0; transition: opacity 0.1s; z-index: 5; }
        
        #killfeed { position: absolute; bottom: 100px; left: 20px; display: flex; flex-direction: column-reverse; gap: 8px; pointer-events: none; z-index: 10; }
        .kill-msg { background: rgba(0,0,0,0.6); padding: 8px 15px; border-radius: 8px; color: #fff; font-size: 14px; font-weight: 700; border-left: 6px solid #ff4757; animation: slideUp 0.3s ease-out; backdrop-filter: blur(5px); }
        .kill-RED { border-left-color: #ff4757; }
        .kill-BLUE { border-left-color: #1e90ff; }
        @keyframes slideUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
        
        /* TOUCH CONTROLS - REWRITTEN V4 */
        #touch_controls { position: absolute; inset: 0; z-index: 20; display: none; pointer-events: none; }
        .touch-zone { position: absolute; bottom: 0; height: 100%; width: 50%; pointer-events: auto; }
        #zone_move { left: 0; }
        #zone_look { right: 0; }
        
        .joystick-base { position: absolute; width: 140px; height: 140px; background: rgba(255,255,255,0.1); border: 2px solid rgba(255,255,255,0.2); border-radius: 50%; display: none; pointer-events: none; transform: translate(-50%, -50%); backdrop-filter: blur(10px); }
        .joystick-stick { position: absolute; width: 70px; height: 70px; background: #fff; border-radius: 50%; top: 35px; left: 35px; box-shadow: 0 5px 20px rgba(0,0,0,0.4); }
        
        #mobile_buttons { position: absolute; bottom: 30px; right: 30px; display: flex; flex-direction: column; gap: 15px; pointer-events: none; }
        .m-btn { width: 95px; height: 95px; background: rgba(255,255,255,0.15); border: 3px solid rgba(255,255,255,0.4); border-radius: 50%; display: flex; justify-content: center; align-items: center; font-weight: 900; font-size: 20px; color: #fff; pointer-events: auto; backdrop-filter: blur(10px); transition: transform 0.1s, background 0.1s; user-select: none; -webkit-tap-highlight-color: transparent; box-shadow: 0 5px 15px rgba(0,0,0,0.2); }
        .m-btn:active { transform: scale(0.85); background: rgba(255,255,255,0.3); }
        #btn_fire { background: rgba(255,71,87,0.4); border-color: #ff4757; width: 120px; height: 120px; box-shadow: 0 0 20px rgba(255,71,87,0.3); }
        #btn_fire:active { background: rgba(255,71,87,0.6); }
        #btn_jump { font-size: 24px; }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/OBJLoader.js"></script>
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
        <div id="team_scores">
            <div class="score-box score-RED">RED: <span id="score_red">0</span></div>
            <div class="score-box score-BLUE">BLUE: <span id="score_blue">0</span></div>
        </div>
        <div style="display: flex; gap: 10px; align-items: center;">
            <div id="team_indicator">TEAM</div>
            <div class="stat-box">
                <div style="color: #ff4757; font-size: 20px;">❤</div>
                <div id="hp_val" class="stat-val">100</div>
            </div>
            <div class="stat-box">
                <div style="color: #ffa502; font-size: 20px;">★</div>
                <div id="score_val" class="stat-val">0</div>
            </div>
        </div>
    </div>

    <div id="map_display">
        <div id="map_name">ARENA</div>
        <div id="round_info">ROUND 1</div>
    </div>

    <div id="killfeed"></div>
    
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
        let scene, camera, renderer, sunLight;
        let players = {}, myId = null, myName = "Player", ws, myTeam = "RED";
        let keys = { KeyW:0, KeyA:0, KeyS:0, KeyD:0, Space:0 };
        let moveSpeed = 0.22, yaw = 0, pitch = 0;
        let myHp = 100, myScore = 0, isMobile = false;

        let playerModelTemplate = null;

        let velocityY = 0;
        const gravity = -0.012;
        const jumpForce = 0.26;
        let canJump = true;

        let weapon, isShooting = false;
        let mapGroup = new THREE.Group();
        let collidableObjects = [], raycastTargets = [];
        let objectBounds = [];

        let activeTouches = {};
        let dataMove = { startX: 0, startY: 0, curX: 0, curY: 0 };
        let lastPos = new THREE.Vector3(), lastYaw = 0;

        function seededRandom(seed) {
            const x = Math.sin(seed++) * 10000;
            return x - Math.floor(x);
        }

        function checkMobile() {
            isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || (window.innerWidth < 900);
            if(isMobile) {
                document.getElementById("touch_controls").style.display = "block";
                moveSpeed = 0.28;
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

            const ambient = new THREE.AmbientLight(0xffffff, 0.5);
            scene.add(ambient);

            sunLight = new THREE.DirectionalLight(0xffffff, 1.2);
            sunLight.position.set(50, 100, 50);
            sunLight.castShadow = true;
            sunLight.shadow.mapSize.width = 2048;
            sunLight.shadow.mapSize.height = 2048;
            sunLight.shadow.camera.near = 0.5;
            sunLight.shadow.camera.far = 500;
            sunLight.shadow.camera.left = -150;
            sunLight.shadow.camera.right = 150;
            sunLight.shadow.camera.top = 150;
            sunLight.shadow.camera.bottom = -150;
            scene.add(sunLight);

            scene.add(mapGroup);
            buildWeapon();
            camera.position.y = 1.7;

            // Загрузка модели персонажа
            const loader = new THREE.OBJLoader();
            loader.load('/models/player.obj', (obj) => {
                obj.traverse((child) => {
                    if (child.isMesh) {
                        child.castShadow = true;
                        child.receiveShadow = true;
                    }
                });
                // Масштабируем и центрируем модель под размер хитбокса (примерно 1.8м высота)
                const box = new THREE.Box3().setFromObject(obj);
                const size = box.getSize(new THREE.Vector3());
                const center = box.getCenter(new THREE.Vector3());
                
                const scale = 1.8 / size.y;
                obj.scale.set(scale, scale, scale);
                
                // Сдвигаем модель так, чтобы ноги были на 0 (по Y)
                obj.position.y = (size.y / 2 - center.y) * scale;
                
                playerModelTemplate = obj;
                console.log("Player model loaded");
                // Обновляем уже существующих игроков
                for(let id in players) {
                    if(id !== myId) {
                        const p = players[id];
                        // Удаляем старые части (body, legs, head)
                        const toRemove = [];
                        p.group.traverse((child) => {
                            if(child !== p.group && child !== p.weapon && child !== p.hitbox && child !== p.label) {
                                toRemove.push(child);
                            }
                        });
                        toRemove.forEach(c => p.group.remove(c));
                        
                        // Добавляем модель
                        const teamColor = p.team === "RED" ? 0xff4757 : 0x1e90ff;
                        const model = playerModelTemplate.clone();
                        model.traverse((child) => {
                            if (child.isMesh) {
                                child.material = new THREE.MeshStandardMaterial({ color: teamColor, roughness: 0.5 });
                                child.castShadow = true; child.receiveShadow = true;
                            }
                        });
                        model.rotation.y = Math.PI;
                        p.group.add(model);
                    }
                }
            });

            if(!isMobile) {
                document.body.addEventListener('click', () => {
                    if(document.pointerLockElement !== document.body) document.body.requestPointerLock();
                });
                window.addEventListener('mousedown', (e) => {
                    if (document.pointerLockElement === document.body && e.button === 0) performShoot();
                });
                document.addEventListener('mousemove', (e) => {
                    if (document.pointerLockElement === document.body) {
                        yaw -= e.movementX * 0.0022;
                        pitch -= e.movementY * 0.0022;
                        pitch = Math.max(-Math.PI/2.3, Math.min(Math.PI/2.3, pitch));
                        camera.rotation.set(pitch, yaw, 0, 'YXZ');
                    }
                });
                window.addEventListener('keydown', (e) => { if(e.code in keys) keys[e.code] = 1; });
                window.addEventListener('keyup', (e) => { if(e.code in keys) keys[e.code] = 0; });
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
            const body = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.05, 0.4), new THREE.MeshStandardMaterial({ color: 0x37474f, roughness: 0.4 }));
            const barrel = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.15), new THREE.MeshStandardMaterial({ color: 0x212121 }));
            barrel.rotation.x = Math.PI / 2;
            barrel.position.set(0, 0, -0.25);
            weapon.add(body, barrel);
            weapon.position.set(0.2, -0.2, -0.35);
            camera.add(weapon);
            scene.add(camera);
        }

        function generateMapStructure(mapData) {
            while(mapGroup.children.length > 0){ mapGroup.remove(mapGroup.children[0]); }
            collidableObjects = []; raycastTargets = []; objectBounds = [];

            renderer.setClearColor(mapData.sky);
            scene.background = new THREE.Color(mapData.sky);
            scene.fog = new THREE.Fog(mapData.sky, 30, 250);
            
            const floorSize = 400;
            const floorGeo = new THREE.PlaneGeometry(floorSize, floorSize);
            const floorMat = new THREE.MeshStandardMaterial({ color: mapData.ground, roughness: 0.8 });
            const floor = new THREE.Mesh(floorGeo, floorMat);
            floor.rotation.x = -Math.PI / 2;
            floor.receiveShadow = true;
            mapGroup.add(floor);

            const grid = new THREE.GridHelper(floorSize, 80, 0x000000, 0x000000);
            grid.position.y = 0.05; grid.material.opacity = 0.05; grid.material.transparent = true;
            mapGroup.add(grid);

            // Базы команд
            const baseGeo = new THREE.CircleGeometry(30, 32);
            const redBase = new THREE.Mesh(baseGeo, new THREE.MeshBasicMaterial({ color: 0xff4757, transparent: true, opacity: 0.15 }));
            redBase.rotation.x = -Math.PI/2; redBase.position.set(-160, 0.06, 0);
            mapGroup.add(redBase);
            const blueBase = new THREE.Mesh(baseGeo, new THREE.MeshBasicMaterial({ color: 0x1e90ff, transparent: true, opacity: 0.15 }));
            blueBase.rotation.x = -Math.PI/2; blueBase.position.set(160, 0.06, 0);
            mapGroup.add(blueBase);

            const colors = [0xff4757, 0x2ed573, 0x1e90ff, 0xffa502, 0x747d8c];
            let currentSeed = mapData.seed || 123;
            
            for(let i=0; i<150; i++) {
                const size = 3 + seededRandom(currentSeed++) * 10;
                const type = Math.floor(seededRandom(currentSeed++) * 4);
                let geo;
                if(type === 0) geo = new THREE.BoxGeometry(size, size, size);
                else if(type === 1) geo = new THREE.TetrahedronGeometry(size);
                else if(type === 2) geo = new THREE.OctahedronGeometry(size);
                else geo = new THREE.CylinderGeometry(size/2, size/2, size, 6);

                const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: colors[i % colors.length], roughness: 0.5 }));
                const rx = (seededRandom(currentSeed++)-0.5) * 360;
                const rz = (seededRandom(currentSeed++)-0.5) * 360;
                
                // Избегаем спавн-зон
                if(Math.abs(rx) > 130 || Math.abs(rz) > 40) {
                    mesh.position.set(rx, size/2, rz);
                    mesh.rotation.set(seededRandom(currentSeed++), seededRandom(currentSeed++), seededRandom(currentSeed++));
                    mesh.castShadow = true; mesh.receiveShadow = true;
                    mapGroup.add(mesh); collidableObjects.push(mesh); raycastTargets.push(mesh);
                }
            }

            const wallMat = new THREE.MeshStandardMaterial({ color: 0x2f3542 });
            const limit = floorSize / 2;
            const wallGeo = [{w:floorSize, h:40, d:10, x:0, z:limit}, {w:floorSize, h:40, d:10, x:0, z:-limit}, {w:10, h:40, d:floorSize, x:limit, z:0}, {w:10, h:40, d:floorSize, x:-limit, z:0}];
            wallGeo.forEach(w => {
                const mesh = new THREE.Mesh(new THREE.BoxGeometry(w.w, w.h, w.d), wallMat);
                mesh.position.set(w.x, w.h/2, w.z);
                mapGroup.add(mesh); collidableObjects.push(mesh);
            });

            collidableObjects.forEach(obj => { obj.updateMatrixWorld(); objectBounds.push(new THREE.Box3().setFromObject(obj)); });
        }

        function performShoot() {
            if(isShooting) return;
            isShooting = true;
            weapon.position.z = -0.32; setTimeout(() => weapon.position.z = -0.35, 60);
            const flash = new THREE.PointLight(0xffff00, 2, 5);
            flash.position.set(0, 0, -0.4).applyMatrix4(weapon.matrixWorld);
            scene.add(flash); setTimeout(() => scene.remove(flash), 40);
            const points = [new THREE.Vector3(0, 0, -0.3).applyMatrix4(weapon.matrixWorld), new THREE.Vector3(0, 0, -150).applyMatrix4(weapon.matrixWorld)];
            const tracer = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), new THREE.LineBasicMaterial({ color: 0xffff00, transparent: true, opacity: 0.8 }));
            scene.add(tracer); setTimeout(() => scene.remove(tracer), 40);
            if(ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "shoot" }));
            const dir = new THREE.Vector3(); camera.getWorldDirection(dir);
            const ray = new THREE.Raycaster(camera.position, dir, 0, 200);
            const hits = ray.intersectObjects(raycastTargets, false);
            if(hits.length > 0) {
                let targetMesh = hits[0].object;
                if(targetMesh.userData.playerId) ws.send(JSON.stringify({ type: "hit", target: targetMesh.userData.playerId }));
            }
            setTimeout(() => { isShooting = false; }, 100);
        }

        function performEnemyShoot(id) {
            const p = players[id]; if(!p || !p.weapon) return;
            const flash = new THREE.PointLight(0xffff00, 2, 5);
            flash.position.set(0, 0, -0.4).applyMatrix4(p.weapon.matrixWorld);
            scene.add(flash); setTimeout(() => scene.remove(flash), 40);
            const start = new THREE.Vector3(0, 0, -0.4).applyMatrix4(p.weapon.matrixWorld);
            const end = new THREE.Vector3(0, 0, -150).applyMatrix4(p.weapon.matrixWorld);
            const tracer = new THREE.Line(new THREE.BufferGeometry().setFromPoints([start, end]), new THREE.LineBasicMaterial({ color: 0xffff00, transparent: true, opacity: 0.5 }));
            scene.add(tracer); setTimeout(() => scene.remove(tracer), 40);
        }

        function triggerHitmarker() {
            const hm = document.getElementById("hitmarker");
            hm.style.opacity = "1"; setTimeout(() => hm.style.opacity = "0", 70);
            weapon.position.z -= 0.02; setTimeout(() => weapon.position.z += 0.02, 50);
        }

        function createExplosion(pos) {
            const count = 15;
            for(let i=0; i<count; i++) {
                const part = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.15, 0.15), new THREE.MeshBasicMaterial({ color: 0xff4757 }));
                part.position.copy(pos); scene.add(part);
                const vel = new THREE.Vector3((Math.random()-0.5)*0.3, Math.random()*0.3, (Math.random()-0.5)*0.3);
                const anim = () => { part.position.add(vel); vel.y -= 0.01; part.scale.multiplyScalar(0.94); if(part.scale.x > 0.01) requestAnimationFrame(anim); else scene.remove(part); };
                anim();
            }
        }

        function generateNameplate(name, hp, team) {
            const canvas = document.createElement('canvas'); canvas.width = 240; canvas.height = 70;
            const ctx = canvas.getContext('2d');
            ctx.font = "bold 24px sans-serif"; ctx.fillStyle = team === "RED" ? "#ff4757" : "#1e90ff"; ctx.textAlign = "center"; ctx.fillText(name, 120, 25);
            ctx.fillStyle = "rgba(0,0,0,0.4)"; ctx.fillRect(40, 40, 160, 12);
            ctx.fillStyle = team === "RED" ? "#ff4757" : "#1e90ff"; ctx.fillRect(40, 40, Math.max(0, hp) * 1.6, 12);
            const tex = new THREE.CanvasTexture(canvas); const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex }));
            sprite.scale.set(1.8, 0.5, 1); return sprite;
        }

        function updatePlayerLabel(id) {
            let p = players[id]; if(!p) return;
            if(p.label) p.group.remove(p.label);
            p.label = generateNameplate(p.name, p.hp, p.team); p.label.position.y = 2.3; p.group.add(p.label);
        }

        function spawnEnemyCharacter(id, info) {
            const group = new THREE.Group();
            const teamColor = info.team === "RED" ? 0xff4757 : 0x1e90ff;
            
            let model;
            if (playerModelTemplate) {
                model = playerModelTemplate.clone();
                model.traverse((child) => {
                    if (child.isMesh) {
                        child.material = new THREE.MeshStandardMaterial({ 
                            color: teamColor, 
                            roughness: 0.5,
                            metalness: 0.2
                        });
                    }
                });
                // Поворачиваем модель лицом вперед (обычно OBJ смотрят по оси Z или -Z)
                model.rotation.y = Math.PI; 
                group.add(model);
            } else {
                // Фолбек на коробки, если модель еще не загрузилась
                const body = new THREE.Mesh(new THREE.BoxGeometry(0.8, 1.2, 0.5), new THREE.MeshStandardMaterial({ color: teamColor, roughness: 0.4 }));
                body.position.y = 0.9; body.castShadow = true;
                const legGeo = new THREE.BoxGeometry(0.3, 0.8, 0.3); const legMat = new THREE.MeshStandardMaterial({ color: 0x2f3542, roughness: 0.4 });
                const legL = new THREE.Mesh(legGeo, legMat); legL.position.set(-0.2, 0.4, 0);
                const legR = new THREE.Mesh(legGeo, legMat); legR.position.set(0.2, 0.4, 0);
                const headGroup = new THREE.Group();
                const head = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.5, 0.5), new THREE.MeshStandardMaterial({ color: 0x2f3542, roughness: 0.3 }));
                const visor = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.15, 0.1), new THREE.MeshBasicMaterial({ color: teamColor }));
                visor.position.set(0, 0.1, -0.21);
                const nose = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.1, 0.2), new THREE.MeshStandardMaterial({ color: 0x2f3542 }));
                nose.position.set(0, 0, -0.3);
                headGroup.add(head, visor, nose); headGroup.position.y = 1.7;
                group.add(body, legL, legR, headGroup);
            }
            
            // Оружие
            const enemyWeapon = new THREE.Group();
            const wBody = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.2, 0.6), new THREE.MeshStandardMaterial({ color: 0x333333 }));
            const wBarrel = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.2), new THREE.MeshStandardMaterial({ color: 0x111111 }));
            wBarrel.rotation.x = Math.PI/2; wBarrel.position.z = -0.3;
            enemyWeapon.add(wBody, wBarrel); enemyWeapon.position.set(0.4, 1.2, -0.4);
            group.add(enemyWeapon);
            
            const hitbox = new THREE.Mesh(new THREE.BoxGeometry(1.2, 2.2, 1.2), new THREE.MeshBasicMaterial({ visible: false }));
            hitbox.position.y = 1; hitbox.userData.playerId = id;
            group.add(hitbox);
            
            group.position.set(info.x, info.y || 0, info.z); scene.add(group);
            players[id] = { group: group, weapon: enemyWeapon, hitbox: hitbox, name: info.name, hp: info.hp, team: info.team, targetX: info.x, targetY: info.y || 0, targetZ: info.z, targetRy: info.ry };
            raycastTargets.push(hitbox); updatePlayerLabel(id);
        }

        function initMobileControls() {
            const zMove = document.getElementById("zone_move");
            const jMove = document.getElementById("joy_move");
            const sMove = jMove.querySelector(".joystick-stick");
            const handleTouch = (e) => {
                const rectMove = zMove.getBoundingClientRect();
                for(let t of e.changedTouches) {
                    if(e.type === "touchstart") {
                        if (t.target.closest('.m-btn')) continue;
                        e.preventDefault();
                        if(t.clientX < rectMove.right) {
                            activeTouches[t.identifier] = { type: 'move', startX: t.clientX, startY: t.clientY };
                            jMove.style.display = "block"; jMove.style.left = t.clientX + "px"; jMove.style.top = t.clientY + "px";
                        } else { activeTouches[t.identifier] = { type: 'look', lastX: t.clientX, lastY: t.clientY }; }
                    } else if(e.type === "touchmove") {
                        const touchData = activeTouches[t.identifier]; if(!touchData) continue;
                        e.preventDefault();
                        if(touchData.type === 'move') {
                            let dx = t.clientX - touchData.startX, dy = t.clientY - touchData.startY;
                            let dist = Math.min(60, Math.sqrt(dx*dx + dy*dy)), angle = Math.atan2(dy, dx);
                            let normalizedDist = dist / 60;
                            dataMove.curX = Math.cos(angle) * normalizedDist; 
                            dataMove.curY = Math.sin(angle) * normalizedDist;
                            sMove.style.transform = `translate(${Math.cos(angle)*dist}px, ${Math.sin(angle)*dist}px)`;
                        } else if(touchData.type === 'look') {
                            yaw -= (t.clientX - touchData.lastX) * 0.006; pitch -= (t.clientY - touchData.lastY) * 0.006;
                            pitch = Math.max(-Math.PI/2.3, Math.min(Math.PI/2.3, pitch)); camera.rotation.set(pitch, yaw, 0, 'YXZ');
                            touchData.lastX = t.clientX; touchData.lastY = t.clientY;
                        }
                    } else if(e.type === "touchend" || e.type === "touchcancel") {
                        const touchData = activeTouches[t.identifier]; if(!touchData) continue;
                        if(touchData.type === 'move') { dataMove.curX = 0; dataMove.curY = 0; jMove.style.display = "none"; sMove.style.transform = "translate(0,0)"; }
                        delete activeTouches[t.identifier];
                    }
                }
            };
            document.addEventListener("touchstart", handleTouch, {passive: false}); document.addEventListener("touchmove", handleTouch, {passive: false});
            document.addEventListener("touchend", handleTouch, {passive: false}); document.addEventListener("touchcancel", handleTouch, {passive: false});
            document.getElementById("btn_fire").addEventListener("touchstart", (e) => { e.preventDefault(); performShoot(); });
            document.getElementById("btn_jump").addEventListener("touchstart", (e) => { e.preventDefault(); if (canJump) { velocityY = jumpForce; canJump = false; } });
        }

        function sendNetworkPosition() {
            if (ws && ws.readyState === WebSocket.OPEN && myId) {
                if (camera.position.distanceTo(lastPos) > 0.01 || Math.abs(yaw - lastYaw) > 0.005) {
                    ws.send(JSON.stringify({ type: "move", x: camera.position.x, y: camera.position.y - 1.7, z: camera.position.z, ry: yaw }));
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
                    myId = data.id; myTeam = data.team;
                    const ti = document.getElementById("team_indicator"); 
                    if(ti) { ti.innerText = "TEAM " + myTeam; ti.className = "team-" + myTeam; }
                    updateTeamScores(data.team_scores);
                    if(document.getElementById("score_val")) document.getElementById("score_val").innerText = myScore;
                    if(document.getElementById("round_info")) document.getElementById("round_info").innerText = "ROUND " + data.round;
                    if(document.getElementById("map_name")) document.getElementById("map_name").innerText = data.map.name;
                    generateMapStructure(data.map); camera.position.set(data.x, 1.7, data.z);
                    for (let id in data.players) if(id !== myId) spawnEnemyCharacter(id, data.players[id]);
                } 
                else if (data.type === "new_player" && data.id !== myId) spawnEnemyCharacter(data.id, data.info);
                else if (data.type === "new_round") {
                    if(document.getElementById("round_info")) document.getElementById("round_info").innerText = "ROUND " + data.round;
                    if(document.getElementById("map_name")) document.getElementById("map_name").innerText = data.map.name;
                    updateTeamScores(data.team_scores);
                    generateMapStructure(data.map); setHpAmount(100);
                    if (data.players) {
                        for (let id in data.players) {
                            if (id === myId) camera.position.set(data.players[id].x, 1.7, data.players[id].z);
                            else {
                                if (!players[id]) spawnEnemyCharacter(id, data.players[id]);
                                else {
                                    players[id].group.position.set(data.players[id].x, data.players[id].y || 0, data.players[id].z);
                                    players[id].targetX = data.players[id].x; players[id].targetY = data.players[id].y || 0;
                                    players[id].targetZ = data.players[id].z; players[id].hp = 100; updatePlayerLabel(id);
                                }
                            }
                        }
                    }
                }
                else if (data.type === "update" && data.id !== myId && players[data.id]) {
                    players[data.id].targetX = data.x; players[data.id].targetY = data.y; players[data.id].targetZ = data.z; players[data.id].targetRy = data.ry;
                }
                else if (data.type === "hp_update") {
                    if(data.id === myId) { setHpAmount(data.hp); triggerFlinch(); }
                    else if(players[data.id]) { 
                        players[data.id].hp = data.hp; 
                        updatePlayerLabel(data.id); 
                        players[data.id].group.traverse((child) => {
                            if(child.isMesh && child.material && child !== players[data.id].hitbox) {
                                const oc = child.material.color.getHex();
                                child.material.color.set(0xffffff);
                                setTimeout(() => child.material.color.set(oc), 50);
                            }
                        });
                    }
                    if(data.by === myId) triggerHitmarker();
                }
                else if (data.type === "enemy_shoot") { if(data.id !== myId) performEnemyShoot(data.id); }
                else if (data.type === "respawn") {
                    updateTeamScores(data.team_scores);
                    if(data.id === myId) { camera.position.set(data.x, 1.7, data.z); setHpAmount(100); }
                    if(data.score_update && data.score_update.id === myId) { myScore = data.score_update.score; if(document.getElementById("score_val")) document.getElementById("score_val").innerText = myScore; }
                    if(players[data.id]) { createExplosion(players[data.id].group.position.clone().add(new THREE.Vector3(0, 1, 0))); players[data.id].group.position.set(data.x, 0, data.z); players[data.id].targetX = data.x; players[data.id].targetY = 0; players[data.id].targetZ = data.z; players[data.id].hp = 100; updatePlayerLabel(data.id); }
                    pushToKillfeed(data.killer, data.victim, data.killer_team);
                }
                else if (data.type === "leave" && players[data.id]) { raycastTargets = raycastTargets.filter(t => t !== players[data.id].hitbox); scene.remove(players[data.id].group); delete players[data.id]; }
            };
        }

        function updateTeamScores(scores) {
            if(!scores) return;
            if(document.getElementById("score_red")) document.getElementById("score_red").innerText = scores.RED;
            if(document.getElementById("score_blue")) document.getElementById("score_blue").innerText = scores.BLUE;
        }

        function checkCollisions(pos) {
            const playerRadius = 0.22; const feetY = pos.y - 1.7; const stepHeight = 0.7;
            for(let i=0; i<objectBounds.length; i++) {
                let box = objectBounds[i]; 
                if (box.max.y <= feetY + stepHeight) continue;
                let closestPoint = new THREE.Vector3(Math.max(box.min.x, Math.min(pos.x, box.max.x)), Math.max(box.min.y, Math.min(pos.y - 0.85, box.max.y)), Math.max(box.min.z, Math.min(pos.z, box.max.z)));
                if(pos.clone().setComponent(1, pos.y - 0.85).distanceTo(closestPoint) < playerRadius) return true;
            }
            return false;
        }

        function getFloorY(pos) {
            let floorY = 0; const feetY = pos.y - 1.7; const checkRadius = 0.22;
            for(let i=0; i<objectBounds.length; i++) {
                let box = objectBounds[i];
                if (pos.x + checkRadius >= box.min.x && pos.x - checkRadius <= box.max.x && pos.z + checkRadius >= box.min.z && pos.z - checkRadius <= box.max.z) {
                    if (box.max.y <= feetY + 0.8) floorY = Math.max(floorY, box.max.y);
                }
            }
            return floorY;
        }

        function pushToKillfeed(killer, victim, team) {
            const kf = document.getElementById("killfeed");
            const div = document.createElement("div"); div.className = "kill-msg kill-" + team;
            div.innerHTML = `⚠️ <b>${killer}</b> ликвидировал <b>${victim}</b>`;
            kf.appendChild(div); setTimeout(() => div.remove(), 4000);
        }

        function triggerFlinch() {
            document.getElementById("damage_flash").style.opacity = "1";
            setTimeout(() => document.getElementById("damage_flash").style.opacity = "0", 80);
        }

        function setHpAmount(hp) { 
            myHp = hp; document.getElementById("hp_val").innerText = Math.max(0, hp);
            document.getElementById("hp_val").style.color = hp < 30 ? "#ff4757" : "#fff";
        }

        document.getElementById("play_btn").addEventListener("click", () => {
            let n = document.getElementById("nickname_input").value.trim(); if(n) myName = n;
            checkMobile(); document.getElementById("login_screen").style.display = "none";
            document.getElementById("hud_top_left").style.display = "flex";
            document.getElementById("map_display").style.display = "block";
            document.getElementById("crosshair_container").style.display = "block";
            init3D(); initNetwork();
        });

        function animate() {
            requestAnimationFrame(animate);
            if(!scene || !camera) return;
            for(let id in players) {
                let p = players[id];
                if(id !== myId) {
                    p.group.position.x += (p.targetX - p.group.position.x) * 0.25;
                    p.group.position.y += (p.targetY - p.group.position.y) * 0.25;
                    p.group.position.z += (p.targetZ - p.group.position.z) * 0.25;
                    p.group.rotation.y += (p.targetRy - p.group.rotation.y) * 0.25;
                    if(p.label) p.label.lookAt(camera.position);
                }
            }
            const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion); forward.y = 0; forward.normalize();
            const side = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion); side.y = 0; side.normalize();
            
            let nextPos = camera.position.clone();
            let moveX = 0, moveZ = 0;
            
            if(!isMobile) {
                if (keys.KeyW) moveZ += 1; if (keys.KeyS) moveZ -= 1; if (keys.KeyA) moveX -= 1; if (keys.KeyD) moveX += 1;
                if (keys.Space && canJump) { velocityY = jumpForce; canJump = false; }
            } else { moveZ = -dataMove.curY; moveX = dataMove.curX; }

            if (moveX !== 0 || moveZ !== 0) {
                // Нормализация вектора движения
                let moveVec = new THREE.Vector3();
                moveVec.addScaledVector(forward, moveZ);
                moveVec.addScaledVector(side, moveX);
                if (moveVec.length() > 1) moveVec.normalize();
                
                nextPos.addScaledVector(moveVec, moveSpeed);
                weapon.position.y = -0.2 + Math.sin(Date.now() * 0.01) * 0.005;
            }

            velocityY += gravity; nextPos.y += velocityY;
            let floorY = getFloorY(nextPos), targetY = floorY + 1.7;
            
            if (nextPos.y < targetY) {
                // Плавный подъем (ступеньки)
                if (targetY - nextPos.y < 0.8) nextPos.y += (targetY - nextPos.y) * 0.4;
                else nextPos.y = targetY;
                velocityY = 0; canJump = true;
            }
            
            // Проверка коллизий раздельно по осям для скольжения вдоль стен
            let testPos = camera.position.clone();
            testPos.y = nextPos.y;
            
            testPos.x = nextPos.x;
            if (checkCollisions(testPos)) nextPos.x = camera.position.x;
            else testPos.x = nextPos.x;
            
            testPos.z = nextPos.z;
            if (checkCollisions(testPos)) nextPos.z = camera.position.z;

            camera.position.copy(nextPos);
            renderer.render(scene, camera);
        }
    </script>
</body>
</html>
"""

@app.get("/models/player.obj")
async def get_model():
    return FileResponse("my_persona_for_shyter.obj")

@app.get("/", response_class=HTMLResponse)
async def get():
    return html_content
