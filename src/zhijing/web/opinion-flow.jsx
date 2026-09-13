import React, {useEffect, useMemo, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Background, BaseEdge, Controls, Handle, MiniMap, Position, ReactFlow, ReactFlowProvider, useReactFlow} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './opinion-flow-source.css';

function OpinionNode({data}) {
  return <div className={'of-node of-node-' + data.kind}>
    <Handle type="target" position={Position.Top} isConnectable={false}/>
    <span className="of-node-kicker">{data.kicker}</span>
    <strong>{data.label}</strong>
    {data.subtitle && <span className="of-node-subtitle">{data.subtitle}</span>}
    <Handle type="source" position={Position.Bottom} isConnectable={false}/>
  </div>;
}
const nodeTypes = {opinion: OpinionNode};
function OverviewEdge({id, sourceX, sourceY, targetX, targetY, style}) {
  // Route sibling branches alongside the stacked cards, never through another viewpoint.
  const side = targetX - 122;
  const path = `M ${sourceX} ${sourceY} L ${sourceX} ${sourceY + 14} L ${side} ${sourceY + 14} L ${side} ${targetY - 16} L ${targetX} ${targetY - 16} L ${targetX} ${targetY}`;
  return <BaseEdge id={id} path={path} style={style}/>;
}
const edgeTypes = {overview: OverviewEdge};
const authorExtent = value => ({excerpt: '摘录', fulltext: '标记为全文', unknown: '完整性未确认'}[value] || '完整性未确认');

