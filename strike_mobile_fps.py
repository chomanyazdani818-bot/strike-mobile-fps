"""
Strike Mobile FPS — single-file edition
Dependency: Panda3D (pip install panda3d)
Run: python strike_mobile_fps.py

This is a playable prototype foundation, not a finished Android APK.
"""
import math
import random
from dataclasses import dataclass

from panda3d.core import (
    AmbientLight, DirectionalLight, Vec3, Vec4, WindowProperties,
    TextNode, CollisionNode, CollisionBox, Point3, BitMask32
)
from direct.showbase.ShowBase import ShowBase
from direct.showbase.ShowBaseGlobal import globalClock
from direct.gui.OnscreenText import OnscreenText
from direct.gui.DirectGui import DirectButton
from direct.task import Task



# ======================== SETTINGS ========================

GAME_SECONDS = 300
TEAM_SIZE = 5
PLAYER_HP = 100
BOT_RESPAWN = 3.0
PLAYER_RESPAWN = 3.0
MOUSE_SENSITIVITY = 0.12
MOVE_SPEED = 8.0
SPRINT_MULTIPLIER = 1.45
BOT_VIEW_DISTANCE = 48.0
BOT_FIRE_RANGE = 34.0
BOT_TICK = 0.22


# ======================== WEAPONS ========================


@dataclass(frozen=True)
class Weapon:
    name: str
    damage: float
    head_multiplier: float
    rpm: float
    magazine: int
    reserve: int
    reload_time: float
    spread: float
    recoil: float
    range: float

WEAPONS = {
    "AK-47": Weapon("AK-47", 27, 2.0, 600, 30, 120, 2.2, 0.012, 1.8, 90),
    "M4A1": Weapon("M4A1", 24, 2.0, 750, 30, 120, 2.0, 0.009, 1.3, 90),
    "AWP": Weapon("AWP", 85, 1.35, 55, 5, 30, 2.8, 0.002, 4.0, 150),
    "Desert Eagle": Weapon("Desert Eagle", 48, 1.8, 220, 7, 35, 2.0, 0.014, 2.5, 65),
    "Glock": Weapon("Glock", 19, 1.7, 400, 20, 100, 1.8, 0.016, 1.2, 55),
    "USP": Weapon("USP", 22, 1.8, 300, 12, 72, 1.8, 0.010, 1.2, 65),
    "MP5": Weapon("MP5", 20, 1.7, 800, 30, 120, 1.9, 0.014, 1.1, 60),
}


# ======================== MAP ========================


def _box(parent, name, pos, scale, color, solid=True):
    from panda3d.core import GeomNode
    from panda3d.core import CollisionBox
    from panda3d.core import CollisionNode
    from panda3d.core import Point3
    from panda3d.core import BitMask32
    model = parent.attachNewNode("box_"+name)
    # Panda built-in cube geometry
    cm = CardMaker(name)
    cm.setFrame(-0.5, 0.5, -0.5, 0.5)
    # Use cube from procedural Geom via built-in model
    cube = loader.loadModel("models/box")
    if cube.isEmpty():
        cube = loader.loadModel("models/misc/rgbCube")
    cube.reparentTo(parent)
    cube.setName(name)
    cube.setPos(*pos)
    cube.setScale(*scale)
    cube.setColor(*color)
    cube.setColorScale(1,1,1,1)
    if solid:
        cnode = CollisionNode("wall")
        cnode.addSolid(CollisionBox(Point3(0,0,0), .5,.5,.5))
        cnp = cube.attachNewNode(cnode)
        cnp.setCollideMask(BitMask32.bit(1))
    return cube

