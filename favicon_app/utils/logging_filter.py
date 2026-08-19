# -*- coding: utf-8 -*-

import logging
import re


class GunicornWorkerTerminationFilter(logging.Filter):
    _NORMAL_TERMINATION = re.compile(
        r'^Worker \(pid:\d+\) was sent SIGTERM!$',
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if (
                record.name == 'gunicorn.error'
                and record.levelno == logging.ERROR
                and self._NORMAL_TERMINATION.fullmatch(record.getMessage())
        ):
            record.levelno = logging.INFO
            record.levelname = logging.getLevelName(logging.INFO)
        return True
