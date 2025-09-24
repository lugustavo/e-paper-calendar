#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Raspberry Pi Zero W + Waveshare e-Paper 2.13'' (V2 250x122)
E-Paper Calendar Display com Google Calendar e Tasks integration

Refatorado com classes e configuração via .env
"""

import argparse
import time
from datetime import datetime
from config import Config
from display_controller import DisplayController
from google_service import GoogleService
from image_renderer import ImageRenderer
from logger_setup import setup_logging

def main():
    # Setup logging
    logger = setup_logging()

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
            return

        # Display initial image
        display.show_image(base_img, full_update=True)

        # Main loop
        page_index = 0
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

                time.sleep(config.UPDATE_INTERVAL)

            except KeyboardInterrupt:
                logger.info("Encerrado pelo usuário (Ctrl+C)")
                break
            except Exception as e:
                logger.exception(f"Erro no loop de atualização: {e}")
                time.sleep(config.UPDATE_INTERVAL)

    except Exception as e:
        logger.exception(f"Erro crítico na inicialização: {e}")
        return 1

    return 0

if __name__ == "__main__":
    exit(main())