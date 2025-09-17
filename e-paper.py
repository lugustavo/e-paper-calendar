#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Raspberry Pi Zero W + Waveshare e-Paper 2.13'' (V2 250x122)
Layout:
  À ESQUERDA: Eventos + Tasks do dia atual (Google Calendar + Google Tasks)
  À DIREITA (TOPO): Calendário do mês (grade correta, seg à dom)
  À DIREITA (BASE): Hora 24h em destaque + data curta

Atualização:
 - Renderização completa inicial
 - Atualização parcial (hora + eventos/tasks) a cada 60 segundos
 - Eventos exibidos em grupos de 3 por vez, rotacionando

Autenticação Google:
 - Detecta automaticamente se está em ambiente com GUI (X/Wayland)
   ou em terminal/headless.
 - GUI: usa loopback `run_local_server(port=0, open_browser=True)`.
 - Headless: usa loopback `run_local_server(open_browser=False)` em porta fixa
   e imprime instruções para criar um túnel SSH local do PC → Raspberry,
   evitando o fluxo OOB (descontinuado pelo Google).

Compatibilidade Pillow 11.x:
 - (Opcional) substitua `draw.textsize` por helper `text_size()` com `textbbox`.

Armazenamento de token:
 - Usa `token.json` (JSON) em vez de pickle e **solicita refresh_token**
   com `access_type='offline'` + `prompt='consent'` na primeira autorização.
 - Após **refresh**, salva o token atualizado novamente (evita re-login).
