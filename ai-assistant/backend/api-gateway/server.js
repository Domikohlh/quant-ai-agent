require('dotenv').config();
const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');

// Import routes
const assistantRoutes = require('./routes/assistant');
const tasksRoutes = require('./routes/tasks');
const stocksRoutes = require('./routes/stocks');
const ragRoutes = require('./routes/rag');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(helmet());
app.use(cors());
app.use(express.json({ limit: '10mb' }));

// Rate limiting
const limiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 100 // limit each IP to 100 requests per windowMs
});
app.use('/api/', limiter);

// API Key middleware
const verifyApiKey = (req, res, next) => {
  const apiKey = req.headers['x-api-key'];
  if (apiKey !== process.env.API_KEY) {
    return res.status(403).json({ error: 'Invalid API key' });
  }
  next();
};

// Routes
app.use('/api/assistant', verifyApiKey, assistantRoutes);
app.use('/api/tasks', verifyApiKey, tasksRoutes);
app.use('/api/stocks', verifyApiKey, stocksRoutes);
app.use('/api/rag', verifyApiKey, ragRoutes);

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'healthy', timestamp: new Date().toISOString() });
});

// Error handler
app.use((err, req, res, next) => {
  console.error(err.stack);
  res.status(500).json({ error: 'Something went wrong!' });
});

// Start server
app.listen(PORT, () => {
  console.log(`API Gateway running on port ${PORT}`);
});
