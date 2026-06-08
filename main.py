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
        # Темы карт: Зеленые поля, Марс, Киберпанк
        self.landscapes = ["#2ecc71", "#e67e22", "#9b59b6"]
        self.current_landscape = self.landscapes[0]

    async def connect(self, websocket: WebSocket, player_id: str):
        await websocket.accept()
        self.active_connections[player_id] = websocket
        
        # Спавним игрока в случайной точке
        x, z = random.randint(-20, 20), random.randint(-20, 20)
        self.players[player_id] = {
            "x": x, "z": z, 
            "color": f"#{random.randint(0, 0xFFFFFF):06x}",
            "hp": 100,
            "score": 0
        }
        
        await websocket.send_text(json.dumps({
            "type": "init",
            "id": player_id,
            "landscape": self.current_landscape,
            "round": self.current_round,
            "players": self.players,
            "x": x, "z": z
        }))

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
        await asyncio.sleep(60) # Раунд длится 60 секунд
        server.current_round += 1
        server.current_landscape = server.landscapes[(server.current_round - 1) % len(server.landscapes)]
        
        # Восстанавливаем всем HP в новом раунде
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
            
            if msg["type"] == "move":
                server.players[player_id]["x"] = msg["x"]
                server.players[player_id]["z"] = msg["z"]
                # Рассылаем поворот башни/тела для реалистичности
                await server.broadcast({
                    "type": "update",
                    "id": player_id,
                    "x": msg["x"],
                    "z": msg["z"],
                    "ry": msg.get("ry", 0)
                })
                
            elif msg["type"] == "hit":
                target_id = msg["target"]
                if target_id in server.players:
                    server.players[target_id]["hp"] -= 25 # Урон от одного попадания
                    
                    if server.players[target_id]["hp"] <= 0:
                        server.players[player_id]["score"] += 1
                        server.players[target_id]["hp"] = 100
                        # Возрождаем убитого в новой точке
                        nx, nz = random.randint(-20, 20), random.randint(-20, 20)
                        server.players[target_id]["x"] = nx
                        server.players[target_id]["z"] = nz
                        
                        await server.broadcast({
                            "type": "respawn",
                            "id": target_id,
                            "x": nx, "z": nz,
                            "killer": player_id
                        })
                    
                    await server.broadcast({
                        "type": "hp_update",
                        "id": target_id,
                        "hp": server.players[target_id]["hp"]
                    })
                    
    except WebSocketDisconnect:
        server.disconnect(player_id)
        await server.broadcast({"type": "leave", "id": player_id})


# --- ТРЁХМЕРНАЯ ГРАФИКА ДЛЯ БРАУЗЕРА (FRONTEND) ---

