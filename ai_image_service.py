"""
AI Image generation service for e-paper display
Generates pixel art images using OpenAI DALL-E API
"""

import os
import logging
import hashlib
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional
from PIL import Image, ImageOps

# Compatibilidade PILLOW
from PIL import Image
try:
    # Para compatibilidade com versões antigas
    if not hasattr(Image, 'Resampling'):
        class Resampling:
            LANCZOS = Image.LANCZOS
            BILINEAR = Image.BILINEAR
            NEAREST = Image.NEAREST
        Image.Resampling = Resampling
    if not hasattr(Image, "Dither"):
        class Dither:
            DITHER = Image.FLOYDSTEINBERG
        Image.Dither = Dither
except:
    pass

logger = logging.getLogger(__name__)

class AIImageService:
    """Handles AI image generation for e-paper display"""

    def __init__(self, config):
        self.config = config
        self.cache_dir = config.BASE_DIR / 'image_cache'
        self.cache_dir.mkdir(exist_ok=True)

        # OpenAI API key from environment
        self.api_key = os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            logger.warning("OPENAI_API_KEY não encontrada. Imagens AI desabilitadas.")

    def _get_cache_path(self, prompt_hash: str) -> Path:
        """Get cache file path for a prompt hash"""
        return self.cache_dir / f"ai_image_{prompt_hash}.png"

    def _generate_daily_prompt(self) -> str:
        """Generate a daily prompt for pixel art"""
        day_of_year = datetime.now().timetuple().tm_yday

        # Get themes from config
        themes = self.config.AI_IMAGE_THEMES

        if not themes:
            # Fallback if no themes configured
            themes = ["uma imagem pixel art simples em preto e branco"]

        # Seleciona tema baseado no dia do ano para consistência diária
        theme = themes[day_of_year % len(themes)]

        return f"8-bit {theme}, muito simples, minimalista, fundo branco limpo"

    def _call_dalle_api(self, prompt: str) -> Optional[bytes]:
        """Call OpenAI DALL-E API to generate image"""
        if not self.api_key:
            return None

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "model": "dall-e-3",
                "prompt": prompt,
                "size": "1024x1024",  # Geramos grande e reduzimos
                "quality": "standard",
                "n": 1
            }

            logger.info("Gerando imagem AI via DALL-E...")
            response = requests.post(
                "https://api.openai.com/v1/images/generations",
                headers=headers,
                json=data,
                timeout=60
            )

            if response.status_code == 200:
                result = response.json()
                image_url = result['data'][0]['url']

                # Download da imagem
                img_response = requests.get(image_url, timeout=30)
                if img_response.status_code == 200:
                    logger.info("Imagem AI gerada com sucesso")
                    return img_response.content

            else:
                logger.error(f"Erro na API DALL-E: {response.status_code} - {response.text}")

        except Exception as e:
            logger.error(f"Erro ao chamar API DALL-E: {e}")

        return None

    def _process_image_for_epaper(self, image_bytes: bytes, target_size: tuple) -> Optional[Image.Image]:
        """Process image for e-paper display (black & white, target size)"""
        try:
            import io
            # Carrega imagem
            img = Image.open(io.BytesIO(image_bytes))

            # Converte para escala de cinza
            img = img.convert('L')

            # Redimensiona mantendo aspecto, depois corta/preenche para tamanho exato
            img.thumbnail(target_size, Image.Resampling.LANCZOS)

            # Cria imagem final com fundo branco
            final_img = Image.new('L', target_size, 255)

            # Centraliza a imagem redimensionada
            paste_x = (target_size[0] - img.width) // 2
            paste_y = (target_size[1] - img.height) // 2
            final_img.paste(img, (paste_x, paste_y))

            # Converte para 1-bit (preto e branco) com dithering
            final_img = final_img.convert('1', dither=Image.Dither.FLOYDSTEINBERG)

            return final_img

        except Exception as e:
            logger.error(f"Erro ao processar imagem: {e}")
            return None

    def get_daily_image(self, size: tuple = (96, 110)) -> Optional[Image.Image]:
        """Get daily AI-generated image, with caching"""
        if not self.api_key:
            return None

        # Gera prompt do dia
        prompt = self._generate_daily_prompt()
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()

        # Verifica cache
        cache_path = self._get_cache_path(prompt_hash)

        if cache_path.exists():
            try:
                cached_img = Image.open(cache_path)
                logger.info("Imagem AI carregada do cache")
                return cached_img
            except Exception as e:
                logger.warning(f"Erro ao carregar cache: {e}")

        # Gera nova imagem
        image_bytes = self._call_dalle_api(prompt)
        if not image_bytes:
            return None

        # Processa para e-paper
        processed_img = self._process_image_for_epaper(image_bytes, size)
        if not processed_img:
            return None

        # Salva no cache
        try:
            processed_img.save(cache_path, "PNG")
            logger.info(f"Imagem AI salva no cache: {cache_path}")
        except Exception as e:
            logger.warning(f"Erro ao salvar cache: {e}")

        return processed_img

    def clear_cache(self, days_old: int = 7):
        """Clear old cached images"""
        try:
            cutoff_time = datetime.now().timestamp() - (days_old * 24 * 3600)

            for cache_file in self.cache_dir.glob("ai_image_*.png"):
                if cache_file.stat().st_mtime < cutoff_time:
                    cache_file.unlink()
                    logger.info(f"Cache removido: {cache_file}")

        except Exception as e:
            logger.warning(f"Erro ao limpar cache: {e}")