const express = require('express');
const router = express.Router();
const Alpaca = require('@alpacahq/alpaca-trade-api');
const axios = require('axios');

const alpaca = new Alpaca({
  keyId: process.env.ALPACA_KEY_ID,
  secretKey: process.env.ALPACA_SECRET_KEY,
  paper: process.env.ALPACA_PAPER === 'true'
});

const MODEL_SERVER_URL = process.env.MODEL_SERVER_URL;
const MODEL_SERVER_API_KEY = process.env.MODEL_SERVER_API_KEY;

// Get stock summary
router.post('/summary', async (req, res) => {
  try {
    const { symbols } = req.body; // e.g., ["AAPL", "GOOGL", "MSFT"]
    
    // Get latest bars for each symbol
    const bars = await alpaca.getBarsV2(symbols.join(','), {
      start: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
      end: new Date().toISOString(),
      timeframe: '1Day',
      limit: 1
    });
    
    const stockData = [];
    for await (const bar of bars) {
      stockData.push({
        symbol: bar.Symbol,
        open: bar.OpenPrice,
        high: bar.HighPrice,
        low: bar.LowPrice,
        close: bar.ClosePrice,
        volume: bar.Volume,
        timestamp: bar.Timestamp
      });
    }
    
    // Get latest news
    const news = await alpaca.getNews({
      symbols: symbols.join(','),
      limit: 10
    });
    
    const newsData = news.map(article => ({
      headline: article.headline,
      summary: article.summary,
      url: article.url,
      created_at: article.created_at
    }));
    
    // Generate AI summary
    const prompt = `Analyze the following stock market data and provide a brief summary:

Stock Data:
${JSON.stringify(stockData, null, 2)}

Recent News:
${newsData.map(n => `- ${n.headline}: ${n.summary}`).join('\n')}

Provide:
1. Key trends for each stock
2. Notable market movements
3. Important news highlights
4. Brief actionable insights

Keep it concise (under 300 words).`;
    
    const modelResponse = await axios.post(
      `${MODEL_SERVER_URL}/generate`,
      {
        prompt: prompt,
        system_prompt: "You are a financial analyst AI. Provide clear, factual analysis without giving specific investment advice.",
        max_tokens: 600,
        temperature: 0.3
      },
      { headers: { 'X-Api-Key': MODEL_SERVER_API_KEY } }
    );
    
    res.json({
      summary: modelResponse.data.response,
      raw_data: {
        stocks: stockData,
        news: newsData
      }
    });
    
  } catch (error) {
    console.error('Stock summary error:', error.message);
    res.status(500).json({ error: error.message });
  }
});

// Get filtered news by keywords
router.post('/news', async (req, res) => {
  try {
    const { symbols, keywords = [] } = req.body;
    
    const news = await alpaca.getNews({
      symbols: symbols.join(','),
      limit: 50
    });
    
    // Filter by keywords if provided
    let filteredNews = news;
    if (keywords.length > 0) {
      filteredNews = news.filter(article => 
        keywords.some(keyword => 
          article.headline.toLowerCase().includes(keyword.toLowerCase()) ||
          article.summary.toLowerCase().includes(keyword.toLowerCase())
        )
      );
    }
    
    res.json({
      news: filteredNews.slice(0, 10).map(article => ({
        headline: article.headline,
        summary: article.summary,
        url: article.url,
        symbols: article.symbols,
        created_at: article.created_at
      }))
    });
    
  } catch (error) {
    console.error('News filter error:', error.message);
    res.status(500).json({ error: error.message });
  }
});

// Get current market status
router.get('/market-status', async (req, res) => {
  try {
    const clock = await alpaca.getClock();
    
    res.json({
      is_open: clock.is_open,
      next_open: clock.next_open,
      next_close: clock.next_close,
      timestamp: clock.timestamp
    });
    
  } catch (error) {
    console.error('Market status error:', error.message);
    res.status(500).json({ error: error.message });
  }
});

module.exports = router;
