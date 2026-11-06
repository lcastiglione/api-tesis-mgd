"""Registra consultas y respuestas HTTP reales para el tutorial de la API."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def record(base_url: str) -> None:
    """Ejecuta el recorrido documentado y conserva el cuerpo completo de cada respuesta."""
    examples: dict = {}
    def call(name: str, path: str, body: dict | None = None) -> dict:
        request = Request(base_url+path,data=None if body is None else json.dumps(body).encode(),
                          headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=180) as response:
            content = json.load(response)
            examples[name] = {'method':request.get_method(),'path':path,'request':body,
                              'status':response.status,'response':content}
            return content
    call('health','/health')
    call('study','/api/v1/study')
    call('instruments','/api/v1/instruments')
    call('configurations','/api/v1/configurations?instrument=SPY&family=P-SMA&limit=1')
    execution = call('execution','/api/v1/executions?instrument=SPY&configuration=sma200&length=1&limit=1')['items'][0]['execution_id']
    call('indicators',f'/api/v1/executions/{execution}/indicators?segment=OOS_continuous&metric=return_annualized&limit=2')
    call('daily',f'/api/v1/executions/{execution}/daily?segment=OOS&alternative=strategy&limit=1')
    call('operations',f'/api/v1/executions/{execution}/operations?limit=1')
    call('configuration-counts','/api/v1/configuration-counts')
    call('configuration-counts-spy','/api/v1/configuration-counts?instrument=SPY')
    call('verify','/api/v1/verify-case',{'instrument':'SPY','configuration':'sma200','length':1})
    (ROOT/'docs/api-examples.json').write_text(json.dumps({'recorded_at':datetime.now(timezone.utc).isoformat(),
        'transport':'HTTP','base_url':base_url,'examples':examples},ensure_ascii=False,indent=2)+'\n')
    print('Recorded',len(examples),'successful HTTP examples; verification:',examples['verify']['response']['passed'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    record(parser.parse_args().base_url.rstrip('/'))
