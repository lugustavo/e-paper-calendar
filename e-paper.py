#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Raspberry Pi Zero W + Waveshare e-Paper 2.13'' (V2 250x122)
Layout:
  • ESQUERDA: Eventos + Tasks do dia atual (Google Calendar + Google Tasks)
  • DIREITA (TOPO): Calendário do mês (grade correta, seg→dom)
  • DIREITA (BASE): Hora 24h em destaque + data curta

Atualização:
 - Renderização completa inicial
 - Atualização parcial (hora + eventos/tasks) a cada 60 segundos
"""

import os, sys
import argparse
import locale
import calendar as pycal
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw, ImageFont

picdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'e-Paper/RaspberryPi_JetsonNano/python/pic')
libdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'e-Paper/RaspberryPi_JetsonNano/python/lib')

# ================= Configurações =================
EPD_WIDTH = 250
EPD_HEIGHT = 122
MARGIN = 6
RIGHT_PANEL_W = 145  # Calendário + Hora
LEFT_PANEL_W = EPD_WIDTH - RIGHT_PANEL_W
TIME_BLOCK_H = 28
LINE_SPACING = 2
MAX_EVENTS = 8  # inclui events + tasks

FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

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

def text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]

def set_portuguese_locale():
    for loc in ("pt_PT.utf8", "pt_BR.utf8", "pt_PT", "pt_BR", "pt"):
        try:
            locale.setlocale(locale.LC_TIME, loc)
            return
        except Exception:
            pass

# ================= Google API =================

def get_google_data(max_items=MAX_EVENTS):
    """
    Retorna lista de (hora, título, origem, local).
    Eventos = Google Calendar
    Tasks = Google Tasks
    """
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    import pickle

    SCOPES = [
        'https://www.googleapis.com/auth/calendar.readonly',
        'https://www.googleapis.com/auth/tasks.readonly'
    ]

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")

    creds = None
    token_path = "token.pickle"
    if os.path.exists(token_path):
        with open(token_path, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0, access_type='offline', prompt='consent')
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    tz = local_tz()
    service_cal = build("calendar", "v3", credentials=creds)
    service_tasks = build("tasks", "v1", credentials=creds)

    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)

    time_min = today.isoformat()
    time_max = tomorrow.isoformat()

    # --- eventos de todos os calendários ---
    events = []
    calendars = service_cal.calendarList().list().execute().get("items", [])
    for cal in calendars:
        cal_id = cal["id"]
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
                    tasks.append((hora, t["title"], "Task", ""))

    all_items = events + tasks
    # ordena por hora (strings tratadas)
    def sortkey(item):
        h = item[0]
        if h == "Dia todo":
            return "00:00"
        return h
    all_items.sort(key=sortkey)
    return all_items[:max_items]

# ================= Desenho =================

def draw_month_calendar(draw, ox, oy, w, h, now):
    set_portuguese_locale()
    title_font = load_font(FONT_BOLD, 14)
    dayname_font = load_font(FONT_REG, 10)
    day_font = load_font(FONT_REG, 12)

    month_name = now.strftime("%B %Y")
    tw, th = text_size(draw, month_name, font=title_font)
    draw.text((ox + (w - tw)//2, oy), month_name, font=title_font, fill=0)

    top_after_title = oy + th + 2
    week_names = pycal.weekheader(2).split()
    cal = pycal.Calendar(firstweekday=pycal.MONDAY)
    cell_w = w // 7
    header_y = top_after_title
    for i, wd in enumerate(week_names):
        tx = ox + i*cell_w + (cell_w - text_size(draw, wd, font=dayname_font)[0])//2
        draw.text((tx, header_y), wd, font=dayname_font, fill=0)

    grid_top = header_y + dayname_font.size + 2
    month_grid = cal.monthdayscalendar(now.year, now.month)
    weeks = len(month_grid)
    cell_h = max(14, (h - (grid_top - oy) - 2) // weeks)

    y = grid_top
    today = now.day
    for row in month_grid:
        for col, day in enumerate(row):
            cx = ox + col*cell_w
            cy = y
            if day:
                txt = str(day)
                tx = cx + cell_w - text_size(draw, txt, day_font)[0] - 2
                ty = cy + 1
                if day == today:
                    draw.rectangle([cx+1, cy+1, cx+cell_w-2, cy+cell_h-2], outline=0, fill=0)
                    draw.text((tx, ty), txt, font=day_font, fill=255)
                else:
                    draw.text((tx, ty), txt, font=day_font, fill=0)
        y += cell_h

def draw_time_block(draw, ox, oy, w, now):
    time_font = load_font(FONT_BOLD, 22)
    date_font = load_font(FONT_REG, 12)
    time_txt = now.strftime("%H:%M")
    date_txt = now.strftime("%a, %d/%m")

    draw.rectangle([ox, oy, ox + w, oy + TIME_BLOCK_H], fill=0)
    tw, _ = text_size(draw, time_txt, font=time_font)
    draw.text((ox + (w - tw)//2, oy + 2), time_txt, font=time_font, fill=255)

    dy = oy + TIME_BLOCK_H + 2
    dw, _ = text_size(draw, date_txt, font=date_font)
    draw.text((ox + (w - dw)//2, dy), date_txt, font=date_font, fill=0)

def draw_events(draw, ox, oy, w, h, items):
    title_font = load_font(FONT_BOLD, 14)
    item_font = load_font(FONT_REG, 12)
    small_font = load_font(FONT_REG, 11)

    draw.text((ox, oy), "Hoje", font=title_font, fill=0)
    y = oy + title_font.size + 2

    def trunc(text, maxw, font):
        if text_size(draw, text, font=font)[0] <= maxw:
            return text
        for i in range(len(text)-1, 0, -1):
            t = text[:i] + "…"
            if text_size(draw, t, font=font)[0] <= maxw:
                return t
        return "…"

    for hora, title, origem, loc in items[:MAX_EVENTS]:
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

def render_dynamic(base_img):
    tz = local_tz()
    now = datetime.now(tz)
    items = get_google_data(MAX_EVENTS)

    img = base_img.copy()
    draw = ImageDraw.Draw(img)

    right_x, right_y = LEFT_PANEL_W + 1, MARGIN
    right_w, right_h = RIGHT_PANEL_W - MARGIN, EPD_HEIGHT - MARGIN*2
    cal_h = right_h - TIME_BLOCK_H - 22
    draw_time_block(draw, right_x+2, right_y + cal_h + 6, right_w-6, now)

    left_x, left_y = MARGIN, MARGIN
    left_w, left_h = LEFT_PANEL_W - MARGIN*2, EPD_HEIGHT - MARGIN*2
    draw.rectangle([left_x+1, left_y+1, left_x+left_w-1, left_y+left_h-1], fill=255)
    draw_events(draw, left_x+2, left_y+2, left_w-6, left_h-4, items)

    return img

def display_on_epaper(img, full=True):
    if os.path.exists(libdir):
        sys.path.append(libdir)
        from waveshare_epd import epd2in13_V2
    epd = epd2in13_V2.EPD()
    if full:
        epd.init(epd.FULL_UPDATE)
        epd.Clear(0xFF)
    else:
        epd.init(epd.PART_UPDATE)
    epd.display(epd.getbuffer(img))
    epd.sleep()

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
        while True:
            img = render_dynamic(base_img)
            display_on_epaper(img, full=False)
            print("Atualizado parcial (hora + eventos)")
            import time
            time.sleep(60)

if __name__ == "__main__":
    main()
