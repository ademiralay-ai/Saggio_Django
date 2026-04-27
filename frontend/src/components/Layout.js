import React, { useState } from 'react';
import { Box, AppBar, Toolbar, Typography, IconButton, Drawer, Avatar, Menu, MenuItem, useMediaQuery, useTheme, Chip } from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft'; 
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch'; 
import Sidebar from './Sidebar';

const drawerWidth = 260;

// --- KAYAN YAZI BİLEŞENİ ---
const StatusTicker = ({ isRunning, message }) => {
  const stats = "💰 TOPLAM KAZANÇ: $154,230  •  ⏱️ TASARRUF: 425 SAAT  •  🤖 AKTİF ROBOT: 5/8  •  🌍 LOKASYON: MERKEZ OFİS  •  ";
  const displayContent = isRunning && message ? `🚀 ${message.toUpperCase()}  •  ${message.toUpperCase()}  •  ` : stats + stats;

  return (
    <Box sx={{ 
      flexGrow: 1, mx: 4, height: 28, bgcolor: 'rgba(255,255,255,0.05)', borderRadius: 1, border: '1px solid #30363d', 
      overflow: 'hidden', position: 'relative', display: { xs: 'none', md: 'flex' }, alignItems: 'center' 
    }}>
      <style>{`
        @keyframes ticker { 0% { transform: translateX(100%); } 100% { transform: translateX(-100%); } }
        .ticker-text:hover { animation-play-state: paused; cursor: default; }
      `}</style>
      <Typography className="ticker-text" variant="caption" sx={{ 
        whiteSpace: 'nowrap', position: 'absolute', animation: 'ticker 30s linear infinite',
        color: isRunning ? '#00e676' : '#a5d6ff', fontWeight: 'bold', fontFamily: 'monospace', fontSize: '11px', pt: 0.3
      }}>
        {displayContent}
      </Typography>
    </Box>
  );
};

// --- LAYOUT BİLEŞENİ ---
const Layout = ({ children, isRunning, tickerMsg }) => {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('sm')); 
  const [isOpen, setIsOpen] = useState(!isMobile); 
  const [anchorEl, setAnchorEl] = useState(null); 

  const handleDrawerToggle = () => setIsOpen(!isOpen);
  const handleProfileMenuOpen = (event) => setAnchorEl(event.currentTarget);
  const handleProfileMenuClose = () => setAnchorEl(null);

  return (
    <Box sx={{ display: 'flex', height: '100vh', bgcolor: '#0d1117' }}>
      
      {/* 1. ÜST BAR (NAVBAR) */}
      <AppBar position="fixed" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1, bgcolor: '#161b22', borderBottom: '1px solid #30363d', boxShadow: 'none' }}>
        <Toolbar sx={{ minHeight: '56px !important' }}> 
          <IconButton color="inherit" edge="start" onClick={handleDrawerToggle} sx={{ mr: 2 }}>
            {isOpen ? <ChevronLeftIcon /> : <MenuIcon />}
          </IconButton>
          
          <Box sx={{ display: 'flex', alignItems: 'center', minWidth: 'fit-content' }}>
            <Chip label="BEK" size="small" sx={{ ml: 1, bgcolor: '#006FB9', color: 'white', fontWeight: 'bold', height: 20, fontSize: '0.65rem', borderRadius: '4px' }} />
          </Box>

          <StatusTicker isRunning={isRunning} message={tickerMsg} />

          <div>
            <IconButton size="small" onClick={handleProfileMenuOpen} color="inherit">
                <Avatar sx={{ bgcolor: '#1f6feb', width: 32, height: 32, fontSize:14 }}>A</Avatar>
            </IconButton>
            <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={handleProfileMenuClose} PaperProps={{ sx: { bgcolor: '#161b22', color: 'white', border: '1px solid #30363d' } }}>
                <MenuItem component="a" href="http://127.0.0.1:8000/admin/" target="_blank" rel="noopener noreferrer" onClick={handleProfileMenuClose}>Admin</MenuItem>
                <MenuItem onClick={handleProfileMenuClose}>Profilim</MenuItem>
                <MenuItem onClick={handleProfileMenuClose}>Ayarlar</MenuItem>
                <MenuItem onClick={handleProfileMenuClose} sx={{ color: '#ff7b72' }}>Çıkış Yap</MenuItem>
            </Menu>
          </div>
        </Toolbar>
      </AppBar>

      {/* 2. SOL MENÜ (DRAWER) */}
      <Box component="nav" sx={{ width: { sm: isOpen ? drawerWidth : 0 }, flexShrink: { sm: 0 }, transition: 'width 0.3s' }}>
        <Drawer variant="temporary" open={isOpen && isMobile} onClose={handleDrawerToggle} ModalProps={{ keepMounted: true }} sx={{ display: { xs: 'block', sm: 'none' }, '& .MuiDrawer-paper': { boxSizing: 'border-box', width: drawerWidth, bgcolor: '#161b22' } }}>
          <Toolbar />
          <Sidebar />
        </Drawer>
        <Drawer variant="persistent" open={isOpen && !isMobile} sx={{ display: { xs: 'none', sm: 'block' }, '& .MuiDrawer-paper': { boxSizing: 'border-box', width: drawerWidth, bgcolor: '#161b22', borderRight: '1px solid #30363d', height: '100vh', position: 'fixed', top: 0 } }}>
            <Toolbar />
            <Sidebar />
        </Drawer>
      </Box>

      {/* 3. ANA İÇERİK ALANI */}
      <Box component="main" sx={{ 
          flexGrow: 1, p: 0, 
          width: { sm: `calc(100% - ${isOpen ? drawerWidth : 0}px)` }, 
          height: '100vh', overflow: 'hidden', display: 'flex', flexDirection: 'column',
          transition: 'width 0.3s, margin 0.3s'
      }}>
        <Toolbar /> {/* Navbar boşluğu */}
        
        {/* BURASI DEĞİŞTİ: Çocukları (App.js) esnek kutu içine alıyoruz */}
        <Box sx={{ flexGrow: 1, position: 'relative', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            {children}
        </Box>
      </Box>

    </Box>
  );
};

export default Layout;