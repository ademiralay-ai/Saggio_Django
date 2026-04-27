import React, { useState, useCallback, useEffect } from 'react';
import ReactFlow, {
  ReactFlowProvider, addEdge, useNodesState, useEdgesState,
  Controls, Background, SelectionMode, Handle, Position, MiniMap, NodeResizer
} from 'reactflow';
import 'reactflow/dist/style.css';
import {
  Box, Paper, Button, Typography, Divider, IconButton,
  Chip, Menu, MenuItem, Slider, Stack, Tooltip
} from '@mui/material';

import SaveIcon from '@mui/icons-material/Save';
import RefreshIcon from '@mui/icons-material/Refresh';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import StopIcon from '@mui/icons-material/Stop';
import SkipNextIcon from '@mui/icons-material/SkipNext';
import DirectionsWalkIcon from '@mui/icons-material/DirectionsWalk';
import PlaylistAddIcon from '@mui/icons-material/PlaylistAdd';

import PropertiesPanel from './components/PropertiesPanel';

const flowStyles = `
  .react-flow__node.selected { border: 2px solid #00f3ff !important; box-shadow: 0 0 15px rgba(0,243,255,0.6); }
  .react-flow__selection { background: rgba(0,243,255,0.1); border: 1px solid #00f3ff; }
  .react-flow__node-group { background: rgba(255,255,255,0.05); border: 2px dashed #ffd700; color: #ffd700; border-radius: 8px; }
  .node-active { border: 3px solid #00e676 !important; box-shadow: 0 0 20px rgba(0,230,118,0.6) !important; transition: all 0.3s ease; }
`;

// --- KOŞUL NODE ---
const ConditionNode = ({ data }) => {
  const detail = data.variable_name
    ? `${data.variable_name} ${data.operator || '=='} ${data.compare_value || '?'}`
    : 'Ayar Bekleniyor';
  return (
    <div style={{ background: '#21262d', color: '#fff', padding: '10px', borderRadius: '8px', border: '2px solid #e8b339', boxShadow: '0 4px 10px rgba(0,0,0,0.5)', minWidth: '160px', textAlign: 'center', fontSize: '12px' }}>
      <Handle type="target" position={Position.Top} style={{ background: '#58a6ff', width: 10, height: 10 }} />
      <div style={{ fontWeight: 'bold', marginBottom: '4px', color: '#ffecb3' }}>{data.label || 'Kosul'}</div>
      <div style={{ color: '#8b949e', fontFamily: 'monospace', fontSize: '11px' }}>{detail}</div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '12px', padding: '0 5px' }}>
        <div><span style={{ fontSize: '9px', color: '#7ee787', display: 'block', marginBottom: 2 }}>EVET</span><Handle type="source" position={Position.Bottom} id="true" style={{ left: '10px', background: '#7ee787', width: 10, height: 10 }} /></div>
        <div><span style={{ fontSize: '9px', color: '#ff7b72', display: 'block', marginBottom: 2 }}>HAYIR</span><Handle type="source" position={Position.Bottom} id="false" style={{ right: '10px', background: '#ff7b72', width: 10, height: 10 }} /></div>
      </div>
    </div>
  );
};

const LoopNode = ({ data }) => (
  <div style={{ background: '#21262d', color: '#fff', padding: '10px', borderRadius: '8px', border: '2px solid #e74c3c', boxShadow: '0 4px 10px rgba(0,0,0,0.5)', minWidth: '160px', textAlign: 'center', fontSize: '12px' }}>
    <Handle type="target" position={Position.Top} style={{ background: '#58a6ff', width: 10, height: 10 }} />
    <div style={{ fontWeight: 'bold', marginBottom: '4px', color: '#ffb3b3' }}>{data.label || 'Dongu'}</div>
    <div style={{ color: '#8b949e', fontFamily: 'monospace', fontSize: '11px' }}>{data.list_name ? `${data.list_name} -> ${data.output_var || 'item'}` : 'Liste secilmedi'}</div>
    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '12px', padding: '0 5px' }}>
      <div><span style={{ fontSize: '9px', color: '#7ee787', display: 'block', marginBottom: 2 }}>DEVAM</span><Handle type="source" position={Position.Bottom} id="continue" style={{ left: '10px', background: '#7ee787', width: 10, height: 10 }} /></div>
      <div><span style={{ fontSize: '9px', color: '#ff7b72', display: 'block', marginBottom: 2 }}>BITTI</span><Handle type="source" position={Position.Bottom} id="done" style={{ right: '10px', background: '#ff7b72', width: 10, height: 10 }} /></div>
    </div>
  </div>
);

