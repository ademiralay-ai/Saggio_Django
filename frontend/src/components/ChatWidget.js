import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { 
  Fab, Paper, TextField, Typography, Box, IconButton, CircularProgress, Tooltip 
} from '@mui/material';
import SmartToyIcon from '@mui/icons-material/SmartToy'; 
import CloseIcon from '@mui/icons-material/Close';
import SendIcon from '@mui/icons-material/Send';
import ThumbUpIcon from '@mui/icons-material/ThumbUp';
import ThumbDownIcon from '@mui/icons-material/ThumbDown';

const ChatWidget = () => {
  const [isOpen, setIsOpen] = useState(false); 
  const [query, setQuery] = useState("");      
  const [loading, setLoading] = useState(false); 
  const [messages, setMessages] = useState([
    { sender: 'bot', text: 'Merhaba! Ben Saggio. Kodlarına yardım edebilirim.', memoryId: null }
  ]);
  
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages]);

  const sendMessage = async () => {
    if (!query.trim()) return;

    const userMsg = { sender: 'user', text: query };
    setMessages(prev => [...prev, userMsg]);
    setQuery("");
    setLoading(true);

    try {
      const res = await axios.post('http://127.0.0.1:8000/api/chat/', { message: userMsg.text });
      
      const botResponse = res.data.reply || "Cevap yok.";
      const memId = res.data.memory_id; // ID'yi al

      setMessages(prev => [...prev, { sender: 'bot', text: botResponse, memoryId: memId }]);

    } catch (error) {
      setMessages(prev => [...prev, { sender: 'bot', text: '⚠️ Bağlantı hatası!' }]);
    } finally {
      setLoading(false);
    }
  };

  const handleRating = async (memoryId, rating, index) => {
    if (!memoryId) return;
    try {
      await axios.post('http://127.0.0.1:8000/api/rate-bot/', { memory_id: memoryId, rating: rating });
      
      // UI Güncelleme (Rengi değiştir)
      const newMessages = [...messages];
      newMessages[index].rated = true;
      newMessages[index].rating = rating;
      setMessages(newMessages);

    } catch (e) {
      console.error("Oylama hatası:", e);
    }
  };

  return (
    <div style={{ position: 'fixed', bottom: 20, right: 20, zIndex: 9999 }}>
      
      {!isOpen && (
        <Fab color="primary" onClick={() => setIsOpen(true)} sx={{ width: 60, height: 60, bgcolor: '#0d6efd' }}>
          <SmartToyIcon sx={{ fontSize: 30 }} />
        </Fab>
      )}

      {isOpen && (
        <Paper elevation={10} sx={{ width: 350, height: 500, display: 'flex', flexDirection: 'column', bgcolor: '#161b22', color: 'white', border: '1px solid #30363d', borderRadius: 2 }}>
          
          <Box sx={{ p: 2, bgcolor: '#21262d', borderBottom: '1px solid #30363d', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Typography variant="subtitle1" fontWeight="bold" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <SmartToyIcon sx={{ color: '#0d6efd' }}/> Saggio Asistan
            </Typography>
            <IconButton size="small" onClick={() => setIsOpen(false)} sx={{ color: '#8b949e' }}><CloseIcon /></IconButton>
          </Box>

          <Box ref={scrollRef} sx={{ flexGrow: 1, p: 2, overflowY: 'auto' }}>
            {messages.map((msg, index) => (
              <Box key={index} sx={{ display: 'flex', flexDirection: 'column', alignItems: msg.sender === 'user' ? 'flex-end' : 'flex-start', mb: 2 }}>
                <Paper sx={{ p: 1.5, maxWidth: '85%', bgcolor: msg.sender === 'user' ? '#0d6efd' : '#30363d', color: 'white', borderRadius: 2 }}>
                    <Typography variant="body2" sx={{whiteSpace: 'pre-wrap'}}>{msg.text}</Typography>
                </Paper>

                {/* OYLAMA BUTONLARI */}
                {msg.sender === 'bot' && msg.memoryId && !msg.rated && (
                  <Box sx={{ display: 'flex', gap: 1, mt: 0.5, ml: 1 }}>
                    <Tooltip title="Başarılı"><IconButton size="small" onClick={() => handleRating(msg.memoryId, 1, index)} sx={{ color: '#8b949e', '&:hover':{color:'#7ee787'} }}><ThumbUpIcon fontSize="inherit" /></IconButton></Tooltip>
                    <Tooltip title="Başarısız"><IconButton size="small" onClick={() => handleRating(msg.memoryId, -1, index)} sx={{ color: '#8b949e', '&:hover':{color:'#ff7b72'} }}><ThumbDownIcon fontSize="inherit" /></IconButton></Tooltip>
                  </Box>
                )}

                {/* OYLANDI BİLGİSİ */}
                {msg.rated && (
                    <Typography variant="caption" sx={{ color: msg.rating === 1 ? '#7ee787' : '#ff7b72', mt: 0.5, ml: 1, fontSize: '10px' }}>
                        {msg.rating === 1 ? "Beğenildi 👍" : "Beğenilmedi 👎"}
                    </Typography>
                )}
              </Box>
            ))}
            {loading && <CircularProgress size={20} sx={{ ml: 2, color: '#8b949e' }} />}
          </Box>

          <Box sx={{ p: 2, borderTop: '1px solid #30363d', display: 'flex', gap: 1 }}>
            <TextField 
                fullWidth size="small" placeholder="Bir şeyler sor..." value={query} onChange={(e) => setQuery(e.target.value)} onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
                sx={{ bgcolor: '#0d1117', input: { color: 'white' }, '& .MuiOutlinedInput-notchedOutline': { borderColor: '#30363d' } }}
            />
            <IconButton color="primary" onClick={sendMessage} sx={{ bgcolor: '#0d6efd', color: 'white', '&:hover':{bgcolor:'#0b5ed7'} }}><SendIcon /></IconButton>
          </Box>
        </Paper>
      )}
    </div>
  );
};

export default ChatWidget;