"""

import os, sys
import argparse
import locale
import calendar as pycal
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw, ImageFont

import socket
import getpass

picdir = "/home/pi/e-Paper/RaspberryPi_JetsonNano/python/pic"
libdir = "/home/pi/e-Paper/RaspberryPi_JetsonNano/python/lib"

if os.path.exists(libdir):
    sys.path.append(libdir)

# ================= Configurações =================
EPD_WIDTH = 250
EPD_HEIGHT = 122
MARGIN = 3
RIGHT_PANEL_W = 144  # Calendário + Hora
LEFT_PANEL_W = EPD_WIDTH - RIGHT_PANEL_W
TIME_BLOCK_H = 15
LINE_SPACING = 2
MAX_EVENTS = 12  # busca mais para poder paginar

FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Porta fixa para o fluxo headless (deve bater com o -L do SSH)
HEADLESS_OAUTH_PORT = 54545

# Caminhos fixos
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")
TOKEN_PATH = os.path.join(BASE_DIR, "token.json")

# Escopos fixos
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/tasks.readonly'
]

# Cache em memória para evitar re-carregar credenciais a cada loop
_CREDS = None

# ================= Utilitários =================

def load_font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def local_tz():
    try:
        from tzlocal import get_localzone
        return get_localzone()
    except Exception:
        return datetime.now().astimezone().tzinfo or timezone.utc


# def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont):
#     """Compatível com Pillow 10+/11+: mede usando textbbox."""
#     bbox = draw.textbbox((0, 0), text, font=font)
#     return bbox[2] - bbox[0], bbox[3] - bbox[1]


def set_portuguese_locale():
    for loc in ("pt_PT.utf8", "pt_BR.utf8", "pt_PT", "pt_BR", "pt"):
        try:
            locale.setlocale(locale.LC_TIME, loc)
            return
        except Exception:
            pass


def has_gui_env() -> bool:
    """Heurística simples para detectar GUI local disponível."""
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or os.environ.get("MIR_SOCKET"):
        return True
    try:
        import shutil
        if shutil.which("xdg-open") or shutil.which("x-www-browser"):
            return True
    except Exception:
        pass
    return False


# ================= Google API =================

def _save_token(creds):
    try:
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    except Exception:
        pass


def get_credentials():
    """Obtém credenciais, renova se expirado e **não** reabre browser sem necessidade.
    Garante `refresh_token` na primeira autorização (offline + consent).
    """
    global _CREDS

    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    # 1) Cache de processo
    if _CREDS and _CREDS.valid:
        return _CREDS

    # 2) Carrega do disco se existir
    creds = None
    if os.path.exists(TOKEN_PATH):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        except Exception:
            creds = None

    # 3) Se inválido/expirado, tenta refresh silencioso
    if creds and not creds.valid and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)  # salva o token renovado
            _CREDS = creds
            return _CREDS
        except Exception:
            pass  # cairá para re-autenticar

    # 4) Precisa autenticar no navegador (primeira vez ou sem refresh_token)
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(f"Credenciais não encontradas: {CREDENTIALS_FILE}")

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)

    # Parâmetros para garantir refresh_token na 1ª vez
    auth_kwargs = dict(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
    )

    if has_gui_env():
        creds = flow.run_local_server(
            port=0,
            open_browser=True,
            authorization_prompt_message=(
                "\nAbra o link no navegador para autorizar o acesso (GUI detectada):\n{url}\n"
            ),
            success_message=(
                "Autorizado com sucesso! Você pode fechar esta aba."
            ),
            **auth_kwargs,
        )
    else:
        host = socket.gethostname()
        user = getpass.getuser() or "pi"
        ssh_hint = (
            f"ssh -N -L {HEADLESS_OAUTH_PORT}:localhost:{HEADLESS_OAUTH_PORT} {user}@{host}"
        )
        creds = flow.run_local_server(
            host="localhost",
            port=HEADLESS_OAUTH_PORT,
            open_browser=False,
            authorization_prompt_message=(
                "\n=== Autorização Google (modo HEADLESS) ===\n"
                "1) No SEU PC, abra um terminal e crie o túnel SSH para o Raspberry:\n"
                f"   {ssh_hint}\n"
                "   (Se o hostname não resolver, troque pelo IP do Raspberry)\n\n"
                "2) Com o túnel ativo, abra no navegador do SEU PC o link abaixo e conclua o login:\n"
                "   {url}\n\n"
                f"O Google irá redirecionar para http://localhost:{HEADLESS_OAUTH_PORT}/,\n"
                "que será encaminhado ao Raspberry pelo túnel.\n"
            ),
            success_message=(
                "Autorizado! Você já pode fechar a aba do navegador."
            ),
            **auth_kwargs,
        )

    _save_token(creds)
    _CREDS = creds
    return _CREDS


def get_google_data(max_items=MAX_EVENTS):
    from googleapiclient.discovery import build

    creds = get_credentials()

    tz = local_tz()
    service_cal = build("calendar", "v3", credentials=creds)
    service_tasks = build("tasks", "v1", credentials=creds)

    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)

    time_min = today.isoformat()
    time_max = tomorrow.isoformat()

    # --- eventos de todos os Calendários ---
    events = []
    calendars = service_cal.calendarList().list().execute().get("items", [])
    for cal in calendars:
        cal_id = cal.get("id")
        if not cal_id:
            continue
        evs = (
            service_cal.events()
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
        for ev in evs:
            start = ev.get("start", {})
            raw = start.get("dateTime") or start.get("date")
            if not raw:
                continue
            if "T" in raw:
                # normaliza e converte timezone
                sdt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(tz)
                hora = sdt.strftime("%H:%M")
            else:
                hora = "Dia todo"
            title = ev.get("summary", "(Sem título)")
            loc = ev.get("location", "")
            events.append((hora, title, "Calendar", loc))

    # --- tasks do dia ---
    tasks = []
    tlist = service_tasks.tasklists().list(maxResults=10).execute().get("items", [])
    for tl in tlist:
        ts = (
            service_tasks.tasks()
            .list(tasklist=tl["id"], showCompleted=False)
            .execute()
            .get("items", [])
        )
        for t in ts:
            due = t.get("due")
            if due:
                dt = datetime.fromisoformat(due.replace("Z", "+00:00")).astimezone(tz)
                if today <= dt < tomorrow:
                    hora = dt.strftime("%H:%M")
                    tasks.append((hora, t.get("title", "(Sem título)"), "Task", ""))

    all_items = events + tasks

    def sortkey(item):
        h = item[0]
        return "00:00" if h == "Dia todo" else h

    all_items.sort(key=sortkey)
    return all_items[:max_items]


# ================= Desenho =================

def draw_month_calendar(draw, ox, oy, w, h, now):
    set_portuguese_locale()
    title_font = load_font(FONT_BOLD, 11)
    dayname_font = load_font(FONT_REG, 9)
    day_font = load_font(FONT_REG, 9)

    month_name = now.strftime(" %B %Y ")
    tw, th = draw.textsize(month_name, title_font)
    draw.text((ox + (w - tw)//2, oy), month_name, font=title_font, fill=0)

    top_after_title = oy + th + 2

    week_names = pycal.weekheader(2).split()
    cal = pycal.Calendar(firstweekday=pycal.MONDAY)
    cell_w = w // 7
    header_y = top_after_title
    for i, wd in enumerate(week_names):
        wd_w, _ = draw.textsize(wd, dayname_font)
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
                txt_w, txt_h = draw.textsize(txt, day_font)
                tx = cx + cell_w - txt_w - 2
                ty = cy + 1
                if day == today_num:
                    draw.rectangle([cx+1, cy+1, cx+cell_w-2, cy+cell_h-2], outline=0, fill=0)
                    draw.text((tx, ty), txt, font=day_font, fill=255)
                else:
                    draw.text((tx, ty), txt, font=day_font, fill=0)
        y += cell_h


def draw_time_block(draw, ox, oy, w, now):
    time_font = load_font(FONT_BOLD, 11)
    time_txt = now.strftime("%H:%M")

    draw.rectangle([ox, oy, ox + w, oy + TIME_BLOCK_H], fill=0)
    tw, _ = draw.textsize(time_txt, time_font)
    draw.text((ox + (w - tw)//2, oy + 2), time_txt, font=time_font, fill=255)


def draw_events(draw, ox, oy, w, h, items, page_index=0, total_pages=1):
    title_font = load_font(FONT_BOLD, 11)
    item_font = load_font(FONT_REG, 9)
    small_font = load_font(FONT_REG, 9)

    if not items:
        titulo = "Eventos (vazio)"
    elif total_pages > 1:
        titulo = f"Eventos ({page_index+1}/{total_pages})"
    else:
        titulo = "Eventos"

    draw.rectangle([ox, oy, ox + w, oy + TIME_BLOCK_H], fill=0)
    tw, _ = draw.textsize(titulo, title_font)
    draw.text((ox + (w - tw)//2, oy + 2), titulo, font=title_font, fill=255)

    y = oy + title_font.size + 8

    def trunc(text, maxw, font):
        if draw.textsize(text, font)[0] <= maxw:
            return text
        low, high = 0, len(text)
        while low < high:
            mid = (low + high) // 2
            cand = text[:mid] + "..."
            if draw.textsize(cand, font)[0] <= maxw:
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


# ================= Pipeline =================

def render_static():
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


def render_dynamic(base_img, page_index=0, page_size=3):
    tz = local_tz()
    now = datetime.now(tz)
    items = get_google_data(MAX_EVENTS)

    if items:
        total_pages = (len(items) + page_size - 1) // page_size
        page_index = page_index % total_pages
        start = page_index * page_size
        end = start + page_size
        show_items = items[start:end]
    else:
        show_items, total_pages = [], 1

    img = base_img.copy()
    draw = ImageDraw.Draw(img)

    right_x, right_y = LEFT_PANEL_W + 2, MARGIN
    right_w, right_h = RIGHT_PANEL_W - MARGIN, EPD_HEIGHT - MARGIN*2
    cal_h = right_h - TIME_BLOCK_H - 8
    draw_time_block(draw, right_x+2, right_y + cal_h + 6, right_w-7, now)

    left_x, left_y = MARGIN, MARGIN
    left_w, left_h = LEFT_PANEL_W - MARGIN*2, EPD_HEIGHT - MARGIN*2
    draw.rectangle([left_x+1, left_y+1, left_x+left_w-1, left_y+left_h-1], fill=255)
    draw_events(draw, left_x+2, left_y+2, left_w-4, left_h-6, show_items,
                page_index=page_index, total_pages=total_pages)

    return img


def display_on_epaper(img, full=True):
    from waveshare_epd import epd2in13_V2
    epd = epd2in13_V2.EPD()
    if full:
        epd.init(epd.FULL_UPDATE)
        epd.Clear(0xFF)
    else:
        epd.displayPartBaseImage(epd.getbuffer(img))
        epd.init(epd.PART_UPDATE)
    epd.display(epd.getbuffer(img))
    # epd.sleep()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", metavar="PNG_PATH", help="Gera PNG em vez do display")
    args = parser.parse_args()

    base_img = render_static()
    img = render_dynamic(base_img)

    if args.dry_run:
        img.save(args.dry_run)
        print("PNG salvo em", args.dry_run)
    else:
        display_on_epaper(base_img, full=True)
        page_index = 0
        while True:
            img = render_dynamic(base_img, page_index)
            display_on_epaper(img, full=False)
            print(f"Atualizado parcial (hora + eventos página {page_index})")
            page_index += 1
            import time
            time.sleep(60)


if __name__ == "__main__":
    main()
