"""Request DTOs for the embedding stage.

Configuration for turning chunk text into vectors. The model and the compute
device are both configurable so evals can compare embedding models
apples-to-apples (see CLAUDE.md) and run wherever the hardware allows.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# Default sentence-transformers model. 768-dimensional, a strong general-purpose
# baseline; swap it via ``EmbeddingRequest.model_name`` to compare alternatives.
DEFAULT_MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"


class Device(str, Enum):
    """Compute backends a torch model can run on.

    Covers the device *types* torch/sentence-transformers accept as a device
    string. Specific indices (e.g. ``cuda:1``) are not modelled — ``cuda``
    targets the default accelerator.
    """

    cpu = "cpu"
    cuda = "cuda"
    mps = "mps"
    xpu = "xpu"


class EmbeddingRequest(BaseModel):
    """Parameters for the embedding stage.

    ``model_name`` is any sentence-transformers model id (defaults to
    all-mpnet-base-v2). ``device`` selects the compute backend and defaults to
    CPU, which runs everywhere.
    """

    # ``model_name`` collides with Pydantic's protected ``model_`` namespace;
    # opt out so the plain field name is usable.
    model_config = ConfigDict(protected_namespaces=())

    model_name: str = Field(
        default=DEFAULT_MODEL_NAME,
        min_length=1,
        description="sentence-transformers model id used to embed chunk text.",
    )
    device: Device = Field(
        default=Device.cpu,
        description="Compute backend to load the model on.",
    )
