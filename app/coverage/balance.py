from .intervals import clip, subtract, total, union


def balance(plan, segments, gaps):
    chains = list(dict.fromkeys(item['chain'] for item in plan))
    tracks, missing_parts = [], []
    planned_mm = mapped_mm = overlap_mm = 0
    for chain in chains:
        planned = union((item['start_mm'], item['end_mm']) for item in plan if item['chain'] == chain)
        raw = [tuple(sorted((span['left']['station_mm'], span['right']['station_mm'])))
               for span in segments if span['left']['chain'] == chain]
        clipped = clip(raw, planned)
        mapped = union(clipped)
        row_planned, row_mapped = total(planned), total(mapped)
        planned_mm += row_planned
        mapped_mm += row_mapped
        overlap_mm += total(clipped) - row_mapped
        for lo, hi in subtract(planned, mapped):
            hits = [gap for gap in gaps if gap['chain'] == chain and gap['start_mm'] < hi and lo < gap['end_mm']]
            missing_parts.append({'chain': chain, 'start_mm': lo, 'end_mm': hi,
                                  'reasons': sorted({gap['reason'] for gap in hits}) or ['NO_COVERAGE'],
                                  'sources': sorted({line for gap in hits for line in gap['sources']})})
        tracks.append({'chain': chain, 'planned_mm': row_planned, 'mapped_mm': row_mapped,
                       'start_mm': min((item['start_mm'] for item in plan if item['chain'] == chain), default=0),
                       'end_mm': max((item['end_mm'] for item in plan if item['chain'] == chain), default=0),
                       'mapped_parts': mapped})
    return {'planned_mm': planned_mm, 'mapped_mm': mapped_mm, 'missing_mm': planned_mm - mapped_mm,
            'overlap_mm': overlap_mm, 'tracks': tracks, 'missing_parts': missing_parts}