const GroupNode = ({ data, selected }) => (
  <>
    <NodeResizer color="#ffd700" isVisible={selected} minWidth={100} minHeight={100} />
    <div style={{ width: '100%', height: '100%', padding: 10 }}>
      <div style={{ fontWeight: 'bold', fontSize: '14px', color: '#ffd700', textTransform: 'uppercase' }}>{data.label || 'Grup'}</div>
    </div>
  </>
);

const nodeTypes = { if_else: ConditionNode, loop_generic: LoopNode, group: GroupNode };

// --- TOOLBOX ---
const Toolbox = () => {
  const onDragStart = (e, type, label) => {
    e.dataTransfer.setData('application/reactflow', type);
    e.dataTransfer.setData('application/label', label);
    e.dataTransfer.effectAllowed = 'move';
  };
  const tools = [
    { category: 'DUZENLEME', color: '#ffd700', items: [{ type: 'group', label: 'Grup Kutusu' }] },
    { category: 'SAP TEMEL', color: '#0072C3', items: [
      { type: 'sap_fill', label: 'Alan Doldur (Sablon)' },
      { type: 'sap_run', label: 'Calistir (F8/Key)' },
      { type: 'sap_wait', label: 'Ekrani Bekle' },
      { type: 'sap_action', label: 'Aksiyon Yap' },
      { type: 'sap_scan', label: 'Derin Tara' },
      { type: 'sap_close', label: 'SAP Kapat' },
    ]},
    { category: 'FTP', color: '#16a085', items: [
      { type: 'ftp_list', label: 'FTP Listele' },
      { type: 'ftp_download', label: 'FTP Indir' },
      { type: 'ftp_upload', label: 'FTP Yukle' },
    ]},
    { category: 'KONTROL AKISI', color: '#fd7e14', items: [
      { type: 'start', label: 'Baslangic' },
      { type: 'if_else', label: 'Kosul (IF/ELSE)' },
      { type: 'loop_generic', label: 'Dongu' },
      { type: 'end', label: 'Bitis' },
    ]},
    { category: 'BETIK', color: '#d2a8ff', items: [
      { type: 'py_script', label: 'Python Script' },
    ]},
  ];
  const nodeColors = {
    sap_fill: '#0072C3', sap_run: '#0072C3', sap_wait: '#0072C3', sap_scan: '#0072C3', sap_action: '#0072C3', sap_close: '#0072C3',
    start: '#2ea043', end: '#c0392b',
    ftp_list: '#16a085', ftp_download: '#16a085', ftp_upload: '#16a085',
    if_else: '#e8b339', loop_generic: '#e74c3c', group: '#ffd700', py_script: '#9b59b6',
  };
  return (
    <Paper sx={{ width: '200px', minWidth: '200px', bgcolor: '#161b22', color: 'white', height: '100%', overflowY: 'auto', zIndex: 2, borderRight: '1px solid #30363d' }}>
      {tools.map((cat, i) => (
        <Box key={i} sx={{ p: '6px 10px' }}>
          <Typography variant="caption" sx={{ color: cat.color, fontWeight: 'bold', fontSize: '10px', textTransform: 'uppercase', letterSpacing: 1 }}>{cat.category}</Typography>
          {cat.items.map((tool) => (
            <Box key={tool.type} onDragStart={(e) => onDragStart(e, tool.type, tool.label)} draggable
              sx={{ p: '5px 8px', mt: '3px', bgcolor: '#21262d', border: `1px solid ${nodeColors[tool.type] || '#444'}`, borderRadius: 1, cursor: 'grab', fontSize: '11px',
                '&:hover': { bgcolor: '#2d333b', borderColor: '#58a6ff', boxShadow: `0 0 6px ${nodeColors[tool.type]}44` }, transition: 'all 0.15s' }}>
              {tool.label}
            </Box>
          ))}
        </Box>
      ))}
    </Paper>
  );
};

