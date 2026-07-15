"""File-processing service.

Houses the processing logic invoked by the API layer, keeping route
handlers thin.
"""

from dtos.requests import ChunkingStrategy, FixedSizeChunkingRequest


def process_file(
    content: bytes,
    strategy: ChunkingStrategy,
    fixed_size: FixedSizeChunkingRequest | None = None,
) -> bool:
    """Process an uploaded file with the given chunking strategy.

    ``fixed_size`` carries the fixed-size chunking parameters and is required
    when ``strategy`` is :attr:`ChunkingStrategy.fixed`.

    Returns True when processing succeeds. Currently this validates that the
    file has content; real chunking logic is wired in as the pipeline matures.
    """
    if strategy is ChunkingStrategy.fixed and fixed_size is None:
        raise ValueError("fixed_size parameters are required for the 'fixed' strategy")
    return len(content) > 0
