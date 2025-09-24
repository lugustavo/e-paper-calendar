"""
E-paper display controller
"""

import logging
from PIL import Image

logger = logging.getLogger(__name__)

class DisplayController:
    """Controls e-paper display operations"""

    def __init__(self, config):
        self.config = config
        self._epd = None

    def _get_epd(self):
        """Get e-paper display instance with lazy loading"""
        if self._epd is None:
            try:
                from waveshare_epd import epd2in13_V2
                self._epd = epd2in13_V2.EPD()
                logger.info("Display inicializado com sucesso")
            except ImportError:
                logger.error("Waveshare EPD library não encontrada")
                raise
            except Exception as e:
                logger.error(f"Falha ao inicializar display: {e}")
                raise

        return self._epd

    def show_image(self, image: Image.Image, full_update: bool = False):
        """
        Display image on e-paper

        Args:
            image: PIL Image to display
            full_update: Whether to use full refresh (True) or partial (False)
        """
        try:
            epd = self._get_epd()

            # Rotate image if configured
            if self.config.ROTATE_DISPLAY:
                image = image.rotate(180, expand=False)

            image_buffer = epd.getbuffer(image)

            if full_update:
                epd.init(epd.FULL_UPDATE)
                epd.Clear(0xFF)
                epd.display(image_buffer)
                logger.info("Display: FULL update")
            else:
                epd.displayPartBaseImage(image_buffer)
                epd.init(epd.PART_UPDATE)
                epd.displayPartial(image_buffer)
                logger.info("Display: PARTIAL update")

            # Note: Keeping display active instead of sleeping for better responsiveness
            # epd.sleep()

        except Exception as e:
            logger.error(f"Erro ao atualizar display: {e}")
            raise

    def clear_display(self):
        """Clear the display to white"""
        try:
            epd = self._get_epd()
            epd.init(epd.FULL_UPDATE)
            epd.Clear(0xFF)
            logger.info("Display limpo")
        except Exception as e:
            logger.error(f"Erro ao limpar display: {e}")
            raise

    def sleep(self):
        """Put display in sleep mode to save power"""
        try:
            if self._epd:
                self._epd.sleep()
                logger.info("Display em modo sleep")
        except Exception as e:
            logger.warning(f"Erro ao colocar display em sleep: {e}")

    def __del__(self):
        """Cleanup on destruction"""
        try:
            self.sleep()
        except:
            pass