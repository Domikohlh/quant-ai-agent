"""
Download and prepare models for deployment.

This script downloads:
1. Primary model (GPT-OSS-20B) - for AWS deployment
2. Local fallback model (Llama 3.2 3B) - for on-device inference
3. Embedding model for RAG
"""
import os
import sys
from pathlib import Path
from huggingface_hub import snapshot_download, login
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.core.config.settings import settings
from backend.utils.logging.logger import get_logger

logger = get_logger(__name__)


def download_primary_model():
    """Download primary model (GPT-OSS-20B)."""
    logger.info("Downloading primary model: GPT-OSS-20B")
    
    # Note: Replace with actual model repo when available
    # GPT-OSS-20B is a placeholder - use actual HuggingFace model ID
    model_id = "OpenGPT-X/GPT-X-20B"  # Example - replace with actual
    
    try:
        # Download model
        model_path = snapshot_download(
            repo_id=model_id,
            local_dir=settings.primary_model_path,
            local_dir_use_symlinks=False,
            resume_download=True,
        )
        
        logger.info(f"Primary model downloaded to: {model_path}")
        
        # Verify model can be loaded
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        logger.info("✅ Primary model tokenizer loaded successfully")
        
        return True
    
    except Exception as e:
        logger.error(f"Failed to download primary model: {e}")
        logger.warning("You may need to manually download the model")
        return False


def download_local_model():
    """Download local fallback model (Llama 3.2 3B)."""
    logger.info("Downloading local model: Llama 3.2 3B")
    
    model_id = "meta-llama/Llama-3.2-3B-Instruct"
    
    try:
        # Download model
        model_path = snapshot_download(
            repo_id=model_id,
            local_dir=settings.local_model_path,
            local_dir_use_symlinks=False,
            resume_download=True,
        )
        
        logger.info(f"Local model downloaded to: {model_path}")
        
        # Verify model can be loaded
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        logger.info("✅ Local model tokenizer loaded successfully")
        
        return True
    
    except Exception as e:
        logger.error(f"Failed to download local model: {e}")
        logger.warning(
            "If this is a gated model, you need to:\n"
            "1. Accept the license at https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct\n"
            "2. Set HF_TOKEN environment variable with your HuggingFace token"
        )
        return False


def download_embedding_model():
    """Download embedding model for RAG."""
    logger.info("Downloading embedding model")
    
    model_id = settings.embedding_model
    
    try:
        from sentence_transformers import SentenceTransformer
        
        # Download and cache model
        model = SentenceTransformer(model_id)
        
        logger.info(f"✅ Embedding model loaded: {model_id}")
        
        # Test embedding
        test_embedding = model.encode("test sentence")
        logger.info(f"Embedding dimension: {len(test_embedding)}")
        
        return True
    
    except Exception as e:
        logger.error(f"Failed to download embedding model: {e}")
        return False


def estimate_model_sizes():
    """Estimate disk space requirements."""
    logger.info("Estimating model sizes:")
    logger.info("  - Primary model (GPT-OSS-20B): ~40 GB")
    logger.info("  - Local model (Llama 3.2 3B): ~6 GB")
    logger.info("  - Embedding model: ~90 MB")
    logger.info("  - Total: ~46 GB")
    logger.info("")
    logger.info("Ensure you have sufficient disk space before proceeding.")


def main():
    """Main download function."""
    logger.info("🚀 Starting model download process")
    
    # Check for HuggingFace token
    hf_token = os.getenv("HF_TOKEN")
    if hf_token:
        logger.info("Using HuggingFace token for authentication")
        login(token=hf_token)
    else:
        logger.warning(
            "No HF_TOKEN found. Some models may require authentication.\n"
            "Set HF_TOKEN environment variable if needed."
        )
    
    # Create model directories
    os.makedirs(settings.primary_model_path, exist_ok=True)
    os.makedirs(settings.local_model_path, exist_ok=True)
    
    # Estimate sizes
    estimate_model_sizes()
    
    # Ask for confirmation
    response = input("\nProceed with download? (yes/no): ")
    if response.lower() != "yes":
        logger.info("Download cancelled")
        return
    
    # Download models
    results = []
    
    logger.info("\n" + "="*60)
    results.append(("Primary Model", download_primary_model()))
    
    logger.info("\n" + "="*60)
    results.append(("Local Model", download_local_model()))
    
    logger.info("\n" + "="*60)
    results.append(("Embedding Model", download_embedding_model()))
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("Download Summary:")
    for name, success in results:
        status = "✅" if success else "❌"
        logger.info(f"  {status} {name}")
    
    all_success = all(success for _, success in results)
    
    if all_success:
        logger.info("\n✅ All models downloaded successfully!")
        logger.info("\nNext steps:")
        logger.info("  1. Review model files in data/models/")
        logger.info("  2. Run: python scripts/deployment/test_models.py")
        logger.info("  3. Deploy to AWS: ./scripts/deployment/deploy_aws.sh")
    else:
        logger.warning("\n⚠️  Some models failed to download")
        logger.warning("Please review errors above and retry")
        sys.exit(1)


if __name__ == "__main__":
    main()
