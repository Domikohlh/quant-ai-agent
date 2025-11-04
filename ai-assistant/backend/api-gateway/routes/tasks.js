const express = require('express');
const router = express.Router();
const axios = require('axios');

const MODEL_SERVER_URL = process.env.MODEL_SERVER_URL;
const MODEL_SERVER_API_KEY = process.env.MODEL_SERVER_API_KEY;
const GOOGLE_API_KEY = process.env.GOOGLE_API_KEY;

// Generate daily task plan
router.post('/daily-plan', async (req, res) => {
  try {
    const { 
      calendar_events = [], 
      priorities = [],
      context = "",
      location = "Los Angeles, CA"
    } = req.body;
    
    // Get weather data (OpenWeatherMap API - you'll need to add this key)
    let weatherInfo = "Weather data unavailable";
    try {
      const weatherResponse = await axios.get(
        `https://api.openweathermap.org/data/2.5/weather?q=${encodeURIComponent(location)}&appid=${process.env.OPENWEATHER_API_KEY}&units=imperial`
      );
      const weather = weatherResponse.data;
      weatherInfo = `Temperature: ${weather.main.temp}°F, Conditions: ${weather.weather[0].description}`;
    } catch (err) {
      console.log('Weather API error:', err.message);
    }
    
    // Build comprehensive prompt
    const today = new Date().toLocaleDateString('en-US', { 
      weekday: 'long', 
      year: 'numeric', 
      month: 'long', 
      day: 'numeric' 
    });
    
    const prompt = `Create a prioritized task plan for today (${today}).

Calendar Events:
${calendar_events.length > 0 ? calendar_events.map(e => `- ${e.time}: ${e.title}`).join('\n') : '- No scheduled events'}

User Priorities:
${priorities.length > 0 ? priorities.map(p => `- ${p}`).join('\n') : '- None specified'}

Weather: ${weatherInfo}

Additional Context:
${context || 'None'}

Please provide:
1. A prioritized task list (5-8 tasks)
2. Estimated time for each task
3. Resources needed
4. Optimal scheduling around calendar events
5. Any weather-related considerations

Format as JSON:
{
  "tasks": [
    {
      "title": "Task name",
      "priority": "high/medium/low",
      "estimated_time": "30 minutes",
      "resources_needed": ["resource1", "resource2"],
      "suggested_time": "9:00 AM - 9:30 AM",
      "notes": "Additional notes"
    }
  ],
  "daily_summary": "Brief overview of the day"
}`;
    
    const modelResponse = await axios.post(
      `${MODEL_SERVER_URL}/generate`,
      {
        prompt: prompt,
        system_prompt: "You are a productivity AI assistant. Create practical, achievable task plans. Always respond with valid JSON.",
        max_tokens: 800,
        temperature: 0.5
      },
      { headers: { 'X-Api-Key': MODEL_SERVER_API_KEY } }
    );
    
    // Parse JSON response
    let taskPlan;
    try {
      const jsonMatch = modelResponse.data.response.match(/\{[\s\S]*\}/);
      taskPlan = JSON.parse(jsonMatch[0]);
    } catch (parseError) {
      // Fallback if JSON parsing fails
      taskPlan = {
        tasks: [],
        daily_summary: modelResponse.data.response
      };
    }
    
    res.json({
      plan: taskPlan,
      date: today,
      weather: weatherInfo
    });
    
  } catch (error) {
    console.error('Daily plan error:', error.message);
    res.status(500).json({ error: error.message });
  }
});

// Analyze task dependencies
router.post('/analyze', async (req, res) => {
  try {
    const { tasks } = req.body;
    
    const prompt = `Analyze the following tasks and identify:
1. Task dependencies (which tasks should be done before others)
2. Tasks that can be done in parallel
3. Critical path (tasks that must be completed sequentially)
4. Potential bottlenecks

Tasks:
${tasks.map((t, i) => `${i + 1}. ${t.title} (${t.estimated_time})`).join('\n')}

Provide a structured analysis with actionable recommendations.`;
    
    const modelResponse = await axios.post(
      `${MODEL_SERVER_URL}/generate`,
      {
        prompt: prompt,
        system_prompt: "You are a project management AI. Provide clear, structured analysis.",
        max_tokens: 600,
        temperature: 0.4
      },
      { headers: { 'X-Api-Key': MODEL_SERVER_API_KEY } }
    );
    
    res.json({
      analysis: modelResponse.data.response
    });
    
  } catch (error) {
    console.error('Task analysis error:', error.message);
    res.status(500).json({ error: error.message });
  }
});

// Get resources for a task
router.post('/resources', async (req, res) => {
  try {
    const { task_description } = req.body;
    
    // Use Google Custom Search API to find resources
    const searchQuery = encodeURIComponent(`${task_description} tutorial guide resources`);
    const searchUrl = `https://www.googleapis.com/customsearch/v1?key=${GOOGLE_API_KEY}&cx=${process.env.GOOGLE_SEARCH_ENGINE_ID}&q=${searchQuery}`;
    
    let searchResults = [];
    try {
      const searchResponse = await axios.get(searchUrl);
      searchResults = searchResponse.data.items?.slice(0, 5).map(item => ({
        title: item.title,
        link: item.link,
        snippet: item.snippet
      })) || [];
    } catch (searchError) {
      console.log('Search API error:', searchError.message);
    }
    
    // Generate AI recommendations
    const prompt = `Suggest resources and tools needed for the following task:

Task: ${task_description}

${searchResults.length > 0 ? `Relevant search results:\n${searchResults.map(r => `- ${r.title}: ${r.snippet}`).join('\n')}` : ''}

Provide:
1. Essential tools/software needed
2. Skills required
3. Recommended learning resources
4. Step-by-step approach
5. Estimated time to complete`;
    
    const modelResponse = await axios.post(
      `${MODEL_SERVER_URL}/generate`,
      {
        prompt: prompt,
        system_prompt: "You are a helpful AI assistant providing practical guidance.",
        max_tokens: 500,
        temperature: 0.6
      },
      { headers: { 'X-Api-Key': MODEL_SERVER_API_KEY } }
    );
    
    res.json({
      recommendations: modelResponse.data.response,
      search_results: searchResults
    });
    
  } catch (error) {
    console.error('Resources error:', error.message);
    res.status(500).json({ error: error.message });
  }
});

module.exports = router;
