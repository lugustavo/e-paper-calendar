#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Raspberry Pi Zero W + Waveshare e-Paper 2.13'' (V2 250x122)
E-Paper Calendar Display com Google Calendar e Tasks integration

Versão corrigida - previne vazamento de file descriptors
"""

import argparse
import signal
import sys
import time
from datetime import datetime
from config import Config
from display_controller import DisplayController
from google_service import GoogleService
from image_renderer import ImageRenderer
from logger_setup import setup_logging

# Variáveis globais para cleanup
display = None
logger = None

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global display, logger
    
    if logger:
        logger.info(f"Sinal recebido: {signum}. Encerrando gracefully...")
    
    if display:
        try:
            display.cleanup()
        except Exception as e:
            if logger:
                logger.warning(f"Erro no cleanup do display: {e}")
    
    sys.exit(0)

def main():
    global display, logger
    
    # Setup logging
    logger = setup_logging()

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", metavar="PNG_PATH",
                       help="Gera PNG em vez do display")
    args = parser.parse_args()

    try:
        # Initialize components
        config = Config()
        google_service = GoogleService(config)
        renderer = ImageRenderer(config)
        display = DisplayController(config)

        logger.info("Sistema iniciado com sucesso")

        # Initial render
        today = datetime.now(config.get_timezone()).date()
        base_img = renderer.render_static()
        img = renderer.render_dynamic(base_img, google_service)

        if args.dry_run:
            img.save(args.dry_run)
            logger.info(f"PNG salvo em {args.dry_run}")
            return 0

        # Display initial image
        display.show_image(base_img, full_update=True)

        # Main loop
        page_index = 0
        error_count = 0
        max_errors = 5
        
        while True:
            try:
                now = datetime.now(config.get_timezone())

                # Check for day change
                if now.date() != today:
                    logger.info("Mudança de dia detectada, regenerando parte estática")
                    base_img = renderer.render_static()
                    display.show_image(base_img, full_update=True)
                    today = now.date()
                    page_index = 0

                # Update dynamic content
                img = renderer.render_dynamic(base_img, google_service, page_index)
                display.show_image(img, full_update=False)

                logger.info(f"Atualização parcial OK (página {page_index + 1})")
                page_index += 1
                
                # Reset error counter on success
                error_count = 0

                time.sleep(config.UPDATE_INTERVAL)

            except KeyboardInterrupt:
                logger.info("Encerrado pelo usuário (Ctrl+C)")
                break
                
            except Exception as e:
                error_count += 1
                logger.exception(f"Erro no loop de atualização ({error_count}/{max_errors}): {e}")
                
                # Se muitos erros consecutivos, tenta reinicializar display
                if error_count >= max_errors:
                    logger.warning("Muitos erros consecutivos, reinicializando display...")
                    try:
                        display.cleanup()
                        display = DisplayController(config)
                        logger.info("Display reinicializado com sucesso")
                        error_count = 0
                    except Exception as reinit_error:
                        logger.error(f"Falha ao reinicializar display: {reinit_error}")
                        break
                
                time.sleep(config.UPDATE_INTERVAL)

    except Exception as e:
        logger.exception(f"Erro crítico na inicialização: {e}")
        return 1
    
    finally:
        # Cleanup ao sair
        if display:
            try:
                display.cleanup()
            except Exception as e:
                logger.warning(f"Erro no cleanup final: {e}")

    return 0

if __name__ == "__main__":
    exit(main())