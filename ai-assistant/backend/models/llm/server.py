"""
LLM Model Inference Server for AWS deployment.
Handles GPT-OSS-20B model inference with GPU acceleration.
"""
import os
import time
import asyncio
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

import torch
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    BitsAndBytesConfig,
    pipeline,
)
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import uvicorn

# Configuration
MODEL_NAME = os.getenv("PRIMARY_MODEL_NAME", "gpt-oss-20b")
MODEL_PATH = os.getenv("PRIMARY_MODEL_PATH", "/models/gpt-oss-20b")
MAX_TOKENS = int(os.getenv("PRIMARY_MODEL_MAX_TOKENS", "4096"))
TEMPERATURE = float(os.getenv("PRIMARY_MODEL_TEMPERATURE", "0.7"))
API_KEY = os.getenv("MODEL_SERVER_API_KEY", "change-this-key")

# Global model variables
tokenizer = None
model = None
pipe = None


class GenerateRequest(BaseModel):
    """Request model for text generation."""
    prompt: str = Field(..., min_length=1, max_length=8000)
    max_tokens: int = Field(default=512, ge=1, le=4096)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    top_k: int = Field(default=50, ge=0, le=100)
    repetition_penalty: float = Field(default=1.1, ge=1.0, le=2.0)
    stream: bool = Field(default=False)
    stop_sequences: Optional[List[str]] = None


class GenerateResponse(BaseModel):
    """Response model for text generation."""
    text: str
    tokens_generated: int
    inference_time: float
    model_name: str


class ModelInfo(BaseModel):
    """Model information."""
    model_name: str
    model_path: str
    device: str
    dtype: str
    max_tokens: int
    loaded: bool


def load_model():
    """Load the model into GPU memory."""
    global tokenizer, model, pipe
    
    print(f"Loading model from {MODEL_PATH}...")
    start_time = time.time()
    
    # Configure 4-bit quantization for memory efficiency
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
    )
    
    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_PATH,
        trust_remote_code=True,
        use_fast=True,
    )
    
    # Add padding token if not present
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    
    # Load model with quantization
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        quantization_config=quantization_config,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.float16,
        low_cpu_mem_usage=True,
    )
    
    # Create text generation pipeline
    pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        device_map="auto",
        max_new_tokens=MAX_TOKENS,
        do_sample=True,
    )
    
    load_time = time.time() - start_time
    print(f"Model loaded successfully in {load_time:.2f}s")
    print(f"Device: {model.device}")
    print(f"Memory allocated: {torch.cuda.memory_allocated(0) / 1024**3:.2f} GB")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for the FastAPI app."""
    # Startup: Load model
    load_model()
    yield
    # Shutdown: Clear memory
    global model, tokenizer, pipe
    del model, tokenizer, pipe
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


# Create FastAPI app
app = FastAPI(
    title="Quant AI Model Server",
    description="LLM inference server for quantitative finance AI",
    version="1.0.0",
    lifespan=lifespan,
)


def verify_api_key(x_api_key: str = Header(...)):
    """Verify API key from request header."""
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Quant AI Model Server",
        "status": "running",
        "model": MODEL_NAME,
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "model_loaded": model is not None,
        "gpu_available": torch.cuda.is_available(),
        "gpu_memory_allocated": f"{torch.cuda.memory_allocated(0) / 1024**3:.2f} GB"
        if torch.cuda.is_available() else "N/A",
    }


@app.get("/info", response_model=ModelInfo)
async def get_model_info(api_key: str = Header(None, alias="X-API-Key")):
    """Get model information."""
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    return ModelInfo(
        model_name=MODEL_NAME,
        model_path=MODEL_PATH,
        device=str(model.device) if model else "not loaded",
        dtype=str(model.dtype) if model else "not loaded",
        max_tokens=MAX_TOKENS,
        loaded=model is not None,
    )


@app.post("/generate", response_model=GenerateResponse)
async def generate_text(
    request: GenerateRequest,
    api_key: str = Header(None, alias="X-API-Key"),
):
    """
    Generate text completion from prompt.
    
    Args:
        request: Generation request parameters
        api_key: API key for authentication
    
    Returns:
        Generated text response
    """
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        start_time = time.time()
        
        # Generate text
        outputs = pipe(
            request.prompt,
            max_new_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            top_k=request.top_k,
            repetition_penalty=request.repetition_penalty,
            do_sample=True,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
            return_full_text=False,
        )
        
        generated_text = outputs[0]["generated_text"]
        
        # Apply stop sequences if provided
        if request.stop_sequences:
            for stop_seq in request.stop_sequences:
                if stop_seq in generated_text:
                    generated_text = generated_text.split(stop_seq)[0]
                    break
        
        inference_time = time.time() - start_time
        
        # Count tokens
        tokens_generated = len(tokenizer.encode(generated_text))
        
        return GenerateResponse(
            text=generated_text,
            tokens_generated=tokens_generated,
            inference_time=inference_time,
            model_name=MODEL_NAME,
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation error: {str(e)}")


@app.post("/generate/stream")
async def generate_text_stream(
    request: GenerateRequest,
    api_key: str = Header(None, alias="X-API-Key"),
):
    """
    Stream text generation (for real-time responses).
    
    Note: Streaming is more complex with transformers pipeline.
    This is a simplified implementation.
    """
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    async def generate_stream():
        """Generator for streaming response."""
        try:
            # Tokenize input
            inputs = tokenizer(request.prompt, return_tensors="pt").to(model.device)
            
            # Generate token by token
            generated_tokens = []
            for _ in range(request.max_tokens):
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=1,
                    temperature=request.temperature,
                    top_p=request.top_p,
                    do_sample=True,
                    pad_token_id=tokenizer.pad_token_id,
                )
                
                # Get new token
                new_token = outputs[0][-1]
                generated_tokens.append(new_token)
                
                # Decode and yield
                token_text = tokenizer.decode([new_token], skip_special_tokens=True)
                yield f"data: {token_text}\n\n"
                
                # Check for stop sequences
                full_text = tokenizer.decode(generated_tokens, skip_special_tokens=True)
                if request.stop_sequences:
                    if any(stop in full_text for stop in request.stop_sequences):
                        break
                
                # Check for EOS token
                if new_token == tokenizer.eos_token_id:
                    break
                
                # Update inputs for next iteration
                inputs["input_ids"] = outputs
                inputs["attention_mask"] = torch.cat([
                    inputs["attention_mask"],
                    torch.ones((1, 1), device=model.device)
                ], dim=1)
                
                await asyncio.sleep(0.01)  # Small delay for streaming effect
            
            yield "data: [DONE]\n\n"
        
        except Exception as e:
            yield f"data: ERROR: {str(e)}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
    )


@app.post("/embeddings")
async def get_embeddings(
    text: str,
    api_key: str = Header(None, alias="X-API-Key"),
):
    """
    Get embeddings for text (if model supports it).
    Note: This is a placeholder - actual implementation depends on model architecture.
    """
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    raise HTTPException(
        status_code=501,
        detail="Embeddings endpoint not implemented for this model"
    )


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        log_level="info",
    )
