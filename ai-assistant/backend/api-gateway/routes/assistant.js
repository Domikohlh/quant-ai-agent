const express = require('express');
const router = express.Router();
const axios = require('axios');

const MODEL_SERVER_URL = process.env.MODEL_SERVER_URL;
const MODEL_SERVER_API_KEY = process.env.MODEL_SERVER_API_KEY;
const RAG_SERVICE_URL = process.env.RAG_SERVICE_URL;
const RAG_SERVICE_API_KEY = process.env.RAG_SERVICE_API_KEY;

// Chat endpoint
router.post('/chat', async (req, res) => {
  try {
    const { message, use_rag = false, context = null } = req.body;
    
    let prompt = message;
    let systemPrompt = "You are a helpful AI assistant. Be concise and accurate.";
    
    // If RAG is enabled, retrieve relevant context
    if (use_rag) {
      try {
        const ragResponse = await axios.post(
          `${RAG_SERVICE_URL}/query`,
          { query: message, k: 3 },
          { headers: { 'X-Api-Key': RAG_SERVICE_API_KEY } }
        );
        
        const ragContext = ragResponse.data.context;
        systemPrompt = `You are a helpful AI assistant. Answer based on the following context from the user's documents:

${ragContext}

If the answer is not in the context, say so. Be concise and accurate.`;
      } catch (ragError) {
        console.error('RAG query failed:', ragError.message);
        // Continue without RAG if it fails
      }
    }
    
    // Add additional context if provided
    if (context) {
      prompt = `${context}\n\nUser query: ${message}`;
    }
    
    // Call model server
    const modelResponse = await axios.post(
      `${MODEL_SERVER_URL}/generate`,
      {
        prompt: prompt,
        system_prompt: systemPrompt,
        max_tokens: 500,
        temperature: 0.7
      },
      { headers: { 'X-Api-Key': MODEL_SERVER_API_KEY } }
    );
    
    res.json({
      response: modelResponse.data.response,
      tokens_used: modelResponse.data.tokens_used,
      used_rag: use_rag
    });
    
  } catch (error) {
    console.error('Chat error:', error.message);
    res.status(500).json({ error: error.message });
  }
});

module.exports = router;
