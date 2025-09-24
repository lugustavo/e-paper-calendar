"""
Logging setup with rotation and compression
"""

import os
import sys
import logging
import time as _time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

def setup_logging(config=None) -> logging.Logger:
    """Setup logging with rotation and compression"""

    if config:
        log_dir = config.LOG_DIR
        log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
        retention_days = config.LOG_RETENTION_DAYS
    else:
        # Default values for early initialization
        base_dir = Path(__file__).parent
        log_dir = base_dir / "logs"
        log_level = logging.INFO
        retention_days = 7

    try:
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / "epaper.log"

        # File handler with rotation
        file_handler = TimedRotatingFileHandler(
            log_file, when="midnight", backupCount=retention_days, encoding="utf-8"
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

        # Custom rotator with compression and cleanup
        def _gzip_rotator(source, dest):
            try:
                import gzip
                import shutil

                # Compress the rotated log
                with open(source, "rb") as f_in:
                    with gzip.open(dest + ".gz", "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)

                # Remove uncompressed file
                try:
                    os.remove(source)
                except Exception:
                    pass

                # Clean old compressed files
                cutoff = _time.time() - retention_days * 24 * 3600
                try:
                    for file_path in log_dir.glob("*.gz"):
                        try:
                            if file_path.stat().st_mtime < cutoff:
                                file_path.unlink()
                        except Exception:
                            pass
                except Exception:
                    pass

            except Exception:
                # Fallback: just rename without compression
                try:
                    os.replace(source, dest)
                except Exception:
                    pass

        file_handler.rotator = _gzip_rotator

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

        # Configure root logger
        logging.basicConfig(
            level=log_level,
            handlers=[console_handler, file_handler]
        )

        logger = logging.getLogger(__name__)
        logger.info("Logging iniciado (retenção %d dias com compressão)", retention_days)

        return logger

    except Exception as e:
        # Fallback to basic logging
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger(__name__)
        logger.warning(f"Falha ao inicializar logging avançado: {e}")
        return logger