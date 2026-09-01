'use client';

import { Background, Controls, MarkerType, ReactFlow, type Edge, type Node } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

const roles = [
  { id: 'alice', label: 'Alice', sub: 'Delegates authority', x: 0, y: 95, color: '#a56eff' },
  { id: 'agent', label: 'agent-7', sub: '$100 mandate', x: 210, y: 95, color: '#4589ff' },
  { id: 'praxis', label: 'Praxis', sub: 'Gateway', x: 420, y: 10, color: '#ee0000' },
  { id: 'cpex', label: 'CPEX / PPE', sub: 'Policy decision', x: 420, y: 180, color: '#0f62fe' },
  { id: 'ocsf', label: 'OCSF evidence', sub: 'Signed record', x: 650, y: 95, color: '#33b1ff' },
  { id: 'ledger', label: 'Immutable ledger', sub: 'Durable proof', x: 880, y: 95, color: '#42be65' },
  { id: 'verify', label: 'Offline verifier', sub: 'Independent trust', x: 1110, y: 95, color: '#f1c21b' },
];

const links = [['alice','agent'],['agent','praxis'],['agent','cpex'],['praxis','ocsf'],['cpex','ocsf'],['ocsf','ledger'],['ledger','verify']];

export function ProofFlow({ activeIndex }: { activeIndex: number }) {
  const activeByStep = ['agent','praxis','praxis','cpex','cpex','ocsf','ledger','verify'];
  const active = activeByStep[Math.min(activeIndex, activeByStep.length - 1)];
  const nodes: Node[] = roles.map(role => ({
    id: role.id,
    position: { x: role.x, y: role.y },
    draggable: false,
    data: { label: <div className="flow-node"><span className="flow-pulse" style={{ background: role.color }} /><strong>{role.label}</strong><small>{role.sub}</small></div> },
    className: role.id === active ? 'flow-card flow-card-active' : 'flow-card',
    style: { borderColor: role.id === active ? role.color : '#3b4552' },
  }));
  const edges: Edge[] = links.map(([source,target], index) => ({
    id: `${source}-${target}`,
    source,
    target,
    animated: index <= Math.min(activeIndex, links.length - 1),
    style: { stroke: index <= activeIndex ? '#78a9ff' : '#3b4552', strokeWidth: 2 },
    markerEnd: { type: MarkerType.ArrowClosed, color: index <= activeIndex ? '#78a9ff' : '#3b4552' },
  }));

  return (
    <div className="flow-wrap" aria-label="Verdict-to-proof architecture">
      <ReactFlow nodes={nodes} edges={edges} fitView fitViewOptions={{ padding: .16 }} nodesDraggable={false} nodesConnectable={false} panOnDrag zoomOnScroll minZoom={.6} maxZoom={1.25} proOptions={{ hideAttribution: true }}>
        <Background color="#26303a" gap={22} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
