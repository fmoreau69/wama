# WAMA Imager - AI Models

This directory contains AI models for video generation in the WAMA Imager application.

## Directory Structure

```
imager/
├── README.md (this file)
└── wan/
    └── models--Wan-AI--*/  (auto-downloaded from Hugging Face)
```

## Available Models

### Text-to-Video (TI2V)

| Model            | ID            | Size | VRAM Required |
|------------------|---------------|------|---------------|
| Wan 2.2 TI2V 5B | `wan-ti2v-5b` | ~5GB | ~8GB |

**Hugging Face**: [Wan-AI/Wan2.2-TI2V-5B-Diffusers](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers)

### Text-to-Video (T2V)

| Model           | ID            | Size | VRAM Required |
|-----------------|---------------|------|---------------|
| Wan 2.2 T2V 14B | `wan-t2v-14b` | ~25GB | ~24GB+ |

**Hugging Face**: [Wan-AI/Wan2.2-T2V-A14B-Diffusers](https://huggingface.co/Wan-AI/Wan2.2-T2V-A14B-Diffusers)

### Image-to-Video (I2V)

| Model | ID | Size | VRAM Required |
|-------|-----|------|---------------|
| Wan 2.2 I2V 14B | `wan-i2v-14b` | ~25GB | ~24GB+ |

**Hugging Face**: [Wan-AI/Wan2.2-I2V-A14B-Diffusers](https://huggingface.co/Wan-AI/Wan2.2-I2V-A14B-Diffusers)

## Automatic Download

Models are automatically downloaded from Hugging Face when first used.
The download location is `AI-models/imager/wan/`.

### First-time download times (approximate)

- **Wan TI2V 5B**: 5-10 minutes (~16GB)
- **Wan T2V 14B**: 20-40 minutes (~25GB)
- **Wan I2V 14B**: 20-40 minutes (~25GB)

## Manual Download

If you prefer to pre-download models:

```bash
# Install huggingface-cli
pip install huggingface_hub

# Download T2V model (1.3B - recommended for most users)
huggingface-cli download Wan-AI/Wan2.1-T2V-1.3B-Diffusers \
    --local-dir AI-models/imager/wan/models--Wan-AI--Wan2.1-T2V-1.3B-Diffusers

# Download I2V model (14B - requires high-end GPU)
huggingface-cli download Wan-AI/Wan2.2-I2V-A14B-Diffusers \
    --local-dir AI-models/imager/wan/models--Wan-AI--Wan2.2-I2V-A14B-Diffusers
```

## Requirements

### For T2V (Text-to-Video)
- GPU with 8GB+ VRAM (RTX 3070, RTX 4060 or better)
- Or CPU with 16GB+ RAM (very slow)

### For I2V (Image-to-Video)
- GPU with 24GB+ VRAM (RTX 3090, RTX 4090, A100)
- CPU offload enabled automatically for lower VRAM GPUs

## Dependencies

```bash
pip install torch torchvision
pip install diffusers transformers accelerate
pip install ftfy  # Required by Wan models
```

For the latest I2V support, install diffusers from GitHub:
```bash
pip install git+https://github.com/huggingface/diffusers
```

## Disk Usage

| Model                  | Disk Space |
|------------------------|------------|
| Wan TI2V 5B            | ~16GB       |
| Wan T2V 14B            | ~25GB      |
| Wan I2V 14B            | ~25GB      |
| **Total (all models)** | **~30GB**  |

## Clearing Cache

To remove downloaded models and free disk space:

```bash
# Remove all Wan models
rm -rf AI-models/imager/wan/

# Models will be re-downloaded on next use
```

## Troubleshooting

### "CUDA out of memory"
- Use a smaller model (T2V 1.3B instead of I2V 14B)
- Reduce video resolution (480p instead of 720p)
- Close other GPU-intensive applications
- CPU offload is enabled automatically for low VRAM

### "Model not found" errors
- Check your internet connection
- Verify Hugging Face is accessible
- Try pre-downloading the model manually

### Slow generation
- Ensure you're using a CUDA-capable GPU
- Check that PyTorch is using CUDA: `torch.cuda.is_available()`
- T2V 1.3B: ~2-5 minutes per 5s video on RTX 4090
- I2V 14B: ~5-15 minutes per 5s video on RTX 4090

## License

Wan models are released under the **Apache 2.0** license.

## Links

- [Wan Video GitHub](https://github.com/Wan-Video/Wan2.2)
- [Wan-AI on Hugging Face](https://huggingface.co/Wan-AI)
- [Diffusers Documentation](https://huggingface.co/docs/diffusers)
