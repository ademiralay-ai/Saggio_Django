import React from 'react';
import { 
  Paper, Typography, TextField, Box, Divider, FormControl, 
  InputLabel, Select, MenuItem, Alert, Button
} from '@mui/material';
import SettingsIcon from '@mui/icons-material/Settings';

const PropertiesPanel = ({ selectedNode, onChange, templateNames = [], onRefreshTemplates }) => {

  if (!selectedNode) {
    return (
      <Paper sx={{ width: '300px', p: 2, bgcolor: '#161b22', borderRight: '1px solid #30363d', height: '100%', color: '#8b949e', display:'flex', alignItems:'center', justifyContent:'center' }}>
        <Box textAlign="center">
          <Typography variant="h6" sx={{ color: '#30363d', mb: 1 }}>⬅️</Typography>
          <Typography variant="body2">Bir araç seçin...</Typography>
        </Box>
      </Paper>
    );
  }

  const actualType = selectedNode.data?.actionType || selectedNode.type;

  const handleChange = (field, value) => {
    onChange(selectedNode.id, { ...selectedNode.data, [field]: value });
  };

  const inputStyles = { 
    mb: 2, bgcolor: '#0d1117', borderRadius: 1,
    '& .MuiInputBase-input': { color: '#ffffff !important' }, 
    '& .MuiInputLabel-root': { color: '#8b949e !important' },
    '& .MuiFilledInput-root': { bgcolor: '#0d1117' },
    '& .MuiSelect-icon': { color: 'white' },
    '& .MuiFormHelperText-root': { color: '#8b949e !important' }
  };

  const nodeTypeNames = {
    sap_fill: 'SAP Alan Doldur', sap_run: 'SAP Çalıştır (F8)', sap_wait: 'SAP Bekle',
    sap_scan: 'SAP Tara', sap_action: 'SAP Aksiyon', sap_close: 'SAP Kapat',
    ftp_list: 'FTP Listele', ftp_download: 'FTP İndir', ftp_upload: 'FTP Yükle',
    if_else: 'Koşul (IF/ELSE)', loop_generic: 'Döngü', py_script: 'Python Script',
    start: 'Başlangıç', end: 'Bitiş'
  };

  return (
    <Paper sx={{ width: '300px', p: 2, bgcolor: '#161b22', color: 'white', borderLeft: '1px solid #30363d', height: '100%', overflowY: 'auto' }}>
      
      <Box display="flex" alignItems="center" gap={1} mb={2}>
        <SettingsIcon sx={{ color: '#58a6ff' }} />
        <Typography variant="subtitle1" sx={{ fontWeight: 'bold', fontSize: '14px' }}>
          {nodeTypeNames[actualType] || actualType}
        </Typography>
      </Box>
      <Divider sx={{ bgcolor: '#30363d', mb: 2 }} />

      <TextField 
        label="Adım İsmi" fullWidth size="small" variant="filled" 
        value={selectedNode.data?.label || ''} 
        onChange={(e) => handleChange('label', e.target.value)} 
        sx={inputStyles} 
      />

      {actualType === 'sap_fill' && (
        <>
          <FormControl fullWidth size="small" variant="filled" sx={inputStyles}>
            <InputLabel>Sablon</InputLabel>
            <Select value={selectedNode.data?.template_name || ''} onChange={(e) => handleChange('template_name', e.target.value)}>
              <MenuItem value="">-- Sablon Secin --</MenuItem>
              {templateNames.map((name) => (
                <MenuItem key={name} value={name}>{name}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <Box sx={{ mb: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Typography variant="caption" sx={{ color: '#8b949e', fontSize: '10px' }}>
              {templateNames.length > 0 ? `${templateNames.length} sablon bulundu` : 'Kayitli sablon bulunamadi'}
            </Typography>
            <Button size="small" variant="text" onClick={() => onRefreshTemplates && onRefreshTemplates()} sx={{ color: '#8b949e', minWidth: 0, p: '2px 6px', fontSize: '10px' }}>
              Yenile
            </Button>
          </Box>
          <TextField label="SAP Alan ID" fullWidth variant="filled" multiline rows={2} value={selectedNode.data?.field_id || ''} onChange={(e) => handleChange('field_id', e.target.value)} sx={inputStyles} placeholder="wnd[0]/usr/..." />
          <FormControl fullWidth size="small" variant="filled" sx={inputStyles}>
            <InputLabel>Yöntem</InputLabel>
            <Select value={selectedNode.data?.fill_method || 'fixed'} onChange={(e) => handleChange('fill_method', e.target.value)}>
              <MenuItem value="fixed">Sabit Değer / Değişken</MenuItem>
              <MenuItem value="dynamic_date">Dinamik Tarih</MenuItem>
            </Select>
          </FormControl>
          {selectedNode.data?.fill_method === 'dynamic_date' ? (
            <FormControl fullWidth size="small" variant="filled" sx={inputStyles}>
              <InputLabel>Tarih Seçimi</InputLabel>
              <Select value={selectedNode.data?.date_key || 'Bugün'} onChange={(e) => handleChange('date_key', e.target.value)}>
                <MenuItem value="Bugün">Bugün</MenuItem><MenuItem value="Dün">Dün</MenuItem>
                <MenuItem value="5 Gün Önce">5 Gün Önce</MenuItem><MenuItem value="30 Gün Önce">30 Gün Önce</MenuItem>
                <MenuItem value="Bu Ayın Başı">Bu Ayın Başı</MenuItem><MenuItem value="Bu Ayın Sonu">Bu Ayın Sonu</MenuItem>
                <MenuItem value="Önceki Ayın Başı">Önceki Ayın Başı</MenuItem><MenuItem value="Önceki Ayın Sonu">Önceki Ayın Sonu</MenuItem>
                <MenuItem value="Yıl Başı">Yıl Başı</MenuItem>
              </Select>
            </FormControl>
          ) : (
            <TextField label="Değer veya {değişken}" fullWidth size="small" variant="filled" value={selectedNode.data?.value || ''} onChange={(e) => handleChange('value', e.target.value)} sx={inputStyles} placeholder="Örn: ZSD0205 veya {current_item}" />
          )}
          <TextField label="Bekleme (Sn)" type="number" fullWidth variant="filled" value={selectedNode.data?.timeout || ''} onChange={(e) => handleChange('timeout', e.target.value)} sx={inputStyles} placeholder="Varsayılan: 10" />
        </>
      )}

      {actualType === 'sap_run' && <Alert severity="info" sx={{ bgcolor: '#0d1117', color: '#58a6ff', fontSize: '11px', mb: 2 }}>F8 tuşuna basarak SAP raporunu çalıştırır.</Alert>}
      
      {actualType === 'sap_wait' && <TextField label="Bekleme Süresi (Sn)" type="number" fullWidth variant="filled" value={selectedNode.data?.seconds || 5} onChange={(e) => handleChange('seconds', e.target.value)} sx={inputStyles} />}

      {actualType === 'sap_scan' && (
        <>
          <TextField label="SAP Alan ID" fullWidth variant="filled" value={selectedNode.data?.field_id || ''} onChange={(e) => handleChange('field_id', e.target.value)} sx={inputStyles} placeholder="wnd[0]/usr/..." />
          <TextField label="Çıktı Değişkeni" fullWidth variant="filled" value={selectedNode.data?.output_var || ''} onChange={(e) => handleChange('output_var', e.target.value)} sx={inputStyles} placeholder="scanned_value" />
        </>
      )}

      {actualType === 'sap_action' && (
        <>
          <FormControl fullWidth size="small" variant="filled" sx={inputStyles}>
            <InputLabel>Aksiyon Türü</InputLabel>
            <Select value={selectedNode.data?.action || 'click'} onChange={(e) => handleChange('action', e.target.value)}>
              <MenuItem value="click">Tıkla</MenuItem><MenuItem value="press_key">Tuş Bas</MenuItem>
              <MenuItem value="toolbar">Toolbar Tıkla</MenuItem><MenuItem value="select_menu">Menü Seç</MenuItem>
            </Select>
          </FormControl>
          <TextField label="Alan ID / Nesne" fullWidth variant="filled" value={selectedNode.data?.field_id || ''} onChange={(e) => handleChange('field_id', e.target.value)} sx={inputStyles} />
          {selectedNode.data?.action === 'press_key' && (
            <FormControl fullWidth size="small" variant="filled" sx={inputStyles}>
              <InputLabel>Tuş</InputLabel>
              <Select value={selectedNode.data?.key || 'ENTER'} onChange={(e) => handleChange('key', e.target.value)}>
                <MenuItem value="ENTER">Enter</MenuItem><MenuItem value="F8">F8</MenuItem><MenuItem value="F11">F11</MenuItem><MenuItem value="F3">F3</MenuItem><MenuItem value="ESC">ESC</MenuItem>
              </Select>
            </FormControl>
          )}
        </>
      )}

      {actualType === 'sap_close' && <Alert severity="warning" sx={{ bgcolor: '#0d1117', color: '#e8b339', fontSize: '11px', mb: 2 }}>SAP oturumunu / uygulamasını kapatır.</Alert>}

      {actualType === 'ftp_list' && (
        <>
          <TextField label="FTP Yolu" fullWidth variant="filled" value={selectedNode.data?.path || '/'} onChange={(e) => handleChange('path', e.target.value)} sx={inputStyles} placeholder="/raporlar/" />
          <TextField label="Filtre (glob)" fullWidth variant="filled" value={selectedNode.data?.filter || '*'} onChange={(e) => handleChange('filter', e.target.value)} sx={inputStyles} placeholder="*.xlsx" />
          <TextField label="Çıktı Değişkeni" fullWidth variant="filled" value={selectedNode.data?.output_var || 'ftp_files'} onChange={(e) => handleChange('output_var', e.target.value)} sx={inputStyles} />
        </>
      )}

      {actualType === 'ftp_download' && (
        <>
          <TextField label="FTP Kaynak Yolu" fullWidth variant="filled" value={selectedNode.data?.remote_path || ''} onChange={(e) => handleChange('remote_path', e.target.value)} sx={inputStyles} placeholder="/raporlar/{current_item}" />
          <TextField label="Yerel Hedef Yolu" fullWidth variant="filled" value={selectedNode.data?.local_path || ''} onChange={(e) => handleChange('local_path', e.target.value)} sx={inputStyles} placeholder="C:\\Downloads\\{current_item}" />
        </>
      )}

      {actualType === 'ftp_upload' && (
        <>
          <TextField label="Yerel Kaynak Yolu" fullWidth variant="filled" value={selectedNode.data?.local_path || ''} onChange={(e) => handleChange('local_path', e.target.value)} sx={inputStyles} />
          <TextField label="FTP Hedef Yolu" fullWidth variant="filled" value={selectedNode.data?.remote_path || ''} onChange={(e) => handleChange('remote_path', e.target.value)} sx={inputStyles} />
        </>
      )}

      {actualType === 'if_else' && (
        <>
          <Alert severity="info" sx={{ bgcolor: '#0d1117', color: '#e8b339', fontSize: '11px', mb: 2 }}>EVET çıkışı koşul doğruysa, HAYIR çıkışı yanlışsa izlenir.</Alert>
          <TextField label="Değişken Adı" fullWidth variant="filled" value={selectedNode.data?.variable_name || ''} onChange={(e) => handleChange('variable_name', e.target.value)} sx={inputStyles} placeholder="row_count" />
          <FormControl fullWidth variant="filled" sx={inputStyles}>
            <InputLabel>Operatör</InputLabel>
            <Select value={selectedNode.data?.operator || '=='} onChange={(e) => handleChange('operator', e.target.value)}>
              <MenuItem value="==">Eşittir (==)</MenuItem><MenuItem value="!=">Eşit Değil (!=)</MenuItem>
              <MenuItem value=">">Büyüktür</MenuItem><MenuItem value="<">Küçüktür</MenuItem>
              <MenuItem value=">=">Büyük Eşit</MenuItem><MenuItem value="<=">Küçük Eşit</MenuItem>
              <MenuItem value="in">İçerir (in)</MenuItem><MenuItem value="not_in">İçermez (not in)</MenuItem>
            </Select>
          </FormControl>
          <TextField label="Karşılaştırma Değeri" fullWidth variant="filled" value={selectedNode.data?.compare_value || ''} onChange={(e) => handleChange('compare_value', e.target.value)} sx={inputStyles} placeholder="0 veya {beklenen}" />
        </>
      )}

      {actualType === 'loop_generic' && (
        <>
          <TextField label="Liste Değişkeni" fullWidth variant="filled" value={selectedNode.data?.list_name || ''} onChange={(e) => handleChange('list_name', e.target.value)} sx={inputStyles} placeholder="ftp_files" />
          <TextField label="Güncel Eleman Değişkeni" fullWidth variant="filled" value={selectedNode.data?.output_var || 'current_item'} onChange={(e) => handleChange('output_var', e.target.value)} sx={inputStyles} />
          <TextField label="Maks. Tekrar" type="number" fullWidth variant="filled" value={selectedNode.data?.max_iterations || 100} onChange={(e) => handleChange('max_iterations', e.target.value)} sx={inputStyles} />
        </>
      )}

      {actualType === 'py_script' && (
        <>
          <Alert severity="info" sx={{ bgcolor: '#0d1117', color: '#d2a8ff', fontSize: '11px', mb: 2 }}>Python scripti çalıştırır. Yol proje içinde olmalı.</Alert>
          <TextField label="Script Yolu" fullWidth variant="filled" value={selectedNode.data?.script_path || ''} onChange={(e) => handleChange('script_path', e.target.value)} sx={inputStyles} placeholder="scripts/islem.py" />
          <TextField label="Argümanlar (boşlukla ayır)" fullWidth variant="filled" value={selectedNode.data?.args || ''} onChange={(e) => handleChange('args', e.target.value)} sx={inputStyles} placeholder="--input {current_item}" />
          <TextField label="Timeout (Sn)" type="number" fullWidth variant="filled" value={selectedNode.data?.timeout || 30} onChange={(e) => handleChange('timeout', e.target.value)} sx={inputStyles} />
        </>
      )}

      <Divider sx={{ bgcolor: '#30363d', mt: 2, mb: 2 }} />
      <Box sx={{ fontSize: '10px', color: '#484f58' }}>
        <div>ID: {selectedNode.id}</div>
        <div>Tür: {actualType}</div>
        <div>Pozisyon: {Math.round(selectedNode.position?.x || 0)}, {Math.round(selectedNode.position?.y || 0)}</div>
      </Box>
    </Paper>
  );
};

export default PropertiesPanel;
