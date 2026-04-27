import React from 'react';
import { Handle, Position } from 'reactflow';
import { Paper, Typography } from '@mui/material';

const DecisionNode = ({ data }) => {
  return (
    <div style={{ position: 'relative' }}>
        {/* Giriş Bağlantısı (Tepede) */}
        <Handle type="target" position={Position.Top} style={{ background: '#fff', width: 10, height: 10 }} />

        {/* Baklava Şekli (Görsel) */}
        <div style={{
            width: '120px',
            height: '120px',
            backgroundColor: '#fd7e14', // Turuncu
            transform: 'rotate(45deg)', // Döndür
            border: '2px solid #fff',
            borderRadius: '4px',
            boxShadow: '0 4px 8px rgba(0,0,0,0.4)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
        }}>
            {/* Yazıyı Tersi Yönde Döndür (Düz Okunsun Diye) */}
            <div style={{ transform: 'rotate(-45deg)', textAlign: 'center', width: '100%' }}>
                <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'white', fontSize: '12px' }}>
                    {data.label}
                </Typography>
                <Typography variant="caption" sx={{ color: '#000', fontSize: '10px' }}>
                    (IF/ELSE)
                </Typography>
            </div>
        </div>

        {/* ÇIKIŞ 1: FALSE (Solda) */}
        <Handle 
            type="source" 
            position={Position.Left} 
            id="false" 
            style={{ background: '#dc3545', width: 12, height: 12, left: -5 }} // Kırmızı
        />
        <span style={{ position: 'absolute', left: -40, top: '45%', color: '#dc3545', fontSize: '10px', fontWeight: 'bold' }}>FALSE</span>

        {/* ÇIKIŞ 2: TRUE (Sağda) */}
        <Handle 
            type="source" 
            position={Position.Right} 
            id="true" 
            style={{ background: '#198754', width: 12, height: 12, right: -5 }} // Yeşil
        />
        <span style={{ position: 'absolute', right: -35, top: '45%', color: '#198754', fontSize: '10px', fontWeight: 'bold' }}>TRUE</span>
    </div>
  );
};

export default DecisionNode;