def build_map(render):
    global loader
    from direct.showbase.ShowBase import ShowBaseGlobal
    loader = ShowBaseGlobal.loader
    # Ground
    ground = loader.loadModel("models/misc/rgbCube")
    ground.reparentTo(render)
    ground.setPos(0,0,-0.55)
    ground.setScale(65,65,1)
    ground.setColor(0.25,0.29,0.27,1)
    # Outer perimeter and urban cover
    blocks = [
        ((0,30,2),(62,1,4)), ((0,-30,2),(62,1,4)),
        ((30,0,2),(1,62,4)), ((-30,0,2),(1,62,4)),
        ((-12,10,1.5),(12,1,3)), ((-5,10,1.5),(1,10,3)),
        ((12,-8,1.5),(13,1,3)), ((18,-14,1.5),(1,12,3)),
        ((-20,-10,1.5),(1,12,3)), ((-23,-4,1.5),(8,1,3)),
        ((7,18,1.5),(1,8,3)), ((10,22,1.5),(8,1,3)),
        ((-5,-22,1.5),(12,1,3)), ((-12,-18,1.5),(1,8,3)),
    ]
    for i,(p,s) in enumerate(blocks):
        _box(render, f"wall{i}", p, s, (0.42,0.43,0.40,1))
    # Containers and crates as waist-high cover
    for i,(x,y) in enumerate([(-17,4),(-8,-2),(4,5),(17,8),(21,-20),(-3,-14),(9,-23)]):
        _box(render, f"crate{i}", (x,y,0.8), (3.2,2.2,1.6), (0.36,0.39,0.38,1))
    for i,(x,y) in enumerate([(-23,20),(23,18),(-22,-22),(23,-4)]):
        _box(render, f"container{i}", (x,y,1.5), (7,3,3), (0.20,0.31,0.36,1))
    # simple building blocks / rooftops
    for i,(x,y) in enumerate([(-22,0),(22,0),(0,24),(0,-25)]):
        _box(render, f"building{i}", (x,y,3), (9,7,6), (0.48,0.46,0.40,1))


# ======================== PLAYER ========================


class Player:
    def __init__(self, game):
        self.game = game
        self.hp = 100
        self.kills = 0
        self.deaths = 0
        self.team = 0
        self.spawn = Vec3(-25, -24, 1.7)
        self.mag = {}
        self.reserve = {}
        self.weapon_name = "AK-47"
        self.reload_left = 0
        self.fire_cooldown = 0
        self.recoil = 0
        self.dead_left = 0
        self.node = game.render.attachNewNode("player")
        self.node.setPos(self.spawn)
        self._init_weapons()
        self._build_gun()

    def _init_weapons(self):
        for n,w in WEAPONS.items():
            self.mag[n], self.reserve[n] = w.magazine, w.reserve

    def _build_gun(self):
        self.gun = self.game.render.attachNewNode("first_person_weapon")
        body = self.game.loader.loadModel("models/misc/rgbCube")
        body.reparentTo(self.gun); body.setScale(.16,.55,.15); body.setPos(.28,.55,-.22)
        body.setColor(.12,.14,.13,1)
        barrel = self.game.loader.loadModel("models/misc/rgbCube")
        barrel.reparentTo(self.gun); barrel.setScale(.045,.42,.045); barrel.setPos(.28,.98,-.18)
        barrel.setColor(.07,.08,.08,1)
        self.gun.reparentTo(self.game.camera)

    def select_weapon(self, name):
        if name in WEAPONS:
            self.weapon_name = name
            self.reload_left = 0

    def start_fire(self):
        self.firing = True
        self.fire_once()

    def stop_fire(self):
        self.firing = False

    firing = False

    def fire_once(self):
        if self.dead_left > 0 or self.reload_left > 0 or self.fire_cooldown > 0:
            return
        w = WEAPONS[self.weapon_name]
        if self.mag[self.weapon_name] <= 0:
            return
        self.mag[self.weapon_name] -= 1
        self.fire_cooldown = 60.0 / w.rpm
        self.recoil = min(self.recoil + w.recoil, 9)
        self.game.camera.setP(max(-80, self.game.camera.getP()-w.recoil*.12))
        self.game.manager.player_shot(w, self.game.camera.getPos(self.game.render),
                                      self.game.camera.getQuat(self.game.render).getForward(),
                                      w.spread)

    def reload(self):
        if self.reload_left <= 0 and self.mag[self.weapon_name] < WEAPONS[self.weapon_name].magazine and self.reserve[self.weapon_name] > 0:
            self.reload_left = WEAPONS[self.weapon_name].reload_time

    def jump(self):
        self.jump_v = 6.5

    jump_v = 0

    def update(self, dt, keys):
        if self.fire_cooldown > 0: self.fire_cooldown -= dt
        if self.reload_left > 0:
            self.reload_left -= dt
            if self.reload_left <= 0:
                w=WEAPONS[self.weapon_name]
                take=min(w.magazine-self.mag[self.weapon_name], self.reserve[self.weapon_name])
                self.mag[self.weapon_name]+=take; self.reserve[self.weapon_name]-=take
        if self.recoil > 0: self.recoil=max(0,self.recoil-dt*5)
        if self.firing: self.fire_once()
        if self.dead_left > 0:
            self.dead_left -= dt
            if self.dead_left <= 0: self.respawn()
            return
        h = self.game.camera.getH()
        forward = Vec3(-math.sin(math.radians(h)), math.cos(math.radians(h)), 0)
        right = Vec3(math.cos(math.radians(h)), math.sin(math.radians(h)), 0)
        move=Vec3(0,0,0)
        if keys.get("w"): move += forward
        if keys.get("s"): move -= forward
        if keys.get("d"): move += right
        if keys.get("a"): move -= right
        speed=MOVE_SPEED*(SPRINT_MULTIPLIER if keys.get("shift") else 1)
        if move.length()>0:
            move.normalize()
            self.node.setPos(self.node.getPos()+move*speed*dt)
        p=self.node.getPos()
        self.node.setPos(max(-28,min(28,p.x)),max(-28,min(28,p.y)),1.7)
        if self.jump_v:
            self.jump_v=max(0,self.jump_v-18*dt)
            self.node.setZ(min(1.7,self.node.getZ()+self.jump_v*dt))
        self.game.camera.setPos(self.node.getPos())
        self.gun.setZ(-.04 if keys.get("shift") else 0)

    def take_damage(self, amount):
        self.hp=max(0,self.hp-amount)
        if self.hp<=0:
            self.deaths+=1; self.dead_left=PLAYER_RESPAWN; self.node.hide(); self.game.manager.player_died()

    def respawn(self):
        self.hp=100; self.node.setPos(self.spawn); self.node.show()


