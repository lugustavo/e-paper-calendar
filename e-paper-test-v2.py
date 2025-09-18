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

# ===== Logging (retenção 7 dias + compressão .gz) =====
import logging
from logging.handlers import TimedRotatingFileHandler
import time as _time

def _setup_logging():
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        log_dir = os.path.join(base_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "epaper.log")

        # Gira à meia-noite. backupCount mantido por compat, mas a limpeza principal é por idade (7 dias) abaixo.
        file_handler = TimedRotatingFileHandler(
            log_file, when="midnight", backupCount=7, encoding="utf-8"
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

        # Rotaciona comprimindo para .gz e limpa arquivos .gz com mais de 7 dias
        def _gzip_rotator(source, dest):
            try:
                import gzip, shutil
                with open(source, "rb") as f_in, gzip.open(dest + ".gz", "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
                try:
                    os.remove(source)
                except Exception:
                    pass
                # Limpeza por idade (7 dias) dos .gz
                cutoff = _time.time() - 7 * 24 * 3600
                try:
                    for fn in os.listdir(log_dir):
                        if not fn.endswith(".gz"):
                            continue
                        fp = os.path.join(log_dir, fn)
                        try:
                            if os.path.getmtime(fp) < cutoff:
                                os.remove(fp)
                        except Exception:
                            pass
                except Exception:
                    pass
            except Exception:
                # Se algo der errado, pelo menos tenta renomear sem comprimir
                try:
                    os.replace(source, dest)
                except Exception:
                    pass

        file_handler.rotator = _gzip_rotator
        # Observação: não definimos 'namer' para manter a política de limpeza acima por mtime

        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(logging.INFO)
        stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

        logging.basicConfig(level=logging.INFO, handlers=[stream_handler, file_handler])
        logging.getLogger(__name__).info("Logging iniciado (retenção 7 dias com compressão)")
    except Exception as e:
        # Fallback mínimo para não quebrar execução
        logging.basicConfig(level=logging.INFO)
        logging.getLogger(__name__).warning(f"Falha ao inicializar logging avançado: {e}")

_setup_logging()
logger = logging.getLogger(__name__)

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
TOKEN_path_comment_preserver = ""  # (no-op) placeholder to avoid altering comments above
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
    except Exception as e:
        logger.warning(f"Falha ao carregar fonte {path}, usando default. Erro: {e}")
        return ImageFont.load_default()


def local_tz():
    try:
        from tzlocal import get_localzone
        tz = get_localzone()
        return tz
    except Exception as e:
        logger.error(f"Erro ao obter timezone local: {e}")
        return datetime.now().astimezone().tzinfo or timezone.utc


# def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont):
#     """Compatível com Pillow 10+/11+: mede usando textbbox."""
#     bbox = draw.textbbox((0, 0), text, font=font)
#     return bbox[2] - bbox[0], bbox[3] - bbox[1]


def set_portuguese_locale():
    for loc in ("pt_PT.utf8", "pt_BR.utf8", "pt_PT", "pt_BR", "pt"):
        try:
            locale.setlocale(locale.LC_TIME, loc)
            logger.info(f"Locale definido: {loc}")
            return
        except Exception:
            pass
    logger.warning("Não foi possível definir locale para PT")


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
        logger.info("Token salvo/atualizado com sucesso")
    except Exception as e:
        logger.error(f"Erro ao salvar token: {e}")


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
            logger.info("Token carregado do disco")
        except Exception as e:
            logger.error(f"Falha ao carregar token local: {e}")
            creds = None

    # 3) Se inválido/expirado, tenta refresh silencioso
    if creds and not creds.valid and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)  # salva o token renovado
            _CREDS = creds
            logger.info("Token renovado via refresh")
            return _CREDS
        except Exception as e:
            logger.error(f"Falha ao renovar token (refresh): {e}")
            # cairá para re-autenticar

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
        logger.info("Iniciando OAuth (GUI)")
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
        logger.info("Iniciando OAuth (HEADLESS)")
        host = socket.gethostname()
        user = getpass.getuser() or "pi"
        ssh_hint = (
            f"ssh -N -L {HEADLESS_OAUTH_PORT}:localhost:{HEADLESS_OAUTH_PORT} {user}@{host}"
        )
        logger.info(f"Sugestão de túnel SSH: {ssh_hint}")
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
    try:
        calendars = service_cal.calendarList().list().execute().get("items", [])
    except Exception as e:
        logger.error(f"Erro ao listar calendários: {e}")
        calendars = []
    for cal in calendars:
        cal_id = cal.get("id")
        if not cal_id:
            continue
        try:
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
        except Exception as e:
            logger.warning(f"Falha ao buscar eventos do calendário {cal_id}: {e}")
            evs = []
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
    try:
        tlist = service_tasks.tasklists().list(maxResults=10).execute().get("items", [])
    except Exception as e:
        logger.error(f"Erro ao listar tasklists: {e}")
        tlist = []
    for tl in tlist:
        try:
            ts = (
                service_tasks.tasks()
                .list(tasklist=tl["id"], showCompleted=False)
                .execute()
                .get("items", [])
            )
        except Exception as e:
            logger.warning(f"Falha ao buscar tasks da lista {tl.get('title','?')}: {e}")
            ts = []
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
    logger.info(f"Itens carregados: eventos={len(events)}, tasks={len(tasks)}, total={len(all_items)}")
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
    _t0 = _time.perf_counter()
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

    logger.info(f"Render estática concluída em {(_time.perf_counter()-_t0)*1000:.0f} ms")
    return img


def render_dynamic(base_img, page_index=0, page_size=3):
    _t0 = _time.perf_counter()
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

    logger.info(
        f"Render dinâmica p={page_index+1}/{total_pages} itens_mostrados={len(show_items)} em {(_time.perf_counter()-_t0)*1000:.0f} ms"
    )
    return img


def display_on_epaper(img, full=True):
    from waveshare_epd import epd2in13_V2
    epd = epd2in13_V2.EPD()
    if full:
        epd.init(epd.FULL_UPDATE)
        epd.Clear(0xFF)
        epd.display(epd.getbuffer(img))
        logger.info("Display: FULL update")
    else:
        epd.displayPartBaseImage(epd.getbuffer(img))
        epd.init(epd.PART_UPDATE)
        epd.displayPartial(epd.getbuffer(img))
        logger.info("Display: PARTIAL update")
    #epd.sleep()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", metavar="PNG_PATH", help="Gera PNG em vez do display")
    args = parser.parse_args()

    base_img = render_static()
    img = render_dynamic(base_img)

    if args.dry_run:
        img.save(args.dry_run)
        logger.info(f"PNG salvo em {args.dry_run}")
    else:
        display_on_epaper(base_img, full=True)
        page_index = 0
        while True:
            try:
                img = render_dynamic(base_img, page_index)
                display_on_epaper(img, full=False)
                img.save('out-test.png')
                logger.info(f"Atualização parcial OK (página {page_index})")
                page_index += 1
                import time
                time.sleep(60)
            except KeyboardInterrupt:
                logger.info("Encerrado pelo usuário (Ctrl+C)")
                break
            except Exception as e:
                logger.exception(f"Erro no loop de atualização: {e}")
                import time
                time.sleep(60)
            finally:
                logging.info("Putting display to sleep.")
                epd.sleep()
                epd2in13_V2.epdconfig.module_exit()


if __name__ == "__main__":
    main()
