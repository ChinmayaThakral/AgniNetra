"""TerraMind site embeddings for baseline B4.

The backbone is frozen. B4 is a linear probe on the embedding, which is what makes
it a foundation model baseline rather than a fine tuned model. D35.

**The input scaling is unverified.** TerraTorch ships no standardisation constants
for the S2L2A modality, so the divisor below is the ordinary Sentinel-2 reflectance
convention rather than a value read from the TerraMind model card. A wrong scale
does not fail: it degrades the embedding and yields a low probe score that reads as
a finding about foundation models. This must be checked against the published
TerraMind preprocessing before any B4 number is reported. D57.
"""

from typing import Final

import numpy as np

BACKBONE: Final[str] = "terratorch_terramind_v1_base"
EMBED_DIM: Final[int] = 768
MODALITY: Final[str] = "S2L2A"
# Unverified, see the module docstring.
REFLECTANCE_SCALE: Final[float] = 10000.0


class EmbeddingError(RuntimeError):
    """Raised when the backbone returns something that is not a usable embedding."""


def load_backbone():
    """Return the frozen pretrained backbone in eval mode."""
    import torch
    from terratorch.registry import BACKBONE_REGISTRY

    model = BACKBONE_REGISTRY.build(BACKBONE, pretrained=True, modalities=[MODALITY])
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad = False
    return model, torch


def embed_chips(model, torch, chips: np.ndarray, batch_size: int = 8) -> np.ndarray:
    """Return an (n, 768) array of L2 normalised site embeddings.

    Input is (n, 12, 224, 224) in raw L2A digital numbers. Raises EmbeddingError
    on a non finite embedding rather than letting a NaN reach the probe, where it
    would train silently and score as a real result.
    """
    if chips.ndim != 4 or chips.shape[1] != 12:
        raise EmbeddingError(f"expected (n, 12, 224, 224) chips, got {chips.shape}")

    outputs = []
    with torch.no_grad():
        for start in range(0, len(chips), batch_size):
            batch = chips[start : start + batch_size] / REFLECTANCE_SCALE
            tensor = torch.from_numpy(np.ascontiguousarray(batch, dtype=np.float32))
            result = model(tensor)
            tokens = result[-1] if isinstance(result, (list, tuple)) else result
            pooled = tokens.mean(dim=1) if tokens.ndim == 3 else tokens
            outputs.append(pooled.cpu().numpy())

    embeddings = np.concatenate(outputs, axis=0)
    if embeddings.shape[1] != EMBED_DIM:
        raise EmbeddingError(f"expected {EMBED_DIM} dimensions, got {embeddings.shape[1]}")
    if not np.isfinite(embeddings).all():
        raise EmbeddingError("backbone returned a non finite embedding")

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    if (norms == 0).any():
        raise EmbeddingError("backbone returned a zero embedding, which cannot be normalised")
    return embeddings / norms
