/* PNG fitting only. Avatar/reference layers never enter the exported image. */
(() => {
  'use strict';
  const root = document.getElementById('gear-studio');
  if (!root) return;
  const el = id => document.getElementById('studio-' + id);
  const canvas = el('canvas'), ctx = canvas.getContext('2d');
  const slots = ['head', 'chest', 'boots', 'main_hand', 'off_hand'];
  const attrs = ['x', 'y', 'width', 'rotation'];
  const state = {catalog: null, source: null, transform: null, revision: '', dirty: false,
    context: {slot: 'face', variant: 'm', target: 'new', layer: 'front'},
    refs: {}, face: '', undo: [], redo: [], loading: true, saving: false};
  const images = new Map();
  let loadVersion = 0, gesture = null;
  const copy = value => value ? {...value} : null;

  function message(text, kind = '') {
    el('status').textContent = text;
    el('status').className = 'studio-status' + (kind ? ' is-' + kind : '');
  }
  async function json(url, options) {
    const response = await fetch(url, {credentials: 'same-origin', ...options});
    const type = response.headers.get('content-type') || '';
    if (!type.includes('application/json')) throw new Error('Your session may have expired. Reload and sign in again.');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'The request could not be completed.');
    return data;
  }
  function option(select, value, label) {
    const node = document.createElement('option');
    node.value = value; node.textContent = label; select.append(node);
  }
  function image(url) {
    if (!url) return null;
    if (!images.has(url)) {
      const node = new Image();
      images.set(url, node);
      node.onload = draw;
      node.onerror = () => message('A reference image could not load. Reload to refresh your gear library.', 'error');
      node.src = url;
    }
    const node = images.get(url);
    return node.complete && node.naturalWidth ? node : null;
  }
  function contextFromControls() {
    return {slot: el('slot').value, variant: el('variant').value,
      target: el('target').value, layer: el('layer').value};
  }
  function restoreControls() {
    for (const key of ['slot', 'variant', 'target', 'layer']) el(key).value = state.context[key];
  }
  function targets(preferred = 'new') {
    const slot = el('slot').value, variant = el('variant').value;
    el('target').replaceChildren();
    option(el('target'), 'new', 'Create new ' + (slot === 'face' ? 'face' : 'gear item'));
    if (slot === 'face') {
      for (const face of state.catalog.faces[variant]) {
        if (face.asset_id) option(el('target'), String(face.asset_id), face.name);
      }
    } else {
      for (const item of state.catalog.items.filter(item => item.slot === slot)) {
        option(el('target'), item.id, item.name + (item.active ? '' : ' (inactive)'));
      }
    }
    el('target').value = [...el('target').options].some(o => o.value === preferred) ? preferred : 'new';
  }
  function layerOptions(preferred = 'front') {
    const slot = el('slot').value;
    el('layer').replaceChildren();
    for (const layer of Object.keys(state.catalog.layer_names[slot])) {
      option(el('layer'), layer, {front: 'Front', back: 'Behind the head', underlay: 'Behind the body'}[layer]);
    }
    el('layer').value = [...el('layer').options].some(o => o.value === preferred) ? preferred : 'front';
    el('layer-field').hidden = el('layer').options.length < 2;
  }
  function referenceControls() {
    const {slot, variant, target} = state.context;
    el('references').replaceChildren();
    const add = (key, label, values, chosen, disabled = false) => {
      const group = document.createElement('div'); group.className = 'studio-reference';
      const title = document.createElement('label'); title.textContent = label; title.htmlFor = 'studio-ref-' + key;
      const row = document.createElement('div'); row.className = 'studio-reference-control';
      const select = document.createElement('select'); select.id = title.htmlFor;
      option(select, '', 'None');
      for (const value of values) option(select, value.id, value.name);
      select.value = [...select.options].some(o => o.value === chosen) ? chosen : '';
      if (key === 'face') state.face = select.value; else state.refs[key] = select.value;
      select.disabled = disabled;
      const step = direction => {
        select.selectedIndex = (select.selectedIndex + direction + select.options.length) % select.options.length;
        select.dispatchEvent(new Event('change'));
      };
      for (const direction of [-1, 1]) {
        const button = document.createElement('button'); button.type = 'button';
        button.textContent = direction < 0 ? '‹' : '›';
        button.setAttribute('aria-label', (direction < 0 ? 'Previous ' : 'Next ') + label.toLowerCase());
        button.disabled = disabled; button.addEventListener('click', () => step(direction));
        row.append(button); if (direction === -1) row.append(select);
      }
      select.addEventListener('change', () => {
        if (key === 'face') state.face = select.value; else state.refs[key] = select.value;
        draw();
      });
      group.append(title, row);
      if (disabled) {
        const hint = document.createElement('p'); hint.className = 'studio-reference-note';
        hint.textContent = 'The imported image replaces this element; other layers of the item remain visible.';
        group.append(hint);
      }
      el('references').append(group);
    };
    if (slot !== 'face') {
      const faces = state.catalog.faces[variant];
      add('face', 'Face', faces.map(f => ({id: f.key, name: f.name})),
        faces.some(f => f.key === state.face) ? state.face : (faces[0]?.key || ''));
    }
    for (const key of slots) {
      const editing = slot === key;
      const values = state.catalog.items.filter(item => item.slot === key &&
        (Object.keys(item.layers[variant]).length || (editing && item.id === target)));
      add(key, state.catalog.slots[key], values, editing ? (target === 'new' ? '' : target) : (state.refs[key] || ''), editing);
    }
  }
  function maxWidth() {
    if (!state.source) return 4400;
    const ratio = state.source.width / state.source.height;
    return Math.max(1, Math.floor(Math.min(4400, 4800 * ratio, Math.sqrt(8000000 * ratio))));
  }
  function updateControls() {
    const has = !!state.source && !state.loading && !state.saving;
    for (const id of ['size', 'fit', 'original', ...attrs]) el(id).disabled = !has;
    el('save').disabled = !has;
    el('file').disabled = state.loading || state.saving;
    el('name').disabled = state.loading || state.saving;
    el('price').disabled = state.loading || state.saving;
    for (const id of ['slot', 'variant', 'target', 'layer']) el(id).disabled = state.loading || state.saving;
    el('undo').disabled = !has || !state.undo.length;
    el('redo').disabled = !has || !state.redo.length;
    const isFace = state.context.slot === 'face', isNew = state.context.target === 'new';
    el('name').readOnly = !isFace && !isNew;
    el('name').maxLength = isFace ? 128 : 80;
    el('price-field').hidden = isFace || !isNew;
    el('save').textContent = state.saving ? 'Saving…' : isNew ? ('Add ' + (isFace ? 'face' : 'gear') + ' to game') : 'Save changes';
    el('save-hint').textContent = isFace ? 'A saved face appears in character selection automatically.' :
      'A new item appears in Gear Catalog and the Blacksmith. Existing prices and bonuses stay as they are.';
    if (state.transform) {
      for (const key of attrs) if (document.activeElement !== el(key)) el(key).value = Math.round(state.transform[key] * 10) / 10;
      el('size').max = maxWidth(); el('size').value = state.transform.width;
      el('size-label').value = Math.round(state.transform.width) + ' px';
    } else {
      for (const key of attrs) el(key).value = '';
      el('size-label').value = '—';
    }
  }
  function layerMap() {
    const {slot, variant, target} = state.context;
    const map = {...state.catalog.base[variant]};
    const selectedFace = slot === 'face' && target !== 'new' ?
      state.catalog.faces[variant].find(f => String(f.asset_id) === target) :
      state.catalog.faces[variant].find(f => f.key === state.face);
    if (selectedFace) map.face = selectedFace.image;
    else if (slot !== 'face' && !state.face) delete map.face;
    if (el('show-gear').checked) {
      for (const key of slots) {
        const item = state.catalog.items.find(item => item.id === state.refs[key]);
        if (item) Object.assign(map, item.layers[variant]);
      }
    }
    const edited = state.catalog.layer_names[slot][state.context.layer];
    const show = state.source && el('show-art').checked;
    if (map.boots || (show && edited === 'boots')) delete map['body-lower'];
    if (map['off-hand'] || (show && edited === 'off-hand')) delete map['off-hand-base'];
    return map;
  }
  function drawArtwork() {
    const t = state.transform, h = t.width * state.source.height / state.source.width;
    ctx.save(); ctx.translate(t.x + t.width / 2, t.y + h / 2); ctx.rotate(t.rotation * Math.PI / 180);
    ctx.globalAlpha = Number(el('opacity').value) / 100;
    ctx.drawImage(state.source, -t.width / 2, -h / 2, t.width, h); ctx.restore();
  }
  function corners() {
    const t = state.transform, h = t.width * state.source.height / state.source.width;
    const cx = t.x + t.width / 2, cy = t.y + h / 2, angle = t.rotation * Math.PI / 180;
    return [[-1,-1],[1,-1],[1,1],[-1,1]].map(([x,y]) => {
      const dx = x * t.width / 2, dy = y * h / 2;
      return [cx + dx * Math.cos(angle) - dy * Math.sin(angle), cy + dx * Math.sin(angle) + dy * Math.cos(angle)];
    });
  }
  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!state.catalog) return;
    const layers = layerMap(), imported = state.source && el('show-art').checked;
    const edited = state.catalog.layer_names[state.context.slot][state.context.layer];
    for (const label of state.catalog.order) {
      if (imported && label === edited) drawArtwork();
      else if (layers[label]) {
        const loaded = image(layers[label]);
        if (loaded) ctx.drawImage(loaded, 0, 0, canvas.width, canvas.height);
      }
    }
    const unit = canvas.width / (canvas.clientWidth || canvas.width);
    if (el('grid').checked) {
      ctx.save(); ctx.strokeStyle = '#32738260'; ctx.lineWidth = unit;
      for (let x = 100; x < canvas.width; x += 100) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,canvas.height); ctx.stroke(); }
      for (let y = 100; y < canvas.height; y += 100) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(canvas.width,y); ctx.stroke(); }
      ctx.restore();
    }
    if (imported) {
      const points = corners(); ctx.save(); ctx.strokeStyle = '#227e93'; ctx.lineWidth = 1.5 * unit;
      ctx.setLineDash([5 * unit, 4 * unit]); ctx.beginPath(); ctx.moveTo(...points[0]);
      for (const point of points.slice(1)) ctx.lineTo(...point);
      ctx.closePath(); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = '#fff'; ctx.fillRect(points[2][0] - 6 * unit, points[2][1] - 6 * unit, 12 * unit, 12 * unit);
      ctx.strokeRect(points[2][0] - 6 * unit, points[2][1] - 6 * unit, 12 * unit, 12 * unit); ctx.restore();
    }
  }
  function checkpoint(before) {
    if (!before || JSON.stringify(before) === JSON.stringify(state.transform)) return;
    state.undo.push(before); if (state.undo.length > 60) state.undo.shift();
    state.redo = []; state.dirty = true; updateControls();
  }
  function apply(values) {
    if (!state.source) return;
    state.transform = {...state.transform, ...values};
    for (const key of ['x','y']) state.transform[key] = Math.max(-4400, Math.min(4400, state.transform[key]));
    state.transform.width = Math.max(1, Math.min(maxWidth(), state.transform.width));
    state.transform.rotation = Math.max(-180, Math.min(180, state.transform.rotation));
    updateControls(); draw();
  }
  function fit() {
    const anchors = {face:[613,190,205],head:[600,170,420],chest:[630,560,570],
      boots:[550,1030,570],main_hand:[300,750,390],off_hand:[810,740,370]};
    const [cx,cy,width] = anchors[state.context.slot];
    const height = width * state.source.height / state.source.width;
    apply({x:cx-width/2,y:cy-height/2,width,rotation:0});
  }
  async function croppedSource(url) {
    const node = new Image();
    await new Promise((resolve,reject) => { node.onload=resolve; node.onerror=() => reject(new Error('This image could not be opened. Choose a valid PNG.')); node.src=url; });
    const w=node.naturalWidth,h=node.naturalHeight;
    if (w>10000 || h>10000 || w*h>40000000) throw new Error('Use a PNG up to 40 megapixels and 10,000 pixels per side.');
    const raw=document.createElement('canvas'); raw.width=w; raw.height=h;
    const rawCtx=raw.getContext('2d',{willReadFrequently:true}); rawCtx.drawImage(node,0,0);
    const pixels=rawCtx.getImageData(0,0,w,h).data;
    let left=w,top=h,right=-1,bottom=-1;
    for (let y=0;y<h;y++) for (let x=0;x<w;x++) if (pixels[(y*w+x)*4+3]) {
      left=Math.min(left,x);top=Math.min(top,y);right=Math.max(right,x);bottom=Math.max(bottom,y);
    }
    if (right<0) throw new Error('This PNG is completely transparent. Choose visible artwork.');
    const cropped=document.createElement('canvas'); cropped.width=right-left+1;cropped.height=bottom-top+1;
    cropped.getContext('2d').drawImage(raw,left,top,cropped.width,cropped.height,0,0,cropped.width,cropped.height);
    return {canvas:cropped,bounds:{x:left,y:top,width:cropped.width,rotation:0},aligned:w===1100 && h===1200};
  }
  async function openContext() {
    const version=++loadVersion; state.loading=true;state.source=null;state.transform=null;
    state.revision='';state.undo=[];state.redo=[];state.dirty=false;
    state.context=contextFromControls(); referenceControls(); updateControls();draw();
    const {slot,target,variant,layer}=state.context;
    el('name').value=target==='new' ? '' : slot==='face' ?
      state.catalog.faces[variant].find(f=>String(f.asset_id)===target)?.name || '' :
      state.catalog.items.find(item=>item.id===target)?.name || '';
    try {
      if (target!=='new') {
        const editor=await json(root.dataset.editor+'?'+new URLSearchParams({slot,target,variant,layer}));
        if (version!==loadVersion) return;
        state.revision=editor.revision;
        const label=state.catalog.layer_names[slot][layer];
        const packaged=slot==='face' ? state.catalog.faces[variant].find(f=>String(f.asset_id)===target)?.image :
          state.catalog.items.find(item=>item.id===target)?.layers[variant][label];
        const url=editor.source_url || packaged;
        if (url) {
          const loaded=await croppedSource(url);
          if (version!==loadVersion) return;
          state.source=loaded.canvas;state.transform=editor.transform || loaded.bounds;
        }
      }
      message(state.source ? 'Ready to adjust. Try other gear on the right to check alignment.' : 'Choose a PNG to start.');
    } catch(error) { message(error.message,'error'); }
    finally { if(version===loadVersion) { state.loading=false;updateControls();draw(); } }
  }
  async function changeContext(kind) {
    if (state.dirty && !window.confirm('Discard unsaved artwork changes and open another element?')) { restoreControls();return; }
    const previous=state.context;
    if (kind==='slot') { targets();layerOptions(); }
    else if (kind==='variant') { targets(previous.slot==='face' ? 'new' : previous.target); }
    await openContext();
  }
  async function importFile(file) {
    if (!file || state.loading || state.saving) return;
    if (!file.name.toLowerCase().endsWith('.png') || file.size>16*1024*1024) { message('Choose a PNG file up to 16 MiB.','error');return; }
    state.loading=true;updateControls();const url=URL.createObjectURL(file);
    try {
      const loaded=await croppedSource(url);
      state.source=loaded.canvas;state.transform={x:0,y:0,width:loaded.canvas.width,rotation:0};
      if (loaded.aligned) apply(loaded.bounds); else fit();
      state.undo=[];state.redo=[];state.dirty=true;
      if (!el('name').value) el('name').value=file.name.replace(/\.png$/i,'').slice(0,el('name').maxLength);
      message('PNG imported. Drag to move, use the corner to resize, and try reference gear.');
    } catch(error) { message(error.message,'error'); }
    finally { URL.revokeObjectURL(url);state.loading=false;updateControls();draw(); }
  }
  async function save() {
    if (!state.source || state.loading || state.saving) return;
    if (!el('name').value.trim()) { el('name').focus();message('Give the face or item a name before saving.','error');return; }
    state.saving=true;updateControls();message('Saving your artwork…');
    try {
      const blob=await new Promise(resolve=>state.source.toBlob(resolve,'image/png'));
      if (!blob) throw new Error('The image could not be prepared. Please import it again.');
      const data=new FormData();data.append('image',blob,'source.png');data.append('csrf_token',el('csrf').value);
      data.append('metadata',JSON.stringify({...state.context,name:el('name').value,price:el('price').value,
        transform:state.transform,revision:state.revision}));
      const result=await json(root.dataset.save,{method:'POST',body:data});
      state.revision=result.revision;state.context.target=result.target;state.dirty=false;
      state.catalog=await json(root.dataset.catalog);
      targets(result.target);referenceControls();message(result.message,'success');
    } catch(error) { message(error.message,'error'); }
    finally { state.saving=false;updateControls();draw(); }
  }
  for (const kind of ['slot','variant','target','layer']) el(kind).addEventListener('change',()=>changeContext(kind));
  el('file').addEventListener('change',()=>importFile(el('file').files[0]));
  for (const name of ['dragenter','dragover']) el('drop-zone').addEventListener(name,e=>{e.preventDefault();el('drop-zone').classList.add('is-over');});
  for (const name of ['dragleave','drop']) el('drop-zone').addEventListener(name,e=>{e.preventDefault();el('drop-zone').classList.remove('is-over');});
  el('drop-zone').addEventListener('drop',e=>importFile(e.dataTransfer.files[0]));
  el('fit').addEventListener('click',()=>{const before=copy(state.transform);fit();checkpoint(before);});
  el('original').addEventListener('click',()=>{const before=copy(state.transform);apply({width:state.source.width});checkpoint(before);});
  const numberBefore=new Map();
  for (const attr of attrs) {
    el(attr).addEventListener('focus',()=>numberBefore.set(attr,copy(state.transform)));
    el(attr).addEventListener('input',()=>{
      const value=el(attr).valueAsNumber;if(!Number.isFinite(value)) return;
      if(!numberBefore.has(attr)) numberBefore.set(attr,copy(state.transform));
      apply({[attr]:value});state.dirty=true;
    });
    el(attr).addEventListener('change',()=>{checkpoint(numberBefore.get(attr));numberBefore.delete(attr);});
    el(attr).addEventListener('blur',()=>{
      checkpoint(numberBefore.get(attr));numberBefore.delete(attr);
      el(attr).value=state.transform ? Math.round(state.transform[attr]*10)/10 : '';
    });
  }
  let sizeBefore=null;
  el('size').addEventListener('input',()=>{if(!sizeBefore) sizeBefore=copy(state.transform);apply({width:Number(el('size').value)});state.dirty=true;});
  el('size').addEventListener('change',()=>{checkpoint(sizeBefore);sizeBefore=null;});
  for (const name of ['undo','redo']) el(name).addEventListener('click',()=>{
    const from=state[name],to=state[name==='undo'?'redo':'undo'];
    if(!from.length) return;to.push(copy(state.transform));state.transform=from.pop();state.dirty=true;updateControls();draw();
  });
  el('save').addEventListener('click',save);
  el('name').addEventListener('input',()=>{if(state.source) state.dirty=true;});
  el('price').addEventListener('input',()=>{if(state.source) state.dirty=true;});
  el('background').addEventListener('change',()=>{el('stage').className='studio-stage is-'+el('background').value;});
  for(const id of ['show-art','show-gear','grid','opacity']) el(id).addEventListener('input',draw);
  el('clear-gear').addEventListener('click',()=>{state.refs={};referenceControls();draw();});
  const point=e=>{const box=canvas.getBoundingClientRect();return {x:(e.clientX-box.left)*canvas.width/box.width,y:(e.clientY-box.top)*canvas.height/box.height};};
  canvas.addEventListener('pointerdown',e=>{
    if(!state.source || state.loading || state.saving || !el('show-art').checked) return;
    e.preventDefault();canvas.focus();canvas.setPointerCapture(e.pointerId);
    const p=point(e),corner=corners()[2],unit=canvas.width/canvas.clientWidth;
    const h=state.transform.width*state.source.height/state.source.width;
    const center={x:state.transform.x+state.transform.width/2,y:state.transform.y+h/2};
    gesture={start:p,before:copy(state.transform),center,
      mode:Math.hypot(p.x-corner[0],p.y-corner[1])<22*unit?'scale':'move',
      distance:Math.max(1,Math.hypot(p.x-center.x,p.y-center.y))};
  });
  canvas.addEventListener('pointermove',e=>{
    if(!gesture) return;const p=point(e),g=gesture;
    if(g.mode==='move') apply({x:g.before.x+p.x-g.start.x,y:g.before.y+p.y-g.start.y});
    else {
      const width=Math.max(1,Math.min(maxWidth(),g.before.width*Math.hypot(p.x-g.center.x,p.y-g.center.y)/g.distance));
      apply({width,x:g.center.x-width/2,y:g.center.y-width*state.source.height/state.source.width/2});
    }
    state.dirty=true;
  });
  const finish=()=>{if(gesture) {const before=gesture.before;gesture=null;checkpoint(before);}};
  canvas.addEventListener('pointerup',finish);canvas.addEventListener('pointercancel',finish);canvas.addEventListener('lostpointercapture',finish);
  canvas.addEventListener('keydown',e=>{
    if(!state.source || state.loading || state.saving) return;
    const moves={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
    if(!moves[e.key]) return;e.preventDefault();const before=copy(state.transform),step=e.shiftKey?10:1;
    apply({x:state.transform.x+moves[e.key][0]*step,y:state.transform.y+moves[e.key][1]*step});checkpoint(before);
  });
  window.addEventListener('beforeunload',e=>{if(state.dirty) {e.preventDefault();e.returnValue='';}});
  new ResizeObserver(draw).observe(canvas);
  updateControls();
  (async()=>{
    try {state.catalog=await json(root.dataset.catalog);targets();layerOptions();await openContext();}
    catch(error) {message(error.message,'error');}
  })();
})();
