from datetime import datetime

DATETIME_FORMAT = '%a, %d %b %Y %H:%M:%S GMT'


def string_from_datetime(date: datetime):
    """
    Parse datetime to date string
    :param date: datetime object
    :returns: str
    """
    rfc1123_date = None
    try:
        rfc1123_date = date.strftime(DATETIME_FORMAT)
    except ValueError:
        pass
    return rfc1123_date
