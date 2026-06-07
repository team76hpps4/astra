def get_bonding_table(primary_channel):
    """Return valid 20/40/80 MHz bonding groups for a given primary channel."""
    # UNII-1 (36–48)
    if primary_channel == 36:
        return {
            20: [36],
            40: [36, 40],
            80: [36, 40, 44, 48],
        }

    if primary_channel == 40:
        return {
            20: [40],
            40: [36, 40],
            80: [36, 40, 44, 48],
        }

    # UNII-2A (52–64) DFS
    if primary_channel == 52:
        return {
            20: [52],
            40: [52, 56],
            80: [52, 56, 60, 64],
        }

    if primary_channel == 56:
        return {
            20: [56],
            40: [52, 56],
            80: [52, 56, 60, 64],
        }

    # UNII-2C (100–144) DFS
    if primary_channel == 100:
        return {
            20: [100],
            40: [100, 104],
            80: [100, 104, 108, 112],
        }

    if primary_channel == 132:
        return {
            20: [132],
            40: [132, 136],
            80: [132, 136, 140, 144],
        }

    # Fallback
    return {20: [primary_channel]}


def width_allowed(width, bonding_table, banned_channels):
    """Return True if chosen width's bonded channels avoid banned channels."""
    channels_used = bonding_table.get(width, [])
    for ch in channels_used:
        if ch in banned_channels:
            return False
    return True