// --- ANA UYGULAMA ---
export default function App() {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesState] = useEdgesState([]);
  const [reactFlowInstance, setReactFlowInstance] = useState(null);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [processName, setProcessName] = useState('');
  const [toast, setToast] = useState({ show: false, message: '', type: 'success' });

  // Calistirma durumu
  const [isRunning, setIsRunning] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [isStepMode, setIsStepMode] = useState(false);
  const [speedFactor, setSpeedFactor] = useState(1.0);
  const [tickerMsg, setTickerMsg] = useState('');
  const [menuAnchor, setMenuAnchor] = useState(null);
  const [templateMenuAnchor, setTemplateMenuAnchor] = useState(null);
  const [templateNames, setTemplateNames] = useState([]);

  const processId = document.querySelector('meta[name="process-id"]')?.content || '';
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

  const showToast = (msg, type = 'success') => {
    setToast({ show: true, message: msg, type });
    setTimeout(() => setToast(p => ({ ...p, show: false })), 3500);
  };

  const fetchTemplateNames = useCallback(async (silent = false) => {
    try {
      const res = await fetch('/sap-template/list/');
      const data = await res.json();
      if (data?.ok && Array.isArray(data.names)) {
        setTemplateNames(data.names);
        if (!silent) showToast(`${data.names.length} sablon yüklendi`, 'info');
      } else if (!silent) {
        showToast('Sablon listesi alinamadi', 'warning');
      }
    } catch (err) {
      if (!silent) showToast('Sablon listesi alinamadi', 'warning');
    }
  }, []);

  // Flow yukle
  useEffect(() => {
    if (!processId) return;
    fetch(`/sap-process/${processId}/flow/data/`)
      .then(r => r.json())
      .then(data => {
        const rfNodes = (data.nodes || []).map(n => ({
          id: n.id,
          type: ['if_else', 'loop_generic', 'group'].includes(n.type) ? n.type : 'default',
          position: { x: n.x || 0, y: n.y || 0 },
          data: { label: n.label, actionType: n.type, ...(n.config || {}) },
          style: getNodeStyle(n.type),
        }));
        const rfEdges = (data.connections || []).map(c => ({
          id: c.id, source: c.from, target: c.to,
          sourceHandle: c.fromPort || null, targetHandle: c.toPort || null,
          label: c.label || '', type: 'smoothstep', animated: true,
          style: { stroke: c.label === 'true' || c.label === 'EVET' ? '#7ee787' : c.label === 'false' || c.label === 'HAYIR' ? '#ff7b72' : '#58a6ff', strokeWidth: 2 },
          labelStyle: { fill: '#fff', fontWeight: 700, fontSize: 11 },
        }));
        setNodes(rfNodes);
        setEdges(rfEdges);
        setProcessName(data.process_name || '');
      })
      .catch(() => showToast('Akis yuklenemedi', 'error'));
  }, [processId, setEdges, setNodes]);

  useEffect(() => {
    fetchTemplateNames(true);
  }, [fetchTemplateNames]);

  // Aktif node polling
  useEffect(() => {
    if (!isRunning || !processId) return;
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/sap-process/${processId}/flow/run/status/`);
        const data = await res.json();
        setTickerMsg(data.message || '');
        setIsPaused(data.is_paused || false);
        if (!data.is_running) {
          setIsRunning(false);
          setIsPaused(false);
          if (data.error) showToast(`Hata: ${data.error}`, 'error');
          else showToast('Tamamlandi', 'success');
        }
        // Aktif node vurgula
        const activeId = data.active_node_id;
        setNodes(nds => nds.map(n => {
          const isActive = n.id === activeId;
          const base = getNodeStyle(n.data?.actionType || n.type);
          if (isActive) {
            return { ...n, className: 'node-active', style: { ...base, border: '3px solid #00e676', boxShadow: '0 0 20px rgba(0,230,118,0.6)', transition: 'all 0.3s ease' } };
          }
          return { ...n, className: '', style: base };
        }));
      } catch (e) { /* ignore */ }
    }, 500);
    return () => clearInterval(interval);
  }, [isRunning, processId, setNodes]);

  function getNodeStyle(type) {
    const colorMap = {
      sap_fill: '#0072C3', sap_run: '#0072C3', sap_wait: '#0072C3', sap_scan: '#0072C3', sap_action: '#0072C3', sap_close: '#0072C3',
      start: '#2ea043', end: '#c0392b',
      ftp_list: '#16a085', ftp_download: '#16a085', ftp_upload: '#16a085',
      py_script: '#9b59b6',
    };
    if (['if_else', 'loop_generic', 'group'].includes(type)) return undefined;
    if (type === 'group') return { width: 300, height: 200, backgroundColor: 'rgba(255,255,255,0.05)', border: '2px dashed #ffd700', zIndex: -1 };
    return { background: '#21262d', color: '#fff', border: `1px solid ${colorMap[type] || '#58a6ff'}`, borderRadius: '8px', fontSize: '12px', minWidth: '140px' };
  }

  const onConnect = useCallback((params) => {
    const isTrue = params.sourceHandle === 'true' || params.sourceHandle === 'continue';
    const isFalse = params.sourceHandle === 'false' || params.sourceHandle === 'done';
    const edgeColor = isTrue ? '#7ee787' : isFalse ? '#ff7b72' : '#58a6ff';
    const label = isTrue ? 'EVET' : isFalse ? 'HAYIR' : '';
    setEdges(eds => addEdge({ ...params, type: 'smoothstep', animated: true, label, style: { stroke: edgeColor, strokeWidth: 2 }, labelStyle: { fill: edgeColor, fontWeight: 700, fontSize: 11 } }, eds));
  }, [setEdges]);

  const onDrop = useCallback((e) => {
    e.preventDefault();
    const type = e.dataTransfer.getData('application/reactflow');
    const label = e.dataTransfer.getData('application/label');
    if (!type || !reactFlowInstance) return;
    const pos = reactFlowInstance.screenToFlowPosition({ x: e.clientX, y: e.clientY });
    const newNode = {
      id: `node_${+new Date()}`,
      type: ['if_else', 'loop_generic', 'group'].includes(type) ? type : 'default',
      position: pos,
      data: { label: label, actionType: type },
      style: getNodeStyle(type),
    };
    setNodes(nds => nds.concat(newNode));
    setSelectedNodeId(newNode.id);
  }, [reactFlowInstance, setNodes]);

  const onNodeContextMenu = useCallback((e, node) => {
    e.preventDefault();
    setSelectedNodeId(node.id);
    setMenuAnchor({ mouseX: e.clientX - 2, mouseY: e.clientY - 4 });
  }, []);

  const addTemplateNode = (templateName) => {
    if (!templateName) return;
    const pos = reactFlowInstance
      ? reactFlowInstance.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 })
      : { x: 180, y: 180 };
    const newNode = {
      id: `node_${+new Date()}`,
      type: 'default',
      position: pos,
      data: {
        label: `Sablon: ${templateName}`,
        actionType: 'sap_fill',
        template_name: templateName,
      },
      style: getNodeStyle('sap_fill'),
    };
    setNodes(nds => nds.concat(newNode));
    setSelectedNodeId(newNode.id);
    setTemplateMenuAnchor(null);
    showToast(`Sablon adimi eklendi: ${templateName}`, 'success');
  };

  const saveFlow = async () => {
    if (!reactFlowInstance) return;
    const flowObj = reactFlowInstance.toObject();
    const nodesData = flowObj.nodes.map((n, idx) => ({
      id: n.id, type: n.data?.actionType || n.type,
      label: n.data?.label || '', x: Math.round(n.position.x), y: Math.round(n.position.y),
      order: idx,
      config: (() => { const { label, actionType, ...rest } = n.data || {}; return rest; })(),
    }));
    const connections = flowObj.edges.map(e => ({
      id: e.id, from: e.source, to: e.target,
      fromPort: e.sourceHandle || 'output', toPort: e.targetHandle || 'input', label: e.label || '',
    }));
    try {
      const res = await fetch(`/sap-process/${processId}/flow/save/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({ nodes: nodesData, connections }),
      });
      const data = await res.json();
      if (data.ok) showToast(`Kaydedildi (${data.saved_steps} adim)`, 'success');
      else showToast(`Kayit hatasi: ${data.error}`, 'error');
    } catch (err) { showToast('Baglanti hatasi', 'error'); }
  };

  const startRun = async (startNodeId = null, stepMode = false) => {
    setMenuAnchor(null);
    try {
      const res = await fetch(`/sap-process/${processId}/flow/run/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({ start_node_id: startNodeId || '', speed_factor: speedFactor, step_mode: stepMode }),
      });
      const data = await res.json();
      if (data.ok) {
        setIsRunning(true);
        setIsPaused(false);
        setIsStepMode(stepMode);
        showToast(stepMode ? 'Adim modu baslatildi' : 'Calistirma baslatildi', 'info');
      } else {
        showToast(`Hata: ${data.error}`, 'error');
      }
    } catch (err) { showToast('Baglanti hatasi', 'error'); }
  };

  const togglePause = async () => {
    const command = isPaused ? 'resume' : 'pause';
    try {
      await fetch(`/sap-process/${processId}/flow/run/control/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({ command }),
      });
      setIsPaused(!isPaused);
      showToast(isPaused ? 'Devam ediyor' : 'Duraklatialdi', 'info');
    } catch (err) { showToast('Hata', 'error'); }
  };

  const stopRun = async () => {
    try {
      await fetch(`/sap-process/${processId}/flow/run/control/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({ command: 'stop' }),
      });
      setIsRunning(false);
      setIsPaused(false);
      setTickerMsg('');
      setNodes(nds => nds.map(n => ({ ...n, className: '', style: getNodeStyle(n.data?.actionType || n.type) })));
      showToast('Durduruldu', 'warning');
    } catch (err) { showToast('Hata', 'error'); }
  };

  const nextStep = async () => {
    try {
      await fetch(`/sap-process/${processId}/flow/run/control/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({ command: 'next_step' }),
      });
      showToast('Sonraki adima gecildi', 'info');
    } catch (err) { showToast('Hata', 'error'); }
  };

  const goBack = () => { window.location.href = `/sap-process/${processId}/`; };
  const toastColors = { success: '#2e7d32', error: '#d32f2f', info: '#0288d1', warning: '#ed6c02' };

  return (
    <Box sx={{ width: '100vw', height: '100vh', display: 'flex', flexDirection: 'column', bgcolor: '#010409', overflow: 'hidden' }}>
      <style>{flowStyles}</style>

      {/* TICKER BAR */}
      {(isRunning || tickerMsg) && (
        <Box sx={{ bgcolor: isRunning ? '#0d2137' : '#1a1a1a', borderBottom: '1px solid #1f6feb', px: 2, py: '3px', display: 'flex', alignItems: 'center', gap: 1, flexShrink: 0 }}>
          <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: isRunning && !isPaused ? '#2ea043' : '#e8b339', animation: isRunning && !isPaused ? 'pulse 1s infinite' : 'none' }} />
          <Typography variant="caption" sx={{ color: '#58a6ff', fontSize: '11px', flexGrow: 1 }}>{tickerMsg || 'Hazir'}</Typography>
        </Box>
      )}

      {/* TOOLBAR */}
      <Box sx={{ p: '6px 12px', bgcolor: '#161b22', borderBottom: '1px solid #30363d', display: 'flex', alignItems: 'center', gap: 1, flexShrink: 0, zIndex: 9, flexWrap: 'wrap' }}>
        <IconButton size="small" onClick={goBack} sx={{ color: '#8b949e' }}><ArrowBackIcon /></IconButton>
        <RocketLaunchIcon sx={{ color: '#2f81f7', fontSize: 20 }} />
        <Typography variant="subtitle2" sx={{ color: 'white', fontWeight: 'bold', fontSize: '12px' }}>SAGGIO RPA</Typography>
        <Divider orientation="vertical" flexItem sx={{ bgcolor: '#30363d' }} />

        {processName && (
          <Chip label={processName} size="small" variant="outlined" sx={{ color: '#58a6ff', borderColor: '#30363d', fontSize: '11px' }} />
        )}
        <Divider orientation="vertical" flexItem sx={{ bgcolor: '#30363d' }} />

        {/* Kaydet / Yenile */}
        <Button variant="contained" color="success" size="small" onClick={saveFlow} startIcon={<SaveIcon />} sx={{ fontSize: '11px' }}>Kaydet</Button>
        <Button variant="outlined" size="small" onClick={() => window.location.reload()} sx={{ color: '#8b949e', borderColor: '#30363d', fontSize: '11px' }} startIcon={<RefreshIcon />}>Yenile</Button>
        <Divider orientation="vertical" flexItem sx={{ bgcolor: '#30363d' }} />

        {/* Sablon araci */}
        <Button
          variant="outlined"
          size="small"
          onClick={(e) => setTemplateMenuAnchor(e.currentTarget)}
          startIcon={<PlaylistAddIcon />}
          sx={{ color: '#58a6ff', borderColor: '#2b4f77', fontSize: '11px' }}
        >
          Sablon Ekle
        </Button>
        <Button
          variant="text"
          size="small"
          onClick={() => fetchTemplateNames()}
          sx={{ color: '#8b949e', fontSize: '10px', minWidth: 28, px: 1 }}
          title="Sablon listesini yenile"
        >
          <RefreshIcon sx={{ fontSize: 16 }} />
        </Button>
        <Divider orientation="vertical" flexItem sx={{ bgcolor: '#30363d' }} />

        {/* Hiz Slider */}
        <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 130 }}>
          <Typography variant="caption" sx={{ color: '#8b949e', fontSize: '10px', whiteSpace: 'nowrap' }}>GEC: {speedFactor}s</Typography>
          <Slider size="small" value={speedFactor} min={0} max={10} step={0.5}
            onChange={(e, v) => setSpeedFactor(v)}
            sx={{ color: '#58a6ff', width: 80, '& .MuiSlider-thumb': { width: 10, height: 10 } }} />
        </Stack>
        <Divider orientation="vertical" flexItem sx={{ bgcolor: '#30363d' }} />

        {/* Calistirma kontrolleri */}
        <Tooltip title="Bastan Calistir (Otomatik)">
          <span>
            <Button variant="contained" color="error" size="small" onClick={() => startRun(null, false)} disabled={isRunning} sx={{ minWidth: 36, p: '4px 8px' }}><PlayArrowIcon sx={{ fontSize: 18 }} /></Button>
          </span>
        </Tooltip>
        <Tooltip title="Adim Adim Calistir">
          <span>
            <Button variant="outlined" color="info" size="small" onClick={() => startRun(null, true)} disabled={isRunning} sx={{ minWidth: 36, p: '4px 8px', borderColor: '#30363d' }}><DirectionsWalkIcon sx={{ fontSize: 18 }} /></Button>
          </span>
        </Tooltip>
        {isRunning && (
          <>
            <Tooltip title={isPaused ? 'Devam Ettir' : 'Duraklat'}>
              <Button variant="contained" color={isPaused ? 'success' : 'warning'} size="small" onClick={togglePause} sx={{ minWidth: 36, p: '4px 8px' }}>
                {isPaused ? <PlayArrowIcon sx={{ fontSize: 18 }} /> : <PauseIcon sx={{ fontSize: 18 }} />}
              </Button>
            </Tooltip>
            <Tooltip title="Durdur">
              <Button variant="contained" color="error" size="small" onClick={stopRun} sx={{ minWidth: 36, p: '4px 8px', bgcolor: '#6e1a1a' }}><StopIcon sx={{ fontSize: 18 }} /></Button>
            </Tooltip>
            {isStepMode && (
              <Tooltip title="Sonraki Adim">
                <Button variant="contained" color="primary" size="small" onClick={nextStep} startIcon={<SkipNextIcon />} sx={{ fontSize: '11px' }}>ILERI</Button>
              </Tooltip>
            )}
          </>
        )}

        <Box sx={{ flexGrow: 1 }} />
        <Typography variant="caption" sx={{ color: '#484f58', fontSize: '10px' }}>
          {nodes.length} node • {edges.length} baglanti
        </Typography>
      </Box>

      {/* FLOW ALANI */}
      <ReactFlowProvider>
        <Box sx={{ display: 'flex', flexGrow: 1, overflow: 'hidden' }}>
          <Toolbox />
          <Box sx={{ flexGrow: 1, bgcolor: '#0d1117', position: 'relative' }}>
            <ReactFlow
              nodes={nodes} edges={edges}
              onNodesChange={onNodesChange} onEdgesChange={onEdgesState}
              onConnect={onConnect} onInit={setReactFlowInstance}
              onDrop={onDrop} onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; }}
              onNodeClick={(e, n) => setSelectedNodeId(n.id)}
              onPaneClick={() => setSelectedNodeId(null)}
              onNodeContextMenu={onNodeContextMenu}
              selectionOnDrag={true} selectionMode={SelectionMode.Partial}
              panOnDrag={[1, 2]} fitView nodeTypes={nodeTypes}
              deleteKeyCode={['Delete', 'Backspace']}
            >
              <MiniMap nodeColor={n => n.type === 'if_else' ? '#e8b339' : n.type === 'loop_generic' ? '#e74c3c' : '#58a6ff'} style={{ backgroundColor: '#161b22' }} />
              <Controls />
              <Background color="#1e2530" gap={20} />
            </ReactFlow>
          </Box>
          <PropertiesPanel
            selectedNode={nodes.find(n => n.id === selectedNodeId)}
            onChange={(id, data) => setNodes(nds => nds.map(n => n.id === id ? { ...n, data } : n))}
            templateNames={templateNames}
            onRefreshTemplates={() => fetchTemplateNames()}
          />
        </Box>
      </ReactFlowProvider>

      {/* SABLON SEC MENU */}
      <Menu
        anchorEl={templateMenuAnchor}
        open={Boolean(templateMenuAnchor)}
        onClose={() => setTemplateMenuAnchor(null)}
        PaperProps={{ sx: { bgcolor: '#21262d', color: 'white', border: '1px solid #30363d', maxHeight: 360 } }}
      >
        {templateNames.length === 0 ? (
          <MenuItem disabled sx={{ fontSize: '12px' }}>Kayitli sablon yok</MenuItem>
        ) : (
          templateNames.map((tplName) => (
            <MenuItem key={tplName} onClick={() => addTemplateNode(tplName)} sx={{ fontSize: '12px', '&:hover': { bgcolor: '#2d333b' } }}>
              {tplName}
            </MenuItem>
          ))
        )}
      </Menu>

      {/* SAG TIK MENU */}
      <Menu open={menuAnchor !== null} onClose={() => setMenuAnchor(null)}
        anchorReference="anchorPosition"
        anchorPosition={menuAnchor ? { top: menuAnchor.mouseY, left: menuAnchor.mouseX } : undefined}
        PaperProps={{ sx: { bgcolor: '#21262d', color: 'white', border: '1px solid #30363d' } }}>
        <MenuItem onClick={() => startRun(selectedNodeId, false)} sx={{ fontSize: '13px', '&:hover': { bgcolor: '#2d333b' } }}>
          <PlayArrowIcon sx={{ mr: 1, fontSize: 16, color: '#7ee787' }} /> Buradan Calistir (Otomatik)
        </MenuItem>
        <MenuItem onClick={() => startRun(selectedNodeId, true)} sx={{ fontSize: '13px', '&:hover': { bgcolor: '#2d333b' } }}>
          <DirectionsWalkIcon sx={{ mr: 1, fontSize: 16, color: '#58a6ff' }} /> Buradan Calistir (Adim Adim)
        </MenuItem>
        <MenuItem onClick={() => { setMenuAnchor(null); setNodes(nds => nds.filter(n => n.id !== selectedNodeId)); setSelectedNodeId(null); }}
          sx={{ fontSize: '13px', color: '#ff7b72', '&:hover': { bgcolor: '#2d333b' } }}>
          Secili Node'u Sil
        </MenuItem>
      </Menu>

      {/* TOAST */}
      {toast.show && (
        <Box sx={{ position: 'fixed', bottom: 20, right: 20, bgcolor: toastColors[toast.type] || '#2c3e50', color: 'white', p: '10px 16px', borderRadius: 2, zIndex: 9999, fontSize: '13px', boxShadow: '0 4px 12px rgba(0,0,0,0.3)' }}>
          {toast.message}
        </Box>
      )}
    </Box>
  );
}