# ======================== BOT AI ========================


class Bot:
    def __init__(self, game, team, index):
        self.game=game; self.team=team; self.index=index
        self.hp=100; self.kills=0; self.deaths=0; self.dead=0
        self.spawn=Vec3((-23 if team==0 else 23)+random.uniform(-3,3),
                        (-20+index*9 if team==0 else 20-index*9),1.0)
        self.pos=self.spawn
        self.node=game.render.attachNewNode("bot")
        self.body=game.loader.loadModel("models/misc/rgbCube")
        self.body.reparentTo(self.node); self.body.setScale(.55,.38,1.0)
        self.body.setColor((.12,.32,.85,1) if team==0 else (.78,.18,.12,1))
        self.head=game.loader.loadModel("models/misc/rgbCube")
        self.head.reparentTo(self.node); self.head.setScale(.30,.30,.30); self.head.setZ(1.18)
        self.head.setColor(.65,.55,.44,1)
        self.node.setPos(self.pos)
        self.target=None; self.think=0; self.fire=0
        self.wander=Vec3(random.uniform(-25,25),random.uniform(-25,25),0)

    def update(self,dt):
        if self.dead>0:
            self.dead-=dt
            if self.dead<=0: self.respawn()
            return
        self.think-=dt
        if self.think<=0:
            self.think=BOT_TICK+random.uniform(0,.18)
            candidates=[]
            if self.game.player.hp>0 and self.game.player.team!=self.team:
                candidates.append((self.game.player.node.getPos(),self.game.player))
            for b in self.game.manager.bots:
                if b is not self and b.team!=self.team and b.dead<=0:
                    candidates.append((b.node.getPos(),b))
            visible=[(p,o) for p,o in candidates if (p-self.pos).length()<BOT_VIEW_DISTANCE]
            self.target=min(visible,key=lambda q:(q[0]-self.pos).length())[1] if visible else None
            if self.hp<45 or not self.target:
                self.wander=Vec3(random.uniform(-25,25),random.uniform(-25,25),0)
        dest=self.wander
        if self.target:
            dest=self.target.node.getPos()
        delta=Vec3(dest.x-self.pos.x,dest.y-self.pos.y,0)
        dist=delta.length()
        if dist>1.5:
            delta.normalize()
            self.pos+=delta*min(4.0*dt,dist)
            self.node.setPos(self.pos)
            self.node.lookAt(dest.x,dest.y,self.pos.z)
        self.fire-=dt
        if self.target and dist<BOT_FIRE_RANGE and self.fire<=0:
            self.fire=random.uniform(.38,.75)
            # Accuracy improves at close range; bots use hitscan with modest hit chance.
            chance=max(.12,min(.72,.62-dist/85))
            if random.random()<chance:
                damage=random.randint(8,15)
                if self.target is self.game.player:
                    self.game.player.take_damage(damage)
                else:
                    self.target.take_damage(damage,self)

    def take_damage(self,amount,attacker=None):
        self.hp-=amount
        if self.hp<=0:
            self.dead=BOT_RESPAWN; self.deaths+=1; self.node.hide()
            if attacker:
                attacker.kills+=1
                self.game.manager.add_kill(attacker.team)

    def respawn(self):
        self.hp=100; self.pos=self.spawn; self.node.setPos(self.pos); self.node.show()


