// three.js renderer for the comparison. render.cjs opens this page headless,
// calls window.renderAt(t) for every frame and screenshots the canvas.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { Line2 } from "three/addons/lines/Line2.js";
import { LineGeometry } from "three/addons/lines/LineGeometry.js";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { BokehPass } from "three/addons/postprocessing/BokehPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { cameraAt, lookBasis, phonePose, laptopPose, lidTilt, screenLocal, tileLocal, phoneLaunchLocal,
  heroState, heroPoint, floorString, verticalFov } from "../motion.js";

const params = new URLSearchParams(location.search);
const spec = await (await fetch("../scene.json")).json();
const format = spec.formats[params.get("format") || "story"];
const W = format.width, H = format.height;

const renderer = new THREE.WebGLRenderer({ antialias: false, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(W, H);
renderer.toneMapping = THREE.NeutralToneMapping;
renderer.toneMappingExposure = 1.0;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(spec.colors.background);
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.22;

const camera = new THREE.PerspectiveCamera(THREE.MathUtils.radToDeg(verticalFov(spec, W / H)), W / H, 0.05, 80);
const color = (hex) => new THREE.Color(hex);

// Light: a soft key from above, cyan behind the phone and violet behind the laptop.
const key = new THREE.DirectionalLight(0xffffff, 1.3);
key.position.set(2, 6, 5);
scene.add(key);
const cyan = new THREE.PointLight(color(spec.colors.wave1), 22, 9, 2);
cyan.position.set(-2.4, 0.9, 0.2);
scene.add(cyan);
const violet = new THREE.PointLight(color(spec.colors.wave3), 26, 10, 2);
violet.position.set(2.8, 1.6, -3.2);
scene.add(violet);

const loader = new THREE.TextureLoader();
const texture = async (url) => {
  const t = await loader.loadAsync(new URL(url, new URL("../", location.href)).href);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
};
const [phoneTex, afterTex, beforeTex, photoTex, backdropTex] = await Promise.all(
  [spec.phone.screen, spec.laptop.screen, spec.laptop.screenBefore, spec.photo.image, spec.backdrop.image].map(texture));

// Far glow plane so the sky above the devices carries colour.
const backdrop = new THREE.Mesh(new THREE.PlaneGeometry(...spec.backdrop.size), new THREE.MeshBasicMaterial({ map: backdropTex, depthWrite: false }));
backdrop.position.set(...spec.backdrop.position);
scene.add(backdrop);

const bodyMaterial = new THREE.MeshPhysicalMaterial({ color: spec.colors.body, metalness: 0.75, roughness: 0.3, clearcoat: 0.6, clearcoatRoughness: 0.25 });
const screenMaterial = (map, extra = {}) => new THREE.MeshBasicMaterial({ map, transparent: true, color: new THREE.Color(0.92, 0.92, 0.92), ...extra });

// Phone.
const phone = new THREE.Group();
{
  const [w, h, d] = spec.phone.size, inset = spec.phone.screenInset;
  phone.add(new THREE.Mesh(new RoundedBoxGeometry(w, h, d, 6, spec.phone.radius), bodyMaterial));
  const glass = new THREE.Mesh(new THREE.PlaneGeometry(w - inset * 2, h - inset * 2), screenMaterial(phoneTex));
  glass.position.z = d / 2 + 0.001;
  phone.add(glass);
}
scene.add(phone);

// Laptop: base, keyboard well, hinge pivot, lid and two screen states.
const laptop = new THREE.Group();
const lidPivot = new THREE.Group();
let beforeScreen;
{
  const l = spec.laptop, [bw, bh, bd] = l.base;
  const base = new THREE.Mesh(new RoundedBoxGeometry(bw, bh, bd, 4, l.radius), bodyMaterial);
  base.position.y = bh / 2;
  laptop.add(base);
  const well = new THREE.Mesh(new THREE.PlaneGeometry(bw * 0.86, bd * 0.42), new THREE.MeshStandardMaterial({ color: 0x0b0f16, roughness: 0.8 }));
  well.rotation.x = -Math.PI / 2;
  well.position.set(0, bh + 0.002, -bd * 0.16);
  laptop.add(well);
  const pad = new THREE.Mesh(new THREE.PlaneGeometry(bw * 0.3, bd * 0.26), new THREE.MeshStandardMaterial({ color: 0x232c3b, roughness: 0.45, metalness: 0.3 }));
  pad.rotation.x = -Math.PI / 2;
  pad.position.set(0, bh + 0.002, bd * 0.26);
  laptop.add(pad);

  lidPivot.position.set(0, bh, -bd / 2);
  lidPivot.rotation.x = lidTilt(spec);
  const [lw, lh, lt] = l.lid;
  const lid = new THREE.Mesh(new RoundedBoxGeometry(lw, lh, lt, 4, l.radius / 2), bodyMaterial);
  lid.position.set(0, lh / 2, lt / 2);
  lidPivot.add(lid);
  const c = screenLocal(spec), [sw, sh] = l.screenSize;
  const after = new THREE.Mesh(new THREE.PlaneGeometry(sw, sh), screenMaterial(afterTex));
  after.position.set(...c);
  lidPivot.add(after);
  beforeScreen = new THREE.Mesh(new THREE.PlaneGeometry(sw, sh), screenMaterial(beforeTex, { depthWrite: false }));
  beforeScreen.position.set(c[0], c[1], c[2] + 0.0015);
  lidPivot.add(beforeScreen);
  laptop.add(lidPivot);
}
scene.add(laptop);

// String field.
const resolution = new THREE.Vector2(W, H);
const stops = [color(spec.colors.wave1), color(spec.colors.wave2), color(spec.colors.wave3)];
const gradient = (u) => (u < 0.45 ? stops[0].clone().lerp(stops[1], u / 0.45) : stops[1].clone().lerp(stops[2], (u - 0.45) / 0.55));
const floor = [];
for (let i = 0; i < spec.strings.count; i++) {
  const material = new LineMaterial({ vertexColors: true, linewidth: 0.012, worldUnits: true, resolution });
  const line = new Line2(new LineGeometry(), material);
  line.frustumCulled = false;
  scene.add(line);
  floor.push(line);
}
const heroLine = new Line2(new LineGeometry(), new LineMaterial({ vertexColors: true, linewidth: 0.026, worldUnits: true, resolution }));
heroLine.frustumCulled = false;
scene.add(heroLine);
const bead = new THREE.Mesh(new THREE.SphereGeometry(0.05, 24, 16), new THREE.MeshBasicMaterial({ color: new THREE.Color(4, 6, 6.5) }));
scene.add(bead);
const card = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: photoTex, transparent: true, side: THREE.DoubleSide, color: new THREE.Color(0.66, 0.66, 0.66) }));
scene.add(card);

