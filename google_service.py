"""
Google Calendar and Tasks service integration
"""

import os
import socket
import getpass
import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
except ImportError:
    print("Google API libraries não encontradas. Instale com:")
    print("pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")
    raise

from display_controller import DisplayController
from image_renderer import ImageRenderer

logger = logging.getLogger(__name__)

class GoogleService:
    """Manages Google Calendar and Tasks API interactions"""

    def __init__(self, config):
        self.config = config
        self._credentials = None
        self._calendar_service = None
        self._tasks_service = None

    def _has_gui_env(self) -> bool:
        """Detect if GUI environment is available"""
        if (os.environ.get("DISPLAY") or
            os.environ.get("WAYLAND_DISPLAY") or
            os.environ.get("MIR_SOCKET")):
            return True

        try:
            import shutil
            if shutil.which("xdg-open") or shutil.which("x-www-browser"):
                return True
        except Exception:
            pass

        return False

    def _save_token(self, credentials):
        """Save credentials to token file"""
        try:
            with open(self.config.TOKEN_FILE, "w") as f:
                f.write(credentials.to_json())
            logger.info("Token salvo/atualizado com sucesso")
        except Exception as e:
            logger.error(f"Erro ao salvar token: {e}")

    def _show_auth_message(self):
        """Show authentication message on e-paper display"""
        try:
            from PIL import Image, ImageDraw
            from image_renderer import FontManager

            display = DisplayController(self.config)
            font_manager = FontManager(self.config)

            # Create authentication message image
            img = Image.new("1", (self.config.EPD_WIDTH, self.config.EPD_HEIGHT), 255)
            draw = ImageDraw.Draw(img)

            # Title
            font_title = font_manager.get_font('bold', self.config.FONT_SIZE_TITLE)
            title = self.config.MSG_AUTH_TITLE
            tw, th = draw.textsize(title, font=font_title)
            draw.text(((self.config.EPD_WIDTH - tw)//2, 15), title, font=font_title, fill=0)

            # Message
            font_msg = font_manager.get_font('regular', self.config.FONT_SIZE_SUBTITLE)
            msg = self.config.MSG_AUTH_MESSAGE
            lines = msg.split('\n')
            y_offset = 50
            for line in lines:
                lw, lh = draw.textsize(line, font=font_msg)
                draw.text(((self.config.EPD_WIDTH - lw)//2, y_offset), line, font=font_msg, fill=0)
                y_offset += lh + 2

            # Google "G" logo placeholder
            g_font = font_manager.get_font('bold', 36)
            gw, gh = draw.textsize("G", g_font)
            draw.text(((self.config.EPD_WIDTH - gw)//2, self.config.EPD_HEIGHT - gh - 15),
                     "G", font=g_font, fill=0)

            display.show_image(img, full_update=True)
            logger.info("Mensagem de autenticação exibida no display")

        except Exception as e:
            logger.warning(f"Não foi possível exibir mensagem no e-ink: {e}")

    def get_credentials(self) -> Credentials:
        """Get Google API credentials with automatic refresh"""
        # Return cached credentials if valid
        if self._credentials and self._credentials.valid:
            return self._credentials

        # Load from file if exists
        creds = None
        if self.config.TOKEN_FILE.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self.config.TOKEN_FILE), self.config.SCOPES
                )
                logger.info("Token carregado do disco")
            except Exception as e:
                logger.error(f"Falha ao carregar token local: {e}")
                creds = None

        # Check if credentials are valid
        if creds and creds.valid:
            self._credentials = creds
            return self._credentials

        # Try to refresh if refresh token exists
        if creds and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_token(creds)
                self._credentials = creds
                logger.info("Token renovado via refresh")
                return self._credentials
            except Exception as e:
                logger.error(f"Falha ao renovar token: {e}")
                creds = None

        # Need to authenticate
        if not self.config.CREDENTIALS_FILE.exists():
            raise FileNotFoundError(f"Credenciais não encontradas: {self.config.CREDENTIALS_FILE}")

        # Show authentication message on display
        self._show_auth_message()

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.config.CREDENTIALS_FILE), self.config.SCOPES
        )

        auth_kwargs = {
            'access_type': 'offline',
            'include_granted_scopes': 'true',
        }

        # Force consent on first run
        if not self.config.TOKEN_FILE.exists():
            auth_kwargs["prompt"] = "consent"

        if self._has_gui_env():
            logger.info("Iniciando OAuth (GUI)")
            creds = flow.run_local_server(port=0, open_browser=True, **auth_kwargs)
        else:
            logger.info("Iniciando OAuth (HEADLESS)")
            host = socket.gethostname()
            user = getpass.getuser() or "pi"
            ssh_hint = f"ssh -N -L {self.config.HEADLESS_OAUTH_PORT}:localhost:{self.config.HEADLESS_OAUTH_PORT} {user}@{host}"
            logger.info(f"Sugestão de túnel SSH: {ssh_hint}")
            creds = flow.run_local_server(
                host="localhost",
                port=self.config.HEADLESS_OAUTH_PORT,
                open_browser=False,
                **auth_kwargs,
            )

        self._save_token(creds)
        self._credentials = creds
        return self._credentials

    def _get_calendar_service(self):
        """Get Calendar service instance"""
        if not self._calendar_service:
            creds = self.get_credentials()
            self._calendar_service = build("calendar", "v3", credentials=creds)
        return self._calendar_service

    def _get_tasks_service(self):
        """Get Tasks service instance"""
        if not self._tasks_service:
            creds = self.get_credentials()
            self._tasks_service = build("tasks", "v1", credentials=creds)
        return self._tasks_service

    def get_events_and_tasks(self) -> List[Tuple[str, str, str, str]]:
        """
        Get today's events and tasks
        Returns: List of (time, title, source, location) tuples
        """
        tz = self.config.get_timezone()
        today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)

        time_min = today.isoformat()
        time_max = tomorrow.isoformat()

        events = []
        tasks = []

        # Get calendar events
        try:
            cal_service = self._get_calendar_service()
            calendars = cal_service.calendarList().list().execute().get("items", [])

            for cal in calendars:
                cal_id = cal.get("id")
                if not cal_id:
                    continue

                try:
                    cal_events = (
                        cal_service.events()
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

                    for event in cal_events:
                        start = event.get("start", {})
                        raw_time = start.get("dateTime") or start.get("date")

                        if not raw_time:
                            continue

                        if "T" in raw_time:
                            # Parse datetime with timezone
                            event_dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00")).astimezone(tz)
                            time_str = event_dt.strftime("%H:%M")
                        else:
                            time_str = "Dia todo"

                        title = event.get("summary", "(Sem título)")
                        location = event.get("location", "")
                        events.append((time_str, title, "Calendar", location))

                except Exception as e:
                    logger.warning(f"Falha ao buscar eventos do calendário {cal_id}: {e}")

        except Exception as e:
            logger.error(f"Erro ao listar calendários: {e}")

        # Get tasks
        try:
            tasks_service = self._get_tasks_service()
            task_lists = tasks_service.tasklists().list(maxResults=10).execute().get("items", [])

            for task_list in task_lists:
                try:
                    task_items = (
                        tasks_service.tasks()
                        .list(tasklist=task_list["id"], showCompleted=False)
                        .execute()
                        .get("items", [])
                    )

                    for task in task_items:
                        due = task.get("due")
                        if due:
                            task_dt = datetime.fromisoformat(due.replace("Z", "+00:00")).astimezone(tz)
                            if today <= task_dt < tomorrow:
                                time_str = task_dt.strftime("%H:%M")
                                title = task.get("title", "(Sem título)")
                                tasks.append((time_str, title, "Task", ""))

                except Exception as e:
                    logger.warning(f"Falha ao buscar tasks da lista {task_list.get('title', '?')}: {e}")

        except Exception as e:
            logger.error(f"Erro ao listar task lists: {e}")

        # Combine and sort
        all_items = events + tasks

        def sort_key(item):
            time_str = item[0]
            return "00:00" if time_str == "Dia todo" else time_str

        all_items.sort(key=sort_key)

        logger.info(f"Dados carregados: eventos={len(events)}, tasks={len(tasks)}, total={len(all_items)}")
        return all_items[:self.config.MAX_EVENTS]