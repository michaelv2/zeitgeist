from dotenv import load_dotenv
import os
from datetime import date
load_dotenv()
from email_briefing import fetch_briefing

result = fetch_briefing(os.environ['GMAIL_USER'], os.environ['GMAIL_APP_PASSWORD'], target_date=date(2026, 3, 24))
print(result or 'No briefing found')