# ======================== GAME MANAGER ========================


class GameManager:
    def __init__(self,game,player):
        self.game=game; self.player=player
        self.bots=[]
        for team in (0,1):
            for i in range(4 if team == 0 else 5):
                self.bots.append(Bot(game,team,i))
        self.blue_score=0; self.red_score=0
        self.time_left=GAME_SECONDS; self.finished=False
        self.result=""
        self.player.team=0

    def update(self,dt):
        if self.finished: return
        self.time_left=max(0,self.time_left-dt)
        for bot in self.bots: bot.update(dt)
        if self.time_left<=0:
            self.finished=True
            self.result="BLUE TEAM WINS" if self.blue_score>=self.red_score else "RED TEAM WINS"

    def add_kill(self,team):
        if team==0: self.blue_score+=1
        else: self.red_score+=1

    def player_died(self):
        self.add_kill(1)

    def player_shot(self,weapon,origin,direction,spread):
        direction=Vec3(direction)
        direction.x+=random.uniform(-spread,spread)
        direction.z+=random.uniform(-spread,spread)
        direction.normalize()
        best=None; best_d=weapon.range
        # Bots are approximated by torso/head spheres along the ray.
        for bot in self.bots:
            if bot.team==self.player.team or bot.dead>0: continue
            center=bot.node.getPos()+Vec3(0,0,.65)
            to=center-origin
            along=to.dot(direction)
            if 0<along<best_d:
                closest=origin+direction*along
                if (center-closest).length()<.9:
                    best=bot; best_d=along
        if best:
            hit=origin+direction*best_d
            head=(hit-(best.node.getPos()+Vec3(0,0,1.18))).length()<.34
            was_alive = best.dead <= 0
            best.take_damage(weapon.damage*(weapon.head_multiplier if head else 1), self.player)
            if was_alive and best.dead > 0:
                self.player.kills += 1
                self.add_kill(0)


# ======================== HUD ========================


class HUD:
    def __init__(self,game):
        self.game=game
        self.info=OnscreenText(text="",pos=(-1.30,.92),scale=.045,fg=(1,1,1,1),
                               align=TextNode.ALeft,mayChange=True)
        self.center=OnscreenText(text="+",pos=(0,0),scale=.06,fg=(1,1,1,1))
        self.notice=OnscreenText(text="WASD move | Mouse aim | Click fire | R reload | 1-5 weapons",
                                 pos=(0,-.94),scale=.04,fg=(1,1,1,1),mayChange=True)
        self.map_text=OnscreenText(text="MINI MAP\\nBLUE: You / Allies\\nRED: Enemies",
                                   pos=(1.15,.88),scale=.035,fg=(1,1,1,1),
                                   align=TextNode.ACenter,mayChange=True)
        self.end=OnscreenText(text="",pos=(0,.15),scale=.10,fg=(1,.85,.2,1),mayChange=True)
        self.map_visible=True

    def toggle_map(self):
        self.map_visible=not self.map_visible
        self.map_text.show() if self.map_visible else self.map_text.hide()

    def update(self,m,p):
        from weapons import WEAPONS
        w=WEAPONS[p.weapon_name]
        self.info.setText(
            f"HP {p.hp:3.0f}   K/D {p.kills}/{p.deaths}\\n"
            f"BLUE {m.blue_score}  -  RED {m.red_score}\\n"
            f"{int(m.time_left//60):02d}:{int(m.time_left%60):02d}\\n"
            f"{p.weapon_name}  {p.mag[p.weapon_name]}/{p.reserve[p.weapon_name]}"
        )
        if m.finished: self.end.setText(m.result+"\\nPress ESC to exit")


# ======================== TOUCH CONTROLS ========================

"""Touch-friendly on-screen controls.
On Android builds, Panda3D reports touch pointers through the mouse interface on many
backends. These large clickable regions also work with mouse for desktop testing.
"""

