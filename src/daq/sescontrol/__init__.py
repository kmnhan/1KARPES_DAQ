import logging
import sys

log = logging.getLogger("scan")
log.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
# handler = logging.FileHandler(f"D:/daq_logs/{log.name}.log", mode="a", encoding="utf-8")
handler.setFormatter(
    logging.Formatter("%(asctime)s | %(name)s | %(levelname)s - %(message)s")
)
log.addHandler(handler)
