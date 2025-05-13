import logging
import sys

logging.addLevelName(5, "TRACE")
logging.TRACE = 5

log = logging.getLogger("powermeter")

log.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(
    logging.Formatter("%(asctime)s | %(name)s | %(levelname)s - %(message)s")
)
log.addHandler(handler)
