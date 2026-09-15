/* Shared, local-only graph explorer for the desktop companion and workspace. */
(() => {
  'use strict';
  let sequence = 0;
  const kinds = {topic: '主题', answer: '资料', concept: '概念'};
  const extentLabels = {fulltext: '完整正文', excerpt: '摘要资料', unknown: '完整性未确认'};
  const el = (tag, text, cls) => {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (cls) item.className = cls;
    return item;
  };
  const svg = (tag, attrs = {}, text) => {
    const item = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attrs).forEach(([name, value]) => item.setAttribute(name, String(value)));
    if (text !== undefined) item.textContent = text;
    return item;
  };
  const button = (text, cls, action) => {
    const item = el('button', text, cls); item.type = 'button';
    item.addEventListener('click', action); return item;
  };
  const safeLink = value => {
    try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; }
    catch { return null; }
  };
  const shorten = (text, limit) => Array.from(String(text || '')).slice(0, limit).join('');

  function layout(nodes, edges, focus, compact) {
    const width = compact ? 520 : 1000, height = compact ? 440 : 630;
    const points = new Map();
    nodes.forEach((node, index) => {
      const angle = index * Math.PI * 2 / Math.max(nodes.length - 1, 1);
      points.set(node.id, node.id === focus ? {x: width / 2, y: height / 2} : {
        x: width / 2 + Math.cos(angle) * width * .34,
        y: height / 2 + Math.sin(angle) * height * .34,
      });
    });
    // Deterministic spring layout, bounded by the small diagram preview size.
    for (let step = 0; step < 150; step++) {
      const forces = new Map(nodes.map(node => [node.id, {x: 0, y: 0}]));
      nodes.forEach((a, i) => nodes.slice(i + 1).forEach(b => {
        const p = points.get(a.id), q = points.get(b.id);
        const dx = p.x - q.x || .1, dy = p.y - q.y || .1;
        const distance = Math.max(25, Math.hypot(dx, dy));
        const strength = 8500 / (distance * distance);
        forces.get(a.id).x += dx / distance * strength;
        forces.get(a.id).y += dy / distance * strength;
        forces.get(b.id).x -= dx / distance * strength;
        forces.get(b.id).y -= dy / distance * strength;
        // Keep label cards apart as well as their central points.
        if (Math.abs(dx) < 160 && Math.abs(dy) < 76) {
          forces.get(a.id).y += Math.sign(dy) * 2.8;
          forces.get(b.id).y -= Math.sign(dy) * 2.8;
        }
      }));
      edges.forEach(edge => {
        const p = points.get(edge.source), q = points.get(edge.target);
        if (!p || !q) return;
        const dx = q.x - p.x, dy = q.y - p.y, distance = Math.max(1, Math.hypot(dx, dy));
        const strength = (distance - (compact ? 160 : 210)) * .006;
        forces.get(edge.source).x += dx / distance * strength;
        forces.get(edge.source).y += dy / distance * strength;
        forces.get(edge.target).x -= dx / distance * strength;
        forces.get(edge.target).y -= dy / distance * strength;
      });
      nodes.forEach(node => {
        if (node.id === focus) return;
        const p = points.get(node.id), force = forces.get(node.id);
        p.x = Math.max(82, Math.min(width - 82, p.x + Math.max(-5, Math.min(5, force.x))));
        p.y = Math.max(45, Math.min(height - 45, p.y + Math.max(-5, Math.min(5, force.y))));
      });
    }
    // Resolve label rectangles after the springs settle. Do not clamp the
    // result back into the old bounds: dense graphs must be allowed to grow.
    for (let step = 0; step < 120; step++) {
      let moved = false;
      nodes.forEach((a, i) => nodes.slice(i + 1).forEach(b => {
        const p = points.get(a.id), q = points.get(b.id);
        const dx = p.x - q.x, dy = p.y - q.y;
        const overlapX = 178 - Math.abs(dx), overlapY = 88 - Math.abs(dy);
        if (overlapX <= 0 || overlapY <= 0) return;
        moved = true;
        const axis = overlapX < overlapY ? 'x' : 'y';
        const shift = ((axis === 'x' ? overlapX : overlapY) + 1) * (Math.sign(axis === 'x' ? dx : dy) || 1);
        if (a.id === focus) q[axis] -= shift;
        else if (b.id === focus) p[axis] += shift;
        else { p[axis] += shift / 2; q[axis] -= shift / 2; }
      }));
      if (!moved) break;
    }
    const coordinates = [...points.values()];
    const left = Math.min(...coordinates.map(point => point.x)) - 96;
    const top = Math.min(...coordinates.map(point => point.y)) - 65;
    const right = Math.max(...coordinates.map(point => point.x)) + 96;
    const bottom = Math.max(...coordinates.map(point => point.y)) + 85;
    return {points, bounds: {x: left, y: top, width: Math.max(260, right - left), height: Math.max(180, bottom - top)}};
  }

  function render(root, graph, {compact = false, onOpenSource} = {}) {
    const nodes = graph.nodes || [], edges = graph.edges || [];
    const byId = new Map(nodes.map(node => [node.id, node]));
    const adjacent = new Map(nodes.map(node => [node.id, []]));
    edges.forEach(edge => {
      if (adjacent.has(edge.source) && adjacent.has(edge.target)) {
        adjacent.get(edge.source).push(edge); adjacent.get(edge.target).push(edge);
      }
    });
    const ordered = [...nodes].sort((a, b) => adjacent.get(b.id).length - adjacent.get(a.id).length);
    const state = {selected: ordered[0]?.id, view: 'map', query: '', listLimit: 20, zoom: 1};
    const prefix = 'km-' + (++sequence), cap = compact ? 7 : 18;
    const shell = el('section', undefined, 'knowledge-map' + (compact ? ' km-compact' : ''));
    shell.setAttribute('aria-label', '思维导图探索器'); root.replaceChildren(shell);
    const overview = el('div', undefined, 'km-overview');
    const heading = el('div');
    heading.append(el('span', graph.mode === 'extractive' ? '资料分类图' : '概念关系图', 'km-eyebrow'),
      el('h3', graph.mode === 'extractive' ? '让资料各就其位' : '沿着联系，理解知识'));
    const counts = el('p', `${nodes.length} 个节点 · ${edges.length} 条关系`, 'km-count');
    heading.append(counts);
    const download = button('导出 JSON', 'km-export', () => {
      const blob = new Blob([JSON.stringify(graph, null, 2)], {type: 'application/json;charset=utf-8'});
      const url = URL.createObjectURL(blob), link = el('a');
      link.href = url; link.download = '知境思维导图-' + new Date().toISOString().replace(/[:.]/g, '-') + '.json';
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    overview.append(heading, download); shell.append(overview);
    const scope = el('p', undefined, 'km-scope');
    const included = graph.included_sources;
    scope.textContent = (Number.isInteger(included) ? `本次使用 ${included} / ${graph.total_sources} 篇资料。` : `范围内共 ${graph.total_sources || 0} 篇资料。`)
      + (graph.truncated ? '已达到数量上限，可调整范围后重新生成。' : '');
    const extents = graph.content_extent_counts;
    if (extents && (extents.excerpt || extents.unknown)) scope.append(el('span', ` 其中 ${extents.excerpt || 0} 篇摘要，${extents.unknown || 0} 篇完整性未确认。`));
    shell.append(scope);
    const notice = el('details', undefined, 'km-notice');
    notice.append(el('summary', graph.mode === 'extractive' ? '按资料标签归类，不代表语义推理' : '关系来自资料分析，点开核对依据'));
    notice.append(el('p', [graph.classification, graph.analysis_notice].filter(Boolean).join('\n'))); shell.append(notice);
    if (!nodes.length) {
      const empty = el('div', undefined, 'km-empty');
      empty.append(el('span', '◇', 'km-empty-mark'), el('h3', '知识的联系，从一份资料开始'),
        el('p', '当前范围还没有可展示的节点。导入资料或调整范围后，再生成一次。'));
      shell.append(empty); return;
    }
    const tools = el('div', undefined, 'km-toolbar');
    const searchLabel = el('label', '找一个节点', 'km-search-label'); searchLabel.htmlFor = prefix + '-search';
    const search = el('input', undefined, 'km-search'); search.id = searchLabel.htmlFor; search.type = 'search';
    search.placeholder = '搜索名称或解释…'; search.maxLength = 200;
    searchLabel.append(search);
    const views = el('div', undefined, 'km-views'); views.setAttribute('aria-label', '地图展示方式');
    const mapButton = button('图谱', 'km-view-map', () => { state.view = 'map'; state.query = ''; search.value = ''; updateView(); });
    const listButton = button('列表', 'km-view-list', () => { state.view = 'list'; updateView(); });
    views.append(mapButton, listButton); tools.append(searchLabel, views); shell.append(tools);
    const body = el('div', undefined, 'km-body');
    const explorer = el('div', undefined, 'km-explorer');
    const diagram = el('div', undefined, 'km-diagram');
    const canvas = svg('svg', {class: 'km-canvas', role: 'group', 'aria-label': '知识关系图，点选节点查看关系与依据'});
    const chartTools = el('div', undefined, 'km-chart-tools');
    const zoomLabel = el('span', '100%', 'km-zoom-label');
    const zoomOut = button('−', 'km-zoom-out', () => zoom(.8)); zoomOut.setAttribute('aria-label', '缩小');
    const zoomIn = button('＋', 'km-zoom-in', () => zoom(1.25)); zoomIn.setAttribute('aria-label', '放大');
    const reset = button('适应', 'km-reset', () => { state.zoom = 1; camera = {...base}; updateCamera(); }); reset.setAttribute('aria-label', '适应画布');
    chartTools.append(zoomOut, zoomLabel, zoomIn, reset);
    const diagramStatus = el('p', '', 'km-diagram-status'); diagramStatus.setAttribute('role', 'status');
    diagram.append(canvas, chartTools); explorer.append(diagram, diagramStatus);
    const list = el('div', undefined, 'km-node-list'); explorer.append(list);
    const detail = el('aside', undefined, 'km-detail'); detail.setAttribute('aria-label', '节点与关系详情');
    body.append(explorer, detail); shell.append(body);
    let base = {x: 0, y: 0, width: 1000, height: 630}, camera = {...base}, drag = null;

    function updateCamera() {
      canvas.setAttribute('viewBox', `${camera.x} ${camera.y} ${camera.width} ${camera.height}`);
      zoomLabel.textContent = Math.round(state.zoom * 100) + '%';
      zoomOut.disabled = state.zoom <= .5; zoomIn.disabled = state.zoom >= 3;
    }
    function zoom(factor) {
      const next = Math.max(.5, Math.min(3, state.zoom * factor));
      const width = base.width / next, height = base.height / next;
      camera.x += (camera.width - width) / 2; camera.y += (camera.height - height) / 2;
      camera.width = width; camera.height = height; state.zoom = next; updateCamera();
    }
    canvas.addEventListener('pointerdown', event => {
      if (event.button !== 0 || event.target.closest('.km-node')) return;
      drag = {x: event.clientX, y: event.clientY, camera: {...camera}};
      canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener('pointermove', event => {
      if (!drag) return;
      const rect = canvas.getBoundingClientRect();
      const scale = Math.max(camera.width / rect.width, camera.height / rect.height);
      camera.x = drag.camera.x - (event.clientX - drag.x) * scale;
      camera.y = drag.camera.y - (event.clientY - drag.y) * scale; updateCamera();
    });
    const stopDrag = () => { drag = null; };
    canvas.addEventListener('pointerup', stopDrag); canvas.addEventListener('pointercancel', stopDrag);
    canvas.addEventListener('lostpointercapture', stopDrag);

    function previewNodes() {
      const ids = new Set([state.selected]);
      (adjacent.get(state.selected) || []).forEach(edge => { ids.add(edge.source); ids.add(edge.target); });
      // Focus on actual neighbours first; disconnected nodes stay reachable in the list.
      const related = [...ids].map(id => byId.get(id)).filter(Boolean);
      return related.length > 1 ? related.slice(0, cap) : [byId.get(state.selected)];
    }
    function draw() {
      const preview = previewNodes();
      const ids = new Set(preview.map(node => node.id));
      const visibleEdges = edges.filter(edge => ids.has(edge.source) && ids.has(edge.target));
      const {points, bounds} = layout(preview, visibleEdges, state.selected, compact);
      base = bounds; camera = {...base}; state.zoom = 1;
      canvas.replaceChildren(svg('title', {}, '思维导图'));
      const defs = svg('defs'), marker = svg('marker', {id: prefix + '-arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: 'auto'});
      marker.append(svg('path', {d: 'M 0 0 L 10 5 L 0 10 z', fill: '#9aaac5'})); defs.append(marker); canvas.append(defs);
      visibleEdges.forEach((edge, index) => {
        const a = points.get(edge.source), b = points.get(edge.target);
        const dx = b.x - a.x, dy = b.y - a.y;
        const shortenBy = Math.min(1, 1 / Math.max(Math.abs(dx) / 74, Math.abs(dy) / 31));
        const ax = a.x + dx * shortenBy, ay = a.y + dy * shortenBy;
        const bx = b.x - dx * shortenBy, by = b.y - dy * shortenBy;
        const path = svg('path', {class: 'km-edge', d: `M ${ax} ${ay} L ${bx} ${by}`, 'marker-end': `url(#${prefix}-arrow)`});
        path.append(svg('title', {}, `${byId.get(edge.source).data.label} → ${byId.get(edge.target).data.label}：${edge.label || '相关'}`)); canvas.append(path);
        // Dense diagrams show edge labels on selection in the inspector instead.
        const label = edge.label || '相关';
        if (visibleEdges.length <= 6 && Math.hypot(bx - ax, by - ay) > Array.from(label).length * 13 + 28) {
          canvas.append(svg('text', {x: (ax + bx) / 2, y: (ay + by) / 2 - 7 - (index % 2) * 2, class: 'km-edge-label', 'text-anchor': 'middle'}, label));
        }
      });
      preview.forEach(node => {
        const point = points.get(node.id), active = node.id === state.selected;
        const group = svg('g', {class: 'km-node' + (active ? ' is-selected' : ''), 'data-node-id': node.id,
          'data-kind': node.data.kind, transform: `translate(${point.x - 74},${point.y - 31})`,
          tabindex: 0, role: 'button', 'aria-label': node.data.label, 'aria-pressed': active});
        group.append(svg('rect', {width: 148, height: 62, rx: 15}), svg('title', {}, node.data.label));
        group.append(svg('text', {x: 13, y: 20, class: 'km-node-kind'}, kinds[node.data.kind] || '节点'));
        const label = Array.from(node.data.label || '');
        group.append(svg('text', {x: 13, y: 44, class: 'km-node-label'}, label.slice(0, 8).join('') + (label.length > 8 ? '…' : '')));
        group.addEventListener('click', () => choose(node.id));
        group.addEventListener('keydown', event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); choose(node.id, true); } });
        canvas.append(group);
      });
      const neighbourCount = new Set((adjacent.get(state.selected) || []).flatMap(edge => [edge.source, edge.target])).size;
      diagramStatus.textContent = `聚焦「${byId.get(state.selected).data.label}」 · 图示 ${preview.length} / ${nodes.length} 个节点。`
        + (neighbourCount > cap ? '部分相邻节点未绘出，可在关系列表继续探索。' : '其他节点可通过搜索或列表查看。')
        + ' 拖动画布移动，＋／− 缩放。';
      updateCamera();
    }
    async function openSource(sourceId, control) {
      if (!onOpenSource || control.disabled) return;
      control.disabled = true;
      try { await onOpenSource(sourceId); }
      catch { const message = el('p', '暂时无法打开这份资料，请稍后重试。', 'km-error'); message.setAttribute('role', 'alert'); detail.append(message); }
      finally { control.disabled = false; }
    }
    function citations(parent, items, heading = '原文依据') {
      if (!items?.length) return;
      const box = el('div', undefined, 'km-evidence'); box.append(el('h4', `${heading} · ${items.length} 处`));
      items.forEach(item => {
        const entry = el('details', undefined, 'km-citation');
        entry.append(el('summary', item.title || '原文片段'), el('blockquote', item.excerpt || ''));
        const links = el('div', undefined, 'km-citation-links');
        if (item.source_id && onOpenSource) {
          const open = button('在资料中查看', 'km-open-source', () => openSource(item.source_id, open)); links.append(open);
        }
        const href = safeLink(item.url);
        if (href) { const link = el('a', '访问原始链接'); link.href = href; link.target = '_blank'; link.rel = 'noopener noreferrer'; links.append(link); }
        entry.append(links); box.append(entry);
      }); parent.append(box);
    }
    function relationDetail(edge) {
      detail.replaceChildren(button('← 返回节点', 'km-back', showNode));
      const source = byId.get(edge.source), target = byId.get(edge.target);
      detail.append(el('span', edge.label || '相关', 'km-eyebrow'), el('h3', source.data.label + ' → ' + target.data.label),
        el('p', edge.data?.explanation || '这条连线来自导入资料的主题标签，表示归类，不表示因果、支持或反驳。', 'km-description'));
      const targets = el('div', undefined, 'km-relation-targets');
      [source, target].forEach(node => targets.append(button('查看 ' + node.data.label, 'km-neighbour', () => choose(node.id)))); detail.append(targets);
      citations(detail, edge.data?.evidence);
      if (!edge.data?.evidence?.length && target.data.kind === 'answer') citations(detail, target.data.evidence, '资料正文节选（归类依据为导入标签）');
    }
    function showNode() {
      const node = byId.get(state.selected); detail.replaceChildren();
      detail.append(el('span', kinds[node.data.kind] || '节点', 'km-eyebrow'), el('h3', node.data.label));
      if (node.data.content_extent) detail.append(el('span', extentLabels[node.data.content_extent] || '完整性未确认', 'km-extent'));
      detail.append(el('p', node.data.description || (node.data.kind === 'topic' ? '来自导入资料的主题标签。展开关联资料，查看这个主题下的内容。' : '来自已导入的资料，可结合原文继续阅读。'), 'km-description'));
      if (node.data.source_id && onOpenSource) {
        const open = button('打开这篇资料', 'km-open-source', () => openSource(node.data.source_id, open)); detail.append(open);
      }
      const relationships = adjacent.get(node.id) || [];
      detail.append(el('h4', `相邻关系 · ${relationships.length}`));
      const relations = el('div', undefined, 'km-relations');
      relationships.forEach(edge => {
        const outgoing = edge.source === node.id, other = byId.get(outgoing ? edge.target : edge.source);
        const row = el('div', undefined, 'km-relation-row');
        const inspect = button((outgoing ? '→ ' : '← ') + (edge.label || '相关') + ' · ' + other.data.label, 'km-relation', () => relationDetail(edge));
        inspect.title = outgoing ? `${node.data.label} → ${other.data.label}` : `${other.data.label} → ${node.data.label}`;
        const jump = button('聚焦', 'km-neighbour', () => choose(other.id)); jump.setAttribute('aria-label', '聚焦 ' + other.data.label);
        row.append(inspect, jump); relations.append(row);
      });
      if (!relationships.length) relations.append(el('p', '当前没有与这个节点相连的关系。可搜索或切换列表探索其他节点。', 'km-muted'));
      detail.append(relations); citations(detail, node.data.evidence, node.data.kind === 'answer' ? '资料正文节选' : '原文依据');
    }
    function drawList() {
      const query = state.query.toLocaleLowerCase();
      const matches = nodes.filter(node => `${node.data.label}\n${node.data.description || ''}`.toLocaleLowerCase().includes(query));
      list.replaceChildren(el('p', query ? `找到 ${matches.length} 个节点` : `全部 ${nodes.length} 个节点`, 'km-list-count'));
      matches.slice(0, state.listLimit).forEach(node => {
        const item = button('', 'km-node-item', () => choose(node.id)); item.dataset.nodeId = node.id;
        item.setAttribute('aria-label', node.data.label);
        item.append(el('span', kinds[node.data.kind] || '节点', 'km-kind-pill'), el('span', node.data.label, 'km-item-label'), el('small', `${adjacent.get(node.id).length} 条关系`));
        list.append(item);
      });
      if (!matches.length) list.append(el('p', '没有匹配的节点，换一个关键词试试。', 'km-empty-search'));
      if (matches.length > state.listLimit) list.append(button(`再显示 ${Math.min(20, matches.length - state.listLimit)} 个`, 'km-load-more', () => { state.listLimit += 20; drawList(); }));
    }
    function updateView() {
      const listVisible = state.view === 'list' || !!state.query;
      diagram.hidden = diagramStatus.hidden = listVisible; list.hidden = !listVisible;
      mapButton.setAttribute('aria-pressed', !listVisible); listButton.setAttribute('aria-pressed', listVisible);
      if (listVisible) drawList();
    }
    function choose(id, keyboard = false) {
      state.selected = id; state.query = ''; search.value = ''; state.view = 'map';
      draw(); showNode(); updateView();
      if (keyboard) [...canvas.querySelectorAll('.km-node')].find(node => node.getAttribute('data-node-id') === id)?.focus();
    }
    search.addEventListener('input', () => { state.query = search.value.trim(); state.listLimit = 20; updateView(); });
    draw(); showNode(); updateView();
  }
  window.ZhijingKnowledgeMap = {render};
})();
