# agents/sentiment_analyst.py
import os
import json
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import ToolMessage, AIMessage
from langchain_core.pydantic_v1 import BaseModel, Field

from core.state import AgentState
from tools.news_data import news_tools, fetch_financial_news

# ==========================================
# 1. CONFIGURATION
# ==========================================
# Gemini 3.0 Flash: High context, low cost, decent reasoning
MODEL_NAME = "gemini-3.0-flash-001" 

# ==========================================
# 2. OUTPUT SCHEMA
# ==========================================
class SentimentScore(BaseModel):
    ticker: str
    score: float = Field(description="Sentiment score between -1.0 (Bearish) and 1.0 (Bullish). 0 is Neutral.")
    summary: str = Field(description="One sentence summary of the primary driver for this score.")

class SentimentReport(BaseModel):
    reports: list[SentimentScore]
    market_sentiment: str = Field(description="Overall market mood: 'FEAR', 'NEUTRAL', 'GREED'")

# ==========================================
# 3. AGENT LOGIC
# ==========================================
def sentiment_analyst_node(state: AgentState):
    """
    The Sentiment Analyst.
    1. Reads tickers from 'market_data'.
    2. Fetches news for each.
    3. Calculates a sentiment score (0.0 to 1.0).
    """
    
    # Auth
    credentials, project_id = google.auth.default()
    
    # Initialize LLM with Vertex AI
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        credentials=credentials,
        temperature=0.1 # Low temp for consistent scoring
    )

    # 1. Identify Tickers from State
    market_data = state.get("market_data", {})
    # Handle structure: market_data might be {'stocks': {...}, 'macro': {...}}
    stocks_data = market_data.get("stocks", {})
    tickers = list(stocks_data.keys())
    
    if not tickers:
        # Fallback if Data Engineer failed or wasn't run
        tickers = ["AAPL", "NVDA", "TSLA", "MSFT"] 

    # 2. Fetch News (Manual Tool Execution for Batch Efficiency)
    # Instead of making the LLM call the tool 4 times (4 round trips),
    # we pre-fetch the data here in Python. This is faster and cheaper.
    
    news_corpus = {}
    for ticker in tickers:
        news_items = fetch_financial_news(ticker, count=5)
        news_corpus[ticker] = "\n".join(news_items)

    # 3. Analyze Sentiment
    # We construct a single prompt to analyze ALL tickers at once.
    # This maximizes the efficiency of Gemini's context window.
    
    system_prompt = (
        "You are a Senior Sentiment Analyst for a hedge fund.\n"
        "Your job is to read financial news and assign a Sentiment Score (-1.0 to 1.0) for each asset.\n\n"
        "SCORING RULES:\n"
        "-1.0: Catastrophic news (bankruptcy, regulatory ban, massive recall).\n"
        "-0.5: Bad earnings, analyst downgrade, negative macro impact.\n"
        " 0.0: No significant news or balanced news.\n"
        "+0.5: Beat earnings, product launch, analyst upgrade.\n"
        "+1.0: Game-changing partnership, massive earnings surprise, regulatory win.\n\n"
        "INPUT DATA:\n"
    )
    
    # Inject the news directly into the prompt
    user_content = "Analyze the following news:\n\n"
    for ticker, news in news_corpus.items():
        user_content += f"--- {ticker} ---\n{news}\n\n"

    # Define Chain
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("user", user_content)
    ])
    
    # We use 'with_structured_output' to get clean JSON back
    chain = prompt | llm.with_structured_output(SentimentReport)
    
    try:
        report = chain.invoke({})
        print(f"🧠 SENTIMENT ANALYSIS COMPLETE: {report.market_sentiment}")
        for item in report.reports:
            print(f"   - {item.ticker}: {item.score} ({item.summary})")
            
        # Convert Pydantic to Dict for State storage
        sentiment_data = {
            "overall_mood": report.market_sentiment,
            "scores": {item.ticker: item.score for item in report.reports},
            "summaries": {item.ticker: item.summary for item in report.reports}
        }
        
    except Exception as e:
        print(f"⚠️ SENTIMENT ERROR: {e}")
        sentiment_data = {"error": str(e)}

    # Return updated state
    return {
        "sentiment_data": sentiment_data,
        # We append a simple AI message to history so the supervisor knows what happened
        "messages": [AIMessage(content=f"Sentiment Analysis complete. Market Mood: {sentiment_data.get('overall_mood', 'Unknown')}")]
    }
