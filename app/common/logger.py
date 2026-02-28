# logger.py
import inspect
import logging
import os
import sys
from pathlib import Path

# Optional: color codes
LOG_COLORS = {
  "DEBUG": "\033[94m",
  "INFO": "\033[92m",
  "WARNING": "\033[93m",
  "ERROR": "\033[91m",
  "CRITICAL": "\033[95m",
  "RESET": "\033[0m"
}


class ColoredFormatter(logging.Formatter):
  def format(self, record):
    levelname = record.levelname
    if levelname in LOG_COLORS:
      record.levelname = f"{LOG_COLORS[levelname]}{levelname}{LOG_COLORS['RESET']}"
    return super().format(record)


def get_logger() -> logging.Logger:
  frame = inspect.stack()[1]
  file_path = Path(frame.filename).with_suffix('')
  parts = file_path.parts[-3:]

  short_packages = ".".join(
    part[0] if i < len(parts) - 1 else part for i, part in enumerate(parts)
  )

  cls_instance = frame.frame.f_locals.get('self', None)
  if cls_instance:
    cls_name = cls_instance.__class__.__name__
    if cls_name != file_path.name:
      logger_name = f"{short_packages}.{cls_name}"
    else:
      logger_name = short_packages
  else:
    logger_name = short_packages

  logger = logging.getLogger(logger_name)
  if not logger.hasHandlers():
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(ColoredFormatter(
      "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
      datefmt="%Y-%m-%d %H:%M:%S"
    ))

    # File handler
    log_dir = Path("../../../logs")
    log_dir.mkdir(exist_ok=True)
    fh = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter(
      "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
      datefmt="%Y-%m-%d %H:%M:%S"
    ))

    logger.addHandler(ch)
    logger.addHandler(fh)
    logger.propagate = False
  return logger
