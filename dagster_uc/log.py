import logging
import sys

logging.basicConfig(
    level=logging.WARNING,
    handlers=[logging.StreamHandler(sys.stdout)],
    format="%(asctime)s - %(name)s.%(funcName)s():%(lineno)d - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
