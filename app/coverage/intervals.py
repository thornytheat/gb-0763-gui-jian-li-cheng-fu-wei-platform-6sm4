def union(intervals):
    merged = []
    for lo, hi in sorted((lo, hi) for lo, hi in intervals if lo < hi):
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return merged


def total(intervals):
    return sum(hi - lo for lo, hi in intervals)


def clip(intervals, bounds):
    frames = union(bounds)
    pieces = []
    for lo, hi in intervals:
        pieces.extend((max(lo, mark), min(hi, bound))
                      for mark, bound in frames if max(lo, mark) < min(hi, bound))
    return pieces


def subtract(intervals, cuts):
    blocks = union(cuts)
    remaining = []
    for lo, hi in union(intervals):
        cursor = lo
        for mark, bound in blocks:
            if bound <= cursor or mark >= hi:
                continue
            if mark > cursor:
                remaining.append([cursor, mark])
            cursor = bound
        if cursor < hi:
            remaining.append([cursor, hi])
    return remaining
