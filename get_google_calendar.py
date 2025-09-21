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
            creds = flow.run_local_server(port=0, access_type='offline', prompt='consent')
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

def list_calendars(service_calendar):
    calendar_list = service_calendar.calendarList().list().execute()
    return calendar_list.get('items', [])

def get_formatted_events_all_calendars(service_calendar, max_results=5):
    """Retorna eventos do dia atual de todos os calendarios"""
    local_tz = get_localzone()
    now = datetime.datetime.now(local_tz)
    start_of_day = datetime.datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=local_tz)
    end_of_day = start_of_day + datetime.timedelta(days=1)

    all_events = []
    calendars = list_calendars(service_calendar)

    for cal in calendars:
        cal_id = cal['id']
        cal_name = cal.get('summary', cal_id)
        events_result = service_calendar.events().list(
            calendarId=cal_id,
            timeMin=start_of_day.isoformat(),
            timeMax=end_of_day.isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime').execute()
        events = events_result.get('items', [])
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            try:
                dt = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
                dt = dt.astimezone(local_tz)
                start_str = dt.strftime("%H:%M")
            except Exception:
                start_str = "(Dia inteiro)"
            title = event.get('summary', '(Sem titulo)')
            all_events.append(f"[{cal_name}] {start_str} - {title}")

    return all_events

def get_formatted_tasks(service_tasks, max_lists=5):
    """Retorna apenas tarefas com prazo para o dia atual (inclui hora se existir)"""
    local_tz = get_localzone()
    today = datetime.datetime.now(local_tz).date()
    tasklists = service_tasks.tasklists().list(maxResults=max_lists).execute().get('items', [])
    formatted = []
    for tasklist in tasklists:
        tasks = service_tasks.tasks().list(tasklist=tasklist['id']).execute().get('items', [])
        todays_tasks = []
        for task in tasks:
            due = task.get('due')
            if due:
                try:
                    dt = datetime.datetime.fromisoformat(due.replace("Z", "+00:00")).astimezone(local_tz)
                    if dt.date() != today:
                        continue
                    # inclui hora se não for 00:00
                    if dt.hour == 0 and dt.minute == 0:
                        due_str = dt.strftime("%d/%m")
                    else:
                        due_str = dt.strftime("%d/%m %H:%M")
                except Exception:
                    continue
            else:
                continue  # ignora tarefas sem prazo
            status = "OK" if task.get('status') == "completed" else "X"
            title = task.get('title', '(Sem titulo)')
            todays_tasks.append(f"  {status} {title} (até {due_str})")
        if todays_tasks:
            formatted.append(f"[{tasklist['title']}]")
            formatted.extend(todays_tasks)
    if not formatted:
        formatted.append("(Nenhuma tarefa para hoje)")
    return formatted

def main():
    creds = get_creds()
    service_calendar = build('calendar', 'v3', credentials=creds)
    service_tasks = build('tasks', 'v1', credentials=creds)

    events = get_formatted_events_all_calendars(service_calendar)
    tasks = get_formatted_tasks(service_tasks)

    print("=== EVENTOS DE HOJE (TODOS CALENDARIOS) ===")
    for e in events:
        print(e)

    print("\n=== TAREFAS DE HOJE ===")
    for t in tasks:
        print(t)

if __name__ == '__main__':
    main()