function Map({result, compact, onSelectGroup}) {
  const [groupIndex, setGroupIndex] = useState(-1);
  const [page, setPage] = useState(0);
  const flow = useReactFlow();
  const group = result.groups[groupIndex];
  const overview = groupIndex === -1;
  const pageSize = overview ? (compact ? 2 : 6) : (compact ? 1 : 3);
  const positions = group?.positions || [];
  const items = overview ? result.groups : positions;
  const visible = items.slice(page * pageSize, (page + 1) * pageSize);
  const columns = compact ? 1 : Math.min(3, Math.max(1, visible.length));
  const diagram = useMemo(() => {
    const center = compact ? 0 : (columns - 1) * 126;
    const nodes = [{id: 'question', type: 'opinion', position: {x: center, y: 0},
      data: {kind: 'question', kicker: '问题', label: result.question, subtitle: result.included_sources + ' 篇所选回答'},
      ariaLabel: '问题：' + result.question}];
    const edges = [];
    if (overview) {
      visible.forEach((viewpoint, index) => {
        const absoluteIndex = page * pageSize + index, id = 'overview-' + absoluteIndex;
        nodes.push({id, type: 'opinion', position: {x: compact ? 0 : (index % columns) * 252, y: 146 + Math.floor(index / columns) * 142},
          data: {kind: 'group', kicker: '观点 ' + (absoluteIndex + 1), label: viewpoint.label,
            subtitle: viewpoint.answer_count + ' 篇回答 · 点击展开作者'},
          ariaLabel: '观点：' + viewpoint.label + '，' + viewpoint.answer_count + ' 篇回答，点击展开作者'});
        edges.push({id: 'question-' + id, source: 'question', target: id, type: 'overview'});
      });
    } else if (group) {
      nodes.push({id: 'group', type: 'opinion', position: {x: center, y: 146},
        data: {kind: 'group', kicker: '观点 ' + (groupIndex + 1) + ' / ' + result.groups.length, label: group.label,
          subtitle: group.answer_count + ' 篇回答 · 点击查看归类依据'}, ariaLabel: '观点：' + group.label});
      edges.push({id: 'question-group', source: 'question', target: 'group', type: 'smoothstep'});
      visible.forEach((position, index) => {
        const id = 'answer-' + index;
        nodes.push({id, type: 'opinion', position: {x: compact ? 0 : (index % columns) * 252, y: 300 + Math.floor(index / columns) * 142},
          data: {kind: 'author', kicker: position.author_name || '未署名', label: position.summary,
            subtitle: authorExtent(position.content_extent) + ' · 点击查看原文'},
          ariaLabel: (position.author_name || '未署名') + '的回答：' + position.summary});
        edges.push({id: 'group-' + id, source: 'group', target: id, type: 'smoothstep'});
      });
    }
    return {nodes, edges};
  }, [result, groupIndex, page, compact]);
  useEffect(() => {
    const frame = requestAnimationFrame(() => flow.fitView({padding: 0.07, maxZoom: 1, duration: 0}));
    return () => cancelAnimationFrame(frame);
  }, [diagram, flow]);
  function choose(index) {
    setGroupIndex(index); setPage(0);
    if (index >= 0) onSelectGroup?.(result.groups[index]?.id);
  }
  const [detail, setDetail] = useState(null);
  useEffect(() => setDetail(null), [groupIndex, page]);
  function activateNode(id) {
    if (id.startsWith('overview-')) choose(Number(id.slice(9)));
    else if (id === 'group') { setDetail(null); onSelectGroup?.(group.id, true); }
    else if (id.startsWith('answer-')) setDetail(visible[Number(id.slice(7))]);
  }
  return <div className={'opinion-flow' + (compact ? ' opinion-flow-compact' : '')}>
    <div className="of-toolbar">
      <label>查看观点<select aria-label="切换知识地图观点" value={groupIndex} onChange={event => choose(Number(event.target.value))}>
        <option value={-1}>全部观点（{result.groups.length} 类）</option>
        {result.groups.map((item, index) => <option key={item.id} value={index}>{index + 1}. {item.label}（{item.answer_count} 篇）</option>)}
      </select></label>
      {!overview && <button type="button" onClick={() => choose(-1)}>全部观点</button>}
      <span>{items.length ? page * pageSize + 1 : 0}–{Math.min((page + 1) * pageSize, items.length)} / {items.length} {overview ? '类观点' : '篇回答'}</span>
      <button type="button" aria-label={overview ? '上一组观点' : '上一组作者回答'} disabled={!page} onClick={() => setPage(page - 1)}>←</button>
      <button type="button" aria-label={overview ? '下一组观点' : '下一组作者回答'} disabled={(page + 1) * pageSize >= items.length} onClick={() => setPage(page + 1)}>→</button>
    </div>
    <div className="of-canvas" role="region" aria-label="问题、观点与作者回答关系图">
      <ReactFlow nodes={diagram.nodes} edges={diagram.edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} nodesDraggable={false} nodesConnectable={false}
        elementsSelectable minZoom={0.2} maxZoom={1.5} fitView fitViewOptions={{padding: 0.07, maxZoom: 1}}
        preventScrolling={false} zoomOnScroll={false} proOptions={{hideAttribution: false}}
        onNodeClick={(_, node) => activateNode(node.id)}
        onKeyDown={event => {
          const node = event.target.closest?.('.react-flow__node');
          if (node !== event.target || !['Enter', ' '].includes(event.key)) return;
          event.preventDefault(); activateNode(node.dataset.id);
        }}
        ariaLabelConfig={{'controls.zoomIn.ariaLabel': '放大关系图', 'controls.zoomOut.ariaLabel': '缩小关系图',
          'controls.fitView.ariaLabel': '适应关系图', 'minimap.ariaLabel': '关系图导航', 'node.a11yDescription.default': '按回车或空格展开观点或回答依据。'}}>
        <Background color="#dbe4f3" gap={18}/>
        <Controls showInteractive={false}/>
        {!compact && <MiniMap nodeColor={node => node.id === 'question' ? '#bccbf9' : node.data.kind === 'group' ? '#c5e2dc' : '#dce5f4'} pannable zoomable/>}
      </ReactFlow>
    </div>
    {detail && <div className="of-detail" role="region" aria-label="作者回答原文依据">
      <button type="button" onClick={() => setDetail(null)} aria-label="收起节点详情">收起</button>
      <strong>{detail.author_name || '未署名'}</strong><p>{detail.summary}</p>
      {(detail.evidence || []).map((citation, index) => <blockquote key={index}>{citation.excerpt}</blockquote>)}
      <span>{authorExtent(detail.content_extent)} · 仅代表这篇回答中的观点</span>
    </div>}
    <p className="of-help">先比较不同观点，点击观点展开作者回答。拖动平移，使用 ＋ / − 缩放；分页可查看全部观点和回答。</p>
  </div>;
}

globalThis.ZhijingOpinionFlow = {
  render(element, result, options = {}) {
    const root = createRoot(element);
    root.render(<ReactFlowProvider><Map result={result} compact={Boolean(options.compact)} onSelectGroup={options.onSelectGroup}/></ReactFlowProvider>);
    return () => root.unmount();
  },
};
