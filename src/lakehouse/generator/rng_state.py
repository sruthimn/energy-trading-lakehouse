"""Save and restore a random generator, so a simulation can continue later."""


def encode_rng(state: tuple) -> list:
    """The generator state as plain lists, so it can be saved as JSON."""
    version, internal, gauss = state
    return [version, list(internal), gauss]


def decode_rng(data: list) -> tuple:
    return (data[0], tuple(data[1]), data[2])