// Post: depth of field, then bloom, then tone mapping.
const target = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType, samples: 4 });
const composer = new EffectComposer(renderer, target);
composer.setPixelRatio(1);
composer.setSize(W, H);
composer.addPass(new RenderPass(scene, camera));
const bokeh = new BokehPass(scene, camera, { focus: 5, aperture: 0.0016, maxblur: 0.006 });
composer.addPass(bokeh);
composer.addPass(new UnrealBloomPass(new THREE.Vector2(W, H), 0.85, 0.55, 0.82));
composer.addPass(new OutputPass());

const v3 = (a) => new THREE.Vector3(...a);
const tmpQ = new THREE.Quaternion();

window.renderAt = (t) => {
  const pp = phonePose(spec, t), lp = laptopPose(spec, t);
  phone.position.set(...pp.position);
  phone.rotation.set(...pp.rotation);
  laptop.position.set(...lp.position);
  laptop.rotation.set(...lp.rotation);
  scene.updateMatrixWorld(true);

  const cam = cameraAt(spec, t), basis = lookBasis(cam.pos, cam.look);
  camera.matrixAutoUpdate = false;
  camera.matrix.makeBasis(v3(basis.x), v3(basis.y), v3(basis.z)).setPosition(v3(cam.pos));
  camera.matrixWorld.copy(camera.matrix);
  camera.matrixWorldInverse.copy(camera.matrix).invert();
  bokeh.uniforms.focus.value = cam.focus;

  for (let i = 0; i < floor.length; i++) {
    const { points, level } = floorString(spec, t, i);
    const colors = [];
    points.forEach((_, k) => { const c = gradient(k / (points.length - 1)).multiplyScalar(level * 3.2); colors.push(c.r, c.g, c.b); });
    floor[i].geometry.setPositions(points.flat());
    floor[i].geometry.setColors(colors);
  }

  const p0 = phone.localToWorld(v3(phoneLaunchLocal(spec))).toArray();
  const p1 = lidPivot.localToWorld(v3(tileLocal(spec))).toArray();
  const hero = heroState(spec, t), heroPts = [], heroCols = [];
  const glow = 1.6 + 2.2 * Math.exp(-3 * Math.max(0, hero.since)) * (hero.since >= 0 ? 1 : 0);
  for (let k = 0; k <= 120; k++) {
    const s = k / 120;
    heroPts.push(...heroPoint(spec, t, p0, p1, s));
    const c = gradient(s).multiplyScalar(glow);
    heroCols.push(c.r, c.g, c.b);
  }
  heroLine.geometry.setPositions(heroPts);
  heroLine.geometry.setColors(heroCols);

  const at = heroPoint(spec, t, p0, p1, hero.travel);
  bead.position.set(...at);
  bead.visible = hero.travel > 0 && hero.travel < 1;
  card.position.set(...at);
  const size = THREE.MathUtils.lerp(spec.photo.size, spec.laptop.tile.w * spec.laptop.screenSize[0], hero.travel);
  card.scale.set(size, size, 1);
  card.quaternion.copy(phone.getWorldQuaternion(new THREE.Quaternion())).slerp(lidPivot.getWorldQuaternion(tmpQ), hero.travel);
  card.material.opacity = hero.cardOpacity;
  card.visible = hero.cardOpacity > 0.001;
  beforeScreen.material.opacity = 1 - hero.arrived;

  composer.render();
};

window.renderAt(params.has("t") ? Number(params.get("t")) : 0);
window.ready = true;
