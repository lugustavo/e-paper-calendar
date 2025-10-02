"""
E-paper display controller - Fixed version
Corrige vazamento de file descriptors
"""

import logging
from PIL import Image

logger = logging.getLogger(__name__)

class DisplayController:
    """Controls e-paper display operations"""

    def __init__(self, config):
        self.config = config
        self._epd = None
        self._initialized = False

    def _initialize_display(self):
        """Initialize display hardware (chamado apenas uma vez)"""
        if self._initialized:
            return
            
        try:
            from waveshare_epd import epd2in13_V2
            
            if self._epd is None:
                self._epd = epd2in13_V2.EPD()
                logger.info("Display hardware inicializado")
            
            self._initialized = True
            
        except ImportError:
            logger.error("Waveshare EPD library n�o encontrada")
            raise
        except Exception as e:
            logger.error(f"Falha ao inicializar display: {e}")
            raise

    def show_image(self, image: Image.Image, full_update: bool = False):
        """
        Display image on e-paper

        Args:
            image: PIL Image to display
            full_update: Whether to use full refresh (True) or partial (False)
        """
        try:
            # Inicializa display apenas uma vez
            self._initialize_display()
            
            if self._epd is None:
                raise RuntimeError("Display n�o inicializado")

            # Rotate image if configured
            if self.config.ROTATE_DISPLAY:
                image = image.rotate(180, expand=False)

            image_buffer = self._epd.getbuffer(image)

            if full_update:
                self._epd.init(self._epd.FULL_UPDATE)
                self._epd.Clear(0xFF)
                self._epd.display(image_buffer)
                logger.info("Display: FULL update")
            else:
                self._epd.displayPartBaseImage(image_buffer)
                self._epd.init(self._epd.PART_UPDATE)
                self._epd.displayPartial(image_buffer)
                logger.info("Display: PARTIAL update")

            # Note: Keeping display active instead of sleeping for better responsiveness
            # epd.sleep()

        except Exception as e:
            logger.error(f"Erro ao atualizar display: {e}")
            # Em caso de erro, tenta reinicializar na pr�xima vez
            self._initialized = False
            raise

    def clear_display(self):
        """Clear the display to white"""
        try:
            self._initialize_display()
            
            if self._epd is None:
                raise RuntimeError("Display n�o inicializado")
                
            self._epd.init(self._epd.FULL_UPDATE)
            self._epd.Clear(0xFF)
            logger.info("Display limpo")
        except Exception as e:
            logger.error(f"Erro ao limpar display: {e}")
            self._initialized = False
            raise

    def sleep(self):
        """Put display in sleep mode to save power"""
        try:
            if self._epd and self._initialized:
                self._epd.sleep()
                logger.info("Display em modo sleep")
        except Exception as e:
            logger.warning(f"Erro ao colocar display em sleep: {e}")

    def cleanup(self):
        """Cleanup resources properly"""
        try:
            if self._epd and self._initialized:
                self._epd.sleep()
                # Cleanup SPI connections
                try:
                    self._epd.module_exit()
                except:
                    pass
                logger.info("Display cleanup conclu�do")
        except Exception as e:
            logger.warning(f"Erro no cleanup: {e}")
        finally:
            self._epd = None
            self._initialized = False

    def __del__(self):
        """Cleanup on destruction"""
        try:
            self.cleanup()
        except:
            pass