html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>3D Arena Shooter</title>
    <style>
        body { margin: 0; overflow: hidden; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; user-select: none; }
        #ui { position: absolute; top: 10px; left: 10px; color: white; background: rgba(0,0,0,0.7); padding: 15px; border-radius: 8px; border: 1px solid #444; }
        #crosshair { position: absolute; top: 50%; left: 50%; width: 4px; height: 4px; background: #00ff00; border-radius: 50%; transform: translate(-50%, -50%); pointer-events: none; box-shadow: 0 0 5px #00ff00; }
        #hp_bar_container { position: absolute; bottom: 20px; left: 20px; width: 300px; height: 20px; background: rgba(0,0,0,0.5); border: 2px solid #fff; }
        #hp_bar { width: 100%; height: 100%; background: #2ecc71; transition: width 0.2s, background-color 0.2s; }
        #damage_overlay { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,0,0,0.3); pointer-events: none; opacity: 0; transition: opacity 0.1s; }
        h3 { margin: 0 0 10px 0; font-size: 16px; color: #f1c40f; }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
    <div id="ui">
        <h3>ARENA ONLINE</h3>
        <div id="round_info">Загрузка...</div>
        <div id="score_info">Фраги: 0</div>
        <div style="font-size: 12px; margin-top: 10px; color: #aaa;">WASD - Движение<br>Мышь - Обзор / Огонь</div>
    </div>
    <div id="hp_bar_container"><div id="hp_bar"></div></div>
    <div id="crosshair"></div>
    <div id="damage_overlay"></div>

    <script>
        let scene, camera, renderer, ground;
        let players = {};
        let myId = null;
        let ws;
        let keys = { w:0, a:0, s:0, d:0 };
        let moveSpeed = 0.25;
        let myHp = 100;
        let myScore = 0;
        
        let weapon;
        let isShooting = false;
        let recoilOffset = 0;
        
        let obstacles = new THREE.Group();

        function init3D() {
            scene = new THREE.Scene();
            scene.background = new THREE.Color(0x87ceeb);
            scene.fog = new THREE.Fog(0x87ceeb, 20, 80);
            
            camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
            renderer = new THREE.WebGLRenderer({ antialias: true });
            renderer.setSize(window.innerWidth, window.innerHeight);
            renderer.shadowMap.enabled = true;
            document.body.appendChild(renderer.domElement);
            
            // Освещение
            const light = new THREE.DirectionalLight(0xffffff, 0.8);
            light.position.set(20, 50, 20);
            light.castShadow = true;
            scene.add(light);
            scene.add(new THREE.AmbientLight(0x606060));

            // Земля
            const geometry = new THREE.PlaneGeometry(200, 200);
            const material = new THREE.MeshLambertMaterial({ color: 0x2ecc71 });
            ground = new THREE.Mesh(geometry, material);
            ground.rotation.x = -Math.PI / 2;
            ground.receiveShadow = true;
            scene.add(ground);
            scene.add(obstacles);

            // Оружие от первого лица
            createWeapon();

            camera.position.y = 1.6; // Высота глаз

            // Управление
            document.body.requestPointerLock = document.body.requestPointerLock || document.body.mozRequestPointerLock;
            document.addEventListener('click', () => { 
                if(document.pointerLockElement !== document.body) {
                    document.body.requestPointerLock(); 
                } else {
                    shoot();
                }
            });
            document.addEventListener('mousemove', onMouseMove);
            
            window.addEventListener('keydown', (e) => { if(e.key.toLowerCase() in keys) keys[e.key.toLowerCase()] = 1; });
            window.addEventListener('keyup', (e) => { if(e.key.toLowerCase() in keys) keys[e.key.toLowerCase()] = 0; });
            window.addEventListener('resize', () => {
                camera.aspect = window.innerWidth / window.innerHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(window.innerWidth, window.innerHeight);
            });
            
            animate();
        }

        function createWeapon() {
            const gunGroup = new THREE.Group();
            
            // Ствол
            const barrelGeo = new THREE.BoxGeometry(0.1, 0.1, 0.6);
            const barrelMat = new THREE.MeshLambertMaterial({ color: 0x222222 });
            const barrel = new THREE.Mesh(barrelGeo, barrelMat);
            barrel.position.set(0, 0, -0.2);
            
            // Рукоятка
            const gripGeo = new THREE.BoxGeometry(0.1, 0.2, 0.1);
            const grip = new THREE.Mesh(gripGeo, barrelMat);
            grip.position.set(0, -0.15, 0.05);
            grip.rotation.x = 0.2;

            gunGroup.add(barrel);
            gunGroup.add(grip);
            
            // Позиция оружия относительно камеры
            gunGroup.position.set(0.3, -0.25, -0.5);
            weapon = gunGroup;
            camera.add(weapon);
            scene.add(camera);
        }

        // Генерация укрытий (города)
        function generateMapObstacles(seedRound) {
            // Удаляем старые
            while(obstacles.children.length > 0){ 
                obstacles.remove(obstacles.children[0]); 
            }
            
            // Генерируем псевдослучайно на основе раунда
            for(let i=0; i<30; i++) {
                const w = 2 + (Math.sin(seedRound + i) * 3 + 3);
                const h = 2 + (Math.cos(seedRound * i) * 4 + 4);
                const d = 2 + (Math.sin(seedRound - i) * 3 + 3);
                
                const boxGeo = new THREE.BoxGeometry(w, h, d);
                const boxMat = new THREE.MeshLambertMaterial({ color: 0x7f8c8d });
                const box = new THREE.Mesh(boxGeo, boxMat);
                
                box.position.set(
                    (Math.sin(i * 123) * 40),
                    h/2,
                    (Math.cos(i * 321) * 40)
                );
                box.castShadow = true;
                box.receiveShadow = true;
                obstacles.add(box);
            }
        }

        let yaw = 0, pitch = 0;
        function onMouseMove(e) {
            if (document.pointerLockElement === document.body) {
                yaw -= e.movementX * 0.002;
                pitch -= e.movementY * 0.002;
                pitch = Math.max(-Math.PI/2.1, Math.min(Math.PI/2.1, pitch));
                camera.rotation.set(pitch, yaw, 0, 'YXZ');
            }
        }

        function shoot() {
            if(isShooting) return;
            isShooting = true;
            recoilOffset = 0.1; // Отдача
            
            // Raycasting (проверка попадания)
            const raycaster = new THREE.Raycaster();
            raycaster.setFromCamera(new THREE.Vector2(0, 0), camera);
            
            // Собираем всех врагов в массив
            const enemyMeshes = [];
            for (let id in players) {
                enemyMeshes.push(players[id]);
            }
            
            const intersects = raycaster.intersectObjects(enemyMeshes, true);
            
            if(intersects.length > 0) {
                // Ищем ID игрока, в которого попали
                let hitObject = intersects[0].object;
                while(hitObject.parent && hitObject.parent.type !== "Scene") {
                    if(hitObject.userData.id) break;
                    hitObject = hitObject.parent;
                }
                
                if(hitObject.userData.id && ws) {
                    ws.send(JSON.stringify({
                        type: "hit",
                        target: hitObject.userData.id
                    }));
                }
            }
            
            // Звук выстрела (заглушка)
            setTimeout(() => { isShooting = false; }, 150);
        }

        function initNetwork() {
            const proto = location.protocol === "https:" ? "wss://" : "ws://";
            const randomId = Math.floor(Math.random() * 100000);
            ws = new WebSocket(proto + location.host + "/ws/player_" + randomId);

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);

                if (data.type === "init") {
                    myId = data.id;
                    ground.material.color.set(data.landscape);
                    scene.fog.color.set(data.landscape);
                    document.getElementById("round_info").innerText = "Раунд: " + data.round;
                    generateMapObstacles(data.round);
                    
                    camera.position.x = data.x;
                    camera.position.z = data.z;

                    for (let id in data.players) {
                        if (id !== myId) createEnemy(id, data.players[id]);
                    }
                } 
                else if (data.type === "new_round") {
                    ground.material.color.set(data.landscape);
                    scene.fog.color.set(data.landscape);
                    document.getElementById("round_info").innerText = "Раунд: " + data.round;
                    generateMapObstacles(data.round);
                }
                else if (data.type === "update" && data.id !== myId) {
                    if (!players[data.id]) createEnemy(data.id, data);
                    // Плавная интерполяция
                    players[data.id].position.x = data.x;
                    players[data.id].position.z = data.z;
                    players[data.id].rotation.y = data.ry;
                }
                else if (data.type === "hp_update") {
                    if(data.id === myId) {
                        updateHp(data.hp);
                        flashDamage();
                    }
                }
                else if (data.type === "respawn") {
                    if(data.id === myId) {
                        camera.position.x = data.x;
                        camera.position.z = data.z;
                        updateHp(100);
                        document.body.style.background = "red";
                        setTimeout(() => document.body.style.background = "", 100);
                    } else if (data.killer === myId) {
                        myScore++;
                        document.getElementById("score_info").innerText = "Фраги: " + myScore;
                        // Эффект попадания (маркер)
                        document.getElementById("crosshair").style.background = "red";
                        setTimeout(() => document.getElementById("crosshair").style.background = "#00ff00", 200);
                    }
                    if(players[data.id]) {
                        players[data.id].position.set(data.x, 0, data.z);
                    }
                }
                else if (data.type === "leave" && players[data.id]) {
                    scene.remove(players[data.id]);
                    delete players[data.id];
                }
            };
        }

        function createEnemy(id, info) {
            const group = new THREE.Group();
            group.userData.id = id;

            // Туловище
            const bodyGeo = new THREE.CylinderGeometry(0.4, 0.4, 1.4, 8);
            const bodyMat = new THREE.MeshLambertMaterial({ color: info.color || 0xff0000 });
            const body = new THREE.Mesh(bodyGeo, bodyMat);
            body.position.y = 0.7;
            body.castShadow = true;
            body.userData.id = id;

            // Голова
            const headGeo = new THREE.BoxGeometry(0.5, 0.5, 0.5);
            const headMat = new THREE.MeshLambertMaterial({ color: 0xffccaa });
            const head = new THREE.Mesh(headGeo, headMat);
            head.position.y = 1.65;
            head.castShadow = true;
            head.userData.id = id;

            // Рюкзак (чтобы видеть где спина)
            const packGeo = new THREE.BoxGeometry(0.5, 0.6, 0.3);
            const pack = new THREE.Mesh(packGeo, bodyMat);
            pack.position.set(0, 0.8, 0.3);
            pack.userData.id = id;

            group.add(body);
            group.add(head);
            group.add(pack);
            
            group.position.set(info.x || 0, 0, info.z || 0);
            scene.add(group);
            players[id] = group;
        }

        function updateHp(hp) {
            myHp = hp;
            const bar = document.getElementById("hp_bar");
            bar.style.width = hp + "%";
            if(hp > 50) bar.style.background = "#2ecc71";
            else if(hp > 20) bar.style.background = "#f1c40f";
            else bar.style.background = "#e74c3c";
        }

        function flashDamage() {
            const overlay = document.getElementById("damage_overlay");
            overlay.style.opacity = "1";
            setTimeout(() => { overlay.style.opacity = "0"; }, 150);
        }

        function animate() {
            requestAnimationFrame(animate);

            // Анимация отдачи
            if(recoilOffset > 0) {
                weapon.rotation.x = recoilOffset;
                recoilOffset -= 0.01;
            } else {
                weapon.rotation.x = 0;
            }

            // Движение
            const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
            forward.y = 0; forward.normalize();
            const side = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion);
            side.y = 0; side.normalize();

            let moved = false;
            if (keys.w) { camera.position.addScaledVector(forward, moveSpeed); moved = true; }
            if (keys.s) { camera.position.addScaledVector(forward, -moveSpeed); moved = true; }
            if (keys.a) { camera.position.addScaledVector(side, -moveSpeed); moved = true; }
            if (keys.d) { camera.position.addScaledVector(side, moveSpeed); moved = true; }

            // Эффект шагов (качание камеры)
            if(moved && !isShooting) {
                weapon.position.y = -0.25 + Math.sin(Date.now() * 0.01) * 0.02;
            } else {
                weapon.position.y = -0.25;
            }

            // Отправка координат (шлем также yaw камеры, чтобы моделька крутилась)
            if (ws && ws.readyState === WebSocket.OPEN && myId && moved) {
                ws.send(JSON.stringify({
                    type: "move",
                    x: camera.position.x,
                    z: camera.position.z,
                    ry: yaw // передаем поворот по Y
                }));
            }

            renderer.render(scene, camera);
        }

        window.onload = () => {
            init3D();
            initNetwork();
        };
    </script>
</body>
</html>
"""

@app.get("/")
async def get():
    return HTMLResponse(html_content)
