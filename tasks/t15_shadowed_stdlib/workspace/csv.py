# Legacy helper kept around "for reference". Nobody imports it anymore.
# (Its filename shadows the standard library's csv module.)

LEGACY_DELIMITER = "|"


def legacy_split(line: str) -> list[str]:
    return line.split(LEGACY_DELIMITER)