class TouchControls:
    def __init__(self,game):
        self.game=game
        self.buttons=[]
        # Visible control labels are positioned to avoid overlapping HUD.
        self._button("FIRE", .88, -.62, game.player.start_fire, game.player.stop_fire)
        self._button("ADS", .68, -.68, lambda: game.camLens.setFov(55), lambda: game.camLens.setFov(80))
        self._button("JUMP", .88, -.82, game.player.jump)
        self._button("RELOAD", .62, -.88, game.player.reload)
        self._button("SWAP", .40, -.88, lambda: game.player.select_weapon("M4A1"))
        self._button("MAP", 1.12, .60, game.hud.toggle_map)

    def _button(self,label,x,y,command,release=None):
        b=DirectButton(text=label,scale=.055,pos=(x,0,y),frameColor=(.08,.12,.16,.78),
                       text_fg=(1,1,1,1),command=command,extraArgs=[])
        if release:
            b.bind("B1release",lambda *_: release())
        self.buttons.append(b)


# ======================== MAIN APPLICATION ========================


class StrikeFPS(ShowBase):
    def __init__(self):
        super().__init__()
        self.disableMouse()
        self.setBackgroundColor(0.48, 0.62, 0.70, 1)
        props = WindowProperties()
        props.setTitle("Strike Mobile FPS")
        props.setCursorHidden(True)
        self.win.requestProperties(props)
        self.setFrameRateMeter(False)

        self.render.setShaderAuto()
        self._lighting()
        build_map(self.render)

        self.player = Player(self)
        self.manager = GameManager(self, self.player)
        self.hud = HUD(self)
        self.controls = TouchControls(self)

        self.accept("escape", self.userExit)
        self.accept("mouse1", self.player.start_fire)
        self.accept("mouse1-up", self.player.stop_fire)
        self.accept("r", self.player.reload)
        self.accept("space", self.player.jump)
        self.accept("1", lambda: self.player.select_weapon("AK-47"))
        self.accept("2", lambda: self.player.select_weapon("M4A1"))
        self.accept("3", lambda: self.player.select_weapon("AWP"))
        self.accept("4", lambda: self.player.select_weapon("Desert Eagle"))
        self.accept("5", lambda: self.player.select_weapon("MP5"))
        self.accept("tab", self.hud.toggle_map)

        self.keys = {k: False for k in ["w","a","s","d","shift","control"]}
        for key in ["w","a","s","d","shift","control"]:
            self.accept(key, self.set_key, [key, True])
            self.accept(key+"-up", self.set_key, [key, False])

        self.camera.setPos(0, 0, 0)
        self.camera.setHpr(0, 0, 0)
        self.camLens.setFov(80)
        self.taskMgr.add(self.update, "game-update")
        self.taskMgr.add(self.mouse_look, "mouse-look")
        self.mouse_center = None
        self.accept("window-event", self.window_event)
        self.window_event(self.win)

    def _lighting(self):
        ambient = AmbientLight("ambient")
        ambient.setColor(Vec4(0.48, 0.50, 0.55, 1))
        self.render.setLight(self.render.attachNewNode(ambient))
        sun = DirectionalLight("sun")
        sun.setColor(Vec4(0.95, 0.91, 0.82, 1))
        sun.setDirection(Vec3(-1, -2, -3))
        self.render.setLight(self.render.attachNewNode(sun))

    def set_key(self, key, value):
        self.keys[key] = value

    def window_event(self, window):
        if window and window.getProperties().getForeground():
            self.mouse_center = (window.getXSize()//2, window.getYSize()//2)

    def mouse_look(self, task):
        if self.mouseWatcherNode.hasMouse() and self.mouse_center:
            m = self.win.getPointer(0)
            cx, cy = self.mouse_center
            dx, dy = m.getX()-cx, m.getY()-cy
            if abs(dx)+abs(dy) > 0:
                self.camera.setH(self.camera.getH()-dx*0.12)
                self.camera.setP(max(-80, min(80, self.camera.getP()+dy*0.10)))
                self.win.movePointer(0, cx, cy)
        return Task.cont

    def update(self, task):
        dt = min(globalClock.getDt(), 0.05)
        if not self.manager.finished:
            self.player.update(dt, self.keys)
            self.manager.update(dt)
            self.hud.update(self.manager, self.player)
        return Task.cont

app = StrikeFPS()
app.run()
