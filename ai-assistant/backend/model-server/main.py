from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
import torch
from transformers import (
    AutoModelForCausalLM, 
    AutoTokenizer,
    BitsAndBytesConfig,
    GenerationConfig
)
from config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Assistant Model Server - GPT-OSS-20B")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request/Response Models
class GenerateRequest(BaseModel):
    prompt: str = Field(..., description="Input prompt for the model")
    max_tokens: int = Field(500, ge=1, le=2048)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    top_p: float = Field(0.9, ge=0.0, le=1.0)
    top_k: int = Field(50, ge=0, le=100)
    repetition_penalty: float = Field(1.1, ge=1.0, le=2.0)
    system_prompt: Optional[str] = None

class GenerateResponse(BaseModel):
    response: str
    tokens_used: int
    model: str
    generation_time: float

class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    model_name: str
    device: str
    vram_used: Optional[float] = None

# Security
async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return x_api_key

# Model Server Class for GPT-OSS-20B
class GPTOSSModelServer:
    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.device = settings.DEVICE
        self.generation_config = None
        
    def load_model(self):
        """Load GPT-OSS-20B with optimizations"""
        logger.info(f"Loading model: {settings.MODEL_NAME}")
        
        # Configure quantization for 20B model
        if settings.USE_QUANTIZATION:
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True if settings.QUANTIZATION_BITS == 4 else False,
                load_in_8bit=True if settings.QUANTIZATION_BITS == 8 else False,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4"  # Normal Float 4-bit
            )
        else:
            quantization_config = None
        
        # Load tokenizer
        logger.info("Loading tokenizer...")
        self.tokenizer = AutoTokenizer.from_pretrained(
            settings.MODEL_NAME,
            cache_dir=settings.MODEL_CACHE_DIR,
            token=settings.HUGGINGFACE_TOKEN if settings.HUGGINGFACE_TOKEN else None,
            trust_remote_code=True  # GPT-OSS may need this
        )
        
        # Set pad token if not exists
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        
        # Load model with optimizations
        logger.info("Loading model (this may take several minutes)...")
        
        load_kwargs = {
            "cache_dir": settings.MODEL_CACHE_DIR,
            "device_map": "auto",
            "torch_dtype": torch.float16,
            "trust_remote_code": True,
        }
        
        if settings.HUGGINGFACE_TOKEN:
            load_kwargs["token"] = settings.HUGGINGFACE_TOKEN
        
        if quantization_config:
            load_kwargs["quantization_config"] = quantization_config
        
        self.model = AutoModelForCausalLM.from_pretrained(
            settings.MODEL_NAME,
            **load_kwargs
        )
        
        # Configure generation settings optimized for GPT-OSS
        self.generation_config = GenerationConfig(
            do_sample=True,
            temperature=settings.DEFAULT_TEMPERATURE,
            top_p=settings.DEFAULT_TOP_P,
            top_k=settings.DEFAULT_TOP_K,
            repetition_penalty=1.1,
            pad_token_id=self.tokenizer.pad_token_id,
            eos_token_id=self.tokenizer.eos_token_id,
            max_new_tokens=500,
        )
        
        logger.info(f"Model loaded successfully on {self.device}")
        logger.info(f"Model size: ~20B parameters")
        
        # Log VRAM usage
        if torch.cuda.is_available():
            vram_allocated = torch.cuda.memory_allocated() / 1024**3
            vram_reserved = torch.cuda.memory_reserved() / 1024**3
            logger.info(f"VRAM allocated: {vram_allocated:.2f}GB")
            logger.info(f"VRAM reserved: {vram_reserved:.2f}GB")
    
    def format_prompt(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Format prompt for GPT-OSS-20B
        Adjust this based on the specific prompt format GPT-OSS expects
        """
        if system_prompt:
            # Format with system context
            formatted = f"""### System:
{system_prompt}

### User:
{prompt}

### Assistant:
"""
        else:
            # Simple format
            formatted = f"""### User:
{prompt}

### Assistant:
"""
        
        return formatted
    
    def generate(
        self, 
        prompt: str, 
        max_tokens: int,
        temperature: float,
        top_p: float,
        top_k: int,
        repetition_penalty: float,
        system_prompt: Optional[str] = None
    ) -> tuple[str, int, float]:
        """Generate text using GPT-OSS-20B"""
        
        import time
        start_time = time.time()
        
        # Format prompt
        formatted_prompt = self.format_prompt(prompt, system_prompt)
        
        # Tokenize
        inputs = self.tokenizer(
            formatted_prompt, 
            return_tensors="pt",
            truncation=True,
            max_length=settings.MAX_LENGTH - max_tokens,
            padding=False
        ).to(self.device)
        
        input_length = inputs['input_ids'].shape[1]
        
        # Update generation config
        gen_config = GenerationConfig(
            do_sample=True,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            repetition_penalty=repetition_penalty,
            pad_token_id=self.tokenizer.pad_token_id,
            eos_token_id=self.tokenizer.eos_token_id,
            max_new_tokens=max_tokens,
        )
        
        # Generate
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                generation_config=gen_config,
                return_dict_in_generate=True,
                output_scores=False
            )
        
        # Decode only the generated part
        generated_ids = outputs.sequences[0][input_length:]
        generated_text = self.tokenizer.decode(
            generated_ids, 
            skip_special_tokens=True,
            clean_up_tokenization_spaces=True
        )
        
        generation_time = time.time() - start_time
        tokens_generated = len(generated_ids)
        
        logger.info(f"Generated {tokens_generated} tokens in {generation_time:.2f}s "
                   f"({tokens_generated/generation_time:.2f} tokens/s)")
        
        return generated_text.strip(), tokens_generated, generation_time

# Initialize model server
model_server = GPTOSSModelServer()

@app.on_event("startup")
async def startup_event():
    """Load model on startup"""
    logger.info("Starting GPT-OSS-20B model server...")
    try:
        model_server.load_model()
        logger.info("Model server ready!")
    except Exception as e:
        logger.error(f"Failed to load model: {str(e)}")
        raise

@app.post("/generate", response_model=GenerateResponse, dependencies=[Depends(verify_api_key)])
async def generate(request: GenerateRequest):
    """Generate text from prompt"""
    try:
        response, tokens, gen_time = model_server.generate(
            prompt=request.prompt,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            top_k=request.top_k,
            repetition_penalty=request.repetition_penalty,
            system_prompt=request.system_prompt
        )
        
        return GenerateResponse(
            response=response,
            tokens_used=tokens,
            model=settings.MODEL_NAME,
            generation_time=gen_time
        )
    
    except Exception as e:
        logger.error(f"Generation error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    vram_used = None
    if torch.cuda.is_available() and model_server.model is not None:
        vram_used = torch.cuda.memory_allocated() / 1024**3
    
    return HealthResponse(
        status="healthy" if model_server.model is not None else "unhealthy",
        model_loaded=model_server.model is not None,
        model_name=settings.MODEL_NAME,
        device=settings.DEVICE,
        vram_used=vram_used
    )

@app.post("/reload", dependencies=[Depends(verify_api_key)])
async def reload_model():
    """Reload model (useful after fine-tuning)"""
    try:
        # Clear existing model
        if model_server.model is not None:
            del model_server.model
            torch.cuda.empty_cache()
        
        model_server.load_model()
        return {"status": "success", "message": "Model reloaded"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
async def get_stats():
    """Get model statistics"""
    stats = {
        "model_name": settings.MODEL_NAME,
        "device": settings.DEVICE,
    }
    
    if torch.cuda.is_available():
        stats.update({
            "gpu_name": torch.cuda.get_device_name(0),
            "vram_allocated_gb": torch.cuda.memory_allocated() / 1024**3,
            "vram_reserved_gb": torch.cuda.memory_reserved() / 1024**3,
            "vram_total_gb": torch.cuda.get_device_properties(0).total_memory / 1024**3,
        })
    
    return stats

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        workers=settings.WORKERS,
        reload=False
    )
