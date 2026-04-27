import React, { useState } from 'react';
import { 
  List, ListItemButton, ListItemIcon, ListItemText, Collapse, Divider, Box 
} from '@mui/material';
import {
  ExpandLess, ExpandMore, 
  Dashboard as DashboardIcon,
  SmartToy as RobotIcon,
  Settings as SettingsIcon,
  People as PeopleIcon,
  BarChart as ChartIcon,
  VpnKey as AdminIcon,
  Description as LogIcon
} from '@mui/icons-material';

const Sidebar = ({ isOpen }) => {
  // Alt menülerin açık/kapalı durumunu tutan state
  const [openSubmenu, setOpenSubmenu] = useState({});

  const handleSubmenuClick = (menuName) => {
    setOpenSubmenu((prev) => ({ ...prev, [menuName]: !prev[menuName] }));
  };

  // --- MENÜ YAPISI (Burayı ileride veritabanından çekeceğiz) ---
  const menuItems = [
    {
      title: "Dashboard",
      icon: <DashboardIcon />,
      path: "/dashboard"
    },
    {
      title: "Robot Operasyonları",
      icon: <RobotIcon />,
      children: [ // Alt menüler
        { title: "Aktif Robotlar", icon: <RobotIcon fontSize="small"/>, path: "/robots/active" },
        { title: "Görev Zamanlayıcı", icon: <SettingsIcon fontSize="small"/>, path: "/robots/schedule" },
        { title: "İşlem Logları", icon: <LogIcon fontSize="small"/>, path: "/robots/logs" }
      ]
    },
    {
      title: "Raporlar",
      icon: <ChartIcon />,
      children: [
        { title: "Kazanç Analizi", path: "/reports/savings" },
        { title: "Hata Raporları", path: "/reports/errors" }
      ]
    },
    // --- SADECE ADMIN GÖRECEK KISIM (Örnek) ---
    {
      title: "Sistem Yönetimi",
      icon: <AdminIcon />,
      isAdmin: true, // İleride bu flag'e göre gizleyeceğiz
      children: [
        { title: "Kullanıcılar", icon: <PeopleIcon fontSize="small"/>, path: "/admin/users" },
        { title: "Yetki Ayarları", icon: <SettingsIcon fontSize="small"/>, path: "/admin/roles" }
      ]
    }
  ];

  return (
    <Box sx={{ width: '100%', maxWidth: 360, bgcolor: '#161b22', color: 'white', height: '100vh', overflowY: 'auto' }}>
        <List component="nav">
            {menuItems.map((item, index) => (
                <div key={index}>
                    {/* Ana Menü Elemanı */}
                    <ListItemButton onClick={() => item.children && handleSubmenuClick(item.title)}>
                        <ListItemIcon sx={{ color: '#8b949e' }}>
                            {item.icon}
                        </ListItemIcon>
                        <ListItemText primary={item.title} />
                        {/* Alt menüsü varsa ok işareti koy */}
                        {item.children ? (openSubmenu[item.title] ? <ExpandLess /> : <ExpandMore />) : null}
                    </ListItemButton>

                    {/* Alt Menüler (Collapse) */}
                    {item.children && (
                        <Collapse in={openSubmenu[item.title]} timeout="auto" unmountOnExit>
                            <List component="div" disablePadding>
                                {item.children.map((subItem, subIndex) => (
                                    <ListItemButton key={subIndex} sx={{ pl: 4, bgcolor: '#0d1117' }}>
                                        {subItem.icon && (
                                            <ListItemIcon sx={{ color: '#8b949e', minWidth: 35 }}>
                                                {subItem.icon}
                                            </ListItemIcon>
                                        )}
                                        <ListItemText primary={subItem.title} primaryTypographyProps={{ fontSize: '0.9rem', color: '#c9d1d9' }} />
                                    </ListItemButton>
                                ))}
                            </List>
                        </Collapse>
                    )}
                </div>
            ))}
        </List>
    </Box>
  );
};

export default Sidebar;