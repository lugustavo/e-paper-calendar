"""
Configuration management using environment variables and .env file
"""

import os
import sys
import locale
from datetime import timezone
from pathlib import Path
from typing import List, Optional
import logging

try:
    from dotenv import load_dotenv
except ImportError:
    print("python-dotenv não encontrado. Instale com: pip install python-dotenv")
    sys.exit(1)

try:
    from tzlocal import get_localzone
except ImportError:
    print("tzlocal não encontrado. Instale com: pip install tzlocal")
    sys.exit(1)

logger = logging.getLogger(__name__)

class Config:
    """Centralizes all configuration management"""

    def __init__(self):
        # Load .env file
        env_path = Path(__file__).parent / '.env'
        load_dotenv(env_path)

        # Base directory
        self.BASE_DIR = Path(__file__).parent

        # Display dimensions
        self.EPD_WIDTH = self._get_int('EPD_WIDTH', 250)
        self.EPD_HEIGHT = self._get_int('EPD_HEIGHT', 122)
        self.MARGIN = self._get_int('MARGIN', 3)
        self.RIGHT_PANEL_W = self._get_int('RIGHT_PANEL_W', 144)
        self.LEFT_PANEL_W = self._get_int('LEFT_PANEL_W', 106)
        self.TIME_BLOCK_H = self._get_int('TIME_BLOCK_H', 15)
        self.LINE_SPACING = self._get_int('LINE_SPACING', 2)

        # Display settings
        self.ROTATE_DISPLAY = self._get_bool('ROTATE_DISPLAY', True)
        self.UPDATE_INTERVAL = self._get_int('UPDATE_INTERVAL', 60)

        # Event settings
        self.MAX_EVENTS = self._get_int('MAX_EVENTS', 12)
        self.EVENTS_PER_PAGE = self._get_int('EVENTS_PER_PAGE', 3)

        # AI Image settings
        self.AI_IMAGES_ENABLED = self._get_bool('AI_IMAGES_ENABLED', True)
        self.AI_IMAGE_CACHE_DAYS = self._get_int('AI_IMAGE_CACHE_DAYS', 7)
        self.AI_IMAGE_WIDTH = self._get_int('AI_IMAGE_WIDTH', 96)
        self.AI_IMAGE_HEIGHT = self._get_int('AI_IMAGE_HEIGHT', 110)

        # AI Image themes (separated by comma)
        default_themes = (
            "uma pequena casa pixel art em preto e branco,"
            "um gato pixel art dormindo em preto e branco,"
            "uma árvore pixel art simples em preto e branco,"
            "um café pixel art com vapor em preto e branco,"
            "um livro aberto pixel art em preto e branco,"
            "uma planta em vaso pixel art em preto e branco,"
            "um coração pixel art simples em preto e branco,"
            "uma estrela pixel art brilhante em preto e branco,"
            "uma lua crescente pixel art em preto e branco,"
            "um sol pixel art sorrindo em preto e branco,"
            "uma nuvem fofa pixel art em preto e branco,"
            "um pássaro voando pixel art em preto e branco,"
            "uma flor simples pixel art em preto e branco,"
            "um guarda-chuva pixel art em preto e branco,"
            "uma bicicleta pixel art em preto e branco"
        )
        self.AI_IMAGE_THEMES = [theme.strip() for theme in self._get_str('AI_IMAGE_THEMES', default_themes).split(',') if theme.strip()]

        # Font paths
        self.FONT_REGULAR = self._get_str('FONT_REGULAR', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
        self.FONT_BOLD = self._get_str('FONT_BOLD', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')

        # Font sizes
        self.FONT_SIZE_TITLE = self._get_int('FONT_SIZE_TITLE', 14)
        self.FONT_SIZE_SUBTITLE = self._get_int('FONT_SIZE_SUBTITLE', 11)
        self.FONT_SIZE_REGULAR = self._get_int('FONT_SIZE_REGULAR', 9)
        self.FONT_SIZE_SMALL = self._get_int('FONT_SIZE_SMALL', 9)
        self.FONT_SIZE_CALENDAR_TITLE = self._get_int('FONT_SIZE_CALENDAR_TITLE', 11)
        self.FONT_SIZE_CALENDAR_DAY = self._get_int('FONT_SIZE_CALENDAR_DAY', 9)
        self.FONT_SIZE_TIME = self._get_int('FONT_SIZE_TIME', 11)
        self.FONT_SIZE_EMOJI = self._get_int('FONT_SIZE_EMOJI', 35)
        self.FONT_SIZE_NO_EVENTS = self._get_int('FONT_SIZE_NO_EVENTS', 17)

        # Google API settings
        self.CREDENTIALS_FILE = self.BASE_DIR / self._get_str('CREDENTIALS_FILE', 'credentials_raspberry-pi.json')
        self.TOKEN_FILE = self.BASE_DIR / self._get_str('TOKEN_FILE', 'token.json')
        self.HEADLESS_OAUTH_PORT = self._get_int('HEADLESS_OAUTH_PORT', 54545)

        # Google API scopes
        self.SCOPES = [
            'https://www.googleapis.com/auth/calendar.readonly',
            'https://www.googleapis.com/auth/tasks.readonly'
        ]

        # Waveshare library paths
        self.WAVESHARE_PIC_DIR = self._get_str('WAVESHARE_PIC_DIR', '/home/pi/e-Paper/RaspberryPi_JetsonNano/python/pic')
        self.WAVESHARE_LIB_DIR = self._get_str('WAVESHARE_LIB_DIR', '/home/pi/e-Paper/RaspberryPi_JetsonNano/python/lib')

        # Logging settings
        self.LOG_DIR = self.BASE_DIR / self._get_str('LOG_DIR', 'logs')
        self.LOG_RETENTION_DAYS = self._get_int('LOG_RETENTION_DAYS', 7)
        self.LOG_LEVEL = self._get_str('LOG_LEVEL', 'INFO')

        # Locale settings
        self.PREFERRED_LOCALES = self._get_str('PREFERRED_LOCALES', 'pt_PT.utf8,pt_BR.utf8,pt_PT,pt_BR,pt').split(',')

        # Display messages
        self.MSG_NO_EVENTS = self._get_str('MSG_NO_EVENTS', 'Sem Eventos')
        self.MSG_FREE_DAY = self._get_str('MSG_FREE_DAY', 'Dia livre')
        self.MSG_EMOJI_HAPPY = self._get_str('MSG_EMOJI_HAPPY', '😊')
        self.MSG_AUTH_TITLE = self._get_str('MSG_AUTH_TITLE', '● Google Login ●')
        self.MSG_AUTH_MESSAGE = self._get_str('MSG_AUTH_MESSAGE', 'Autenticação necessária\nSiga o link exibido no log')

        # Initialize derived settings
        self._setup_paths()
        self._setup_locale()
        self._timezone = None

    def _get_str(self, key: str, default: str) -> str:
        """Get string environment variable with default"""
        return os.getenv(key, default)

    def _get_int(self, key: str, default: int) -> int:
        """Get integer environment variable with default"""
        try:
            return int(os.getenv(key, str(default)))
        except ValueError:
            logger.warning(f"Invalid integer value for {key}, using default: {default}")
            return default

    def _get_bool(self, key: str, default: bool) -> bool:
        """Get boolean environment variable with default"""
        value = os.getenv(key, str(default)).lower()
        return value in ('true', '1', 'yes', 'on')

    def _setup_paths(self):
        """Setup and validate paths"""
        # Add Waveshare library to path if it exists
        if os.path.exists(self.WAVESHARE_LIB_DIR):
            if self.WAVESHARE_LIB_DIR not in sys.path:
                sys.path.append(self.WAVESHARE_LIB_DIR)

        # Create log directory
        self.LOG_DIR.mkdir(exist_ok=True)

    def _setup_locale(self):
        """Setup Portuguese locale"""
        for loc in self.PREFERRED_LOCALES:
            try:
                locale.setlocale(locale.LC_TIME, loc.strip())
                logger.info(f"Locale definido: {loc}")
                return
            except Exception:
                continue
        logger.warning("Não foi possível definir locale para PT")

    def get_timezone(self):
        """Get local timezone with caching"""
        if self._timezone is None:
            try:
                self._timezone = get_localzone()
            except Exception as e:
                logger.error(f"Erro ao obter timezone local: {e}")
                self._timezone = timezone.utc
        return self._timezone

    def validate_paths(self) -> List[str]:
        """Validate critical paths and return list of missing files"""
        missing = []

        if not self.CREDENTIALS_FILE.exists():
            missing.append(str(self.CREDENTIALS_FILE))

        if not os.path.exists(self.FONT_REGULAR):
            missing.append(self.FONT_REGULAR)

        if not os.path.exists(self.FONT_BOLD):
            missing.append(self.FONT_BOLD)

        return missing