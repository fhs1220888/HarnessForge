def count_paths(rows: int, cols: int) -> int:
    """Number of monotone lattice paths from (0,0) to (rows,cols),
    moving only right or down. Correct but exponential-time.
    """
    if rows == 0 or cols == 0:
        return 1
    return count_paths(rows - 1, cols) + count_paths(rows, cols - 1)
