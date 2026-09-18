"""Read-only OpenAI model-access probe; no billable model generation."""
import os
from pathlib import Path
from urllib.parse import quote
import requests
from dotenv import load_dotenv


def main():
    load_dotenv(Path(__file__).resolve().parents[1]/'.env')
    key=os.getenv('OPENAI_API_KEY','').strip()
    model=os.getenv('ASTRA_MODEL','gpt-6-astra').strip() or 'gpt-6-astra'
    if not key:
        raise ValueError('OPENAI_API_KEY missing; keep it in the local .env.')
    with requests.Session() as session:
        response=session.get('https://api.openai.com/v1/models/'+quote(model,safe=''),
                             headers={'Authorization':'Bearer '+key},timeout=(10,30),allow_redirects=False)
    if response.status_code!=200:
        print('Model metadata request failed: HTTP',response.status_code)
        print('No generation requested. Check key, project permissions and model availability.')
        return 1
    print('Model metadata accessible:',response.json().get('id'))
    print('No model generation requested. This does not prove generation quota or current billing availability.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
