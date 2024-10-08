import logging
import sys

logging.basicConfig(
    level=logging.WARNING,
    handlers=[logging.StreamHandler(sys.stdout)],
    format="%(filename)s: " "%(levelname)s: " "%(funcName)s(): " "%(lineno)d:\t" "%(message)s",
)
logger = logging.getLogger(__name__)
