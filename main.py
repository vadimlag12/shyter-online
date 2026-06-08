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
        # Цвета для разных ландшафтов: Зеленые поля, Пустыня, Неоновый город
        self.landscapes = ["#2ecc71", "#f1c40f", "#9b59b6"]
        self.current_landscape = self.landscapes[0]

    async def connect(self, websocket: WebSocket, player_id: str):
        await websocket.accept()
        self.active_connections[player_id] = websocket
        self.players[player_id] = {"x": 0, "z": 0, "color": f"#{random.randint(0, 0xFFFFFF):06x}"}
        
        # Передаем игроку текущую карту и список уже подключенных людей
        await websocket.send_text(json.dumps({
            "type": "init",
            "id": player_id,
            "landscape": self.current_landscape,
            "round": self.current_round,
            "players": self.players
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

# Фоновый цикл смены раундов (каждые 30 секунд)
async def round_manager():
    while True:
        await asyncio.sleep(30)
        server.current_round += 1
        server.current_landscape = server.landscapes[(server.current_round - 1) % len(server.landscapes)]
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
                await server.broadcast({
                    "type": "update",
                    "id": player_id,
                    "x": msg["x"],
                    "z": msg["z"]
                })
    except WebSocketDisconnect:
        server.disconnect(player_id)
        await server.broadcast({"type": "leave", "id": player_id})

# --- ТРЁХМЕРНАЯ ГРАФИКА ДЛЯ БРАУЗЕРА (FRONTEND) ---

html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>3D HTML5 WebGL Shooter</title>
    <style>
        body { margin: 0; overflow: hidden; font-family: sans-serif; }
        #ui { position: absolute; top: 10px; left: 10px; color: white; background: rgba(0,0,0,0.5); padding: 10px; border-radius: 5px; }
        #crosshair { position: absolute; top: 50%; left: 50%; width: 10px; height: 10px; background: red; border-radius: 50%; transform: translate(-50%, -50%); pointer-events: none; }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
    <div id="ui">
        <div id="round_info">Загрузка раунда...</div>
        <div>Управление: WASD / Мышь (кликни на экран для захвата)</div>
    </div>
    <div id="crosshair"></div>

    <script>
        let scene, camera, renderer, ground;
        let players = {};
        let myId = null;
        let ws;
        let keys = { w:0, a:0, s:0, d:0 };
        let moveSpeed = 0.2;
        
        // Настройка 3D Сцены
        function init3D() {
            scene = new THREE.Scene();
            scene.background = new THREE.Color(0x87ceeb);
            
            camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
            renderer = new THREE.WebGLRenderer({ antialias: true });
            renderer.setSize(window.innerWidth, window.innerHeight);
            document.body.appendChild(renderer.domElement);
            
            // Свет
            const light = new THREE.DirectionalLight(0xffffff, 1);
            light.position.set(5, 10, 7).normalize();
            scene.add(light);
            scene.add(new THREE.AmbientLight(0x404040));

            // Земля (Ландшафт)
            const geometry = new THREE.PlaneGeometry(100, 100);
            const material = new THREE.MeshLambertMaterial({ color: 0x2ecc71 });
            ground = new THREE.Mesh(geometry, material);
            ground.rotation.x = -Math.PI / 2;
            scene.add(ground);

            camera.position.y = 2; // Рост игрока

            // Захват мыши для FPS управления
            document.body.requestPointerLock = document.body.requestPointerLock || document.body.mozRequestPointerLock;
            document.addEventListener('click', () => { document.body.requestPointerLock(); });
            document.addEventListener('mousemove', onMouseMove);
            
            window.addEventListener('keydown', (e) => { if(e.key in keys) keys[e.key] = 1; });
            window.addEventListener('keyup', (e) => { if(e.key in keys) keys[e.key] = 0; });
            
            animate();
        }

        let yaw = 0, pitch = 0;
        function onMouseMove(e) {
            if (document.pointerLockElement === document.body) {
                yaw -= e.movementX * 0.002;
                pitch -= e.movementY * 0.002;
                pitch = Math.max(-Math.PI/2.5, Math.min(Math.PI/2.5, pitch));
                camera.rotation.set(pitch, yaw, 0, 'YXZ');
            }
        }

        // Подключение к WebSocket на Render
        function initNetwork() {
            const proto = location.protocol === "https:" ? "wss://" : "ws://";
            const randomId = Math.floor(Math.random() * 10000);
            ws = new WebSocket(proto + location.host + "/ws/user_" + randomId);

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);

                if (data.type === "init") {
                    myId = data.id;
                    ground.material.color.set(data.landscape);
                    document.getElementById("round_info").innerText = "Раунд: " + data.round;
                    
                    // Создаем уже существующих игроков
                    for (let id in data.players) {
                        if (id !== myId) createEnemy(id, data.players[id]);
                    }
                } 
                else if (data.type === "new_round") {
                    ground.material.color.set(data.landscape);
                    document.getElementById("round_info").innerText = "Раунд: " + data.round;
                }
                else if (data.type === "update" && data.id !== myId) {
                    if (!players[data.id]) createEnemy(data.id, data);
                    players[data.id].position.set(data.x, 1, data.z);
                }
                else if (data.type === "leave" && players[data.id]) {
                    scene.remove(players[data.id]);
                    delete players[data.id];
                }
            };
        }

        function createEnemy(id, info) {
            const cubeGeo = new THREE.BoxGeometry(1, 2, 1);
            const cubeMat = new THREE.MeshLambertMaterial({ color: info.color || 0xff0000 });
            const mesh = new THREE.Mesh(cubeGeo, cubeMat);
            mesh.position.set(info.x || 0, 1, info.z || 0);
            scene.add(mesh);
            players[id] = mesh;
        }

        // Главный цикл отрисовки и физики
        function animate() {
            requestAnimationFrame(animate);

            // Движение игрока с учетом направления взгляда
            const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
            forward.y = 0; forward.normalize();
            const side = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion);
            side.y = 0; side.normalize();

            if (keys.w) { camera.position.addScaledVector(forward, moveSpeed); }
            if (keys.s) { camera.position.addScaledVector(forward, -moveSpeed); }
            if (keys.a) { camera.position.addScaledVector(side, -moveSpeed); }
            if (keys.d) { camera.position.addScaledVector(side, moveSpeed); }

            // Отправка координат серверу
            if (ws && ws.readyState === WebSocket.OPEN && myId) {
                ws.send(json_string = JSON.stringify({
                    type: "move",
                    x: camera.position.x,
                    z: camera.position.z
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