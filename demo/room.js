'use strict';
(() => {
  const el = id => document.getElementById(id);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const clone = v => JSON.parse(JSON.stringify(v));
  const viewport = el('viewport');
  const api = window.homeAPI;

  const SHORT_ROOM = {
    living: '客厅', dining: '餐厅', kitchen: '厨房', hall: '走廊', entry: '玄关',
    bed: '主卧', bed2: '次卧', bed3: '书房', bed4: '客房', bath: '主卫', bath2: '次卫',
    master: '主卧', elder: '次卧', study: '书房'
  };
  const categories = {
    sofa: '#5a8096', table: '#c88e58', storage: '#788f73', television: '#4e596a',
    oven: '#675a86', fireplace: '#a85d51', bed: '#8b789d', chair: '#a37958',
    sink: '#69958e', bathtub: '#719d9b', toilet: '#8da5ae', dishwasher: '#676d76'
  };

  const ICONS = {
    bulb: `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a6.5 6.5 0 0 0-4.2 11.45c.75.64 1.2 1.54 1.2 2.55h6c0-1.01.45-1.91 1.2-2.55A6.5 6.5 0 0 0 12 2zm-2.5 16h5v1.3a2.5 2.5 0 0 1-5 0V18z"/></svg>`,
    snow: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"><path d="M12 2v20M4.93 4.93l14.14 14.14M2 12h20M4.93 19.07L19.07 4.93"/></svg>`,
    flame: `<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M12.4 2.3c.5 3.2-1.8 4.9-2.8 7.1-.7 1.5-.2 3.2 1.2 3.9-.3-1.4.5-2.6 1.7-3.4 2.1 2.1 3.5 4.6 3.5 7.1a5 5 0 0 1-10 0c0-3.3 2-6.1 4.1-8.4.9-1 1.8-3.2 2.3-6.3z"/></svg>`,
    curtain: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4h18M5 4v16M10 4c0 6-2 10-5 12M19 4v16M14 4c0 6 2 10 5 12"/></svg>`,
    power: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 2v10M18.4 6.6a9 9 0 1 1-12.8 0"/></svg>`,
    sun: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>`,
    check: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>`
  };

  // Custom Floating Glass Popover Menu
  let activePopover = null;
  let activeTrigger = null;

  function closeMenu() {
    if (activePopover) { activePopover.remove(); activePopover = null; }
    if (activeTrigger) { activeTrigger.setAttribute('aria-expanded', 'false'); activeTrigger = null; }
  }

  function openMenu(triggerEl, items) {
    if (activeTrigger === triggerEl) { closeMenu(); return; }
    closeMenu();
    const host = triggerEl.closest('dialog') || document.body;
    const menu = document.createElement('div');
    menu.className = 'glass-popover-menu';
    menu.setAttribute('role', 'listbox');

    for (const opt of items) {
      if (opt.sep) {
        const s = document.createElement('div');
        s.className = 'popover-sep';
        menu.append(s);
        continue;
      }
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'popover-item' + (opt.checked ? ' is-active' : '');
      b.innerHTML = `<span class="popover-check" aria-hidden="true">${ICONS.check}</span><span>${esc(opt.label)}</span>`;
      b.onclick = e => {
        e.stopPropagation();
        closeMenu();
        opt.onPick?.();
      };
      menu.append(b);
    }

    host.append(menu);
    activePopover = menu;
    activeTrigger = triggerEl;
    triggerEl.setAttribute('aria-expanded', 'true');

    const r = triggerEl.getBoundingClientRect();
    const m = menu.getBoundingClientRect();
    let left = optAlignRight(triggerEl) ? r.right - m.width : r.left;
    left = Math.max(12, Math.min(left, window.innerWidth - m.width - 12));
    let top = r.bottom + 6;
    if (top + m.height > window.innerHeight - 12 && r.top - m.height - 6 > 12) top = r.top - m.height - 6;
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
  }

  function optAlignRight(btn) { return btn.id === 'moreMenuBtn'; }

  document.addEventListener('pointerdown', e => {
    if (activePopover && !activePopover.contains(e.target) && !activeTrigger?.contains(e.target)) closeMenu();
  });
  window.addEventListener('resize', closeMenu);

  let toastTimer = 0;
  function showToast(msg, bad = false) {
    const node = el('stageToast');
    if (!node || !msg) return;
    node.textContent = msg;
    node.classList.toggle('is-bad', Boolean(bad));
    if (!node.hidden) {
      node.style.animation = 'none';
      void node.offsetWidth;
      node.style.animation = '';
    }
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.hidden = true; }, 2400);
  }

  function syncSlidingPills(scope = document) {
    const bars = scope.querySelectorAll('.view-switch, .scene-bar, .seg-bar, .swatch-bar');
    bars.forEach(bar => {
      const active = bar.querySelector('button[aria-pressed="true"]');
      let thumb = bar.querySelector(':scope > .seg-pill-thumb');
      if (!active || !active.offsetWidth) {
        if (thumb) thumb.style.opacity = '0';
        return;
      }
      const firstMount = !thumb;
      if (!thumb) {
        thumb = document.createElement('span');
        thumb.className = 'seg-pill-thumb';
        thumb.setAttribute('aria-hidden', 'true');
        bar.prepend(thumb);
      }
      if (firstMount) thumb.style.transition = 'none';
      bar.classList.add('has-pill-thumb');
      thumb.style.opacity = '1';
      thumb.style.height = `${active.offsetHeight}px`;
      thumb.style.width = `${active.offsetWidth}px`;
      thumb.style.transform = `translate3d(${active.offsetLeft}px, ${active.offsetTop}px, 0)`;
      if (firstMount) {
        requestAnimationFrame(() => { if (thumb) thumb.style.transition = ''; });
      }
    });
  }

  try {
    const { THREE: T, SCAN_HOME: source, LED_BULB_ASSET: bulbAsset } = window;
    const renderer = new T.WebGLRenderer({
      antialias: true,
      alpha: true,
      preserveDrawingBuffer: false,
      powerPreference: 'high-performance'
    });
    const baseDPR = Math.min(window.devicePixelRatio || 1, 1.75);
    let currentDPR = baseDPR;
    renderer.setPixelRatio(baseDPR);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = T.PCFSoftShadowMap;
    renderer.toneMapping = T.ACESFilmicToneMapping;

    const canvas = renderer.domElement;
    canvas.tabIndex = 0;

    const scene = new T.Scene();
    const scanHome = new T.Group(), thresholds = new T.Group(), scanObjects = new T.Group();
    scanHome.add(thresholds, scanObjects);
    const customHome = new T.Group();
    customHome.visible = false;
    const deviceNodesGroup = new T.Group();
    scene.add(scanHome, customHome, deviceNodesGroup);

    // Studio PMREM & PBR LED Bulb
    const decode = (s, K) => new K(Uint8Array.from(atob(s), ch => ch.charCodeAt(0)).buffer);
    const bPos = new T.BufferAttribute(decode(bulbAsset.position, Float32Array), 3);
    const bNorm = new T.BufferAttribute(decode(bulbAsset.normal, Float32Array), 3);
    const bUv = new T.BufferAttribute(decode(bulbAsset.uv, Float32Array), 2);
    const bTris = decode(bulbAsset.index, Uint16Array), bGroups = [[], []];
    for (let i = 0; i < bTris.length; i += 3) {
      const y = (bPos.getY(bTris[i]) + bPos.getY(bTris[i + 1]) + bPos.getY(bTris[i + 2])) / 3;
      bGroups[y > 0.047 ? 1 : 0].push(bTris[i], bTris[i + 1], bTris[i + 2]);
    }
    const bulbParts = bGroups.map(idx => new T.BufferGeometry()
      .setAttribute('position', bPos).setAttribute('normal', bNorm).setAttribute('uv', bUv).setIndex(idx));
    const bulbTextures = bulbAsset.textures.map((uri, i) => {
      const tex = new T.TextureLoader().load(uri, () => repaint());
      tex.flipY = false;
      tex.anisotropy = Math.min(4, renderer.capabilities.getMaxAnisotropy());
      if (i === 1) tex.colorSpace = T.SRGBColorSpace;
      return tex;
    });

    const studio = new T.Scene();
    studio.background = new T.Color('#353c46');
    const addLightPanel = (w, h, x, y, z, intensity, tint) => {
      const m = new T.Mesh(
        new T.PlaneGeometry(w, h),
        new T.MeshBasicMaterial({ color: new T.Color(tint).multiplyScalar(intensity), side: T.DoubleSide, toneMapped: false })
      );
      m.position.set(x, y, z); m.lookAt(0, 0, 0); studio.add(m);
    };
    addLightPanel(4, 2, -3, 2, 2, 3.1, '#f2f3ff');
    addLightPanel(1, 4, 3, 1, -2, 4.0, '#fff1de');
    addLightPanel(2, 2, 0, -3, -2, 1.4, '#eff5ff');
    const pmrem = new T.PMREMGenerator(renderer);
    const reflections = pmrem.fromScene(studio, 0.06, 0.1, 30);
    pmrem.dispose();
    studio.traverse(o => { o.geometry?.dispose(); o.material?.dispose(); });

    const makeBulbMetalMat = () => new T.MeshStandardMaterial({
      map: bulbTextures[1], normalMap: bulbTextures[0], roughnessMap: bulbTextures[2], metalnessMap: bulbTextures[2],
      roughness: 1, metalness: 1, envMap: reflections.texture, envMapIntensity: 0.92, side: T.DoubleSide
    });
    const sharedBulbMetal = makeBulbMetalMat();

    function makeBadgeTex(symbol, bgHex, ringHex) {
      const c = document.createElement('canvas');
      c.width = c.height = 96;
      const ctx = c.getContext('2d');
      ctx.beginPath(); ctx.arc(48, 48, 40, 0, Math.PI * 2);
      ctx.fillStyle = bgHex; ctx.fill();
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 3; ctx.stroke();
      ctx.beginPath(); ctx.arc(48, 48, 32, 0, Math.PI * 2);
      ctx.strokeStyle = ringHex; ctx.lineWidth = 5.5; ctx.stroke();
      if (symbol) {
        ctx.fillStyle = ringHex;
        ctx.font = 'bold 28px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(symbol, 48, 50);
      }
      const tex = new T.CanvasTexture(c);
      tex.colorSpace = T.SRGBColorSpace;
      return tex;
    }
    const badgeLampOff = makeBadgeTex('', '#fffdf4', '#244c43');
    const badgeLampOn = makeBadgeTex('', '#ffd275', '#8a5514');
    const badgeAc = makeBadgeTex('❄', '#eaf4fb', '#245f78');
    const badgeCurtain = makeBadgeTex('▥', '#e6f4f1', '#1f6357');
    const badgeGeneric = makeBadgeTex('◈', '#f1f5f9', '#365665');

    // Apple 11-Room Scan Geometry
    const mat = (color, rough = 0.86, opacity = 1) => new T.MeshStandardMaterial({
      color, roughness: rough, side: T.DoubleSide, flatShading: true,
      transparent: opacity < 1, opacity
    });
    const structure = {
      floor: mat('#b8b9a4'), wall: mat('#e4e0d4'), door: mat('#b49f85'),
      window: mat('#97b1b6'), opening: mat('#e4e0d4')
    };
    const thresholdMat = mat('#b8b9a4');
    const vec = (p, y = 0) => new T.Vector3(p[0], y, p[1]);

    const scanRooms = new Map();
    const scanFurnMats = new Map();
    for (const entry of source.rooms) {
      const rBounds = new T.Box3();
      for (const part of entry.meshes) {
        const g = new T.BufferGeometry();
        g.setAttribute('position', new T.Float32BufferAttribute(part.p, 3));
        g.setIndex(part.i);
        g.computeVertexNormals();
        g.computeBoundingBox();
        const original = new T.Color().setRGB(...part.color, T.SRGBColorSpace);
        const tint = part.furniture && categories[part.kind];
        let mMat;
        if (part.furniture) {
          const mKey = `${part.kind}|${original.getHexString()}`;
          mMat = scanFurnMats.get(mKey);
          if (!mMat) {
            mMat = mat(tint || original);
            scanFurnMats.set(mKey, mMat);
          }
        } else {
          mMat = structure[part.kind] || mat(original);
        }
        const mesh = new T.Mesh(g, mMat);
        mesh.castShadow = part.kind !== 'floor';
        mesh.receiveShadow = true;
        mesh.matrixAutoUpdate = false;
        mesh.updateMatrix();
        mesh.userData = { original, tint };
        (part.furniture ? scanObjects : scanHome).add(mesh);
        if (!part.furniture) rBounds.union(g.boundingBox);
      }
      const floorBounds = new T.Box3().setFromPoints(entry.outline.map(p => vec(p)));
      scanRooms.set(entry.id, { ...entry, bounds: rBounds, floorBounds, neighbors: new Map() });
    }

    const passage = new T.Mesh(
      new T.PlaneGeometry(1, 1),
      new T.MeshBasicMaterial({ color: '#367d69', side: T.DoubleSide, transparent: true, opacity: 0.83, depthWrite: false })
    );
    passage.visible = false;
    thresholds.add(passage);

    for (const door of source.portals) {
      scanRooms.get(door.a).neighbors.set(door.b, door);
      scanRooms.get(door.b).neighbors.set(door.a, door);
      const tangent = vec(door.t);
      const a = vec(door.p, 0.013), b = vec(door.q, 0.013);
      const n = new T.Vector3(-tangent.z, 0, tangent.x);
      if (n.dot(b.clone().sub(a)) < 0) n.negate();
      a.addScaledVector(n, -0.075);
      b.addScaledVector(n, 0.075);
      const edge = door.w * 0.49;
      const corners = [
        a.clone().addScaledVector(tangent, -edge), a.clone().addScaledVector(tangent, edge),
        b.clone().addScaledVector(tangent, edge), b.clone().addScaledVector(tangent, -edge)
      ];
      const g = new T.BufferGeometry().setFromPoints(corners);
      g.setIndex([0, 1, 2, 0, 2, 3]);
      g.computeVertexNormals();
      const th = new T.Mesh(g, thresholdMat);
      th.receiveShadow = true;
      th.matrixAutoUpdate = false;
      th.updateMatrix();
      thresholds.add(th);
      door.mid = a.clone().lerp(b, 0.5);
      door.depth = a.distanceTo(b);
    }

    const scanTotalBounds = new T.Box3();
    for (const r of scanRooms.values()) scanTotalBounds.union(r.bounds);

    const base = new T.Mesh(new T.PlaneGeometry(180, 180), new T.ShadowMaterial({ color: '#34444b', opacity: 0.34 }));
    base.rotation.x = -Math.PI / 2;
    base.position.y = -0.177;
    base.receiveShadow = true;
    const sky = new T.HemisphereLight('#f5f6ff', '#9c9786', 1.5);
    const sun = new T.DirectionalLight('#fff5e5', 2.0);
    sun.position.set(-6, 21, 10);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    Object.assign(sun.shadow.camera, { left: -17, right: 17, top: 17, bottom: -17, near: 0.25, far: 50 });
    sun.shadow.normalBias = 0.022;
    sun.shadow.bias = -0.00012;
    sun.shadow.autoUpdate = false;
    sun.shadow.needsUpdate = true;
    scene.add(base, sky, sun);

    const livingScan = scanRooms.get('living');
    const scanCeilingY = livingScan ? livingScan.bounds.max.y - 0.025 : 2.52;
    const cursorGroup = new T.Group();
    const ringMat = new T.MeshBasicMaterial({ color: '#287869', side: T.DoubleSide, transparent: true, opacity: 0.88, depthTest: false });
    const makeRing = (rIn, rOut, m) => {
      const o = new T.Mesh(new T.RingGeometry(rIn, rOut, 38), m);
      o.rotation.x = -Math.PI / 2; o.renderOrder = 4; return o;
    };
    const floorRing = makeRing(0.13, 0.15, ringMat);
    const topRing = makeRing(0.09, 0.105, ringMat);
    topRing.position.y = scanCeilingY;
    const riserGeo = new T.BufferGeometry().setFromPoints([new T.Vector3(), new T.Vector3(0, scanCeilingY, 0)]);
    const riser = new T.Line(riserGeo, new T.LineDashedMaterial({ color: '#436c61', dashSize: 0.065, gapSize: 0.045, depthTest: false, transparent: true, opacity: 0.75 }));
    riser.renderOrder = 4; riser.computeLineDistances();
    cursorGroup.add(floorRing, topRing, riser);
    cursorGroup.visible = false;
    scene.add(cursorGroup);

    const selRing = makeRing(0.11, 0.135, new T.MeshBasicMaterial({ color: '#273946', side: T.DoubleSide, transparent: true, opacity: 0.8, depthTest: false }));
    selRing.visible = false;
    scene.add(selRing);

    // Dedicated Indoor Wall-Mounted Perspective Camera + Ceiling Enclosure for Room Camera Feeds
    const indoorCam = new T.PerspectiveCamera(68, 16 / 10, 0.08, 24);
    const indoorCeiling = new T.Mesh(
      new T.PlaneGeometry(45, 45),
      new T.MeshStandardMaterial({ color: '#eae6dd', roughness: 0.92, side: T.DoubleSide })
    );
    indoorCeiling.rotation.x = Math.PI / 2;
    indoorCeiling.visible = false;
    const indoorBounceLight = new T.PointLight('#ffd8a6', 0, 9.5, 1.5);
    indoorBounceLight.visible = false;
    scene.add(indoorCeiling, indoorBounceLight);
    const snapCanvas = document.createElement('canvas');
    snapCanvas.width = 560;
    snapCanvas.height = 350;
    const snapCtx = snapCanvas.getContext('2d');

    // ==========================================================================
    // Continuous Spring Camera & App State
    // ==========================================================================
    const camera = new T.OrthographicCamera(-1, 1, 1, -1, 0.06, 125);
    const ANGLE = (33 * Math.PI) / 180, YAW = 0.48;
    const urlParams = new URLSearchParams(location.search);
    let currentKey = ['house', 'apartment', 'custom', 'apple'].includes(urlParams.get('plan')) ? urlParams.get('plan') : 'house';
    if (currentKey === 'apple') currentKey = 'house';
    let plan2D = urlParams.get('view') === '2d';
    let selectedRoom = null;
    let yaw3 = YAW, tilt3 = ANGLE, zoom = 1;
    let focusPoint = null, closeupBulbId = null;
    let installingBulb = false;
    let walker = null, walkMode = false, walkMotion = null, walkedRoom = null;

    let showScanObjects = true;
    let colorScanByCategory = true;

    let types = {};
    let snapshot = null;
    let localPlan = null;
    let activeDeviceId = null;
    let busyDevices = new Set();
    let camAttachment = null;

    let customTotalBounds = new T.Box3(new T.Vector3(-6, 0, -4), new T.Vector3(6, 2.55, 4));
    const customRoomBounds = new Map();
    let customCenter = [590, 360];
    const deviceVisuals = new Map();

    const isScanMode = () => currentKey === 'house';
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    const liveRay = new T.Raycaster();
    const floorPlane = new T.Plane(new T.Vector3(0, 1, 0), 0);
    const wrap = a => Math.atan2(Math.sin(a), Math.cos(a));
    const aspect = () => viewport.clientWidth / Math.max(1, viewport.clientHeight) || 1;
    const logHeight = (w, h) => Math.log(Math.max(0.5, Math.max(h, w / aspect()) / zoom));

    function activeLayoutBounds() {
      if (isScanMode()) return (selectedRoom && scanRooms.get(selectedRoom)?.floorBounds) || scanTotalBounds;
      return (selectedRoom && customRoomBounds.get(selectedRoom)) || customTotalBounds;
    }

    function desired() {
      if (focusPoint) {
        return { x: focusPoint.x, y: focusPoint.y, z: focusPoint.z, polar: 1.31, yaw: yaw3, scale: logHeight(0.35, 0.34), detail: 1 };
      }
      const box = activeLayoutBounds();
      const center = box.getCenter(new T.Vector3());
      const size = box.getSize(new T.Vector3());
      const out = {
        x: center.x, y: plan2D ? 0 : 0.31, z: center.z,
        polar: plan2D ? 0 : tilt3, yaw: plan2D ? 0 : yaw3, detail: 0
      };
      const pad = selectedRoom ? 2.15 : 2.55;
      const c = Math.abs(Math.cos(yaw3)), s = Math.abs(Math.sin(yaw3));
      const maxH = isScanMode() ? scanTotalBounds.max.y : 2.55;
      out.scale = plan2D
        ? logHeight(size.x + pad, size.z + pad)
        : logHeight(size.x * c + size.z * s + pad, (size.x * s + size.z * c) * Math.cos(tilt3) + (selectedRoom ? 2.5 : maxH) * Math.sin(tilt3) + pad);
      return out;
    }

    let state = desired();
    const dampKeys = Object.keys(state);
    const velocity = Object.fromEntries(dampKeys.map(k => [k, 0]));
    let goal = { ...state }, motion = null, lastTime = null, stiffness = 11.5, drawFrame = 0;
    let slowFrames = 0;
    const camTarget = new T.Vector3();
    let canvasRect = { left: 0, top: 0, width: 1, height: 1 };

    function setAdaptiveDPR(nextDpr) {
      if (Math.abs(nextDpr - currentDPR) < 0.04) return;
      currentDPR = nextDpr;
      renderer.setPixelRatio(currentDPR);
      if (viewport.clientWidth && viewport.clientHeight) {
        renderer.setSize(viewport.clientWidth, viewport.clientHeight, false);
      }
    }

    // Smooth 3D State & Selection Halo Tween Engine (0% CPU when idle!)
    const ringAnim = { x: 0, z: 0, tx: 0, tz: 0, pulse: 0, initialized: false };
    let fxFrame = 0, fxLast = null;

    function startFxLoop() {
      if (reduced.matches) return;
      if (!fxFrame) { fxLast = null; fxFrame = requestAnimationFrame(stepFx); }
    }

    function stepFx(now) {
      const dt = fxLast === null ? 1 / 60 : Math.min(0.06, (now - fxLast) / 1000);
      fxLast = now;
      let active = false;
      const kPos = 1 - Math.exp(-18 * dt);
      const kLight = 1 - Math.exp(-11.5 * dt);

      if (selRing.visible && ringAnim.initialized) {
        const dx = ringAnim.tx - ringAnim.x, dz = ringAnim.tz - ringAnim.z;
        if (Math.hypot(dx, dz) > 0.0015 || ringAnim.pulse > 0.004) {
          ringAnim.x += dx * kPos;
          ringAnim.z += dz * kPos;
          ringAnim.pulse *= Math.exp(-10 * dt);
          selRing.position.set(ringAnim.x, 0.018, ringAnim.z);
          active = true;
        } else {
          ringAnim.x = ringAnim.tx; ringAnim.z = ringAnim.tz; ringAnim.pulse = 0;
          selRing.position.set(ringAnim.x, 0.018, ringAnim.z);
        }
      }

      for (const vis of deviceVisuals.values()) {
        if (vis.light && vis.tgtIntensity !== undefined) {
          const di = vis.tgtIntensity - vis.light.intensity;
          const de = vis.tgtEmissive - vis.diffuser.emissiveIntensity;
          const dc = Math.abs(vis.tgtColor.r - vis.light.color.r) + Math.abs(vis.tgtColor.g - vis.light.color.g) + Math.abs(vis.tgtColor.b - vis.light.color.b);
          if (Math.abs(di) > 0.08 || Math.abs(de) > 0.006 || dc > 0.006) {
            vis.light.intensity += di * kLight;
            vis.diffuser.emissiveIntensity += de * kLight;
            vis.light.color.lerp(vis.tgtColor, kLight);
            vis.diffuser.emissive.lerp(vis.tgtColor, kLight);
            active = true;
          } else {
            vis.light.intensity = vis.tgtIntensity;
            vis.diffuser.emissiveIntensity = vis.tgtEmissive;
            vis.light.color.copy(vis.tgtColor);
            vis.diffuser.emissive.copy(vis.tgtColor);
          }
        }
        if (vis.boxMesh && vis.tgtScaleX !== undefined) {
          const ds = vis.tgtScaleX - vis.boxMesh.scale.x;
          const dc = vis.tgtBodyColor
            ? Math.abs(vis.tgtBodyColor.r - vis.boxMesh.material.color.r) + Math.abs(vis.tgtBodyColor.g - vis.boxMesh.material.color.g) + Math.abs(vis.tgtBodyColor.b - vis.boxMesh.material.color.b)
            : 0;
          if (Math.abs(ds) > 0.003 || dc > 0.006) {
            vis.boxMesh.scale.x += ds * kLight;
            if (vis.tgtBodyColor) vis.boxMesh.material.color.lerp(vis.tgtBodyColor, kLight);
            active = true;
          } else {
            vis.boxMesh.scale.x = vis.tgtScaleX;
            if (vis.tgtBodyColor) vis.boxMesh.material.color.copy(vis.tgtBodyColor);
          }
        }
      }

      repaint();
      if (active) fxFrame = requestAnimationFrame(stepFx);
      else { fxFrame = 0; fxLast = null; }
    }

    function updateDeviceMarkers(metersPerPixel, polar, detail) {
      const overheadFactor = (1 - T.MathUtils.smoothstep(polar, 0.12, 0.44)) * (1 - T.MathUtils.smoothstep(detail, 0.04, 0.35));
      const mScale = metersPerPixel * 23;
      for (const [id, vis] of deviceVisuals) {
        if (!vis.marker) continue;
        vis.marker.visible = overheadFactor > 0.015;
        vis.marker.material.opacity = overheadFactor;
        vis.marker.scale.setScalar(id === activeDeviceId ? mScale * 1.18 : mScale);
      }
      const ringAdj = T.MathUtils.clamp(metersPerPixel * 70, 0.85, 2.0);
      floorRing.scale.setScalar(ringAdj);
      topRing.scale.setScalar(ringAdj);
      if (selRing.visible) {
        selRing.scale.setScalar(ringAdj * (1 + ringAnim.pulse * 0.28));
        selRing.material.opacity = 0.78 + ringAnim.pulse * 0.2;
      }
    }

    function render() {
      if (drawFrame) { cancelAnimationFrame(drawFrame); drawFrame = 0; }
      if (!viewport.clientWidth || !viewport.clientHeight) return;
      const ratio = aspect(), half = Math.exp(state.scale) * 0.5;
      const { yaw, polar } = state;
      const dist = 38 * Math.exp(state.detail * Math.log(2 / 38));
      const sin = Math.sin(polar), cos = Math.cos(polar);
      const relief = Math.min(1, Math.max(0, sin / Math.sin(ANGLE)));
      const shift = half * 0.14 * relief * (1 - state.detail);

      camera.top = half + shift;
      camera.bottom = -half + shift;
      camera.left = -half * ratio;
      camera.right = half * ratio;
      camera.updateProjectionMatrix();

      camTarget.set(state.x, state.y, state.z);
      camera.position.set(Math.sin(yaw) * sin, cos, Math.cos(yaw) * sin).multiplyScalar(dist).add(camTarget);
      camera.up.set(-Math.sin(yaw) * cos, sin, -Math.cos(yaw) * cos);
      camera.lookAt(camTarget);

      base.material.opacity = 0.07 + 0.17 * relief;
      sun.intensity = 0.52 + 1.48 * relief;
      sky.intensity = 2.45 - 0.95 * relief;

      const showHome = state.detail < 0.92;
      const targetScanVis = isScanMode() && showHome;
      const targetCustVis = !isScanMode() && showHome;
      if (scanHome.visible !== targetScanVis || customHome.visible !== targetCustVis) sun.shadow.needsUpdate = true;
      scanHome.visible = targetScanVis;
      customHome.visible = targetCustVis;
      base.visible = showHome;
      base.position.y = isScanMode() ? -0.177 : -0.05;
      for (const [id, vis] of deviceVisuals) vis.node.visible = showHome || id === closeupBulbId;

      updateDeviceMarkers((half * 2) / viewport.clientHeight, polar, state.detail);
      renderer.render(scene, camera);
    }

    function repaint() { if (!drawFrame) drawFrame = requestAnimationFrame(render); }

    function stopSpring(keepVelocity = false) {
      if (motion) { cancelAnimationFrame(motion); motion = null; }
      lastTime = null;
      slowFrames = 0;
      if (!keepVelocity) for (const k of dampKeys) velocity[k] = 0;
      if (currentDPR < baseDPR) setAdaptiveDPR(baseDPR);
    }

    function tick(now) {
      const rawDt = lastTime === null ? 1 / 60 : (now - lastTime) / 1000;
      if (rawDt > 0.026 && baseDPR > 1.2) {
        if (++slowFrames >= 3) setAdaptiveDPR(Math.max(1.05, baseDPR * 0.72));
      } else {
        slowFrames = Math.max(0, slowFrames - 1);
      }
      const dt = Math.min(0.08, rawDt);
      lastTime = now;
      let remaining = false;
      const decay = Math.exp(-stiffness * dt);
      for (const k of dampKeys) {
        const offset = state[k] - goal[k], rate = velocity[k], step = (rate + stiffness * offset) * dt;
        state[k] = goal[k] + (offset + step) * decay;
        velocity[k] = (rate - stiffness * step) * decay;
        if (Math.abs(state[k] - goal[k]) > 0.00045 || Math.abs(velocity[k]) > 0.003) remaining = true;
      }
      if (remaining) motion = requestAnimationFrame(tick);
      else { state = { ...goal }; stopSpring(); }
      repaint();
    }

    function move({ speed = 11.5, scaleOnly = false } = {}) {
      const end = desired();
      if (scaleOnly) {
        const src = motion ? goal : state;
        for (const k of dampKeys) if (k !== 'scale') end[k] = src[k];
      }
      end.yaw = state.yaw + wrap(end.yaw - state.yaw);
      goal = end;
      stiffness = speed;
      if (reduced.matches) { stopSpring(); state = { ...goal }; render(); return; }
      if (!motion) motion = requestAnimationFrame(tick);
    }

    function resize() {
      if (!viewport.clientWidth || !viewport.clientHeight) return;
      renderer.setSize(viewport.clientWidth, viewport.clientHeight, false);
      canvasRect = canvas.getBoundingClientRect();
      syncSlidingPills();
      if (!motion) { state.scale = desired().scale; render(); }
      else goal.scale = desired().scale;
    }

    function updateURL() {
      const next = new URL(location.href);
      next.searchParams.set('plan', currentKey);
      if (plan2D) next.searchParams.set('view', '2d'); else next.searchParams.delete('view');
      try { history.replaceState(null, '', next); } catch {}
    }

    // ==========================================================================
    // 3D Builders & Live Preview
    // ==========================================================================
    function planToWorld(px, py) {
      if (isScanMode()) return [(px - 816.2013) / 100, (py - 825.0033) / 100];
      return [(px - customCenter[0]) / 100, (py - customCenter[1]) / 100];
    }

    function pointInPoly2D(x, y, poly) {
      let hit = false;
      for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
        const [a, b] = poly[i], [c, d] = poly[j];
        if ((b > y) !== (d > y) && x < ((c - a) * (y - b)) / (d - b) + a) hit = !hit;
      }
      return hit;
    }

    function roomOfPlanItem(it) {
      if (!localPlan?.rooms) return null;
      return localPlan.rooms.find(r => pointInPoly2D(it.x, it.y, r.p)) || null;
    }

    const sharedSocketGeo = new T.CylinderGeometry(0.029, 0.024, 0.03, 18);
    const sharedSocketMat = new T.MeshStandardMaterial({
      color: '#b5b2a9', roughness: 0.56, envMap: reflections.texture, envMapIntensity: 0.5
    });
    const sharedHitGeo = new T.SphereGeometry(0.16, 8, 6);
    const sharedHitMat = new T.MeshBasicMaterial({ visible: false });
    const sharedUnitBoxGeo = new T.BoxGeometry(1, 1, 1);
    const sharedGeos = new Set([bulbParts[0], bulbParts[1], sharedSocketGeo, sharedHitGeo, sharedUnitBoxGeo]);
    const sharedMats = new Set([sharedBulbMetal, sharedSocketMat, sharedHitMat]);

    function applyBulbShaderHook(shader) {
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', '#include <common>\nvarying float bulbLocalY;')
        .replace('#include <begin_vertex>', '#include <begin_vertex>\nbulbLocalY = position.y;');
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', '#include <common>\nvarying float bulbLocalY;')
        .replace('#include <emissivemap_fragment>', '#include <emissivemap_fragment>\ntotalEmissiveRadiance *= smoothstep(0.047, 0.061, bulbLocalY);');
    }

    function disposeGroup(grp) {
      while (grp.children.length) {
        const ch = grp.children.pop();
        disposeGroup(ch);
        if (ch.geometry && !sharedGeos.has(ch.geometry)) ch.geometry.dispose?.();
        if (Array.isArray(ch.material)) ch.material.forEach(m => { if (!sharedMats.has(m)) m.dispose?.(); });
        else if (ch.material && !sharedMats.has(ch.material)) ch.material.dispose?.();
      }
    }

    const LAMP_TINT_MAP = { '暖白': '#ffd19b', '自然光': '#fff1dc', '冷白': '#dceeff' };
    let lastTopologySig = '';

    function planTopologySig(plan) {
      if (!plan) return '';
      const rSig = (plan.rooms || []).map(r => `${r.id}:${r.restricted ? 1 : 0}`).join(',');
      const wSig = `${plan.walls?.length || 0}:${plan.doors?.length || 0}:${plan.windows?.length || 0}`;
      const iSig = (plan.items || [])
        .map(it => `${it.id}:${it.type}:${it.x}:${it.y}:${it.w || 0}:${it.h || 0}:${it.angle || 0}:${it.mount || ''}`)
        .join('|');
      return `${currentKey}#${rSig}#${wSig}#${iSig}`;
    }

    function makePbrCeilingBulb(worldX, ceilY, worldZ, item) {
      const node = new T.Group();
      node.position.set(worldX, ceilY, worldZ);
      const shape = new T.Group();
      shape.rotation.z = Math.PI;
      shape.position.y = -0.02;
      shape.matrixAutoUpdate = false;
      shape.updateMatrix();
      node.add(shape);

      const diffuser = makeBulbMetalMat();
      diffuser.customProgramCacheKey = () => 'led-bulb-diffuser-v1';
      diffuser.onBeforeCompile = applyBulbShaderHook;

      const isMounted = item.mount === 'ceiling';
      const housing = new T.Mesh(bulbParts[0], sharedBulbMetal);
      const globe = new T.Mesh(bulbParts[1], diffuser);
      housing.castShadow = isMounted; globe.castShadow = isMounted;
      housing.matrixAutoUpdate = false; housing.updateMatrix();
      globe.matrixAutoUpdate = false; globe.updateMatrix();
      shape.add(housing, globe);

      const socket = new T.Mesh(sharedSocketGeo, sharedSocketMat);
      socket.position.y = -0.014;
      socket.matrixAutoUpdate = false;
      socket.updateMatrix();
      node.add(socket);

      const on = Boolean(item.power);
      const lvl = on ? (Number(item.level ?? 65) / 100) : 0;
      const lightColor = LAMP_TINT_MAP[item.color_temp] || '#ffd19b';
      const maxIntensity = isMounted ? 185 : 7.8;

      let light;
      if (isMounted) {
        light = new T.SpotLight(lightColor, lvl * maxIntensity, 9, 1.17, 0.52, 2);
        light.position.y = -0.125;
        light.target.position.y = -3;
        light.castShadow = true;
        light.shadow.mapSize.set(512, 512);
        light.shadow.camera.near = 0.16; light.shadow.camera.far = 9;
        light.shadow.autoUpdate = false;
        light.shadow.needsUpdate = true;
        node.add(light, light.target);
      } else {
        light = new T.PointLight(lightColor, lvl * maxIntensity, 7.2, 1.75);
        light.position.y = -0.16;
        node.add(light);
      }

      diffuser.emissive.set(lightColor);
      diffuser.emissiveIntensity = lvl * 1.35;

      const hit = new T.Mesh(sharedHitGeo, sharedHitMat);
      hit.position.y = -0.06;
      hit.matrixAutoUpdate = false;
      hit.updateMatrix();
      hit.userData.deviceId = item.id;
      node.add(hit);

      const marker = new T.Sprite(new T.SpriteMaterial({
        map: on ? badgeLampOn : badgeLampOff,
        transparent: true, depthTest: false, depthWrite: false, toneMapped: false
      }));
      marker.position.y = 0.02;
      marker.renderOrder = 6;
      marker.userData.deviceId = item.id;
      node.add(marker);

      deviceNodesGroup.add(node);
      deviceVisuals.set(item.id, {
        node, marker, hit, light, diffuser, maxIntensity,
        tgtIntensity: lvl * maxIntensity,
        tgtEmissive: lvl * 1.35,
        tgtColor: new T.Color(lightColor),
        worldPos: new T.Vector3(worldX, ceilY, worldZ),
        isCeilingBulb: true
      });
    }

    function rebuild3DFromPlan() {
      disposeGroup(deviceNodesGroup);
      deviceVisuals.clear();
      if (!localPlan) return;

      if (!isScanMode()) {
        disposeGroup(customHome);
        customRoomBounds.clear();
        const pts = localPlan.outline?.length ? localPlan.outline : [[0, 0], [800, 0], [800, 520], [0, 520]];
        const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
        customCenter = [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
        const wSpan = Math.max(2, (Math.max(...xs) - Math.min(...xs)) / 100);
        const dSpan = Math.max(2, (Math.max(...ys) - Math.min(...ys)) / 100);
        customTotalBounds = new T.Box3(new T.Vector3(-wSpan / 2, 0, -dSpan / 2), new T.Vector3(wSpan / 2, 2.55, dSpan / 2));

        const slab = new T.Mesh(new T.BoxGeometry(wSpan + 0.14, 0.06, dSpan + 0.14), mat('#d5dad6', 0.9));
        slab.position.y = -0.03; slab.receiveShadow = true;
        slab.matrixAutoUpdate = false; slab.updateMatrix();
        customHome.add(slab);

        const zoneTint = { public: '#c8cac0', rest: '#c5c2cb', work: '#bec8ce', guest: '#cbc7bd' };
        for (const r of (localPlan.rooms || [])) {
          if (r.restricted) continue;
          const rxs = r.p.map(p => p[0]), rys = r.p.map(p => p[1]);
          const [x0, z0] = planToWorld(Math.min(...rxs), Math.min(...rys));
          const [x1, z1] = planToWorld(Math.max(...rxs), Math.max(...rys));
          customRoomBounds.set(r.id, new T.Box3(new T.Vector3(x0, 0, z0), new T.Vector3(x1, 2.55, z1)));

          const sh = new T.Shape();
          r.p.forEach(([px, py], i) => {
            const [wx, wz] = planToWorld(px, py);
            if (i === 0) sh.moveTo(wx, -wz); else sh.lineTo(wx, -wz);
          });
          sh.closePath();
          const fg = new T.ShapeGeometry(sh);
          fg.rotateX(-Math.PI / 2);
          const fm = new T.Mesh(fg, mat(zoneTint[r.zone] || '#c6c9bf', 0.88));
          fm.position.y = 0.005; fm.receiveShadow = true;
          fm.matrixAutoUpdate = false; fm.updateMatrix();
          customHome.add(fm);
        }

        const WALL_H = 2.52, WALL_T = 0.11;
        for (const w of (localPlan.walls || [])) {
          const [ax, az] = planToWorld(w.a[0], w.a[1]);
          const [bx, bz] = planToWorld(w.b[0], w.b[1]);
          const len = Math.hypot(bx - ax, bz - az);
          if (len < 0.04) continue;
          const wm = new T.Mesh(new T.BoxGeometry(len + WALL_T * 0.4, WALL_H, WALL_T), structure.wall);
          wm.position.set((ax + bx) / 2, WALL_H / 2, (az + bz) / 2);
          wm.rotation.y = -Math.atan2(bz - az, bx - ax);
          wm.castShadow = true; wm.receiveShadow = true;
          wm.matrixAutoUpdate = false; wm.updateMatrix();
          customHome.add(wm);
        }
        for (const d of (localPlan.doors || [])) {
          const [ax, az] = planToWorld(d.a[0], d.a[1]);
          const [bx, bz] = planToWorld(d.b[0], d.b[1]);
          const len = Math.hypot(bx - ax, bz - az);
          if (len < 0.04) continue;
          const sill = new T.Mesh(new T.BoxGeometry(len, 0.015, 0.16), structure.door);
          sill.position.set((ax + bx) / 2, 0.008, (az + bz) / 2);
          sill.rotation.y = -Math.atan2(bz - az, bx - ax);
          sill.matrixAutoUpdate = false; sill.updateMatrix();
          customHome.add(sill);
        }
        for (const win of (localPlan.windows || [])) {
          const [ax, az] = planToWorld(win.a[0], win.a[1]);
          const [bx, bz] = planToWorld(win.b[0], win.b[1]);
          const len = Math.hypot(bx - ax, bz - az);
          if (len < 0.04) continue;
          const pane = new T.Mesh(new T.BoxGeometry(len, 1.2, 0.05), mat('#97b5be', 0.3, 0.55));
          pane.position.set((ax + bx) / 2, 1.4, (az + bz) / 2);
          pane.rotation.y = -Math.atan2(bz - az, bx - ax);
          pane.matrixAutoUpdate = false; pane.updateMatrix();
          customHome.add(pane);
        }
      }

      for (const it of (localPlan.items || [])) {
        if (isScanMode() && it.type === 'scanned') continue;
        if (isScanMode() && !Object.keys(types[it.type]?.caps || {}).length && !it.id.startsWith('user-')) continue;

        const [wx, wz] = planToWorld(it.x, it.y);
        let ceilY = isScanMode() ? scanCeilingY : 2.48;
        if (isScanMode()) {
          const rm = roomOfPlanItem(it);
          const sr = rm && scanRooms.get(rm.id);
          if (sr) ceilY = sr.bounds.max.y - 0.032;
        }

        if (it.type === 'lamp' || it.type === 'switch') {
          makePbrCeilingBulb(wx, ceilY, wz, it);
        } else {
          const tspec = types[it.type] || {};
          const hasCaps = Object.keys(tspec.caps || {}).length > 0;
          const iw = Math.max(0.22, (it.w || tspec.w || 45) / 100);
          const idp = Math.max(0.22, (it.h || tspec.h || 40) / 100);
          const h3d = it.type === 'ac' ? 0.26 : it.type === 'curtain' ? 2.05 : Math.max(0.18, (tspec.height3d || 62) / 100);
          const posY = it.type === 'ac' ? 2.05 : it.type === 'curtain' ? 1.12 : h3d / 2;

          let bodyHex = tspec.color || '#cbd5e1';
          if (it.type === 'ac') bodyHex = it.power ? (it.mode === '制热' ? '#f6cfa7' : '#b8dfee') : '#dce3e6';
          if (it.type === 'curtain') bodyHex = '#9bbab7';

          const widthFactor = it.type === 'curtain' ? Math.max(0.18, 1 - (Number(it.position ?? 50) / 100) * 0.8) : 1;
          const node = new T.Group();
          node.position.set(wx, posY, wz);
          node.rotation.y = -((it.angle || 0) * Math.PI) / 180;

          const boxMesh = new T.Mesh(sharedUnitBoxGeo, mat(bodyHex, 0.72));
          boxMesh.scale.set(iw * widthFactor, h3d, idp);
          boxMesh.castShadow = true; boxMesh.receiveShadow = true;
          boxMesh.userData.deviceId = it.id;
          node.add(boxMesh);

          let marker = null;
          if (hasCaps) {
            const bTex = it.type === 'ac' ? badgeAc : it.type === 'curtain' ? badgeCurtain : badgeGeneric;
            marker = new T.Sprite(new T.SpriteMaterial({
              map: bTex, transparent: true, depthTest: false, depthWrite: false, toneMapped: false
            }));
            marker.position.y = h3d / 2 + 0.15;
            marker.renderOrder = 6;
            marker.userData.deviceId = it.id;
            node.add(marker);
          }

          deviceNodesGroup.add(node);
          deviceVisuals.set(it.id, {
            node, marker, hit: boxMesh, boxMesh, baseW: iw,
            tgtScaleX: iw * widthFactor,
            tgtBodyColor: new T.Color(bodyHex),
            worldPos: new T.Vector3(wx, posY, wz),
            isCeilingBulb: false
          });
        }
      }

      lastTopologySig = planTopologySig(localPlan);
      updateSelectionRing(true);
      sun.shadow.needsUpdate = true;
      repaint();
    }

    function sync3DStatesFromPlan() {
      if (!localPlan) return;
      for (const it of (localPlan.items || [])) {
        const vis = deviceVisuals.get(it.id);
        if (!vis) continue;
        if (it.type === 'lamp' || it.type === 'switch') {
          const on = Boolean(it.power);
          const lvl = on ? (Number(it.level ?? 65) / 100) : 0;
          const hex = LAMP_TINT_MAP[it.color_temp] || '#ffd19b';
          vis.tgtIntensity = lvl * (vis.maxIntensity || 7.8);
          vis.tgtEmissive = lvl * 1.35;
          vis.tgtColor.set(hex);
          if (vis.marker) vis.marker.material.map = on ? badgeLampOn : badgeLampOff;
          if (reduced.matches) {
            vis.light.intensity = vis.tgtIntensity;
            vis.diffuser.emissiveIntensity = vis.tgtEmissive;
            vis.light.color.copy(vis.tgtColor);
            vis.diffuser.emissive.copy(vis.tgtColor);
          }
        } else if (vis.boxMesh) {
          const tspec = types[it.type] || {};
          let bodyHex = tspec.color || '#cbd5e1';
          if (it.type === 'ac') bodyHex = it.power ? (it.mode === '制热' ? '#f6cfa7' : '#b8dfee') : '#dce3e6';
          if (it.type === 'curtain') bodyHex = '#9bbab7';
          const wf = it.type === 'curtain' ? Math.max(0.18, 1 - (Number(it.position ?? 50) / 100) * 0.8) : 1;
          vis.tgtScaleX = (vis.baseW || 0.45) * wf;
          vis.tgtBodyColor.set(bodyHex);
          if (reduced.matches) {
            vis.boxMesh.scale.x = vis.tgtScaleX;
            vis.boxMesh.material.color.copy(vis.tgtBodyColor);
          }
        }
      }
      updateSelectionRing();
      if (reduced.matches) repaint();
      else startFxLoop();
    }

    function updateSelectionRing(instant = false) {
      const vis = activeDeviceId && deviceVisuals.get(activeDeviceId);
      if (vis && !closeupBulbId) {
        const wasHidden = !selRing.visible;
        selRing.visible = true;
        ringAnim.tx = vis.worldPos.x;
        ringAnim.tz = vis.worldPos.z;
        if (instant || wasHidden || !ringAnim.initialized || reduced.matches) {
          ringAnim.x = ringAnim.tx;
          ringAnim.z = ringAnim.tz;
          ringAnim.initialized = true;
          ringAnim.pulse = reduced.matches ? 0 : 0.75;
          selRing.position.set(ringAnim.x, 0.018, ringAnim.z);
          if (!reduced.matches) startFxLoop();
        } else if (Math.hypot(ringAnim.tx - ringAnim.x, ringAnim.tz - ringAnim.z) > 0.01) {
          ringAnim.pulse = 1;
          startFxLoop();
        }
      } else {
        selRing.visible = false;
      }
    }

    function preview3DDeviceValue(item, capKey, numVal) {
      const vis = deviceVisuals.get(item.id);
      if (!vis) return;
      if (capKey === 'level' && vis.light && vis.diffuser) {
        const lvl = Math.max(0, Math.min(1, numVal / 100));
        const ti = lvl * (vis.maxIntensity || 7.8);
        vis.light.intensity = ti;
        vis.tgtIntensity = ti;
        vis.diffuser.emissiveIntensity = lvl * 1.35;
        vis.tgtEmissive = lvl * 1.35;
        repaint();
      } else if (capKey === 'position' && vis.boxMesh) {
        const sx = (vis.baseW || 0.45) * Math.max(0.18, 1 - (Math.max(0, Math.min(100, numVal)) / 100) * 0.8);
        vis.boxMesh.scale.x = sx;
        vis.tgtScaleX = sx;
        repaint();
      }
    }

    function syncScanFinishes() {
      scanObjects.visible = showScanObjects;
      sun.shadow.needsUpdate = true;
      for (const m of scanObjects.children) {
        const { original, tint } = m.userData;
        if (colorScanByCategory && tint) m.material.color.set(tint);
        else m.material.color.copy(original);
      }
      repaint();
    }

    function bulbPlacementError(worldPt) {
      if (!worldPt || !livingScan) return '请点选客厅内部地面';
      const poly = livingScan.outline;
      let inside = false, clearance = Infinity;
      for (let i = 0; i < poly.length; i++) {
        const [x, y] = poly[i], [a, b] = poly[(i + 1) % poly.length];
        if ((y > worldPt.z) !== (b > worldPt.z) && worldPt.x < ((a - x) * (worldPt.z - y)) / (b - y) + x) inside = !inside;
        const d = (a - x) ** 2 + (b - y) ** 2;
        const t = d ? Math.max(0, Math.min(1, ((worldPt.x - x) * (a - x) + (worldPt.z - y) * (b - y)) / d)) : 0;
        clearance = Math.min(clearance, Math.hypot(worldPt.x - x - t * (a - x), worldPt.z - y - t * (b - y)));
      }
      if (!inside || clearance < 0.16) return '请离墙面至少 16 厘米';
      const mounted = (localPlan?.items || []).filter(o => o.mount === 'ceiling');
      if (mounted.length >= 4) return '客厅最多安装 4 盏吸顶灯';
      for (const m of mounted) {
        const [mx, mz] = planToWorld(m.x, m.y);
        if (Math.hypot(mx - worldPt.x, mz - worldPt.z) < 0.28) return `离「${m.name}」过近`;
      }
      return '';
    }

    // ==========================================================================
    // Avatar Walking (`walk.js`)
    // ==========================================================================
    function updatePersonUI(statusText) {
      const b = el('walkToggle');
      b.hidden = !isScanMode();
      b.setAttribute('aria-pressed', String(walkMode));
      b.textContent = walkMode ? '退出行走' : walker?.avatar.visible ? '继续行走' : '进入户型';
      const line = el('walkStatus');
      line.hidden = !isScanMode() || !walker?.avatar.visible;
      line.textContent = statusText || `位置：${SHORT_ROOM[walkedRoom] || walkedRoom || '门口'}`;
    }

    function stopWalking() {
      if (walkMotion) { cancelAnimationFrame(walkMotion); walkMotion = null; }
      walker?.stride(0, 0);
    }

    function syncAvatarRoom() {
      if (!walker) return;
      const next = walker.room(walker.avatar.position, walkedRoom);
      if (next && next !== walkedRoom) {
        walkedRoom = next;
        updatePersonUI();
        api.environment(currentKey, { room: walkedRoom, occupied: true, exclusive_walk: true })
          .then(s => applySnapshot(s, false)).catch(() => {});
      }
    }

    function beginWalk(path) {
      if (!path || path.length < 2) { updatePersonUI('此处无法通行'); return; }
      if (walkMotion) cancelAnimationFrame(walkMotion);
      const person = walker.avatar;
      const segments = path.slice(1).map((p, i) => p.distanceTo(path[i]));
      const length = segments.reduce((a, b) => a + b, 0);
      if (length < 0.045) { stopWalking(); updatePersonUI(); repaint(); return; }
      if (selectedRoom) { selectedRoom = null; zoom = 1; passage.visible = false; syncUI(); move({ speed: 9 }); }

      const pace = 2.2, ramp = 0.24, duration = length / pace + ramp;
      let prevT = null, elapsed = 0, leg = 0, done = 0;
      const frame = now => {
        const dt = prevT === null ? 1 / 60 : Math.min(0.065, (now - prevT) / 1000);
        elapsed += dt; prevT = now;
        const t = Math.min(elapsed, duration), rT = Math.min(ramp, duration / 2), spd = length / (duration - rT);
        const distance = t < rT ? (spd * t * t) / (2 * rT)
          : t > duration - rT ? length - (spd * (duration - t) ** 2) / (2 * rT)
            : spd * (t - rT / 2);
        while (leg < segments.length - 1 && distance >= done + segments[leg]) done += segments[leg++];
        const a = path[leg], b = path[leg + 1], n = segments[leg];
        person.position.lerpVectors(a, b, Math.max(0, Math.min(1, n ? (distance - done) / n : 1)));
        const heading = Math.atan2(b.x - a.x, b.z - a.z);
        person.rotation.y += wrap(heading - person.rotation.y) * (1 - Math.exp(-dt * 16));
        walker.stride(distance, Math.min(1, t / rT, (duration - t) / rT));
        syncAvatarRoom();
        if (t < duration) walkMotion = requestAnimationFrame(frame);
        else { walkMotion = null; person.position.copy(path.at(-1)); syncAvatarRoom(); updatePersonUI(); }
        repaint();
      };
      walkMotion = requestAnimationFrame(frame);
    }

    function toggleWalk() {
      if (!isScanMode()) return;
      if (walkMode) { walkMode = false; stopWalking(); updatePersonUI(); repaint(); return; }
      cancelInstall(); unfocusBulb();
      if (!walker) walker = window.createRoomWalker(T, source, scanHome);
      if (!walker.avatar.visible) {
        walker.avatar.position.copy(walker.spawn);
        walker.avatar.visible = true;
        walkedRoom = walker.room(walker.spawn);
        lookAtRoom(walkedRoom);
      }
      walkMode = true; updatePersonUI(); repaint();
    }

    // ==========================================================================
    // Camera & UI State Sync
    // ==========================================================================
    function unfocusBulb() {
      if (!focusPoint && !closeupBulbId) return;
      focusPoint = null; closeupBulbId = null;
      updateSelectionRing();
      renderDevices();
      move({ speed: 11 });
    }

    function cancelInstall() {
      installingBulb = false;
      cursorGroup.visible = false;
      canvas.classList.remove('is-installing');
      el('installBulb').setAttribute('aria-pressed', 'false');
      el('installBulb').textContent = '安装灯泡';
      el('bulbNotice').textContent = '';
      repaint();
    }

    function lookAtRoom(id, door = null) {
      cancelInstall();
      unfocusBulb();
      selectedRoom = id;
      zoom = 1;
      passage.visible = Boolean(door && isScanMode());
      if (door && isScanMode()) {
        passage.rotation.set(-Math.PI / 2, 0, Math.atan2(-door.t[1], door.t[0]));
        passage.position.copy(door.mid); passage.position.y = 0.018;
        passage.scale.set(door.w * 0.94, door.depth + 0.17, 1);
      }
      if (id && localPlan) {
        const rmDev = localPlan.items.find(it => {
          if (!Object.keys(types[it.type]?.caps || {}).length) return false;
          return roomOfPlanItem(it)?.id === id || (id === 'living' && it.mount === 'ceiling');
        });
        if (rmDev) activeDeviceId = rmDev.id;
      }
      updateSelectionRing();
      syncUI();
      updateURL();
      move({ speed: door ? 8.4 : 10.4 });
      if (id && !el('camStrip').hidden && camAttachment && !camAttachment.isUpload) {
        captureIndoorRoomCamera(id);
      }
    }

    function setView2D(to2D) {
      if (plan2D === to2D && !focusPoint) return;
      unfocusBulb();
      plan2D = to2D;
      syncUI();
      updateURL();
      move({ speed: 11.5 });
    }

    function shortRoomLabel(r) {
      if (SHORT_ROOM[r.id]) return SHORT_ROOM[r.id];
      return r.name.length > 3 ? r.name.slice(0, 2) : r.name;
    }

    function shortStateText(it) {
      if (it.type === 'lamp') return it.power ? `${it.level ?? 65}%` : '关闭';
      if (it.type === 'ac') return it.power ? (it.mode === '送风' ? '送风' : `${it.target ?? 26}°`) : '关闭';
      if (it.type === 'curtain') {
        const p = Number(it.position ?? 0);
        return p <= 3 ? '已关' : p >= 97 ? '全开' : `${p}%`;
      }
      if ('power' in it) return it.power ? '开启' : '关闭';
      return '';
    }

    function isItemOn(it) {
      if ('power' in it) return Boolean(it.power);
      if ('position' in it) return Number(it.position ?? 0) > 5;
      return false;
    }

    function itemOrb(it) {
      if (it.type === 'lamp') return { cls: 'is-lamp', svg: ICONS.bulb };
      if (it.type === 'ac') return { cls: it.mode === '制热' ? 'is-ac-heat' : 'is-ac-cool', svg: it.mode === '制热' ? ICONS.flame : ICONS.snow };
      if (it.type === 'curtain') return { cls: 'is-curtain', svg: ICONS.curtain };
      return { cls: 'is-generic', svg: ICONS.power };
    }

    let prevTilesKey = '';
    let prevCtrlSchemaKey = '';
    let prevThermoVal = null;

    function syncUI() {
      el('orbitView').setAttribute('aria-pressed', String(!plan2D));
      el('topView').setAttribute('aria-pressed', String(plan2D));
      el('installBulb').hidden = !isScanMode();
      updatePersonUI();

      const titles = { house: '我的家', apartment: '三居室', custom: '空白户型' };
      el('homeTitleText').textContent = titles[currentKey] || '我的家';

      // Scenes (Patch in-place when button IDs match to preserve sliding pill thumb!)
      const scenes = snapshot?.scenes || {};
      const sOrder = ['normal', 'home', 'away', 'sleep', ...Object.keys(scenes).filter(k => !['home', 'away', 'sleep'].includes(k))];
      const sNames = { normal: '日常', home: '回家', away: '离家', sleep: '睡眠' };
      const sceneStrip = el('sceneStrip');
      const curSceneBtns = [...sceneStrip.querySelectorAll('button[data-scene]')];
      if (curSceneBtns.length === sOrder.length && curSceneBtns.every((b, i) => b.dataset.scene === sOrder[i])) {
        curSceneBtns.forEach(b => {
          const sid = b.dataset.scene;
          b.textContent = sNames[sid] || scenes[sid]?.name || sid;
          b.setAttribute('aria-pressed', String((snapshot?.mode || 'normal') === sid));
        });
      } else {
        sceneStrip.classList.remove('has-pill-thumb');
        sceneStrip.innerHTML = sOrder.map(sid => {
          const label = sNames[sid] || scenes[sid]?.name || sid;
          return `<button type="button" data-scene="${esc(sid)}" aria-pressed="${(snapshot?.mode || 'normal') === sid}">${esc(label)}</button>`;
        }).join('');
      }

      // Rooms (Patch aria-pressed in-place when room list matches)
      if (localPlan) {
        const roomList = el('roomList');
        const expectedRooms = ['__all__', ...localPlan.rooms.map(r => r.id)];
        const curRoomBtns = [...roomList.querySelectorAll('button[data-room]')];
        if (curRoomBtns.length === expectedRooms.length && curRoomBtns.every((b, i) => b.dataset.room === expectedRooms[i])) {
          curRoomBtns.forEach((b, i) => {
            if (i === 0) b.setAttribute('aria-pressed', String(!selectedRoom));
            else {
              const r = localPlan.rooms[i - 1];
              b.setAttribute('aria-pressed', String(selectedRoom === r.id));
              b.disabled = Boolean(r.restricted);
            }
          });
        } else {
          const whole = `<button type="button" data-room="__all__" aria-pressed="${!selectedRoom}">全屋</button>`;
          const rms = localPlan.rooms.map(r =>
            `<button type="button" data-room="${esc(r.id)}" aria-pressed="${selectedRoom === r.id}" ${r.restricted ? 'disabled' : ''}>${esc(shortRoomLabel(r))}</button>`
          ).join('');
          roomList.innerHTML = whole + rms;
        }

        const neighbors = isScanMode() && selectedRoom ? scanRooms.get(selectedRoom)?.neighbors : null;
        el('adjacent').hidden = !neighbors?.size;
        if (neighbors?.size) {
          el('roomLinks').innerHTML = [...neighbors].map(([nid]) => {
            const rObj = localPlan.rooms.find(x => x.id === nid);
            if (rObj?.restricted) return '';
            return `<button type="button" data-portal-to="${esc(nid)}">${esc(SHORT_ROOM[nid] || nid)}</button>`;
          }).join('');
        }
      }

      renderDevices();
      renderTakeoverBar();
      renderEnvModal();
      syncSlidingPills();
    }

    function renderTakeoverBar() {
      const bar = el('takeoverBar');
      if (!bar || !snapshot || !localPlan) return;
      const ovs = snapshot.overrides || {};
      const dues = snapshot.due || {};
      const activeItem = localPlan.items.find(x => x.id === activeDeviceId);
      const focusRid = selectedRoom || (activeItem && roomOfPlanItem(activeItem)?.id) || walkedRoom;

      let rid = null;
      if (focusRid && (ovs[focusRid] !== undefined || dues[focusRid] !== undefined)) rid = focusRid;
      else rid = Object.keys(ovs)[0] || Object.keys(dues)[0] || null;

      if (!rid) {
        bar.hidden = true;
        bar.innerHTML = '';
        return;
      }
      const rObj = localPlan.rooms.find(r => r.id === rid);
      if (!rObj || rObj.restricted) {
        bar.hidden = true;
        return;
      }
      const rName = shortRoomLabel(rObj);
      if (ovs[rid] !== undefined) {
        const sec = ovs[rid];
        const pinned = sec < 0;
        bar.innerHTML = `
          <span class="takeover-info">
            <span class="takeover-dot ${pinned ? 'is-pinned' : ''}"></span>
            <span>${esc(rName)} · ${pinned ? '已固定手动' : `手动接管 ${sec}s`}</span>
          </span>
          <span class="takeover-actions">
            ${pinned ? '' : `<button type="button" data-hold-room="${esc(rid)}">固定</button>`}
            <button type="button" data-rel-room="${esc(rid)}">恢复自动</button>
          </span>`;
        bar.hidden = false;
        return;
      }
      if (dues[rid] !== undefined) {
        bar.innerHTML = `
          <span class="takeover-info">
            <span class="takeover-dot is-due"></span>
            <span>${esc(rName)} · ${dues[rid]}s 后自动关灯</span>
          </span>
          <span class="takeover-actions">
            <button type="button" data-hold-room="${esc(rid)}">保持手动</button>
          </span>`;
        bar.hidden = false;
      }
    }

    function renderDevices() {
      if (!localPlan) return;
      const smarts = localPlan.items.filter(it => Object.keys(types[it.type]?.caps || {}).length > 0);
      const inRoom = selectedRoom
        ? smarts.filter(it => roomOfPlanItem(it)?.id === selectedRoom || (selectedRoom === 'living' && it.mount === 'ceiling'))
        : smarts;
      const tiles = (inRoom.length ? inRoom : smarts).slice(0, 8);

      if (!activeDeviceId || !tiles.some(x => x.id === activeDeviceId)) {
        activeDeviceId = tiles[0]?.id || null;
      }

      // 1. Patch `.acc-tile` cards in-place if visible IDs haven't changed (preserves CSS spring transitions!)
      const nextTilesKey = `${currentKey}|${selectedRoom || '*'}|` + tiles.map(x => x.id).join(',');
      const chipsEl = el('deviceChips');
      const existingTiles = [...chipsEl.querySelectorAll('.acc-tile[data-dev]')];
      if (nextTilesKey === prevTilesKey && existingTiles.length === tiles.length) {
        tiles.forEach((it, idx) => {
          const card = existingTiles[idx];
          const on = isItemOn(it);
          const sel = it.id === activeDeviceId;
          const orb = itemOrb(it);
          card.classList.toggle('is-on', on);
          card.classList.toggle('is-selected', sel);
          const orbBtn = card.querySelector('.acc-orb');
          if (orbBtn && orbBtn.dataset.orbCls !== orb.cls) {
            orbBtn.className = `acc-orb ${orb.cls}`;
            orbBtn.dataset.orbCls = orb.cls;
            orbBtn.innerHTML = orb.svg;
          }
          const nameEl = card.querySelector('.acc-name');
          if (nameEl && nameEl.textContent !== it.name) nameEl.textContent = it.name;
          const valEl = card.querySelector('.acc-val');
          const stTxt = shortStateText(it);
          if (valEl && valEl.textContent !== stTxt) valEl.textContent = stTxt;
        });
      } else {
        prevTilesKey = nextTilesKey;
        chipsEl.innerHTML = tiles.map((it, idx) => {
          const on = isItemOn(it);
          const sel = it.id === activeDeviceId;
          const orb = itemOrb(it);
          return `
            <div class="acc-tile is-entering ${on ? 'is-on' : ''} ${sel ? 'is-selected' : ''}" style="--tile-i:${idx}" data-dev="${esc(it.id)}" role="button" tabindex="0">
              <button type="button" class="acc-orb ${orb.cls}" data-orb-cls="${orb.cls}" data-tile-toggle="${esc(it.id)}" aria-label="开关 ${esc(it.name)}">${orb.svg}</button>
              <div class="acc-info">
                <span class="acc-name">${esc(it.name)}</span>
                <span class="acc-val">${esc(shortStateText(it))}</span>
              </div>
            </div>`;
        }).join('');
        setTimeout(() => chipsEl.querySelectorAll('.is-entering').forEach(n => n.classList.remove('is-entering')), 420);
      }

      const item = localPlan.items.find(x => x.id === activeDeviceId);
      const box = el('deviceControls');
      if (!item) { box.innerHTML = ''; prevCtrlSchemaKey = ''; return; }

      const tspec = types[item.type] || {};
      const caps = tspec.caps || {};
      const capMeta = tspec.cap_meta || {};
      const busy = busyDevices.has(item.id);
      const vis = deviceVisuals.get(item.id);
      const canCloseup = Boolean(vis?.isCeilingBulb);
      const isCloseup = closeupBulbId === item.id;
      const canRemove = Boolean(snapshot?.permissions?.canEditLayout) && (item.mount === 'ceiling' || !isScanMode());
      const schemaKey = `${item.type}|${canCloseup ? 1 : 0}|${canRemove && item.mount === 'ceiling' ? 1 : 0}`;

      // 2. Patch Controls In-Place when same control schema is mounted (smooth slider glide & pill slide!)
      if (schemaKey === prevCtrlSchemaKey && box.children.length > 0 && !sliderDrag) {
        if (item.type === 'lamp') {
          const lvl = Number(item.level ?? 65);
          const gradMap = {
            '暖白': 'linear-gradient(90deg, #fef08a 0%, #fbbf24 100%)',
            '自然光': 'linear-gradient(90deg, #fef9c3 0%, #fcd34d 100%)',
            '冷白': 'linear-gradient(90deg, #e0f2fe 0%, #7dd3fc 100%)'
          };
          const track = box.querySelector('[data-drag-cap="level"]');
          if (track) {
            track.style.setProperty('--pct', `${lvl}%`);
            track.style.setProperty('--fill-grad', gradMap[item.color_temp] || gradMap['暖白']);
          }
          const vEl = el('val-level');
          if (vEl) vEl.textContent = `${lvl}%`;
          box.querySelectorAll('[data-enum-cap="color_temp"]').forEach(b => {
            b.setAttribute('aria-pressed', String((item.color_temp || '暖白') === b.dataset.enumVal));
            b.disabled = busy;
          });
          const cuBtn = box.querySelector('[data-closeup]');
          if (cuBtn) {
            cuBtn.setAttribute('aria-pressed', String(isCloseup));
            cuBtn.textContent = isCloseup ? '返回' : '看细节';
          }
          syncSlidingPills(box);
          return;
        }
        if (item.type === 'ac') {
          const fanOnly = item.mode === '送风';
          const targetT = Number(item.target ?? 26);
          const tRow = box.querySelector('.thermo-row');
          if (tRow) tRow.classList.toggle('is-locked', fanOnly);
          const numEl = el('val-target');
          if (numEl && numEl.textContent !== `${targetT}°`) {
            const dirCls = prevThermoVal !== null && targetT > prevThermoVal ? 'roll-up' : 'roll-down';
            numEl.textContent = `${targetT}°`;
            numEl.classList.remove('roll-up', 'roll-down');
            void numEl.offsetWidth;
            numEl.classList.add(dirCls);
          }
          prevThermoVal = targetT;
          const minusBtn = box.querySelector('[data-step-delta="-1"]');
          const plusBtn = box.querySelector('[data-step-delta="1"]');
          if (minusBtn) minusBtn.disabled = busy || fanOnly || targetT <= 16;
          if (plusBtn) plusBtn.disabled = busy || fanOnly || targetT >= 30;
          box.querySelectorAll('[data-enum-cap="mode"]').forEach(b => {
            b.setAttribute('aria-pressed', String(item.mode === b.dataset.enumVal));
            b.disabled = busy;
          });
          box.querySelectorAll('[data-enum-cap="fan_speed"]').forEach(b => {
            b.setAttribute('aria-pressed', String(item.fan_speed === b.dataset.enumVal));
            b.disabled = busy;
          });
          syncSlidingPills(box);
          return;
        }
        if (item.type === 'curtain') {
          const pos = Number(item.position ?? 50);
          const track = box.querySelector('[data-drag-cap="position"]');
          if (track) track.style.setProperty('--pct', `${pos}%`);
          const vEl = el('val-position');
          if (vEl) vEl.textContent = `${pos}%`;
          const pBtns = box.querySelectorAll('[data-preset-cap="position"]');
          if (pBtns.length === 3) {
            pBtns[0].setAttribute('aria-pressed', String(pos <= 3));
            pBtns[1].setAttribute('aria-pressed', String(pos > 45 && pos < 55));
            pBtns[2].setAttribute('aria-pressed', String(pos >= 97));
          }
          syncSlidingPills(box);
          return;
        }
      }

      const animateSchemaSwap = prevCtrlSchemaKey && prevCtrlSchemaKey !== schemaKey;
      prevCtrlSchemaKey = schemaKey;
      if (item.type === 'ac') prevThermoVal = Number(item.target ?? 26);

      if (item.type === 'lamp') {
        const lvl = Number(item.level ?? 65);
        const gradMap = {
          '暖白': 'linear-gradient(90deg, #fef08a 0%, #fbbf24 100%)',
          '自然光': 'linear-gradient(90deg, #fef9c3 0%, #fcd34d 100%)',
          '冷白': 'linear-gradient(90deg, #e0f2fe 0%, #7dd3fc 100%)'
        };
        const swatches = [
          { val: '暖白', label: '暖白', hex: '#f59e0b' },
          { val: '自然光', label: '自然', hex: '#fde047' },
          { val: '冷白', label: '冷白', hex: '#7dd3fc' }
        ];
        box.innerHTML = `
          <div class="thick-slider" data-drag-cap="level" data-min="1" data-max="100" data-unit="%" style="--pct:${lvl}%;--fill-grad:${gradMap[item.color_temp] || gradMap['暖白']}">
            <div class="thick-slider-fill"></div>
            <div class="thick-slider-overlay">
              <span class="thick-slider-label">${ICONS.sun}<span>亮度</span></span>
              <span class="thick-slider-val" id="val-level">${lvl}%</span>
            </div>
          </div>
          <div class="ctrl-sub-row">
            <div class="swatch-bar">
              ${swatches.map(sw => `
                <button type="button" class="swatch-btn" data-enum-cap="color_temp" data-enum-val="${sw.val}" aria-pressed="${(item.color_temp || '暖白') === sw.val}" ${busy ? 'disabled' : ''}>
                  <span class="swatch-dot" style="background:${sw.hex}"></span><span>${sw.label}</span>
                </button>`).join('')}
            </div>
            ${canCloseup ? `<button type="button" class="sub-pill" data-closeup aria-pressed="${isCloseup}">${isCloseup ? '返回' : '看细节'}</button>` : ''}
            ${canRemove && item.mount === 'ceiling' ? `<button type="button" class="sub-pill is-danger" data-remove>移除</button>` : ''}
          </div>`;
      } else if (item.type === 'ac') {
        const fanOnly = item.mode === '送风';
        const targetT = Number(item.target ?? 26);
        const modes = caps.mode || ['制冷', '制热', '除湿', '送风'];
        const speeds = caps.fan_speed || ['静音', '自动', '强风'];
        box.innerHTML = `
          <div class="thermo-row ${fanOnly ? 'is-locked' : ''}">
            <button type="button" class="step-btn" data-step-cap="target" data-step-delta="-1" ${(busy || fanOnly || targetT <= 16) ? 'disabled' : ''}>−</button>
            <span class="thermo-num" id="val-target">${targetT}°</span>
            <button type="button" class="step-btn" data-step-cap="target" data-step-delta="1" ${(busy || fanOnly || targetT >= 30) ? 'disabled' : ''}>+</button>
          </div>
          <div class="seg-bar">
            ${modes.map(m => `<button type="button" data-enum-cap="mode" data-enum-val="${esc(m)}" aria-pressed="${item.mode === m}" ${busy ? 'disabled' : ''}>${esc(m)}</button>`).join('')}
          </div>
          <div class="seg-bar">
            ${speeds.map(s => `<button type="button" data-enum-cap="fan_speed" data-enum-val="${esc(s)}" aria-pressed="${item.fan_speed === s}" ${busy ? 'disabled' : ''}>${esc(s)}</button>`).join('')}
          </div>`;
      } else if (item.type === 'curtain') {
        const pos = Number(item.position ?? 50);
        box.innerHTML = `
          <div class="thick-slider" data-drag-cap="position" data-min="0" data-max="100" data-unit="%" style="--pct:${pos}%;--fill-grad:linear-gradient(90deg,#99f6e4,#2dd4bf)">
            <div class="thick-slider-fill"></div>
            <div class="thick-slider-overlay">
              <span class="thick-slider-label">${ICONS.curtain}<span>窗帘开合</span></span>
              <span class="thick-slider-val" id="val-position">${pos}%</span>
            </div>
          </div>
          <div class="seg-bar">
            <button type="button" data-preset-cap="position" data-preset-val="0" aria-pressed="${pos <= 3}">全关</button>
            <button type="button" data-preset-cap="position" data-preset-val="50" aria-pressed="${pos > 45 && pos < 55}">半开</button>
            <button type="button" data-preset-cap="position" data-preset-val="100" aria-pressed="${pos >= 97}">全开</button>
          </div>`;
      } else {
        box.innerHTML = Object.keys(caps).filter(k => k !== 'power').map(ck => {
          const dom = caps[ck], meta = capMeta[ck] || {};
          const label = meta.label || ck, unit = meta.unit || '', val = item[ck];
          if (typeof dom[0] === 'number') {
            const pct = Math.round(((Number(val) - dom[0]) / Math.max(1, dom[1] - dom[0])) * 100);
            return `
              <div class="thick-slider" data-drag-cap="${esc(ck)}" data-min="${dom[0]}" data-max="${dom[1]}" data-unit="${esc(unit)}" style="--pct:${pct}%;--fill-grad:linear-gradient(90deg,#a7f3d0,#34d399)">
                <div class="thick-slider-fill"></div>
                <div class="thick-slider-overlay">
                  <span class="thick-slider-label">${esc(label)}</span>
                  <span class="thick-slider-val" id="val-${esc(ck)}">${esc(val)}${esc(unit)}</span>
                </div>
              </div>`;
          }
          return `<div class="seg-bar">${dom.map(opt => `<button type="button" data-enum-cap="${esc(ck)}" data-enum-val="${esc(opt)}" aria-pressed="${val === opt}">${esc(opt)}</button>`).join('')}</div>`;
        }).join('');
      }

      if (animateSchemaSwap) {
        box.classList.remove('is-switching');
        void box.offsetWidth;
        box.classList.add('is-switching');
      }
      syncSlidingPills(box);
    }

    function renderEnvModal() {
      if (!snapshot) return;
      const clim = snapshot.climate || {};
      const f = el('envForm');
      if (!f.contains(document.activeElement)) {
        const s = clim.season || '夏';
        f.elements.season.value = s;
        el('seasonSeg').querySelectorAll('[data-season]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.season === s)));
        f.elements.indoor.value = clim.indoor ?? 26;
        f.elements.humidity.value = clim.humidity ?? 55;
        f.elements.lux.value = clim.lux ?? 120;
      }
      el('occMatrix').innerHTML = (localPlan?.rooms || []).filter(r => !r.restricted).map(r => {
        const occ = Boolean(snapshot.occupied?.[r.id]);
        const ov = snapshot.overrides?.[r.id];
        const isManual = ov !== undefined;
        return `<div class="occ-row">
          <span>${esc(r.name)}</span>
          <button type="button" data-auto-toggle="${esc(r.id)}" aria-pressed="${isManual}">${ov === -1 ? '手动锁' : isManual ? `接管${ov}s` : '自动'}</button>
          <button type="button" data-dnd="${esc(r.id)}" aria-pressed="${Boolean(r.sleep)}">${r.sleep ? '免打扰' : '常规'}</button>
          <button type="button" data-occ="${esc(r.id)}" aria-pressed="${occ}">${occ ? '有人' : '无人'}</button>
        </div>`;
      }).join('');
    }

    // ==========================================================================
    // Snapshot & Commands
    // ==========================================================================
    function applySnapshot(next, resetView = false) {
      snapshot = next;
      localPlan = clone(next.plan);
      if (resetView || planTopologySig(localPlan) !== lastTopologySig) {
        rebuild3DFromPlan();
      } else {
        sync3DStatesFromPlan();
      }
      syncUI();
      if (resetView) {
        selectedRoom = null; zoom = 1; focusPoint = null; closeupBulbId = null;
        move({ speed: 11.5 });
      }
      if (!el('camStrip').hidden && camAttachment && !camAttachment.isUpload) {
        captureIndoorRoomCamera(camAttachment.room);
      }
    }

    async function sendCmd(deviceId, capability, value) {
      if (busyDevices.has(deviceId)) return;
      busyDevices.add(deviceId);

      // Optimistic 0-latency 3D + UI transition on user click!
      const optItem = localPlan?.items?.find(x => x.id === deviceId);
      if (optItem && !(optItem.type === 'ac' && optItem.mode === '送风' && capability === 'target')) {
        optItem[capability] = value;
        sync3DStatesFromPlan();
        renderDevices();
      }

      try {
        const res = await api.command(currentKey, deviceId, capability, value, 'ok');
        busyDevices.delete(deviceId);
        applySnapshot(res.snapshot, false);
      } catch (err) {
        busyDevices.delete(deviceId);
        if (snapshot) {
          localPlan = clone(snapshot.plan);
          sync3DStatesFromPlan();
        }
        showToast(err.message, true);
        renderDevices();
      }
    }

    async function switchHomePlan(nextKey) {
      if (nextKey === currentKey) return;
      if (walkMode) toggleWalk();
      cancelInstall();
      unfocusBulb();
      currentKey = nextKey;
      selectedRoom = null;
      const snap = await api.get(currentKey);
      applySnapshot(snap, true);
      updateURL();
    }

    // ==========================================================================
    // Canvas Pointer & Tactile Slider Drag
    // ==========================================================================
    let pointer = null;
    const ndcTmp = new T.Vector2();

    function raycastFloor(e) {
      const rect = canvasRect.width > 2 ? canvasRect : (canvasRect = canvas.getBoundingClientRect());
      ndcTmp.set(((e.clientX - rect.left) / rect.width) * 2 - 1, 1 - ((e.clientY - rect.top) / rect.height) * 2);
      liveRay.setFromCamera(ndcTmp, camera);
      return liveRay.ray.intersectPlane(floorPlane, new T.Vector3());
    }

    function dragCamera(dx, dy, dtSec) {
      const wasMoving = Boolean(motion);
      stopSpring();
      const invDt = 1 / Math.max(0.008, Math.min(0.08, dtSec || 0.016));
      if (plan2D && !focusPoint) {
        const perPixel = Math.exp(state.scale) / viewport.clientHeight;
        const stepX = -dx * perPixel, stepZ = -dy * perPixel;
        state.x += stepX; state.z += stepZ;
        if (pointer) {
          pointer.vx = pointer.vx * 0.55 + (stepX * invDt) * 0.45;
          pointer.vz = pointer.vz * 0.55 + (stepZ * invDt) * 0.45;
        }
        if (wasMoving && (Math.abs(state.yaw) > 0.002 || state.polar > 0.002)) {
          const center = { x: state.x, y: state.y, z: state.z, scale: state.scale };
          goal = { ...desired(), ...center }; stiffness = 18; motion = requestAnimationFrame(tick);
        }
      } else {
        const dYaw = -dx * 0.0078;
        const dPol = -dy * 0.0078;
        yaw3 = state.yaw + dYaw;
        state.yaw = yaw3;
        if (!focusPoint) { tilt3 = Math.max(0.04, Math.min(1.42, state.polar + dPol)); state.polar = tilt3; }
        if (pointer) {
          pointer.vYaw = pointer.vYaw * 0.55 + (dYaw * invDt) * 0.45;
          pointer.vPol = pointer.vPol * 0.55 + (dPol * invDt) * 0.45;
        }
      }
      repaint();
    }

    canvas.addEventListener('pointerdown', e => {
      if (e.button !== 0 || !e.isPrimary) return;
      canvasRect = canvas.getBoundingClientRect();
      pointer = {
        x: e.clientX, y: e.clientY, startX: e.clientX, startY: e.clientY,
        t: performance.now(), id: e.pointerId, dragged: false,
        vx: 0, vz: 0, vYaw: 0, vPol: 0
      };
      canvas.setPointerCapture(e.pointerId);
      if (installingBulb) {
        const hitFloor = raycastFloor(e);
        if (hitFloor) {
          cursorGroup.visible = true;
          cursorGroup.position.set(hitFloor.x, 0.012, hitFloor.z);
          ringMat.color.set(bulbPlacementError(hitFloor) ? '#b44738' : '#287869');
          repaint();
        }
      }
    });

    canvas.addEventListener('pointermove', e => {
      // Fast bailout: zero raycasting & zero layout reads on idle mouse hover!
      if (!installingBulb && pointer?.id !== e.pointerId) return;

      if (installingBulb && (!pointer || !pointer.dragged)) {
        const hitFloor = raycastFloor(e);
        if (hitFloor) {
          cursorGroup.visible = true;
          cursorGroup.position.set(hitFloor.x, 0.012, hitFloor.z);
          const err = bulbPlacementError(hitFloor);
          ringMat.color.set(err ? '#b44738' : '#287869');
          el('bulbNotice').textContent = err || '点击客厅位置安装灯泡';
          repaint();
        }
      }
      if (pointer?.id !== e.pointerId) return;
      if (!pointer.dragged && Math.hypot(e.clientX - pointer.startX, e.clientY - pointer.startY) < 4) return;
      pointer.dragged = true;
      cursorGroup.visible = false;
      const now = performance.now();
      const dtSec = (now - pointer.t) / 1000;
      dragCamera(e.clientX - pointer.x, e.clientY - pointer.y, dtSec);
      pointer.x = e.clientX; pointer.y = e.clientY; pointer.t = now;
    });

    canvas.addEventListener('pointerup', async e => {
      if (pointer?.id !== e.pointerId) return;
      const pEnd = pointer;
      pointer = null;
      if (pEnd.dragged) {
        // Gentle inertial coasting when user flicks/releaseswithin last 65ms!
        if (!reduced.matches && performance.now() - pEnd.t < 65) {
          if (plan2D && !focusPoint && Math.hypot(pEnd.vx, pEnd.vz) > 0.12) {
            goal = { ...state, x: state.x + pEnd.vx * 0.11, z: state.z + pEnd.vz * 0.11 };
            velocity.x = pEnd.vx * 0.45;
            velocity.z = pEnd.vz * 0.45;
            stiffness = 11.5;
            if (!motion) motion = requestAnimationFrame(tick);
          } else if (!plan2D && Math.hypot(pEnd.vYaw, pEnd.vPol) > 0.15) {
            const throwYaw = T.MathUtils.clamp(pEnd.vYaw * 0.11, -0.55, 0.55);
            const throwPol = focusPoint ? 0 : T.MathUtils.clamp(pEnd.vPol * 0.09, -0.25, 0.25);
            yaw3 = state.yaw + throwYaw;
            if (!focusPoint) tilt3 = T.MathUtils.clamp(state.polar + throwPol, 0.04, 1.42);
            goal = { ...state, yaw: yaw3, polar: focusPoint ? state.polar : tilt3 };
            velocity.yaw = pEnd.vYaw * 0.42;
            if (!focusPoint) velocity.polar = pEnd.vPol * 0.35;
            stiffness = 11;
            if (!motion) motion = requestAnimationFrame(tick);
          }
        }
        return;
      }

      const hitFloor = raycastFloor(e);
      if (installingBulb && hitFloor) {
        const err = bulbPlacementError(hitFloor);
        if (err) { showToast(err, true); return; }
        try {
          const res = await api.mount(currentKey, hitFloor.x, hitFloor.z);
          cancelInstall();
          activeDeviceId = res.item.id;
          applySnapshot(res.snapshot, false);
          showToast(`已安装 ${res.item.name}`);
        } catch (ex) { showToast(ex.message, true); }
        return;
      }

      if (walkMode && !focusPoint && hitFloor && walker) {
        beginWalk(walker.pointPath(walker.avatar.position, hitFloor));
        return;
      }

      const pickTargets = [...deviceVisuals.values()].flatMap(v => v.marker?.visible ? [v.marker, v.hit] : [v.hit]);
      const picked = liveRay.intersectObjects(pickTargets, false)[0];
      if (picked?.object?.userData?.deviceId) {
        activeDeviceId = picked.object.userData.deviceId;
        updateSelectionRing();
        renderDevices();
        repaint();
      }
    });

    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      zoom = Math.max(0.52, Math.min(4.2, zoom * Math.exp(-e.deltaY * 0.0012)));
      move({ speed: 18, scaleOnly: true });
    }, { passive: false });

    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') {
        closeMenu();
        cancelInstall();
        unfocusBulb();
        if (walkMode) toggleWalk();
      }
    });

    // Tactile Slider Drag
    let sliderDrag = null;
    const ctrlHost = el('deviceControls');

    ctrlHost.addEventListener('pointerdown', e => {
      const track = e.target.closest('[data-drag-cap]');
      if (!track) return;
      const item = localPlan?.items.find(x => x.id === activeDeviceId);
      if (!item || busyDevices.has(item.id)) return;
      const cap = track.dataset.dragCap;
      const min = Number(track.dataset.min ?? 0), max = Number(track.dataset.max ?? 100);
      const unit = track.dataset.unit || '';
      track.setPointerCapture(e.pointerId);
      track.classList.add('is-dragging');

      const scrub = cx => {
        const r = track.getBoundingClientRect();
        const ratio = Math.max(0, Math.min(1, (cx - r.left) / Math.max(1, r.width)));
        const val = Math.round(min + ratio * (max - min));
        track.style.setProperty('--pct', `${Math.round(ratio * 100)}%`);
        const vEl = el('val-' + cap);
        if (vEl) vEl.textContent = `${val}${unit}`;
        preview3DDeviceValue(item, cap, val);
        return val;
      };
      sliderDrag = { pointerId: e.pointerId, track, itemId: item.id, cap, value: scrub(e.clientX) };
    });

    ctrlHost.addEventListener('pointermove', e => {
      if (!sliderDrag || sliderDrag.pointerId !== e.pointerId) return;
      const { track, cap, itemId } = sliderDrag;
      const item = localPlan?.items.find(x => x.id === itemId);
      if (!item) return;
      const min = Number(track.dataset.min ?? 0), max = Number(track.dataset.max ?? 100);
      const unit = track.dataset.unit || '';
      const r = track.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (e.clientX - r.left) / Math.max(1, r.width)));
      const val = Math.round(min + ratio * (max - min));
      sliderDrag.value = val;
      track.style.setProperty('--pct', `${Math.round(ratio * 100)}%`);
      const vEl = el('val-' + cap);
      if (vEl) vEl.textContent = `${val}${unit}`;
      preview3DDeviceValue(item, cap, val);
    });

    const endSliderDrag = async e => {
      if (!sliderDrag || sliderDrag.pointerId !== e.pointerId) return;
      const { track, itemId, cap, value } = sliderDrag;
      track.classList.remove('is-dragging');
      sliderDrag = null;
      const item = localPlan?.items.find(x => x.id === itemId);
      if (!item) return;
      if (cap === 'level' && !item.power && value > 3) await sendCmd(itemId, 'power', true);
      await sendCmd(itemId, cap, value);
    };
    ctrlHost.addEventListener('pointerup', endSliderDrag);
    ctrlHost.addEventListener('pointercancel', endSliderDrag);

    // ==========================================================================
    // Panel Event Wiring
    // ==========================================================================
    viewport.prepend(canvas);

    el('orbitView').onclick = () => setView2D(false);
    el('topView').onclick = () => setView2D(true);
    el('walkToggle').onclick = toggleWalk;
    el('reset').onclick = () => {
      cancelInstall(); unfocusBulb();
      selectedRoom = null; zoom = 1; yaw3 = YAW; tilt3 = ANGLE; passage.visible = false;
      syncUI();
      move({ speed: 12.5 });
    };

    el('installBulb').onclick = () => {
      if (!isScanMode()) return;
      if (installingBulb) { cancelInstall(); return; }
      if (walkMode) toggleWalk();
      unfocusBulb();
      installingBulb = true;
      canvas.classList.add('is-installing');
      el('installBulb').setAttribute('aria-pressed', 'true');
      el('installBulb').textContent = '取消安装';
      el('bulbNotice').textContent = '点击客厅地面安装灯泡';
      selectedRoom = 'living'; zoom = 1; passage.visible = false;
      syncUI();
      move({ speed: 12 });
    };

    // Home Picker Menu
    el('homeMenuBtn').onclick = () => {
      openMenu(el('homeMenuBtn'), [
        { label: '我的家', checked: currentKey === 'house', onPick: () => switchHomePlan('house') },
        { label: '三居室', checked: currentKey === 'apartment', onPick: () => switchHomePlan('apartment') },
        { label: '空白户型', checked: currentKey === 'custom', onPick: () => switchHomePlan('custom') }
      ]);
    };

    // More `⋯` Menu (Secondary Options Tucked Cleanly Out of Sight)
    el('moreMenuBtn').onclick = () => {
      const roleLabels = { admin: '管理员', member: '长辈', guest: '访客' };
      const items = [];
      if (isScanMode()) {
        items.push(
          { label: '显示家具', checked: showScanObjects, onPick: () => { showScanObjects = !showScanObjects; syncScanFinishes(); } },
          { label: '类别着色', checked: colorScanByCategory, onPick: () => { colorScanByCategory = !colorScanByCategory; syncScanFinishes(); } },
          { sep: true }
        );
      }
      items.push(
        { label: '环境与传感器…', onPick: () => { el('envModal').showModal(); requestAnimationFrame(() => syncSlidingPills(el('envModal'))); } },
        { label: '新建场景…', onPick: openSceneSheet },
        { label: '添加配件类型…', onPick: () => { el('typeErr').textContent = ''; el('typeModal').showModal(); } },
        { label: '平面图编辑 ↗', onPick: () => { location.href = `floorplan-editor.html?plan=${encodeURIComponent(currentKey === 'house' ? 'apartment' : currentKey)}`; } },
        { sep: true },
        {
          label: `成员：${roleLabels[snapshot?.role] || '管理员'}…`,
          onPick: async () => {
            const ok = await api.switchRole();
            if (ok) applySnapshot(await api.get(currentKey), false);
          }
        }
      );
      openMenu(el('moreMenuBtn'), items);
    };

    el('sceneStrip').onclick = async e => {
      const b = e.target.closest('[data-scene]');
      if (!b) return;
      try {
        const res = await api.scene(currentKey, b.dataset.scene);
        applySnapshot(res, false);
      } catch (err) { showToast(err.message, true); }
    };

    el('roomList').onclick = e => {
      const b = e.target.closest('[data-room]');
      if (!b) return;
      const rid = b.dataset.room;
      if (rid === '__all__') { lookAtRoom(null); return; }
      if (walkMode && isScanMode() && walker) beginWalk(walker.roomPath(walker.avatar.position, rid));
      else lookAtRoom(rid);
    };

    el('takeoverBar').onclick = async e => {
      const holdBtn = e.target.closest('[data-hold-room]');
      if (holdBtn) {
        try {
          applySnapshot(await api.environment(currentKey, { hold_override: holdBtn.dataset.holdRoom }), false);
        } catch (err) { showToast(err.message, true); }
        return;
      }
      const relBtn = e.target.closest('[data-rel-room]');
      if (relBtn) {
        try {
          applySnapshot(await api.environment(currentKey, { release_override: relBtn.dataset.relRoom }), false);
        } catch (err) { showToast(err.message, true); }
      }
    };

    el('roomLinks').onclick = e => {
      const b = e.target.closest('[data-portal-to]');
      if (!b) return;
      const targetId = b.dataset.portalTo;
      const door = scanRooms.get(selectedRoom)?.neighbors.get(targetId);
      if (walkMode && walker) beginWalk(walker.roomPath(walker.avatar.position, targetId));
      else lookAtRoom(targetId, door);
    };

    el('deviceChips').onclick = e => {
      const toggleBtn = e.target.closest('[data-tile-toggle]');
      if (toggleBtn) {
        e.stopPropagation();
        const did = toggleBtn.dataset.tileToggle;
        activeDeviceId = did;
        updateSelectionRing();
        const it = localPlan?.items.find(x => x.id === did);
        if (it) {
          if ('power' in (types[it.type]?.caps || {})) sendCmd(did, 'power', !it.power);
          else if ('position' in (types[it.type]?.caps || {})) sendCmd(did, 'position', Number(it.position ?? 0) > 5 ? 0 : 100);
        }
        return;
      }
      const tile = e.target.closest('[data-dev]');
      if (!tile) return;
      activeDeviceId = tile.dataset.dev;
      if (closeupBulbId) {
        const vis = deviceVisuals.get(activeDeviceId);
        if (vis?.isCeilingBulb) {
          closeupBulbId = activeDeviceId;
          focusPoint = vis.worldPos.clone().add(new T.Vector3(0, -0.053, 0));
          move({ speed: 11 });
        } else unfocusBulb();
      }
      updateSelectionRing();
      renderDevices();
      repaint();
    };

    ctrlHost.onclick = async e => {
      const item = localPlan?.items.find(x => x.id === activeDeviceId);
      if (!item) return;

      const stepBtn = e.target.closest('[data-step-cap]');
      if (stepBtn) {
        const ck = stepBtn.dataset.stepCap;
        const nextVal = Math.max(16, Math.min(30, Number(item[ck] ?? 26) + Number(stepBtn.dataset.stepDelta)));
        if (!item.power) await sendCmd(item.id, 'power', true);
        return sendCmd(item.id, ck, nextVal);
      }

      const presetBtn = e.target.closest('[data-preset-cap]');
      if (presetBtn) return sendCmd(item.id, presetBtn.dataset.presetCap, Number(presetBtn.dataset.presetVal));

      const enumBtn = e.target.closest('[data-enum-cap]');
      if (enumBtn) return sendCmd(item.id, enumBtn.dataset.enumCap, enumBtn.dataset.enumVal);

      if (e.target.closest('[data-closeup]')) {
        if (closeupBulbId === item.id) { unfocusBulb(); return; }
        const vis = deviceVisuals.get(item.id);
        if (!vis) return;
        if (walkMode) toggleWalk();
        closeupBulbId = item.id;
        focusPoint = vis.worldPos.clone().add(new T.Vector3(0, -0.053, 0));
        updateSelectionRing();
        renderDevices();
        move({ speed: 11 });
      }
      if (e.target.closest('[data-remove]')) {
        try {
          unfocusBulb();
          const next = await api.remove(currentKey, item.id, false);
          activeDeviceId = null;
          applySnapshot(next, false);
        } catch (err) {
          if (err.status === 409 && confirm(`${err.message}\n\n确认移除吗？`)) {
            const next = await api.remove(currentKey, item.id, true);
            activeDeviceId = null;
            applySnapshot(next, false);
          } else showToast(err.message, true);
        }
      }
    };

    // ==========================================================================
    // Genuine Indoor Wall-Mounted Room Camera + Classic Siri-Style Assistant
    // ==========================================================================
    function polyEdgeClearance(wx, wz, poly) {
      let minD = Infinity;
      for (let i = 0; i < poly.length; i++) {
        const [x1, z1] = poly[i], [x2, z2] = poly[(i + 1) % poly.length];
        const dx = x2 - x1, dz = z2 - z1, l2 = dx * dx + dz * dz;
        const t = l2 ? Math.max(0, Math.min(1, ((wx - x1) * dx + (wz - z1) * dz) / l2)) : 0;
        minD = Math.min(minD, Math.hypot(wx - (x1 + t * dx), wz - (z1 + t * dz)));
      }
      return minD;
    }

    function solveIndoorCameraPose(rid) {
      let poly = null;
      let ceilY = 2.48;
      if (isScanMode()) {
        const sr = scanRooms.get(rid) || scanRooms.get('living');
        if (sr) {
          poly = sr.outline;
          ceilY = sr.bounds.max.y;
        }
      } else if (localPlan?.rooms) {
        const rObj = localPlan.rooms.find(r => r.id === rid && !r.restricted) || localPlan.rooms.find(r => !r.restricted);
        if (rObj?.p?.length) poly = rObj.p.map(([px, py]) => planToWorld(px, py));
      }
      if (!poly || poly.length < 3) {
        return { eye: new T.Vector3(-1.4, 2.1, -1.4), target: new T.Vector3(0, 0.72, 0), ceilY: 2.48, cx: 0, cz: 0 };
      }

      const xs = poly.map(p => p[0]), zs = poly.map(p => p[1]);
      const minX = Math.min(...xs), maxX = Math.max(...xs);
      const minZ = Math.min(...zs), maxZ = Math.max(...zs);
      const pts = [];
      const N = 12;
      for (let i = 1; i < N; i++) {
        for (let j = 1; j < N; j++) {
          const gx = minX + ((maxX - minX) * i) / N;
          const gz = minZ + ((maxZ - minZ) * j) / N;
          if (!pointInPoly2D(gx, gz, poly)) continue;
          const clr = polyEdgeClearance(gx, gz, poly);
          if (clr >= 0.18) pts.push({ x: gx, z: gz, clr });
        }
      }

      if (!pts.length) {
        const cx = (minX + maxX) / 2, cz = (minZ + maxZ) / 2;
        return { eye: new T.Vector3(minX + 0.3, ceilY - 0.3, minZ + 0.3), target: new T.Vector3(cx, 0.72, cz), ceilY, cx, cz };
      }

      // Open center of the room (pole of inaccessibility)
      pts.sort((a, b) => b.clr - a.clr);
      const centerPt = pts[0];

      // Deepest interior corner looking across longest diagonal into the room
      let bestCorner = pts[0], bestDist = -1;
      for (const p of pts) {
        if (p.clr < 0.22) continue;
        const d = Math.hypot(p.x - centerPt.x, p.z - centerPt.z);
        if (d > bestDist) { bestDist = d; bestCorner = p; }
      }
      const eyeY = Math.min(ceilY - 0.28, 2.16);
      return {
        eye: new T.Vector3(bestCorner.x, eyeY, bestCorner.z),
        target: new T.Vector3(centerPt.x, 0.72, centerPt.z),
        ceilY,
        cx: centerPt.x,
        cz: centerPt.z
      };
    }

    function captureIndoorRoomCamera(requestedRoomId) {
      if (!localPlan) return null;
      const validRooms = localPlan.rooms.filter(r => !r.restricted);
      let rid = requestedRoomId || selectedRoom || walkedRoom || 'living';
      if (!validRooms.some(r => r.id === rid)) rid = validRooms[0]?.id || 'living';
      const rObj = validRooms.find(r => r.id === rid);
      const rLabel = rObj ? shortRoomLabel(rObj) : '客厅';

      const pose = solveIndoorCameraPose(rid);
      indoorCam.position.copy(pose.eye);
      indoorCam.up.set(0, 1, 0);
      indoorCam.lookAt(pose.target);
      indoorCam.updateMatrixWorld();

      // Save main stage state
      const prevSize = renderer.getSize(new T.Vector2());
      const prevPR = renderer.getPixelRatio();
      const prevScanVis = scanHome.visible;
      const prevCustVis = customHome.visible;
      const prevBaseVis = base.visible;
      const prevSelVis = selRing.visible;
      const prevCurVis = cursorGroup.visible;
      const prevPassVis = passage.visible;
      const prevSky = sky.intensity;
      const prevSun = sun.intensity;
      const prevDevVis = new Map();
      const prevMarkerVis = new Map();
      for (const [did, v] of deviceVisuals) {
        prevDevVis.set(did, v.node.visible);
        v.node.visible = true;
        if (v.marker) {
          prevMarkerVis.set(did, v.marker.visible);
          v.marker.visible = false;
        }
      }

      // Configure authentic enclosed indoor room lighting
      scanHome.visible = isScanMode();
      customHome.visible = !isScanMode();
      base.visible = true;
      selRing.visible = false;
      cursorGroup.visible = false;
      passage.visible = false;
      indoorCeiling.position.set(pose.cx, pose.ceilY - 0.01, pose.cz);
      indoorCeiling.visible = true;

      const roomLamps = (localPlan.items || []).filter(it =>
        (it.type === 'lamp' || it.type === 'switch') &&
        (roomOfPlanItem(it)?.id === rid || (rid === 'living' && it.mount === 'ceiling'))
      );
      const activeLamp = roomLamps.find(it => it.power);
      const lampLvl = activeLamp ? (Number(activeLamp.level ?? 70) / 100) : 0;
      const envLux = Number(snapshot?.climate?.lux ?? 95);
      const daylight = activeLamp ? 0.42 : Math.max(0.06, Math.min(0.48, (envLux - 40) / 360));

      sky.intensity = 0.18 + daylight * 0.65 + lampLvl * 0.95;
      sun.intensity = 0.08 + daylight * 0.45;

      if (activeLamp) {
        const tintMap = { '暖白': '#ffd6a1', '自然光': '#fff4e0', '冷白': '#e0f0ff' };
        indoorBounceLight.color.set(tintMap[activeLamp.color_temp] || '#ffd6a1');
        indoorBounceLight.position.set(pose.cx, pose.ceilY - 0.26, pose.cz);
        indoorBounceLight.intensity = 0.8 + lampLvl * 3.1;
        indoorBounceLight.visible = true;
      } else {
        indoorBounceLight.visible = false;
        indoorBounceLight.intensity = 0;
      }

      // Render synchronous 560x350 indoor camera frame & immediately restore main viewport
      renderer.setPixelRatio(1);
      renderer.setSize(560, 350, false);
      renderer.render(scene, indoorCam);
      snapCtx.drawImage(canvas, 0, 0, 560, 350);

      indoorCeiling.visible = false;
      indoorBounceLight.visible = false;
      sky.intensity = prevSky;
      sun.intensity = prevSun;
      scanHome.visible = prevScanVis;
      customHome.visible = prevCustVis;
      base.visible = prevBaseVis;
      selRing.visible = prevSelVis;
      cursorGroup.visible = prevCurVis;
      passage.visible = prevPassVis;
      for (const [did, v] of deviceVisuals) {
        v.node.visible = prevDevVis.get(did);
        if (v.marker) v.marker.visible = prevMarkerVis.get(did);
      }
      renderer.setPixelRatio(prevPR);
      renderer.setSize(prevSize.x, prevSize.y, false);
      renderer.render(scene, camera);

      const dataUrl = snapCanvas.toDataURL('image/jpeg', 0.86);
      camAttachment = { dataUrl, room: rid, label: `${rLabel}镜头`, isUpload: false };
      el('camThumb').src = dataUrl;
      el('camRoomLabel').textContent = `${rLabel}镜头`;
      el('camStrip').hidden = false;
      return camAttachment;
    }

    function inferRoomFromUtterance(text) {
      if (!localPlan?.rooms) return null;
      for (const r of localPlan.rooms) {
        if (!r.restricted && (text.includes(r.name) || text.includes(shortRoomLabel(r)))) return r.id;
      }
      const pairs = [
        [['客厅', '起居'], ['living']], [['餐厅'], ['dining']], [['厨房'], ['kitchen']],
        [['主卧'], ['bed', 'master']], [['次卧', '长辈', '老人'], ['bed2', 'elder']],
        [['书房', '工作', '看书'], ['bed3', 'study']], [['客房'], ['bed4']],
        [['玄关', '门口'], ['entry']], [['走廊', '过道'], ['hall']]
      ];
      for (const [words, rids] of pairs) {
        if (words.some(w => text.includes(w))) {
          const hit = localPlan.rooms.find(r => !r.restricted && rids.includes(r.id));
          if (hit) return hit.id;
        }
      }
      return null;
    }

    let traceTimers = [];
    function clearTraceTimers() {
      while (traceTimers.length) clearTimeout(traceTimers.pop());
    }

    function shortStepDetail(detail) {
      const s = String(detail || '').trim();
      if (s.includes('→') && s.length > 17) return s.split('→').pop().trim();
      return s;
    }

    function focusSpatialStep(step) {
      if (!step || !localPlan) return;
      let did = step.device_id;
      if (!did && step.room_id) {
        const rmItem = localPlan.items.find(it =>
          ['lamp', 'ac', 'curtain', 'switch'].includes(it.type) && roomOfPlanItem(it)?.id === step.room_id
        );
        if (rmItem) did = rmItem.id;
      }
      if (did && localPlan.items.some(x => x.id === did)) {
        activeDeviceId = did;
        updateSelectionRing();
        renderDevices();
        repaint();
      }
    }

    function renderSiriThinking(quoteText) {
      clearTraceTimers();
      const box = el('replyBubble');
      box.classList.remove('is-harness-running');
      box.classList.add('is-thinking');
      box.innerHTML = `
        <button type="button" class="siri-close" aria-label="关闭">✕</button>
        ${quoteText ? `<div class="siri-quote">“${esc(quoteText)}”</div>` : ''}
        <div class="siri-thinking">
          <span class="siri-pulse-dot" aria-hidden="true"></span>
          <span>正在感知空间…</span>
        </div>
      `;
      box.hidden = false;
      box.querySelector('.siri-close').onclick = () => { clearTraceTimers(); box.hidden = true; };
    }

    function renderSiriCard(quoteText, res) {
      clearTraceTimers();
      const box = el('replyBubble');
      box.classList.remove('is-thinking', 'is-harness-running');

      const trace = Array.isArray(res.trace) ? res.trace : [];
      const traceHTML = trace.length ? `
        <div class="siri-trace" id="siriTraceBox">
          <button type="button" class="siri-trace-head" id="siriTraceToggle" aria-expanded="true">
            <span class="siri-trace-head-left">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2l2.2 6.8L21 11l-6.8 2.2L12 20l-2.2-6.8L3 11l6.8-2.2z"/></svg>
              <span id="siriTraceLabel">正在协同 (1/${trace.length})</span>
            </span>
            <svg class="siri-trace-chevron" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>
          </button>
          <div class="siri-trace-collapse">
            <div class="siri-trace-list">
              ${trace.map((st, idx) => `
                <div class="siri-step" data-step-idx="${idx}" title="${esc(st.detail || '')}">
                  <span class="siri-step-dot is-${esc(st.kind || 'probe')}"></span>
                  <span class="siri-step-title">${esc(st.title)}</span>
                  <span class="siri-step-detail">${esc(shortStepDetail(st.detail))}</span>
                </div>
              `).join('')}
            </div>
          </div>
        </div>` : '';

      const cardsHTML = (res.cards || []).map(c => {
        const orb = itemOrb({ type: c.type, mode: c.state?.includes('制热') ? '制热' : '制冷' });
        return `
          <div class="siri-platter ${c.on ? 'is-on' : ''}" data-siri-dev="${esc(c.id)}">
            <span class="siri-platter-orb ${orb.cls}">${orb.svg}</span>
            <span class="siri-platter-name">${esc(c.name)}</span>
            <span class="siri-platter-state">${esc(c.state)}</span>
          </div>`;
      }).join('');

      let actionsHTML = '';
      if (res.requires_confirm) {
        actionsHTML = `
          <div class="siri-options">
            <button type="button" class="btn-primary" data-cf="${esc(res.confirm_token)}" style="height:27px;padding:0 12px;font-size:.75rem">确认执行</button>
            <button type="button" class="btn-secondary" data-cf-no style="height:27px;padding:0 11px;font-size:.75rem">取消</button>
          </div>`;
      } else if (res.options?.length) {
        actionsHTML = `
          <div class="siri-options">
            ${res.options.map(o => `<button type="button" class="siri-opt-pill" data-siri-opt="${esc(o.text)}">${esc(o.label)}</button>`).join('')}
          </div>`;
      }

      box.innerHTML = `
        <button type="button" class="siri-close" aria-label="关闭">✕</button>
        ${quoteText ? `<div class="siri-quote">“${esc(quoteText)}”</div>` : ''}
        ${traceHTML}
        <div class="siri-reply">${esc(res.reply || res.explanation)}</div>
        ${cardsHTML ? `<div class="siri-platter-list">${cardsHTML}</div>` : ''}
        ${actionsHTML}
      `;
      box.hidden = false;

      if (trace.length) {
        box.classList.add('is-harness-running');
        const tBox = box.querySelector('#siriTraceBox');
        const tBtn = box.querySelector('#siriTraceToggle');
        const tLbl = box.querySelector('#siriTraceLabel');
        const stepEls = [...box.querySelectorAll('.siri-step')];
        tBtn.onclick = () => {
          const collapsed = tBox.classList.toggle('is-collapsed');
          tBtn.setAttribute('aria-expanded', String(!collapsed));
        };
        stepEls.forEach((row, idx) => {
          row.onclick = () => focusSpatialStep(trace[idx]);
        });
        trace.forEach((st, idx) => {
          const tid = setTimeout(() => {
            stepEls.forEach((r, j) => r.classList.toggle('is-current', j === idx));
            stepEls[idx]?.classList.add('is-visible');
            if (tLbl) tLbl.textContent = idx + 1 < trace.length ? `正在协同 (${idx + 1}/${trace.length})` : `已完成 ${trace.length} 步协同`;
            focusSpatialStep(st);
          }, idx * 210);
          traceTimers.push(tid);
        });
        traceTimers.push(setTimeout(() => {
          stepEls.forEach(r => r.classList.remove('is-current'));
          box.classList.remove('is-harness-running');
        }, trace.length * 210 + 260));
      }

      box.querySelector('.siri-close').onclick = () => { clearTraceTimers(); box.hidden = true; };
      box.querySelectorAll('[data-siri-dev]').forEach(pl => {
        pl.onclick = () => {
          activeDeviceId = pl.dataset.siriDev;
          updateSelectionRing();
          renderDevices();
          repaint();
        };
      });
      box.querySelectorAll('[data-siri-opt]').forEach(btn => {
        btn.onclick = () => submitUtterance(btn.dataset.siriOpt);
      });
      const cfBtn = box.querySelector('[data-cf]');
      if (cfBtn) {
        cfBtn.onclick = async ev => {
          const cRes = await api.butlerConfirm(currentKey, ev.currentTarget.dataset.cf);
          applySnapshot(cRes.snapshot, false);
          renderSiriCard(quoteText, { reply: '好的，已全部执行。', cards: [] });
        };
      }
      const cfNo = box.querySelector('[data-cf-no]');
      if (cfNo) cfNo.onclick = () => { clearTraceTimers(); box.hidden = true; };
    }

    async function submitUtterance(rawText) {
      const text = (rawText || '').trim();
      if (!text && !camAttachment) return;

      // Auto-capture indoor room camera when user asks to visually inspect a room!
      const wantsVisual = ['看看', '看一眼', '你看', '画面', '镜头', '摄像头', '监控'].some(w => text.includes(w))
        && !['哪个房间', '哪间房', '哪盏灯', '最冷', '最热', '最亮', '最暗'].some(w => text.includes(w));
      let snapCam = camAttachment;
      if (!snapCam && wantsVisual) {
        const mentionedRoom = inferRoomFromUtterance(text) || selectedRoom || walkedRoom || 'living';
        snapCam = captureIndoorRoomCamera(mentionedRoom);
      }

      const displayQuote = text || `${snapCam?.label || '室内镜头'}画面分析`;
      el('butlerInput').value = '';
      renderSiriThinking(displayQuote);
      try {
        const res = await api.butlerChat(currentKey, {
          text: text || '看看这个房间光线怎么样',
          camera_frame: snapCam?.dataUrl || null,
          camera_room: snapCam?.room || selectedRoom || null,
          active_room: selectedRoom || walkedRoom || null,
          router_mode: 'auto'
        });
        applySnapshot(res.snapshot, false);
        renderSiriCard(displayQuote, res);
      } catch (err) {
        renderSiriCard(displayQuote, { reply: err.message, cards: [] });
      }
    }

    el('snapViewBtn').onclick = () => {
      if (!el('camStrip').hidden) {
        camAttachment = null;
        el('camStrip').hidden = true;
        return;
      }
      captureIndoorRoomCamera(selectedRoom || walkedRoom || 'living');
      el('butlerInput').focus();
    };

    el('camRoomSwitchBtn').onclick = () => {
      const rooms = (localPlan?.rooms || []).filter(r => !r.restricted);
      const opts = rooms.map(r => ({
        label: `${shortRoomLabel(r)}镜头`,
        checked: !camAttachment?.isUpload && camAttachment?.room === r.id,
        onPick: () => captureIndoorRoomCamera(r.id)
      }));
      opts.push(
        { sep: true },
        { label: '上传本地照片…', onPick: () => el('camUploadInput').click() }
      );
      openMenu(el('camRoomSwitchBtn'), opts);
    };

    el('camUploadInput').onchange = e => {
      const file = e.target.files?.[0];
      e.target.value = '';
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        const rid = selectedRoom || walkedRoom || 'living';
        camAttachment = { dataUrl: String(reader.result), room: rid, label: '实景照片', isUpload: true };
        el('camThumb').src = camAttachment.dataUrl;
        el('camRoomLabel').textContent = '实景照片';
        el('camStrip').hidden = false;
        el('butlerInput').focus();
      };
      reader.readAsDataURL(file);
    };

    el('clearCamBtn').onclick = () => { camAttachment = null; el('camStrip').hidden = true; };

    el('butlerForm').onsubmit = e => {
      e.preventDefault();
      submitUtterance(el('butlerInput').value);
    };

    // Modals Wiring
    document.querySelectorAll('[data-close]').forEach(b => {
      b.onclick = () => { closeMenu(); el(b.dataset.close).close(); };
    });

    el('seasonSeg').onclick = e => {
      const b = e.target.closest('[data-season]');
      if (!b) return;
      el('envForm').elements.season.value = b.dataset.season;
      el('seasonSeg').querySelectorAll('[data-season]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
      syncSlidingPills(el('seasonSeg').parentElement);
    };

    el('envForm').onsubmit = async e => {
      e.preventDefault();
      const f = e.target.elements;
      try {
        const next = await api.environment(currentKey, {
          climate: {
            season: f.season.value,
            indoor: Number(f.indoor.value),
            outdoor: Number(f.indoor.value) + 2,
            humidity: Number(f.humidity.value),
            lux: Number(f.lux.value),
            stale_sim: false
          }
        });
        applySnapshot(next, false);
        el('envModal').close();
        showToast('环境已更新');
      } catch (err) { showToast(err.message, true); }
    };

    el('occMatrix').onclick = async e => {
      const autoBtn = e.target.closest('[data-auto-toggle]');
      if (autoBtn) {
        const rid = autoBtn.dataset.autoToggle;
        const isManual = snapshot?.overrides?.[rid] !== undefined;
        applySnapshot(await api.environment(currentKey, isManual ? { release_override: rid } : { hold_override: rid }), false);
        return;
      }
      const occBtn = e.target.closest('[data-occ]');
      if (occBtn) {
        const rid = occBtn.dataset.occ;
        applySnapshot(await api.environment(currentKey, { room: rid, occupied: !snapshot?.occupied?.[rid] }), false);
      }
      const dndBtn = e.target.closest('[data-dnd]');
      if (dndBtn) {
        applySnapshot(await api.environment(currentKey, { toggle_sleep_room: dndBtn.dataset.dnd }), false);
      }
    };

    el('typeForm').onsubmit = async e => {
      e.preventDefault();
      const f = e.target.elements;
      try {
        const res = await api.registerType({
          code: f.code.value.trim(), name: f.name.value.trim(), w: 46, h: 40,
          capabilities: [
            { key: 'power', label: '电源', kind: 'bool', default: false },
            { key: f.capKey.value.trim(), label: f.capLabel.value.trim(), kind: 'range', min: Number(f.capMin.value), max: Number(f.capMax.value), unit: f.capUnit.value.trim() }
          ]
        });
        types = res.types;
        el('typeModal').close();
        showToast(`已添加 ${f.name.value.trim()}`);
      } catch (err) { el('typeErr').textContent = err.message; }
    };

    function openSceneSheet() {
      el('sceneErr').textContent = '';
      const sm = (localPlan?.items || []).filter(it => Object.keys(types[it.type]?.caps || {}).length > 0);
      if (sm.length) {
        el('sceneDevValue').value = sm[0].id;
        el('sceneDevLabel').textContent = sm[0].name;
      }
      el('sceneModal').showModal();
    }

    el('sceneDevBtn').onclick = () => {
      const sm = (localPlan?.items || []).filter(it => Object.keys(types[it.type]?.caps || {}).length > 0);
      openMenu(el('sceneDevBtn'), sm.map(it => ({
        label: it.name,
        checked: el('sceneDevValue').value === it.id,
        onPick: () => { el('sceneDevValue').value = it.id; el('sceneDevLabel').textContent = it.name; }
      })));
    };

    el('sceneForm').onsubmit = async e => {
      e.preventDefault();
      const f = e.target.elements;
      const dev = localPlan?.items.find(x => x.id === f.deviceId.value);
      const v = f.val.value.trim();
      const actions = [];
      if (dev) {
        if (v === 'true' || v === 'false') actions.push({ deviceId: dev.id, capability: 'power', value: v === 'true' });
        else if (dev.type === 'lamp') actions.push({ deviceId: dev.id, capability: 'power', value: true }, { deviceId: dev.id, capability: 'level', value: Number(v) });
        else if (dev.type === 'ac') actions.push({ deviceId: dev.id, capability: 'power', value: true }, { deviceId: dev.id, capability: 'target', value: Number(v) });
        else if (dev.type === 'curtain') actions.push({ deviceId: dev.id, capability: 'position', value: Number(v) });
      }
      try {
        const res = await api.saveScene(currentKey, { id: f.id.value.trim(), name: f.name.value.trim(), enable_climate: true, actions });
        closeMenu();
        el('sceneModal').close();
        applySnapshot(res.snapshot, false);
        showToast(`已保存「${res.scene.name}」`);
      } catch (err) { el('sceneErr').textContent = err.message; }
    };

    new ResizeObserver(resize).observe(viewport);
    resize();

    api.ready.then(async ok => {
      if (!ok) return;
      types = await api.types();
      const initial = await api.get(currentKey);
      applySnapshot(initial, true);

      // Pre-warm navmesh walker during browser idle time so clicking '进入户型' is instant!
      const idleInit = window.requestIdleCallback || (fn => setTimeout(fn, 450));
      idleInit(() => {
        if (!walker) walker = window.createRoomWalker(T, source, scanHome);
      });

      setInterval(async () => {
        if (document.hidden || busyDevices.size || installingBulb || sliderDrag) return;
        const ae = document.activeElement;
        if (ae && ae.tagName === 'INPUT') return;
        try {
          const v = await api.get(currentKey);
          if (v.seq > (snapshot?.seq ?? 0)) {
            applySnapshot(v, false);
          } else if (
            snapshot &&
            (Object.keys(snapshot.overrides || {}).length ||
             Object.keys(v.overrides || {}).length ||
             Object.keys(snapshot.due || {}).length ||
             Object.keys(v.due || {}).length)
          ) {
            snapshot.overrides = v.overrides;
            snapshot.due = v.due;
            renderTakeoverBar();
            if (el('envModal').open) renderEnvModal();
          }
        } catch {}
      }, 1000);
    }).catch(err => showToast(err.message, true));

  } catch (error) {
    console.warn('Spatial preview error:', error);
    el('fallback').hidden = false;
    el('renderError').hidden = false;
  }
})();
