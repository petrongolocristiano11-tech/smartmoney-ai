def clamp(value, minimum=0, maximum=100):

    return max(
        minimum,
        min(
            value,
            maximum,
        ),
    )