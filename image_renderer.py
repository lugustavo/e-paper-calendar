"""
Image rendering for e-paper display
"""

import os
import time
import logging
import calendar as pycal
from datetime import datetime
from typing import List, Tuple, Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

class FontManager:
    """Manages font loading and caching"""

    def __init__(self, config):
        self.config = config
        self._font_cache = {}

    def get_font(self, font_type: str, size: int) -> ImageFont.FreeTypeFont:
        """Get font with caching"""
        cache_key = f"{font_type}_{size}"

        if cache_key in self._font_cache:
            return self._font_cache[cache_key]

        if font_type == 'bold':
            font_path = self.config.FONT_BOLD
        else:
            font_path = self.config.FONT_REGULAR

        try:
            font = ImageFont.truetype(font_path, size)
            self._font_cache[cache_key] = font
            return font
        except Exception as e:
            logger.warning(f"Falha ao carregar fonte {font_path} tamanho {size}: {e}")
            default_font = ImageFont.load_default()
            self._font_cache[cache_key] = default_font
            return default_font

class ImageRenderer:
    """Handles all image rendering operations"""

    def __init__(self, config):
        self.config = config
        self.font_manager = FontManager(config)

    def _text_size(self, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
        """Get text size, compatible with Pillow 10+"""
        try:
            # Try new method first (Pillow 10+)
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        except AttributeError:
            # Fallback to old method
            return draw.textsize(text, font=font)

    def _multiline_text_size(self, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
        """Get multiline text size"""
        lines = text.split('\n')
        max_width = 0
        total_height = 0

        for line in lines:
            w, h = self._text_size(draw, line, font)
            max_width = max(max_width, w)
            total_height += h

        return max_width, total_height

    def _truncate_text(self, draw: ImageDraw.ImageDraw, text: str, max_width: int, font: ImageFont.FreeTypeFont) -> str:
        """Truncate text to fit within max_width"""
        if self._text_size(draw, text, font)[0] <= max_width:
            return text

        # Binary search for optimal length
        low, high = 0, len(text)
        while low < high:
            mid = (low + high) // 2
            candidate = text[:mid] + "..."
            if self._text_size(draw, candidate, font)[0] <= max_width:
                low = mid + 1
            else:
                high = mid

        result = text[:max(low - 1, 0)] + ("..." if len(text) > 1 else "")
        return result or "..."

    def _draw_month_calendar(self, draw: ImageDraw.ImageDraw, x: int, y: int,
                           width: int, height: int, current_date: datetime):
        """Draw monthly calendar grid"""
        title_font = self.font_manager.get_font('bold', self.config.FONT_SIZE_CALENDAR_TITLE)
        dayname_font = self.font_manager.get_font('regular', self.config.FONT_SIZE_REGULAR)
        day_font = self.font_manager.get_font('regular', self.config.FONT_SIZE_CALENDAR_DAY)

        # Month title
        month_name = current_date.strftime(" %B %Y ")
        tw, th = self._text_size(draw, month_name, title_font)
        draw.text((x + (width - tw)//2, y), month_name, font=title_font, fill=0)

        # Week day headers
        top_after_title = y + th + 2
        pycal.setfirstweekday(pycal.SUNDAY)
        week_names = pycal.weekheader(2).split()
        cal = pycal.Calendar(firstweekday=pycal.SUNDAY)
        cell_w = width // 7

        header_y = top_after_title
        for i, day_name in enumerate(week_names):
            wd_w, _ = self._text_size(draw, day_name, dayname_font)
            tx = x + i * cell_w + (cell_w - wd_w) // 2
            draw.text((tx, header_y), day_name, font=dayname_font, fill=0)

        # Calendar grid
        grid_top = header_y + dayname_font.size + 2
        month_grid = cal.monthdayscalendar(current_date.year, current_date.month)
        weeks = len(month_grid)
        cell_h = max(14, (height - (grid_top - y) - 2) // weeks)

        current_y = grid_top
        today_num = current_date.day

        for row in month_grid:
            for col, day in enumerate(row):
                if day:
                    cell_x = x + col * cell_w
                    cell_y = current_y

                    day_str = str(day)
                    txt_w, txt_h = self._text_size(draw, day_str, day_font)
                    tx = cell_x + cell_w - txt_w - 2
                    ty = cell_y + 1

                    # Highlight today
                    if day == today_num:
                        draw.rectangle([cell_x + 1, cell_y + 1,
                                      cell_x + cell_w - 2, cell_y + cell_h - 2],
                                     outline=0, fill=0)
                        draw.text((tx, ty), day_str, font=day_font, fill=255)
                    else:
                        draw.text((tx, ty), day_str, font=day_font, fill=0)

            current_y += cell_h

    def _draw_time_block(self, draw: ImageDraw.ImageDraw, x: int, y: int,
                        width: int, current_time: datetime):
        """Draw time display block"""
        time_font = self.font_manager.get_font('bold', self.config.FONT_SIZE_TIME)
        time_text = current_time.strftime("%H:%M")

        # Black background
        draw.rectangle([x, y, x + width, y + self.config.TIME_BLOCK_H], fill=0)

        # White text centered
        tw, _ = self._text_size(draw, time_text, time_font)
        draw.text((x + (width - tw)//2, y + 2), time_text, font=time_font, fill=255)

    def _draw_events(self, draw: ImageDraw.ImageDraw, x: int, y: int,
                    width: int, height: int, items: List[Tuple[str, str, str, str]],
                    page_index: int = 0, total_pages: int = 1):
        """Draw events and tasks list"""
        title_font = self.font_manager.get_font('bold', self.config.FONT_SIZE_SUBTITLE)
        item_font = self.font_manager.get_font('regular', self.config.FONT_SIZE_REGULAR)
        small_font = self.font_manager.get_font('regular', self.config.FONT_SIZE_SMALL)

        # Title bar
        if not items:
            title = self.config.MSG_NO_EVENTS
        elif total_pages > 1:
            title = f"Eventos ({page_index + 1}/{total_pages})"
        else:
            title = "Eventos"

        # Black title bar
        draw.rectangle([x, y, x + width, y + self.config.TIME_BLOCK_H], fill=0)
        tw, _ = self._text_size(draw, title, title_font)
        draw.text((x + (width - tw)//2, y + 2), title, font=title_font, fill=255)

        current_y = y + title_font.size + 8

        # No events message
        if not items:
            # "Dia livre" message
            no_events_font = self.font_manager.get_font('regular', self.config.FONT_SIZE_NO_EVENTS)
            msg = self.config.MSG_FREE_DAY
            mw, _ = self._text_size(draw, msg, no_events_font)
            draw.text((x + (width - mw)//2 - 18, current_y + 10), msg, font=no_events_font, fill=0)

            # Happy emoji
            try:
                emoji_font = self.font_manager.get_font('regular', self.config.FONT_SIZE_EMOJI)
                emoji = self.config.MSG_EMOJI_HAPPY
                ew, _ = self._text_size(draw, emoji, emoji_font)
                draw.text((x + (width - ew)//2 - 10, current_y + 35), emoji, font=emoji_font, fill=0)
            except Exception:
                # Fallback if emoji doesn't render
                pass

            return

        # Draw events
        for time_str, title, source, location in items:
            # Event line
            line1 = f"{time_str} {title}"
            truncated_line1 = self._truncate_text(draw, line1, width, item_font)
            draw.text((x, current_y), truncated_line1, font=item_font, fill=0)
            current_y += item_font.size + 1

            # Location if present
            if location:
                truncated_location = self._truncate_text(draw, location, width - 6, small_font)
                draw.text((x + 6, current_y), truncated_location, font=small_font, fill=0)
                current_y += small_font.size + self.config.LINE_SPACING
            else:
                current_y += self.config.LINE_SPACING

            # Separator line
            draw.line([x, current_y, x + width, current_y], fill=0)
            current_y += 2

            # Stop if we run out of space
            if current_y > y + height - item_font.size:
                break

    def render_static(self) -> Image.Image:
        """Render static elements (calendar grid)"""
        start_time = time.perf_counter()

        current_time = datetime.now(self.config.get_timezone())
        img = Image.new("1", (self.config.EPD_WIDTH, self.config.EPD_HEIGHT), 255)
        draw = ImageDraw.Draw(img)

        # Calculate panel dimensions
        left_x, left_y = self.config.MARGIN, self.config.MARGIN
        left_w = self.config.LEFT_PANEL_W - self.config.MARGIN * 2
        left_h = self.config.EPD_HEIGHT - self.config.MARGIN * 2

        right_x, right_y = self.config.LEFT_PANEL_W + 1, self.config.MARGIN
        right_w = self.config.RIGHT_PANEL_W - self.config.MARGIN
        right_h = self.config.EPD_HEIGHT - self.config.MARGIN * 2

        # Draw panel borders
        draw.rectangle([left_x - 1, left_y - 1, left_x + left_w + 1, left_y + left_h + 1], outline=0)
        draw.rectangle([right_x - 1, right_y - 1, right_x + right_w, right_y + right_h + 1], outline=0)

        # Draw calendar
        cal_height = right_h - self.config.TIME_BLOCK_H - 22
        self._draw_month_calendar(draw, right_x + 2, right_y + 2, right_w - 6, cal_height, current_time)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info(f"Render estática concluída em {elapsed_ms:.0f} ms")

        return img

    def render_dynamic(self, base_image: Image.Image, google_service, page_index: int = 0) -> Image.Image:
        """Render dynamic elements (time, events)"""
        start_time = time.perf_counter()

        current_time = datetime.now(self.config.get_timezone())
        items = google_service.get_events_and_tasks()

        # Calculate pagination
        if items:
            total_pages = (len(items) + self.config.EVENTS_PER_PAGE - 1) // self.config.EVENTS_PER_PAGE
            page_index = page_index % total_pages
            start_idx = page_index * self.config.EVENTS_PER_PAGE
            end_idx = start_idx + self.config.EVENTS_PER_PAGE
            show_items = items[start_idx:end_idx]
        else:
            show_items, total_pages = [], 1

        # Copy base image and get draw context
        img = base_image.copy()
        draw = ImageDraw.Draw(img)

        # Calculate panel dimensions
        right_x, right_y = self.config.LEFT_PANEL_W + 2, self.config.MARGIN
        right_w = self.config.RIGHT_PANEL_W - self.config.MARGIN
        right_h = self.config.EPD_HEIGHT - self.config.MARGIN * 2

        left_x, left_y = self.config.MARGIN, self.config.MARGIN
        left_w = self.config.LEFT_PANEL_W - self.config.MARGIN * 2
        left_h = self.config.EPD_HEIGHT - self.config.MARGIN * 2

        # Draw time block
        cal_height = right_h - self.config.TIME_BLOCK_H - 8
        self._draw_time_block(draw, right_x + 2, right_y + cal_height + 6, right_w - 7, current_time)

        # Clear and draw events area
        draw.rectangle([left_x + 1, left_y + 1, left_x + left_w - 1, left_y + left_h - 1], fill=255)
        self._draw_events(draw, left_x + 2, left_y + 2, left_w - 4, left_h - 6,
                         show_items, page_index=page_index, total_pages=total_pages)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info(f"Render dinâmica p={page_index + 1}/{total_pages} "
                   f"itens_mostrados={len(show_items)} em {elapsed_ms:.0f} ms")

        return img