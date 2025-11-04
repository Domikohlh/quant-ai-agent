const express = require('express');
const router = express.Router();
const axios = require('axios');
const multer = require('multer');
const path = require('path');

const upload = multer({ dest: 'uploads/' });

const RAG_SERVICE_URL = process.env.RAG_SERVICE_URL;
const RAG_SERVICE_API_KEY = process.env.RAG_SERVICE_API_KEY;

// Upload document
router.post('/upload', upload.single('file'), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'No file uploaded' });
    }
    
    const FormData = require('form-data');
    const fs = require('fs');
    const formData = new FormData();
    
    formData.append('file', fs.createReadStream(req.file.path), {
      filename: req.file.originalname
    });
    
    const response = await axios.post(
      `${RAG_SERVICE_URL}/ingest`,
      formData,
      {
        headers: {
          ...formData.getHeaders(),
          'X-Api-Key': RAG_SERVICE_API_KEY
        }
      }
    );
    
    // Clean up uploaded file
    fs.unlinkSync(req.file.path);
    
    res.json(response.data);
    
  } catch (error) {
    console.error('Upload error:', error.message);
    res.status(500).json({ error: error.message });
  }
});

// Query documents
router.post('/query', async (req, res) => {
  try {
    const { query, k = 3 } = req.body;
    
    const response = await axios.post(
      `${RAG_SERVICE_URL}/query`,
      { query, k },
      { headers: { 'X-Api-Key': RAG_SERVICE_API_KEY } }
    );
    
    res.json(response.data);
    
  } catch (error) {
    console.error('Query error:', error.message);
    res.status(500).json({ error: error.message });
  }
});

// List documents
router.get('/documents', async (req, res) => {
  try {
    const response = await axios.get(
      `${RAG_SERVICE_URL}/documents`,
      { headers: { 'X-Api-Key': RAG_SERVICE_API_KEY } }
    );
    
    res.json(response.data);
    
  } catch (error) {
    console.error('List documents error:', error.message);
    res.status(500).json({ error: error.message });
  }
});

// Delete document
router.delete('/documents/:filename', async (req, res) => {
  try {
    const { filename } = req.params;
    
    const response = await axios.delete(
      `${RAG_SERVICE_URL}/documents/${filename}`,
      { headers: { 'X-Api-Key': RAG_SERVICE_API_KEY } }
    );
    
    res.json(response.data);
    
  } catch (error) {
    console.error('Delete document error:', error.message);
    res.status(500).json({ error: error.message });
  }
});

module.exports = router;
