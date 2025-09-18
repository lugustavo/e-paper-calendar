#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E-paper Calendar (Raspberry Pi Zero W + Waveshare 2.13'' V2 250x122)

Refatorado para:
- Logs detalhados (INFO por padrão; use EPAPER_LOG=DEBUG para mais).
- Código mais simples e sem redundâncias.
- Autenticação Google robusta com refresh_token (sem pedir login a cada loop).
- Conserto do fluxo de **atualização parcial** (hora + eventos):
  * FULL_UPDATE inicial + PART_UPDATE preparado corretamente.
  * Partial update usando `displayPartial(...)` (com fallback para `display(...)`).
- Compatível com Pillow 11.x (usa textbbox).

Dicas:
- `credentials.json` e `token.json` ficam ao lado do script.
- Headless: cria instruções para túnel SSH automático (porta 54545). 
"""

import os
import sys
import time
import logging
import socket
import getpass
import locale
import calendar as pycal
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont

# ===================== LOGGING =====================
LOG_LEVEL = os.environ.get("EPAPER_LOG", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("epaper-cal")

# ===================== PATHS / WAVESHARE LIB =====================
PICDIR = "/home/pi/e-Paper/RaspberryPi_JetsonNano/python/pic"
LIBDIR = "/home/pi/e-Paper/RaspberryPi_JetsonNano/python/lib"

if os.path.exists(LIBDIR):
    # Garanta prioridade da lib correta e evite colisão com libs antigas
    try:
        sys.path.remove(LIBDIR)
    except ValueError:
        pass
    sys.path.insert(0, LIBDIR)

# Remova caminhos antigos (ex.: e-Paper.old) que possam conter outra cópia
for _p in list(sys.path):
    if "e-Paper.old" in _p and "waveshare_epd" in _p:
        try:
            sys.path.remove(_p)
            logger.warning("Removendo lib antiga do sys.path: %s", _p)
        except Exception:
            pass

# ===================== DISPLAY LAYOUT =====================
EPD_WIDTH = 250
EPD_HEIGHT = 122
MARGIN = 3
RIGHT_PANEL_W = 144  # Calendário + Hora
LEFT_PANEL_W = EPD_WIDTH - RIGHT_PANEL_W
TIME_BLOCK_H = 19
LINE_SPACING = 2
PAGE_SIZE = 3
MAX_ITEMS_FETCH = 24  # busca bastante para paginar 3/3

FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# ===================== OAUTH / TOKENS =====================
HEADLESS_OAUTH_PORT = 54545
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")
TOKEN_PATH = os.path.join(BASE_DIR, "token.json")
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
]
_CREDS = None  # cache em memória

# ===================== HELPERS =====================

def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception as e:
        logger.debug("Falha ao carregar fonte %s (%s). Usando default.", path, e)
        return ImageFont.load_default()


def local_tz():
    try:
        from tzlocal import get_localzone
        return get_localzone()
    except Exception:
        return datetime.now().astimezone().tzinfo or timezone.utc


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    # Compatível com Pillow 10+/11+: use textbbox
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def set_portuguese_locale():
    for loc in ("pt_PT.utf8", "pt_BR.utf8", "pt_PT", "pt_BR", "pt"):
        try:
            locale.setlocale(locale.LC_TIME, loc)
            return
        except Exception:
            pass


def has_gui_env() -> bool:
    # GUI se houver DISPLAY/Wayland/MIR; ou ferramentas de browser
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or os.environ.get("MIR_SOCKET"):
        return True
    try:
        import shutil
        if shutil.which("xdg-open") or shutil.which("x-www-browser"):
            return True
    except Exception:
        pass
    return False


# ===================== GOOGLE AUTH / CLIENT =====================

def _save_token(creds):
    try:
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
        logger.debug("token.json salvo/atualizado.")
    except Exception as e:
        logger.warning("Falha ao salvar token.json: %s", e)


def get_credentials():
    """Obtém credenciais, renova silenciosamente e evita reabrir o navegador."""
    global _CREDS
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if _CREDS and _CREDS.valid:
        return _CREDS

    creds = None
    if os.path.exists(TOKEN_PATH):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
            logger.debug("token.json carregado.")
        except Exception as e:
            logger.warning("Falha lendo token.json: %s", e)
            creds = None

    if creds and not creds.valid and creds.refresh_token:
        try:
            creds.refresh(Request())
            logger.info("Token Google renovado silenciosamente.")
            _save_token(creds)
            _CREDS = creds
            return _CREDS
        except Exception as e:
            logger.warning("Refresh falhou, será necessário reautenticar: %s", e)

    # Precisa autenticar
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(f"Credenciais não encontradas: {CREDENTIALS_FILE}")

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    auth_kwargs = dict(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    if has_gui_env():
        logger.info("Autorização Google (GUI detectada)...")
        creds = flow.run_local_server(
            port=0,
            open_browser=True,
            authorization_prompt_message=(
                "\nAbra o link no navegador para autorizar o acesso (GUI detectada):\n{url}\n"
            ),
            success_message=("Autorizado com sucesso! Você pode fechar esta aba."),
            **auth_kwargs,
        )
    else:
        host = socket.gethostname()
        user = getpass.getuser() or "pi"
        ssh_hint = f"ssh -N -L {HEADLESS_OAUTH_PORT}:localhost:{HEADLESS_OAUTH_PORT} {user}@{host}"
        logger.info("Autorização Google (modo HEADLESS) — crie o túnel SSH: %s", ssh_hint)
        creds = flow.run_local_server(
            host="localhost",
            port=HEADLESS_OAUTH_PORT,
            open_browser=False,
            authorization_prompt_message=(
                "\n=== Autorização Google (modo HEADLESS) ===\n"
                "1) No SEU PC, crie o túnel SSH para o Raspberry:\n   "
                f"{ssh_hint}\n"
                "2) Com o túnel ativo, abra no navegador do SEU PC o link abaixo e conclua o login:\n   {url}\n\n"
                f"O Google redirecionará para http://localhost:{HEADLESS_OAUTH_PORT}/, encaminhado ao Raspberry.\n"
            ),
            success_message=("Autorizado! Você já pode fechar a aba do navegador."),
            **auth_kwargs,
        )

    _save_token(creds)
    _CREDS = creds
    return _CREDS


class GoogleClient:
    def __init__(self):
        from googleapiclient.discovery import build
        self.creds = get_credentials()
        self.service_cal = build("calendar", "v3", credentials=self.creds)
        self.service_tasks = build("tasks", "v1", credentials=self.creds)
        logger.info("Google API clients prontos.")

    def fetch_today_items(self, max_items=MAX_ITEMS_FETCH) -> List[Tuple[str, str, str, str]]:
        tz = local_tz()
        today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        time_min = today.isoformat()
        time_max = tomorrow.isoformat()

        events: List[Tuple[str, str, str, str]] = []
        try:
            calendars = self.service_cal.calendarList().list().execute().get("items", [])
        except Exception as e:
            logger.error("Falha ao listar calendários: %s", e)
            calendars = []

        for cal in calendars:
            cal_id = cal.get("id")
            if not cal_id:
                continue
            try:
                evs = (
                    self.service_cal.events()
                    .list(
                        calendarId=cal_id,
                        timeMin=time_min,
                        timeMax=time_max,
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute()
                    .get("items", [])
                )
            except Exception as e:
                logger.warning("Falha ao buscar eventos em %s: %s", cal_id, e)
                evs = []

            for ev in evs:
                start = ev.get("start", {})
                raw = start.get("dateTime") or start.get("date")
                if not raw:
                    continue
                if "T" in raw:
                    sdt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(tz)
                    hora = sdt.strftime("%H:%M")
                else:
                    hora = "Dia todo"
                title = ev.get("summary", "(Sem título)")
                loc = ev.get("location", "")
                events.append((hora, title, "Calendar", loc))

        tasks: List[Tuple[str, str, str, str]] = []
        try:
            tlist = self.service_tasks.tasklists().list(maxResults=10).execute().get("items", [])
        except Exception as e:
            logger.error("Falha ao listar Tasklists: %s", e)
            tlist = []

        for tl in tlist:
            try:
                ts = (
                    self.service_tasks.tasks()
                    .list(tasklist=tl["id"], showCompleted=False)
                    .execute()
                    .get("items", [])
                )
            except Exception as e:
                logger.warning("Falha ao buscar Tasks em %s: %s", tl.get("title", tl.get("id")), e)
                ts = []
            for t in ts:
                due = t.get("due")
                if not due:
                    continue
                dt = datetime.fromisoformat(due.replace("Z", "+00:00")).astimezone(tz)
                if today <= dt < tomorrow:
                    hora = dt.strftime("%H:%M")
                    tasks.append((hora, t.get("title", "(Sem título)"), "Task", ""))

        items = events + tasks
        items.sort(key=lambda it: ("00:00" if it[0] == "Dia todo" else it[0], it[1]))
        logger.debug("Itens de hoje: %d", len(items))
        return items[:max_items]


# ===================== RENDERING =====================

def draw_month_calendar(draw: ImageDraw.ImageDraw, ox, oy, w, h, now: datetime):
    set_portuguese_locale()
    title_font = load_font(FONT_BOLD, 11)
    dayname_font = load_font(FONT_REG, 9)
    day_font = load_font(FONT_REG, 9)

    month_name = now.strftime(" %B %Y ")
    tw, th = text_size(draw, month_name, title_font)
    draw.text((ox + (w - tw)//2, oy), month_name, font=title_font, fill=0)

    top_after_title = oy + th + 2

    week_names = pycal.weekheader(2).split()
    cal = pycal.Calendar(firstweekday=pycal.MONDAY)
    cell_w = w // 7
    header_y = top_after_title
    for i, wd in enumerate(week_names):
        wd_w, _ = text_size(draw, wd, dayname_font)
        tx = ox + i*cell_w + (cell_w - wd_w)//2
        draw.text((tx, header_y), wd, font=dayname_font, fill=0)

    grid_top = header_y + dayname_font.size + 2
    month_grid = cal.monthdayscalendar(now.year, now.month)
    weeks = len(month_grid)
    cell_h = max(14, (h - (grid_top - oy) - 2) // weeks)

    y = grid_top
    today_num = now.day
    for row in month_grid:
        for col, day in enumerate(row):
            cx = ox + col*cell_w
            cy = y
            if day:
                txt = str(day)
                txt_w, _ = text_size(draw, txt, day_font)
                tx = cx + cell_w - txt_w - 2
                ty = cy + 1
                if day == today_num:
                    draw.rectangle([cx+1, cy+1, cx+cell_w-2, cy+cell_h-2], outline=0, fill=0)
                    draw.text((tx, ty), txt, font=day_font, fill=255)
                else:
                    draw.text((tx, ty), txt, font=day_font, fill=0)
        y += cell_h


def draw_time_block(draw: ImageDraw.ImageDraw, ox, oy, w, now: datetime):
    time_font = load_font(FONT_BOLD, 11)
    time_txt = now.strftime("%H:%M")
    draw.rectangle([ox, oy, ox + w, oy + TIME_BLOCK_H], fill=0)
    tw, _ = text_size(draw, time_txt, time_font)
    draw.text((ox + (w - tw)//2, oy + 2), time_txt, font=time_font, fill=255)


def draw_events(draw: ImageDraw.ImageDraw, ox, oy, w, h, items: List[Tuple[str,str,str,str]], page_index=0, total_pages=1):
    title_font = load_font(FONT_BOLD, 11)
    item_font = load_font(FONT_REG, 9)
    small_font = load_font(FONT_REG, 9)

    titulo = "Eventos (vazio)" if not items else (f"Eventos ({page_index+1}/{total_pages})" if total_pages > 1 else "Eventos")
    draw.rectangle([ox, oy, ox + w, oy + TIME_BLOCK_H], fill=0)
    tw, _ = text_size(draw, titulo, title_font)
    draw.text((ox + (w - tw)//2, oy + 2), titulo, font=title_font, fill=255)

    y = oy + title_font.size + 12

    def trunc(text: str, maxw: int, font: ImageFont.FreeTypeFont) -> str:
        if text_size(draw, text, font)[0] <= maxw:
            return text
        low, high = 0, len(text)
        while low < high:
            mid = (low + high) // 2
            cand = text[:mid] + "..."
            if text_size(draw, cand, font)[0] <= maxw:
                low = mid + 1
            else:
                high = mid
        best = text[:max(low - 1, 0)] + ("..." if len(text) > 1 else "")
        return best or "..."

    for hora, title, origem, loc in items:
        line1 = f"{hora} {title}"
        draw.text((ox, y), trunc(line1, w, item_font), font=item_font, fill=0)
        y += item_font.size + 1
        if loc:
            draw.text((ox + 6, y), trunc(loc, w-6, small_font), font=small_font, fill=0)
            y += small_font.size + LINE_SPACING
        else:
            y += LINE_SPACING
        draw.line([ox, y, ox + w, y], fill=0)
        y += 2
        if y > oy + h - item_font.size:
            break


def render_static() -> Image.Image:
    tz = local_tz()
    now = datetime.now(tz)
    img = Image.new("1", (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(img)

    left_x, left_y = MARGIN, MARGIN
    left_w, left_h = LEFT_PANEL_W - MARGIN*2, EPD_HEIGHT - MARGIN*2
    right_x, right_y = LEFT_PANEL_W + 1, MARGIN
    right_w, right_h = RIGHT_PANEL_W - MARGIN, EPD_HEIGHT - MARGIN*2

    draw.rectangle([left_x-1, left_y-1, left_x+left_w+1, left_y+left_h+1], outline=0)
    draw.rectangle([right_x-1, right_y-1, right_x+right_w, right_y+right_h+1], outline=0)

    cal_h = right_h - TIME_BLOCK_H - 22
    draw_month_calendar(draw, right_x+2, right_y+2, right_w-6, cal_h, now)

    return img


def render_dynamic(base_img: Image.Image, items: List[Tuple[str,str,str,str]], page_index: int) -> Image.Image:
    tz = local_tz()
    now = datetime.now(tz)

    if items:
        total_pages = (len(items) + PAGE_SIZE - 1) // PAGE_SIZE
        page_index = page_index % total_pages
        start = page_index * PAGE_SIZE
        show_items = items[start : start + PAGE_SIZE]
    else:
        show_items, total_pages = [], 1

    img = base_img.copy()
    draw = ImageDraw.Draw(img)

    # RIGHT: hora
    right_x, right_y = LEFT_PANEL_W + 2, MARGIN
    right_w, right_h = RIGHT_PANEL_W - MARGIN, EPD_HEIGHT - MARGIN*2
    cal_h = right_h - TIME_BLOCK_H - 8
    draw_time_block(draw, right_x+2, right_y + cal_h + 6, right_w-7, now)

    # LEFT: eventos
    left_x, left_y = MARGIN, MARGIN
    left_w, left_h = LEFT_PANEL_W - MARGIN*2, EPD_HEIGHT - MARGIN*2
    draw.rectangle([left_x+1, left_y+1, left_x+left_w-1, left_y+left_h-1], fill=255)
    draw_events(draw, left_x+2, left_y+2, left_w-4, left_h-6, show_items,
                page_index=page_index, total_pages=(len(items)+PAGE_SIZE-1)//PAGE_SIZE if items else 1)

    return img


# ===================== E-PAPER DRIVER WRAPPER =====================
class EPaper:
    def __init__(self):
        from waveshare_epd import epd2in13_V2
        self.epd = epd2in13_V2.EPD()
        self._partial_ready = False
        logger.info("EPD driver inicializado.")
        try:
            import waveshare_epd as _wse
            logger.debug("waveshare_epd: %s", getattr(_wse, "__file__", "<desconhecido>"))
        except Exception:
            pass

    def full_update(self, img: Image.Image):
        logger.info("FULL_UPDATE...")
        self.epd.init(self.epd.FULL_UPDATE)
        self.epd.Clear(0xFF)
        self.epd.display(self.epd.getbuffer(img))
        self._partial_ready = False

    def prepare_partial(self, base_img: Image.Image):
        logger.info("Preparando PART_UPDATE (base image)...")
        self.epd.init(self.epd.PART_UPDATE)
        # Tenta configurar imagem base para diffs de partial update
        try:
            self.epd.displayPartBaseImage(self.epd.getbuffer(base_img))
            logger.debug("Base image definida via displayPartBaseImage().")
        except Exception as e:
            logger.debug("displayPartBaseImage indisponível: %s (seguindo sem ela)", e)
        self._partial_ready = True

    def partial_update(self, img: Image.Image):
        if not self._partial_ready:
            # fallback: se não preparado, prepara agora usando a própria img
            logger.debug("PART_UPDATE não preparado; preparando agora.")
            self.prepare_partial(img)
        try:
            # API típica de partial
            self.epd.displayPartial(self.epd.getbuffer(img))
        except Exception:
            # Alguns drivers expõem apenas display(); ainda funciona em PART_UPDATE
            logger.debug("displayPartial() ausente; usando display().")
            self.epd.display(self.epd.getbuffer(img))

    def sleep(self):
        try:
            self.epd.sleep()
        except Exception:
            pass


# ===================== MAIN LOOP =====================

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", metavar="PNG_PATH", help="Gera PNG em vez do display")
    parser.add_argument("--period", type=int, default=60, help="Intervalo de atualização parcial (s)")
    args = parser.parse_args()

    # 1) Render estático inicial
    base_img = render_static()

    # 2) Google client (uma vez)
    g = GoogleClient()

    # 3) Primeiro conjunto de itens e primeira tela dinâmica
    items = g.fetch_today_items()

    if args.dry_run:
        # Em modo dry-run, só gera PNG da primeira render dinâmica
        first_img = render_dynamic(base_img, items, page_index=0)
        first_img.save(args.dry_run)
        logger.info("PNG salvo em %s", args.dry_run)
        return

    # 4) Display
    ep = EPaper()
    ep.full_update(base_img)
    ep.prepare_partial(base_img)  # garante PART_UPDATE pronto

    page_index = 0
    last_static_date = datetime.now(local_tz()).date()

    try:
        while True:
            # Se mudou o mês/ano, regera estático e re-prepara partial
            now_date = datetime.now(local_tz()).date()
            if now_date != last_static_date and now_date.day == 1:
                logger.info("Mudança de mês/ano detectada. Recriando base estática.")
                base_img = render_static()
                ep.full_update(base_img)
                ep.prepare_partial(base_img)
                last_static_date = now_date

            # Busca itens e atualiza página
            items = g.fetch_today_items()
            frame = render_dynamic(base_img, items, page_index)
            ep.partial_update(frame)

            logger.info("Atualização parcial concluída (página %d).", page_index)
            page_index += 1
            time.sleep(args.period)

    except KeyboardInterrupt:
        logger.info("Encerrando...")
    finally:
        ep.sleep()


if __name__ == "__main__":
    main()
