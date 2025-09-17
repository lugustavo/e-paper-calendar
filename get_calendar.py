# -*- coding: utf-8 -*-
from __future__ import print_function
import datetime
import os.path
from tzlocal import get_localzone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Escopos necessarios (Calendar + Tasks)
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/tasks.readonly'
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")

def get_creds():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds


def get_formatted_events(service_calendar, max_results=20):
    """Retorna apenas eventos do dia atual no fuso horario local"""
    local_tz = get_localzone()
    now = datetime.datetime.now(local_tz)
    start_of_day = datetime.datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=local_tz)
    end_of_day = start_of_day + datetime.timedelta(days=1)

    events_result = service_calendar.events().list(
        calendarId='primary',
        timeMin=start_of_day.isoformat(),
        timeMax=end_of_day.isoformat(),
        maxResults=max_results,
        singleEvents=True,
        orderBy='startTime').execute()
    events = events_result.get('items', [])

    formatted = []
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        try:
            dt = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
            dt = dt.astimezone(local_tz)
            start_str = dt.strftime("%H:%M")
        except Exception:
            start_str = "(Dia inteiro)"
        formatted.append(f"{start_str} - {event.get('summary', '(Sem titulo)')}")
    return formatted


def get_formatted_tasks(service_tasks, max_lists=5):
    """Retorna tarefas formatadas do Google Tasks"""
    local_tz = get_localzone()
    tasklists = service_tasks.tasklists().list(maxResults=max_lists).execute().get('items', [])
    formatted = []
    for tasklist in tasklists:
        formatted.append(f"[{tasklist['title']}]")
        tasks = service_tasks.tasks().list(tasklist=tasklist['id']).execute().get('items', [])
        if not tasks:
            formatted.append("  (Nenhuma tarefa)")
        for task in tasks:
            status = "OK" if task.get('status') == "completed" else "X"
            title = task.get('title', '(Sem titulo)')
            due = task.get('due')
            if due:
                try:
                    dt = datetime.datetime.fromisoformat(due.replace("Z", "+00:00"))
                    dt = dt.astimezone(local_tz)
                    due_str = dt.strftime("%d/%m")
                    formatted.append(f"  {status} {title} (ate {due_str})")
                except Exception:
                    formatted.append(f"  {status} {title}")
            else:
                formatted.append(f"  {status} {title}")
    return formatted


def main():
    creds = get_creds()
    service_calendar = build('calendar', 'v3', credentials=creds)
    service_tasks = build('tasks', 'v1', credentials=creds)

    events = get_formatted_events(service_calendar)
    tasks = get_formatted_tasks(service_tasks)

    print("=== EVENTOS DE HOJE ===")
    for e in events:
        print(e)

    print("\n=== TAREFAS ===")
    for t in tasks:
        print(t)


if __name__ == '__main__':
    main()
